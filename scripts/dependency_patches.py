#!/usr/bin/env python3
"""Apply the platform's ordered dependency patches without discarding local edits."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = {"windows", "linux", "android"}


def patch_plan(root, platform):
    if platform not in PLATFORMS:
        raise ValueError(f"Unknown patch platform: {platform}")
    entries = json.loads((root / "patches/series.json").read_text(encoding="utf-8"))
    seen = set()
    plan = {}
    for entry in entries:
        repository, name, platforms = entry["repository"], entry["patch"], entry["platforms"]
        parts = PurePosixPath(repository)
        if (parts.is_absolute() or ".." in parts.parts or "\\" in repository
                or ":" in repository or not parts.parts):
            raise ValueError(f"Invalid patch repository: {repository}")
        if name != Path(name).name or "/" in name or "\\" in name:
            raise ValueError(f"Invalid patch filename: {name}")
        if name in seen:
            raise ValueError(f"Duplicate patch: {name}")
        if not platforms or not set(platforms) <= PLATFORMS or len(set(platforms)) != len(platforms):
            raise ValueError(f"Invalid platforms for {name}: {platforms}")
        seen.add(name)
        if platform in platforms:
            plan.setdefault(root / repository, []).append(root / "patches" / name)
    files = {path.name for path in (root / "patches").glob("*.patch")}
    if seen != files:
        raise ValueError(f"Patch inventory mismatch: unlisted={sorted(files - seen)}, missing={sorted(seen - files)}")
    return plan


def _series_paths(directory, patches):
    """Repo-relative paths touched by the patch series, de-duplicated."""
    paths = []
    for patch in patches:
        output = subprocess.check_output(
            ["git", "-C", str(directory), "apply", "--numstat", str(patch)],
            text=True)
        for line in output.splitlines():
            fields = line.split("\t")
            if len(fields) != 3:
                continue
            path = fields[2]
            if " => " in path:  # rename: keep the destination path
                path = path.rsplit(" => ", 1)[1].strip("{}")
            paths.append(path)
    return list(dict.fromkeys(paths))


def remaining_patch(directory, patches):
    # Later patches can change earlier hunks. Compare the complete series and
    # each supported prefix using a private index; the user's index is untouched.
    git = ["git", "-C", str(directory)]
    with tempfile.TemporaryDirectory(prefix="aero-patches-") as temporary:
        environment = dict(os.environ, GIT_INDEX_FILE=str(Path(temporary) / "index"))
        subprocess.run(git + ["read-tree", "HEAD"], env=environment, check=True)
        # Seed the private index with the working tree's current state for the
        # files the series touches. setup_dependencies.py applies each
        # dependency's own upstream patch to the working tree (unstaged), so
        # the series' pre-images are written against that state, not pristine
        # HEAD; without this, any series patch overlapping an upstream patch
        # (0019, 0022) can never apply. Scoped to the series' paths so a dirty
        # submodule gitlink (e.g. plume inside rt64) cannot poison the index.
        paths = _series_paths(directory, patches)
        if paths:
            base_diff = subprocess.run(
                git + ["diff", "HEAD", "--binary", "--"] + paths,
                capture_output=True, check=True).stdout
            if base_diff:
                subprocess.run(git + ["apply", "--cached", "--ignore-whitespace",
                                      "--whitespace=nowarn", "-"],
                               input=base_diff, env=environment, check=True)
        trees = [subprocess.check_output(git + ["write-tree"], env=environment).decode().strip()]
        for patch in patches:
            applied = subprocess.run(
                git + ["apply", "--cached", "--ignore-whitespace", "--whitespace=nowarn", str(patch)],
                env=environment, capture_output=True)
            if applied.returncode != 0:
                # The patch may already be present in the seeded base state
                # (the working tree already contains it); verify by reverse
                # application against the private index. Anything else is a
                # genuine conflict with local changes.
                already = subprocess.run(
                    git + ["apply", "--cached", "--reverse", "--check", str(patch)],
                    env=environment, capture_output=True)
                if already.returncode != 0:
                    raise RuntimeError(
                        f"Patch series conflicts with local changes in {directory}. Use a clean worktree.")
            trees.append(subprocess.check_output(git + ["write-tree"], env=environment).decode().strip())
        prefix = Path(temporary) / "prefix.patch"
        remaining = Path(temporary) / "remaining.patch"
        command = git + ["apply", "--ignore-whitespace"]
        for index in range(len(trees) - 1, -1, -1):
            prefix.write_bytes(subprocess.check_output(git + ["diff", "--binary", trees[0], trees[index]]))
            remaining.write_bytes(subprocess.check_output(git + ["diff", "--binary", trees[index], trees[-1]]))
            # An empty diff trivially applies: git apply --check rejects empty
            # input outright ("No valid patches in input"), so it must be
            # short-circuited instead of checked. An empty prefix means the
            # first `index` patches were already in the base state; an empty
            # remaining means nothing is left to apply.
            if prefix.stat().st_size == 0:
                prefix_present = True
            else:
                prefix_present = index == 0 or subprocess.run(
                    command + ["--reverse", "--check", str(prefix)], capture_output=True).returncode == 0
            if prefix_present:
                if index == len(trees) - 1:
                    return b""
                if remaining.stat().st_size == 0:
                    return b""
                if subprocess.run(command + ["--check", str(remaining)], capture_output=True).returncode == 0:
                    return remaining.read_bytes()
        raise RuntimeError(f"Patch series conflicts with local changes in {directory}. Use a clean worktree.")


def apply_patch_series(directory, patches):
    patch = remaining_patch(directory, patches)
    if patch:
        subprocess.run(["git", "-C", str(directory), "apply", "--ignore-whitespace", "--whitespace=nowarn", "-"],
                       input=patch, check=True)


def apply_platform_patches(root, platform):
    # Preflight every dependency before changing any working tree.
    changes = [(directory, remaining_patch(directory, patches))
               for directory, patches in patch_plan(root, platform).items()]
    for directory, patch in changes:
        if patch:
            subprocess.run(["git", "-C", str(directory), "apply", "--ignore-whitespace", "--whitespace=nowarn", "-"],
                           input=patch, check=True)
        print(f"[patches] {directory.relative_to(root)}: {'applied' if patch else 'already applied'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=sorted(PLATFORMS))
    parser.add_argument("--check", action="store_true", help="validate inventory without touching dependencies")
    args = parser.parse_args()
    if args.check:
        for platform in sorted(PLATFORMS):
            patch_plan(ROOT, platform)
        print("Dependency patch inventory passed for Windows, Linux, and Android.")
    elif args.platform:
        apply_platform_patches(ROOT, args.platform)
    else:
        parser.error("choose --platform or --check")


if __name__ == "__main__":
    main()
