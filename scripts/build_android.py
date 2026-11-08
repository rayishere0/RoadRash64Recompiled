#!/usr/bin/env python3
"""Build the full RR64 Android game: host generators, build-time recompile,
NDK cross-compile of the game library, and APK packaging.

Stages:
  1. Fetch pinned dependencies (scripts/setup_dependencies.py) + Android
     deps (SDL / FreeType / AdrenoTools) + Android patches.
  2. Build host tools (N64RecompCLI, RSPRecomp, file_to_c) on the host.
  3. Stage the ROM (build machine only) and verify it.
  4. Run N64Recomp + RSPRecomp (build-time recompilation; the phone never
     recompiles anything).
  5. NDK cross-compile of the native game target (native/ -> libmain.so)
     and APK packaging (android/app, :app:assemble).

Not in this script yet: the launcher (ROM picker/import), touch controls
and Controller Pak saves land in later steps. The APK launches GameActivity
directly and auto-starts from a manually staged ROM (see
docs/ANDROID_GAME_BUILD.md).

The ROM is required on the BUILD machine only, never committed. Pass it
with --rom (a .z64, or a .zip containing one). tools/stage_rom.py verifies
it (32 MiB, SHA-1 87727a298f583ec8325f5655088ff21e37b335b2) and writes the
normalised ROM to build/roadrash64.us.z64 (gitignored).

Incremental rebuilds: after a first full build, re-run with --fast
(--skip-deps --skip-host-tools --skip-codegen). See
docs/ANDROID_GAME_BUILD.md ("Incremental rebuilds"). A run with no new
flags is a full build, exactly as before.

NOT compile-checked: no NDK / Android Studio / ROM on this machine.
"""
import argparse
import contextlib
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

from dependency_patches import apply_platform_patches

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build-android"
NDK_VERSION = "28.2.13676358"
DEPS = {
    "SDL": ("https://github.com/libsdl-org/SDL.git", "5d249570393f7a37e037abf22cd6012a4cc56a71"),
    "freetype": ("https://github.com/freetype/freetype.git", "42608f77f20749dd6ddc9e0536788eaad70ea4b5"),
    "adrenotools": ("https://github.com/bylaws/libadrenotools.git", "8fae8ce254dfc1344527e05301e43f37dea2df80"),
}


def run(*args, cwd=ROOT):
    subprocess.run([str(a) for a in args], cwd=cwd, check=True)


def fetch_repo(url, destination, commit):
    if not (destination / ".git").exists():
        run("git", "init", destination)
        run("git", "-C", destination, "remote", "add", "origin", url)
        run("git", "-C", destination, "fetch", "--depth", "1", "origin", commit)
        run("git", "-C", destination, "checkout", "--detach", "FETCH_HEAD")
    actual = subprocess.check_output(
        ["git", "-C", str(destination), "rev-parse", "HEAD"], text=True).strip()
    if actual != commit:
        raise RuntimeError(f"Unexpected revision in {destination}: {actual} (want {commit})")


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _codegen_stamp(host, suffix):
    """Hash of everything the recompile step reads.

    The stamp lives in build/ (gitignored). If it matches, the generated
    C is already up to date and the translators need not run again:
    re-running them would rewrite build/RecompiledFuncs and force the
    whole game to recompile even though nothing changed. A hash, not
    timestamps: a fresh checkout changes every mtime, so timestamps
    would never let a rebuild skip.
    """
    staged_rom = ROOT / "build/roadrash64.us.z64"
    inputs = [
        staged_rom,
        ROOT / "config/roadrash64.us.toml",
        ROOT / "config/roadrash64.us.audio_rsp.toml",
        host / "bin" / f"N64Recomp{suffix}",
        host / "bin" / f"RSPRecomp{suffix}",
    ]
    digest = hashlib.sha256()
    for path in inputs:
        digest.update(str(path).encode())
        digest.update(b"\0")
        digest.update(_file_sha256(path).encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _codegen_is_current(host, suffix):
    # A stamp from a build whose generated output has since been deleted
    # (build/ wiped, fresh checkout) must not count as up to date.
    if not (ROOT / "build/RecompiledFuncs").is_dir():
        return False
    stamp = ROOT / "build/.codegen-stamp"
    if not stamp.is_file():
        return False
    try:
        return stamp.read_text(encoding="utf-8").strip() == _codegen_stamp(host, suffix)
    except (OSError, UnicodeDecodeError):
        return False


def _codegen_mark_current(host, suffix):
    stamp = ROOT / "build/.codegen-stamp"
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(_codegen_stamp(host, suffix) + "\n", encoding="utf-8")


@contextlib.contextmanager
def _timed(timings, name, skipped=False, extra=0.0):
    start = time.monotonic()
    try:
        yield
    finally:
        timings.append((name, time.monotonic() - start + extra, skipped))


def _print_timings(timings):
    print("Build timings (seconds):")
    for name, seconds, skipped in timings:
        print(f"  {name}: {seconds:.1f}{' (skipped)' if skipped else ''}")
    print(f"  total: {sum(seconds for _, seconds, _ in timings):.1f}")


def prepare_sources():
    # RR64's own pinned deps + patches + overrides (no ROM involved).
    run(sys.executable, "-B", ROOT / "scripts/setup_dependencies.py")
    for name, (url, revision) in DEPS.items():
        destination = WORK / "deps" / name
        fetch_repo(url, destination, revision)
        run("git", "-C", destination, "submodule", "update", "--init", "--recursive")

    # Android boundary patches (patches/series.json). Applied on top of
    # RR64's own patches; idempotent (already-applied is a no-op).
    apply_platform_patches(ROOT, "android")


def package(ndk, sdk, variant, use_daemon=False):
    """Package the native build into the :app APK (adapted from AeroGauge).

    Libraries are the v1 set only: libmain.so (game), libSDL2.so,
    libc++_shared.so. The Turnip hook libraries (librr64_vulkan.so,
    libmain_hook.so, libhook_impl.so) are NOT packaged: RR64_ANDROID_TURNIP
    is OFF for v1 (system driver only — the probe passed on it). They return
    with the Turnip loader. Runtime assets are native/assets/ (copied next
    to the library by the native POST_BUILD step) plus LatoLatin-Regular.ttf;
    no .syms file is loaded at runtime (codegen-time input only).
    """
    staging = WORK / "package"
    # This directory is exclusively generated by this script. Recreate it so
    # stale files can never become release payload (especially a developer ROM).
    if staging.exists():
        shutil.rmtree(staging)
    libraries = staging / "jniLibs" / "arm64-v8a"
    libraries.mkdir(parents=True)
    native = WORK / "native"
    # v1 set only (no Turnip loader/hook libraries — see docstring).
    for source in [native / "libmain.so", native / "SDL" / "libSDL2.so"]:
        if not source.is_file():
            raise RuntimeError(f"Native library missing (native target not built yet): {source}")
        shutil.copy2(source, libraries)
    host = "windows-x86_64" if os.name == "nt" else "linux-x86_64"
    toolchain = ndk / "toolchains" / "llvm" / "prebuilt" / host
    shutil.copy2(toolchain / "sysroot/usr/lib/aarch64-linux-android/libc++_shared.so", libraries)
    strip = toolchain / "bin" / ("llvm-strip.exe" if os.name == "nt" else "llvm-strip")
    for library in libraries.glob("*.so"):
        run(strip, "--strip-unneeded", library)
    assets = staging / "assets"
    shutil.copytree(native / "assets", assets / "assets")
    shutil.copy2(ROOT / "LICENSE", assets / "LICENSE")
    notices = assets / "licenses"
    notices.mkdir()
    for name, source in {
        "SDL.txt": WORK / "deps/SDL/LICENSE.txt",
        "FreeType.txt": WORK / "deps/freetype/docs/FTL.TXT",
        "AdrenoTools.txt": WORK / "deps/adrenotools/LICENSE",
        "linkernsbypass.txt": WORK / "deps/adrenotools/lib/linkernsbypass/LICENSE",
    }.items():
        shutil.copy2(source, notices / name)
    os.environ["ANDROID_HOME"] = str(sdk)
    wrapper = ROOT / "android" / ("gradlew.bat" if os.name == "nt" else "gradlew")
    command = [wrapper] if os.name == "nt" else ["sh", wrapper]
    gradle_args = [] if use_daemon else ["--no-daemon"]
    run(*command, *gradle_args, ":app:assemble" + variant.capitalize(), cwd=ROOT / "android")
    apk = ROOT / f"android/app/build/outputs/apk/{variant}/app-{variant}.apk"
    with zipfile.ZipFile(apk) as archive:
        for name in archive.namelist():
            if name.lower().endswith((".z64", ".v64", ".n64", ".mpk", ".pak")):
                raise RuntimeError(f"Forbidden game data in APK: {name}")
        for name in ["lib/arm64-v8a/libmain.so", "lib/arm64-v8a/libSDL2.so", "lib/arm64-v8a/libc++_shared.so",
                     "assets/assets/LatoLatin-Regular.ttf"]:
            if name not in archive.namelist():
                raise RuntimeError(f"Missing APK payload: {name}")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    result = dist / f"roadrash64-recompiled-android-arm64{'-debug' if variant == 'debug' else ''}.apk"
    shutil.copy2(apk, result)
    print(f"APK: {result}")
    return result


def _check_build_tools(parser, args, ndk):
    """Fail fast when a tool the build invokes is missing from PATH.

    Runs before the ROM staging / dependency fetching work, so a missing
    tool is a seconds-long clear error instead of a traceback minutes
    into the build (what Ray hit with cmake at the host-tools configure).
    Scoped to the stages that actually need each tool: this is only
    reached on non---package-only runs (package-only runs Gradle only),
    and gcc/g++ are only needed by the host-tools configure on Windows.
    """
    if shutil.which(args.cmake) is None:
        parser.error(
            "CMake is not on PATH. Install it from https://cmake.org/download/ "
            "(tick \"Add CMake to the system PATH\" in the Windows installer), "
            "or pass --cmake with the full path to cmake.exe.")
    if shutil.which("ninja") is None:
        host = "windows-x86_64" if os.name == "nt" else "linux-x86_64"
        suffix = ".exe" if os.name == "nt" else ""
        bundle = "ninja-win.zip" if os.name == "nt" else "ninja-linux.zip"
        parser.error(
            "Ninja is not on PATH (this script uses the Ninja generator). "
            f"The Android NDK already ships one at {ndk}/prebuilt/{host}/bin/ninja{suffix} "
            f"(add that directory to PATH), or download {bundle} from "
            "https://github.com/ninja-build/ninja/releases.")
    if os.name == "nt" and not args.skip_host_tools:
        missing = [compiler for compiler in ("gcc", "g++") if shutil.which(compiler) is None]
        if missing:
            parser.error(
                "MinGW " + " and ".join(missing) + " not found on PATH. "
                "The host-tools step needs a C/C++ compiler (MSYS2 mingw-w64, "
                "or a standalone mingw-w64 — add its bin directory to PATH).")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", action="store_true", help="Require release signing environment variables")
    parser.add_argument("--package-only", action="store_true", help="Package an existing native build without rebuilding")
    parser.add_argument("--native-only", action="store_true", help="Stop after the native CMake build; skip package(). Mirror of --package-only.")
    parser.add_argument("--skip-deps", action="store_true", help="Skip prepare_sources() (pinned deps + Android deps + patches). Only safe when the pinned dependencies are already present at the right revisions — use after a full build, not after a clean checkout.")
    parser.add_argument("--skip-host-tools", action="store_true", help="Skip the host-tools configure+build when N64Recomp, RSPRecomp and file_to_c already exist in build-android/host/bin.")
    parser.add_argument("--skip-codegen", action="store_true", help="Skip the N64Recomp/RSPRecomp runs when the generated code is up to date (hash stamp over the staged ROM, the .toml configs and the translator binaries). Regenerates automatically when any input changes.")
    parser.add_argument("--fast", action="store_true", help="Shorthand for --skip-deps --skip-host-tools --skip-codegen: the normal re-run after a successful full build.")
    parser.add_argument("--gradle-daemon", action="store_true", help="Use the Gradle daemon for :app:assemble (drop --no-daemon). Default stays --no-daemon so CI behaviour is unchanged.")
    parser.add_argument("--install", action="store_true", help="Install the finished APK on the connected device")
    parser.add_argument("--rom", default=None, help="Path to your Road Rash 64 (USA) ROM (.z64, or a .zip containing one)")
    parser.add_argument("--jobs", type=int, default=min(os.cpu_count() or 4, 12))
    parser.add_argument("--sdk", default=os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT"))
    parser.add_argument("--cmake", default="cmake")
    args = parser.parse_args()
    if args.fast:
        args.skip_deps = args.skip_host_tools = args.skip_codegen = True
    if args.package_only and args.native_only:
        parser.error("--package-only and --native-only cannot be combined")
    if args.native_only and args.install:
        parser.error("--install needs the packaged APK; it cannot be combined with --native-only")
    if not args.sdk:
        parser.error("Set ANDROID_HOME or pass --sdk")
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if args.release:
        for key in ["ANDROID_KEYSTORE_PATH", "ANDROID_KEYSTORE_PASSWORD", "ANDROID_KEY_ALIAS", "ANDROID_KEY_PASSWORD"]:
            if not os.environ.get(key):
                parser.error(f"Release signing requires {key}")
    sdk = Path(args.sdk).resolve()
    ndk = sdk / "ndk" / NDK_VERSION
    if not (ndk / "build/cmake/android.toolchain.cmake").is_file():
        parser.error(f"Install Android NDK {NDK_VERSION} with sdkmanager")
    WORK.mkdir(exist_ok=True)

    timings = []
    if args.package_only:
        with _timed(timings, "package"):
            package(ndk, sdk, "release" if args.release else "debug", args.gradle_daemon)
        _print_timings(timings)
        return

    # Prerequisite tools (cmake/ninja/gcc): fail fast here, before any
    # slow work, instead of dying with a traceback mid-build. Scoped
    # inside _check_build_tools: --package-only never reaches this point.
    _check_build_tools(parser, args, ndk)

    # --- Stage the ROM (build machine only, never committed). ---
    # Timed as part of codegen below (the staged ROM is a codegen input).
    stage_start = time.monotonic()
    staged_rom = ROOT / "build/roadrash64.us.z64"
    if args.rom:
        run(sys.executable, "-B", ROOT / "tools/stage_rom.py", args.rom)
    elif not staged_rom.is_file():
        parser.error("Place your Road Rash 64 (USA) ROM with --rom, or stage it first:\n"
                     "  python3 tools/stage_rom.py \"/path/to/Road Rash 64 (USA).z64\"\n"
                     "The ROM is required on the build machine only and is never committed.")
    stage_seconds = time.monotonic() - stage_start

    with _timed(timings, "deps", args.skip_deps):
        if not args.skip_deps:
            prepare_sources()

    # --- Host tools (x86_64): translators + shader embedder. ---
    host = WORK / "host"
    suffix = ".exe" if os.name == "nt" else ""
    with _timed(timings, "host tools", args.skip_host_tools):
        if args.skip_host_tools:
            missing = [name for name in ("N64Recomp", "RSPRecomp", "file_to_c")
                       if not (host / "bin" / f"{name}{suffix}").is_file()]
            if missing:
                raise RuntimeError(
                    "Host tools missing from build-android/host/bin: "
                    + ", ".join(missing)
                    + ". Run a full build (without --skip-host-tools) first.")
        else:
            host_flags = []
            if os.name == "nt":
                host_flags = ["-DCMAKE_C_COMPILER=gcc.exe", "-DCMAKE_CXX_COMPILER=g++.exe"]
            run(args.cmake, "-S", ROOT / "android/host-tools", "-B", host, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release", *host_flags)
            run(args.cmake, "--build", host, "--target", "N64RecompCLI", "RSPRecomp", "file_to_c", "-j", args.jobs)

    # --- Recompilation (BUILD TIME, not on the phone). ---
    # --skip-codegen is a conditional skip, not a force skip: if any input
    # changed (ROM, .toml configs, translator binaries) the stamp no longer
    # matches and codegen runs again. The stamp is refreshed after every
    # codegen run, flag or not, so a later --fast run can skip.
    with _timed(timings, "codegen", args.skip_codegen, stage_seconds):
        if args.skip_codegen and _codegen_is_current(host, suffix):
            print("Codegen outputs up to date (stamp matches); skipping N64Recomp/RSPRecomp.")
        else:
            if args.skip_codegen:
                print("Codegen outputs not up to date; regenerating.")
            run(host / "bin" / f"N64Recomp{suffix}", "config/roadrash64.us.toml")
            run(host / "bin" / f"RSPRecomp{suffix}", "config/roadrash64.us.audio_rsp.toml")
            print(f"RecompiledFuncs generated under {ROOT / 'build/RecompiledFuncs'}")
            _codegen_mark_current(host, suffix)

    # --- NDK cross-compile: the native game target (libmain.so). ---
    # Configure native/ (not the repo root): its CMakeLists includes
    # cmake/Android.cmake, which needs -DRR64_HOST_TOOLS for the host
    # file_to_c / DXC used by the RT64 + RecompFrontend shader steps.
    # RR64_BUILD_TESTS=OFF keeps the offline test targets out of the
    # Android build; RR64_EXPERIMENTAL_COURSE=OFF drops the optional
    # user-ROM course packs (they need the external importer tool).
    # ccache (CI): honour the standard CMAKE_*_COMPILER_LAUNCHER env vars so
    # a cached CI run only recompiles what changed. Local builds are
    # unaffected unless the vars are set.
    ccache_flags = []
    for _var in ("CMAKE_C_COMPILER_LAUNCHER", "CMAKE_CXX_COMPILER_LAUNCHER"):
        _launcher = os.environ.get(_var)
        if _launcher:
            ccache_flags.append(f"-D{_var}={_launcher}")
    with _timed(timings, "native"):
        run(args.cmake, "-S", ROOT / "native", "-B", WORK / "native", "-G", "Ninja",
            f"-DCMAKE_TOOLCHAIN_FILE={ndk.as_posix()}/build/cmake/android.toolchain.cmake",
            "-DANDROID_ABI=arm64-v8a", "-DANDROID_PLATFORM=android-28", "-DANDROID_STL=c++_shared",
            "-DCMAKE_BUILD_TYPE=Release",
            f"-DRR64_HOST_TOOLS={WORK.as_posix()}/host/bin",
            "-DRR64_BUILD_TESTS=OFF", "-DRR64_EXPERIMENTAL_COURSE=OFF",
            *ccache_flags)
        run(args.cmake, "--build", WORK / "native", "--target", "RoadRash64Recompiled", "-j", args.jobs)
    if args.native_only:
        _print_timings(timings)
        print("Native build done (--native-only); libmain.so is under build-android/native.")
        return
    with _timed(timings, "package"):
        apk = package(ndk, sdk, "release" if args.release else "debug", args.gradle_daemon)
    if args.install:
        if shutil.which("adb") is None:
            parser.error("--install needs adb on PATH (Android SDK platform-tools)")
        run("adb", "install", "-r", apk)
    print(f"APK: {apk}")
    print("Next: stage the ROM on the device (see docs/ANDROID_GAME_BUILD.md),")
    print("then launch the app — it auto-starts to the title screen.")
    _print_timings(timings)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
