# android/app/ — full-game module (native target wired in; launcher/touch/saves still to come)

The native game target exists now: `native/` builds the shared `main`
library (`libmain.so`, SDLActivity loads it), `GameActivity.java` is the SDL
host, and `android/settings.gradle` includes `:app`. The probe
(`android/probe/`) stays buildable alongside it.

## What exists here

- `build.gradle` — the app-module config, adapted from AeroGauge (AGP 8.9.2,
  NDK 28.2.13676358, compileSdk/targetSdk 35, minSdk 28, arm64-v8a only,
  version from `RR64_VERSION`, release signing from env,
  `useLegacyPackaging=true` for the AdrenoTools Turnip hooks if they ever
  land). No `externalNativeBuild`: `scripts/build_android.py` drives CMake
  directly and Gradle only packages the prebuilt `.so`s.
- `src/main/AndroidManifest.xml` — Vulkan 1.1 feature gate, `GameActivity`
  in a separate `:game` process, `sensorLandscape`, `singleTask`. For now
  `GameActivity` is also the launcher (temporary — see below).
- `src/main/java/.../GameActivity.java` — SDLActivity host: loads
  `c++_shared`, `SDL2`, `main` (the probe's proven set); sets
  `RR64_ANDROID_ROM_PATH` for the native auto-start; copies APK `assets/`
  into internal storage once per install; Back opens Resume / Graphics /
  Exit. No touch controls yet.

## What is still missing (later steps, AFTER this build lands)

- `src/main/java/.../LauncherActivity.java` — SAF ROM picker, ROM import +
  hash check, Turnip driver import (adapt AeroGauge's). When it lands, the
  `MAIN`/`LAUNCHER` intent-filter moves from `GameActivity` back to it and
  `GameActivity` becomes `exported=false` again.
- `src/main/java/.../RomImport.java` — 32 MiB size + byte-order
  normalisation + **SHA-1** gate (see `docs/ANDROID_PROBE.md`, "File-picker
  model" — the runtime re-checks XXH3-64; do NOT copy AeroGauge's SHA-256).
- `src/main/java/.../DriverImport.java`, `TouchControls.java`,
  `SaveTransfer.java` — adapt from AeroGauge (touch controls are a
  redesign for Road Rash: throttle/brake/punch/kick/weapon).
- `native/src/android/rr64_vulkan_loader.cpp` — the app-local
  `vkGetInstanceProcAddr` (system driver vs Turnip). Only needed if a
  device fails `setup()` with `GraphicsDeviceNotFound`; gated behind
  `RR64_ANDROID_TURNIP` (OFF) in `cmake/Android.cmake`.
- Controller Pak saves: desktop has no persistent save at all today
  (`SaveType::None`), so there is nothing to port yet — it is a
  Road Rash-specific runtime task, not a regression.
- Launcher icon (reuse `native/assets/RoadRashIcon.png`).

## How the game starts in this phase (no launcher yet)

`GameActivity` sets `RR64_ANDROID_ROM_PATH` to
`<filesDir>/Road Rash 64 (USA).z64` and the native `SDL_main` auto-starts
from it when the file exists (`--skip-launcher` + `--auto-rom` behaviour,
reusing the existing `main.cpp` machinery). The ROM is staged manually
with `adb` — see `docs/ANDROID_GAME_BUILD.md`. Once validated,
`recomp::select_rom` stores its own copy under the app folder, so later
launches auto-start even if the staged file is gone.
