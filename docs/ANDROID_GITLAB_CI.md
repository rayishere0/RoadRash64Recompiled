# Android CI — GitLab pipeline for the full game

The full native build (RT64 + plume + SDL + the recompiled game) takes
~20 minutes cold on a laptop and fails halfway with no saved log. CI runs
it on a Linux runner instead, with ccache + Gradle + dependency caches, and
saves the full log plus the APK. The first build on CI is still ~20
minutes (cold cache, on GitLab's machine, not yours); later builds should
be minutes.

## Why GitLab, not GitHub Actions

There is already a GitHub Actions workflow for this build
(`.github/workflows/android.yml`, still on main). It cannot run: GitHub
has locked Ray's account out of running Actions ("The job was not started
because your account is locked due to a billing issue"), and that cannot
be fixed right now. This GitLab pipeline is a translation of that
workflow — same build, same requirements, different runner. If the GitHub
billing lock is ever lifted, either CI works; the GitHub workflow needs
the `ROM_REPO` / `ROM_REPO_TOKEN` secrets on the fork, which are already
set.

## What the pipeline does

Pipeline: `.gitlab-ci.yml`. It runs on:

- every push to `main`,
- every merge request.

(and nothing else — ordinary branch pushes do not run it, so they do not
burn compute minutes.)

Steps: check out the repo → fail fast if the ROM variables are missing →
install the toolchain (gcc/g++, CMake, Ninja, ccache, git, Python) →
Android SDK + NDK 28.2.13676358 (exact, the version
`scripts/build_android.py` requires) → restore caches → fetch the ROM
from the private project → `python3 scripts/build_android.py --rom …`
→ upload the APK (`dist/roadrash64-recompiled-android-arm64-debug.apk`)
and the full `build.log` as job artifacts. A new push cancels any
in-progress run for the same branch (`interruptible: true`). Jobs time
out after 1 hour.

Artifacts are kept for 30 days.

## Runner size and the minutes budget

The job runs on a **medium** GitLab SaaS runner
(`saas-linux-medium-amd64`), cost factor **2×** on the Free tier's
**400 compute minutes/month**. Small (1×) has too few cores for a
parallel NDK build — the wall time roughly doubles, so it burns about the
same minutes for a much slower result and risks the 1-hour timeout on a
cold build. Large (3×) buys little. Medium is the sweet spot.

Rough budget (medium, 2×): a cold build is ~25–35 minutes of wall time,
so ~50–70 compute minutes. A cached rebuild is ~5–10 minutes of wall
time, so ~10–20 compute minutes. That is roughly **one cold build plus
~20 cached rebuilds per month**, or ~6 cold builds. If the quota ever
runs out, pipelines stop starting new jobs until next month (extra
minutes cost $10 per 1,000). If builds get slow, the size can be raised
to large later — it costs 3×, so only do it deliberately.

## Setup — one time (Ray only)

### 1. GitLab account

Create an account at https://gitlab.com (Free tier is enough).

### 2. Main project — push, do not mirror

GitLab's **pull mirroring** (Settings → Repository → Mirroring,
direction Pull, from the GitHub URL) is a **Premium-only** feature — a
Free namespace does not get the option, and neither does the "Run CI/CD
for external repository" feature. So the free path is to push the code to
GitLab as a second remote:

1. Create a **blank project** on GitLab, public, named
   `RoadRash64Recompiled` (your namespace, e.g.
   `rayishere0/RoadRash64Recompiled`). Do not use "Import project" —
   a blank project plus a push is the same result and stays in your
   control.
2. In your local clone of the GitHub repo (the one you build from, e.g.
   `D:/road rash port`), add GitLab as a second remote and push main:
   ```
   git remote add gitlab https://gitlab.com/rayishere0/RoadRash64Recompiled.git
   git push gitlab main
   ```
   Use your own GitLab username in place of `rayishere0` if it differs.
3. From now on, every push goes to **both** remotes: `git push origin
   main` (GitHub) and `git push gitlab main` (GitLab). Only the GitLab
   push starts a pipeline. The `.gitlab-ci.yml` must be on main in the
   GitLab project — so merge the PR that adds it on GitHub first, then
   push main to GitLab.

### 3. ROM project — private, on GitLab

The build needs your Road Rash 64 (USA).z64 at build time. It must NEVER
be committed to the public repo. CI fetches it from a private GitLab
project:

1. Create a **private** project on GitLab, e.g.
   `rayishere0/rr64-rom-private`. Put exactly one file at its root:
   `Road Rash 64 (USA).z64`. Nothing else needs to be in it. The ROM is
   32 MiB — add it with git, not the web UI. You already have it in a
   local clone (`D:\rr64-rom-private`): add the GitLab remote there and
   push:
   ```
   git remote add gitlab https://gitlab.com/rayishere0/rr64-rom-private.git
   git push gitlab main
   ```
   The pipeline takes the single `.z64` at the root and passes it to
   `--rom`; `tools/stage_rom.py` verifies it (32 MiB, SHA-1
   `87727a298f583ec8325f5655088ff21e37b335b2`) and rejects anything else.

### 4. Token — read-only, on the ROM project

1. On the **ROM project** (not the main one): Settings → Access Tokens
   → Add new token. Name it e.g. `rr64-ci-rom-read`, role **Reporter**,
   scopes: **read_repository** only. Nothing else. Copy the token —
   GitLab shows it once.
2. On the **main project**: Settings → CI/CD → Variables → Add
   variable, twice:
   - `ROM_REPO` = `rayishere0/rr64-rom-private` (the `group/project`
     path of the private project from step 3)
   - `ROM_REPO_TOKEN` = the token from step 1
   For **both**: tick **Mask variable** (GitLab hides the value in job
   logs), and do **not** tick **Protect variable** — protected variables
   are only available to pipelines on protected branches, so a merge
   request pipeline would not get the token and would fail fast.

The token is only used to clone the private project inside the run. It
is never printed — masked variables are hidden in logs automatically —
and the pipeline never echoes it or the ROM bytes.

## Until the variables exist

The first pipeline will **fail fast in the first minute** with
"ROM_REPO / ROM_REPO_TOKEN CI variables are not set on this project" —
that is expected, not a build error. Add the variables (above), then
re-run: CI/CD → Pipelines → the failed pipeline → Retry (or the failed
job → Retry).

The same applies to the merge request that adds this pipeline: its
pipeline fails fast until the variables are set. That is fine — merge
the pipeline first, add the variables, then re-run.

## Getting the APK

CI/CD → Pipelines → the run → the `android-build` job → on the right,
"Job artifacts" → Download. The download is a zip containing `build.log`
and `dist/roadrash64-recompiled-android-arm64-debug.apk`. Install and
stage the ROM on the device exactly as in `docs/ANDROID_GAME_BUILD.md`
(`adb install -r`, `adb push` + `run-as … cp`, launch `GameActivity`).

## When a build fails

Open the failed `android-build` job and read the job log first — the
failing stage is at the end: dependency fetch, host tools, N64Recomp /
RSPRecomp codegen, NDK compile of `libmain.so`, or Gradle packaging. The
full `build.log` is also in the job artifacts (same download as the APK
above). Send the tail of the log (the failing command and the error
lines) — that is what a fix needs.

To re-run a failed build without a new push: CI/CD → Pipelines → the
failed pipeline → Retry. A re-run reuses the caches, so it is much
faster than the first build.

## Local builds still work

Nothing about the local path changed: `python3 scripts/build_android.py
--rom …` still builds on Windows as before. The script honours the
standard `CMAKE_C_COMPILER_LAUNCHER` / `CMAKE_CXX_COMPILER_LAUNCHER`
environment variables on the native configure step (this pipeline sets
them to `ccache`). Local builds are unaffected unless you set those
variables yourself.
