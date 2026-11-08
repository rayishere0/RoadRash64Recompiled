# Android CI — GitHub Actions build for the full game

The full native build (RT64 + plume + SDL + the recompiled game) takes
~20 minutes cold on a laptop and fails halfway with no saved log. CI runs
it on a Linux runner instead, with ccache + Gradle + dependency caches, and
saves the full log plus the APK. The first build on CI is still ~20
minutes (cold cache, on GitHub's machine, not yours); later builds should
be minutes.

## What CI does

Workflow: `.github/workflows/android.yml`. It runs on:

- every push to `main`,
- every pull request targeting `main`,
- manually, from the Actions tab (Run workflow).

Steps: check out the repo → fail fast if the ROM secrets are missing →
JDK 17 + Ninja + ccache → Android SDK + NDK 28.2.13676358 (exact, the
version `scripts/build_android.py` requires) → restore caches → fetch the
ROM from the private repo → `python3 scripts/build_android.py --rom …`
→ upload the APK (`dist/roadrash64-recompiled-android-arm64-debug.apk`)
on success, or the full `build.log` on failure. A new push cancels any
in-progress run for the same branch. Runs time out after 60 minutes.

The APK artifact is kept for 30 days.

## The ROM — one-time setup (Ray only)

The build needs your Road Rash 64 (USA).z64 at build time. It must NEVER
be committed to this public repo. CI fetches it from a private repo using
two repository secrets:

1. **Create a private repo** (e.g. `rayishere0/rr64-rom-private`).
   Put exactly one file at its root: `Road Rash 64 (USA).z64`. Nothing
   else needs to be in it. The ROM is 32 MiB, which is over GitHub's
   25 MB web-upload limit — add it with git (`clone`, copy the file in,
   `add` / `commit` / `push`), not the web UI. The workflow takes the
   single `.z64` at the root and passes it to `--rom`;
   `tools/stage_rom.py` verifies it (32 MiB, SHA-1
   `87727a298f583ec8325f5655088ff21e37b335b2`) and rejects anything else.
2. **Create a fine-grained personal access token** (GitHub → Settings →
   Developer settings → Personal access tokens → Fine-grained tokens):
   Repository access → "Only select repositories" → the private ROM repo
   → Permissions → Contents: **Read-only**. Nothing else.
3. **Add the secrets on this fork** (repo → Settings → Secrets and
   variables → Actions → New repository secret):
   - `ROM_REPO` = `rayishere0/rr64-rom-private` (the `owner/repo` of the
     private repo from step 1)
   - `ROM_REPO_TOKEN` = the token from step 2

The token is only used to clone the private repo inside the run. It is
never printed — GitHub masks secret values in logs automatically — and
the workflow never echoes it or the ROM bytes.

## Until the secrets exist

The first CI run will **fail fast in the first minute** with
"ROM_REPO / ROM_REPO_TOKEN secrets are not set on this repo" — that is
expected, not a build error. Add the secrets (above), then re-run:
Actions tab → "Android (full game)" → the failed run → "Re-run jobs".

The same applies to the pull request that adds this workflow: its CI run
fails fast until the secrets are set. That is fine — merge the workflow
first, add the secrets, then re-run.

## Getting the APK

Actions tab → "Android (full game)" → the run → Artifacts →
`roadrash64-recompiled-android-arm64-debug`. Download, then install and
stage the ROM on the device exactly as in `docs/ANDROID_GAME_BUILD.md`
(`adb install -r`, `adb push` + `run-as … cp`, launch `GameActivity`).

## When a build fails

Download the `build-log` artifact from the failed run (same place as the
APK above). It is the full output of `scripts/build_android.py`. The
failing stage is at the end of the log: dependency fetch, host tools,
N64Recomp/RSPRecomp codegen, NDK compile of `libmain.so`, or Gradle
packaging. Send the tail of the log (the failing command and the error
lines) — that is what a fix needs.

To re-run a failed build without a new push: Actions tab → the failed run
→ "Re-run jobs". A re-run reuses the caches, so it is much faster than
the first build.

## Local builds still work

Nothing about the local path changed: `python3 scripts/build_android.py
--rom …` still builds on Windows as before. The one script change in this
work is ccache support: `scripts/build_android.py` now honours the
standard `CMAKE_C_COMPILER_LAUNCHER` / `CMAKE_CXX_COMPILER_LAUNCHER`
environment variables on the native configure step (CI sets them to
`ccache`). Local builds are unaffected unless you set those variables
yourself.
