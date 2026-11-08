# RR64 Android — full-game native build

The actual recompiled game building and launching on Android, to the title
screen. The RT64 probe (`android/probe/`, `scripts/build_probe.py`) proved
SDL + RT64 + present on device; this phase turns the desktop game into the
Android shared library the probe's path loads.

**Not compile-checked:** no NDK / Android Studio / ROM on the author's
machine. Every step below must be run on Ray's Windows machine.

## What was built

- **Native game target** (`native/cmake/Application.cmake`): on Android the
  desktop executable becomes a shared library named `main` (`libmain.so`),
  same ~125 sources + `RecompiledFuncs`, plus the new Android bridge
  (`native/src/android/rr64_android.cpp`). Desktop build untouched.
- **Android entry** (`native/src/main.cpp`): `SDL_main` on Android (the
  probe's proven pattern — `SDL_MAIN_HANDLED`, no `SDL2main`), calling
  `rr64::android::initialize()` first (internal storage, `APP_FOLDER_PATH`,
  `native.log`), then the shared startup. Auto-start is the existing
  `--skip-launcher` + `--auto-rom` machinery: the staged ROM path comes
  from the `RR64_ANDROID_ROM_PATH` env var (set by `GameActivity`), and
  `on_launcher_update` starts the game once the renderer is ready and
  `recomp::is_rom_valid()`. `NFD_Init`/`NFD_Quit` and the `nfd.h` include
  are guarded out on Android (no file dialogs — the launcher owns import).
- **JNI bridge** (`native/src/android/rr64_android.{h,cpp}`): adapted from
  AeroGauge — `nativeBackground` / `nativeRequestQuit`, storage/env setup,
  foreground wait. No touch, motion or Vulkan loader in this phase.
- **Game host** (`android/app/.../GameActivity.java`): SDLActivity, loads
  `c++_shared`, `SDL2`, `main`; copies APK `assets/` (fonts, RmlUi
  stylesheet, launcher art) into internal storage once per install; Back
  opens Resume / Graphics / Exit. The manifest launches `GameActivity`
  directly until the real `LauncherActivity` lands.
- **Build wiring**: `native/CMakeLists.txt` includes `cmake/Android.cmake`
  before `Dependencies.cmake`; `cmake/Android.cmake` now derives the repo
  root from its own location (it assumed `CMAKE_SOURCE_DIR` was the root,
  but the build configures `-S native`) and gates AdrenoTools behind
  `RR64_ANDROID_TURNIP` (OFF for v1 — system driver only, the probe passed
  on it). `android/settings.gradle` includes `:app`. `scripts/build_android.py`
  implements the native stage (configure + build + `:app:assemble` +
  optional `--install`).
- **Out of scope on purpose**: launcher UI / ROM picker, touch controls,
  Controller Pak saves (desktop has no persistent save today —
  `SaveType::None`), Turnip driver import, experimental course packs
  (`RR64_EXPERIMENTAL_COURSE=OFF`), offline test targets
  (`RR64_BUILD_TESTS=OFF`), custom-soundtrack FFmpeg decoding.

## Build (Ray's Windows machine)

Prereqs: Python 3.11+, Git, CMake 3.22+, Ninja, JDK 17, MinGW-w64 GCC/G++
(host tools need `gcc.exe`/`g++.exe`), Android SDK with
`platforms;android-35`, `build-tools;35.0.0`, `ndk;28.2.13676358`. The ROM
is needed **on the build machine only**, never committed.

```bat
:: one-time SDK env (or pass --sdk to the script)
set ANDROID_HOME=C:\Users\<you>\AppData\Local\Android\Sdk

:: full build: deps + host tools + build-time recompile + NDK build + APK
python scripts\build_android.py --rom "C:\YourDumps\Road Rash 64 (USA).z64" --jobs 8

:: release APK (requires the four ANDROID_KEYSTORE_* env vars; debug otherwise)
python scripts\build_android.py --rom "C:\YourDumps\Road Rash 64 (USA).z64" --release --install

:: rebuild native only after the first run (deps/host tools/ROM staging cached)
python scripts\build_android.py --rom "C:\YourDumps\Road Rash 64 (USA).z64" --package-only
```

Output: `dist\roadrash64-recompiled-android-arm64-debug.apk`
(or `-release` without `-debug`).

What the script runs underneath (for diagnosis when it breaks):

```bat
cmake -S native -B build-android/native -G Ninja ^
  -DCMAKE_TOOLCHAIN_FILE=%ANDROID_HOME%\ndk\28.2.13676358\build\cmake\android.toolchain.cmake ^
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-28 -DANDROID_STL=c++_shared ^
  -DCMAKE_BUILD_TYPE=Release -DRR64_HOST_TOOLS=build-android/host/bin ^
  -DRR64_BUILD_TESTS=OFF -DRR64_EXPERIMENTAL_COURSE=OFF
cmake --build build-android/native --target RoadRash64Recompiled -j 8
android\gradlew.bat --no-daemon :app:assembleDebug
```

## Stage the ROM on the device (no launcher yet)

The debug APK is debuggable, so the ROM can be pushed with `run-as`:

```bat
adb install -r dist\roadrash64-recompiled-android-arm64-debug.apk
adb push "C:\YourDumps\Road Rash 64 (USA).z64" /data/local/tmp/roadrash64.us.z64
adb shell run-as io.github.rayishere0.roadrash64 cp /data/local/tmp/roadrash64.us.z64 files/"Road Rash 64 (USA).z64"
adb shell am start -n io.github.rayishere0.roadrash64/.GameActivity
```

The file must be the USA v1.0 ROM: 32 MiB, SHA-1
`87727a298f583ec8325f5655088ff21e37b335b2` (the build script verifies it
when staging). The game re-checks it at runtime (XXH3-64
`0x517F53BCD9D13BF2`) and stores its own copy under the app folder, so
later launches auto-start even if the staged file is deleted.

## Expected outcome

The app opens straight to the Road Rash 64 title screen (the
RecompFrontend launcher auto-starts into the game once the stored ROM
validates, then hides itself). Keyboard/gamepad navigate; there are no
touch controls yet, so menu navigation by touch will not work — that is
the next step, not a bug in this one.

## Logcat checks (first run)

- `[RR64-STAGE] App/config folder: ...` — confirm the config landed under
  internal storage (`/data/data/io.github.rayishere0.roadrash64/files/...`).
  `APP_FOLDER_PATH` honoring by RecompFrontend is assumed from AeroGauge
  (unverifiable without the fetched RecompFrontend tree); if the folder
  shows up elsewhere, say so — the bridge's `chdir(storage)` is the
  fallback that keeps relative paths inside internal storage either way.
- `[RR64-AUTO] Validating developer ROM: ...` then `ROM validation
  result=0` (Good), then `[RR64-AUTO] Renderer and launcher ready;
  starting staged ROM from UI thread.`
- `native.log` in internal storage holds the native stdout/stderr copy.

## Resize / rotation

Do **not** test resize with `SDL_SetWindowSize` — on Android the window
size is owned by the surface, and the probe's unchanged swapchain after
its resize step was that false negative, not a broken resize path. The
real test is rotating the device 90° mid-title-screen (and a 180°
landscape flip) and confirming via logcat that the swapchain size follows.
The manifest keeps the full `configChanges` list so Android does not
destroy the activity (and RT64's swapchain) on rotation, and the game
already pumps SDL events on its event thread.

## Known gaps / next steps

1. **Launcher** (`LauncherActivity`, `RomImport`): SAF picker, SHA-1
   import, Turnip driver import UI. When it lands, the launcher
   intent-filter moves from `GameActivity` back to it.
2. **Touch controls**: steering, throttle/brake, punch/kick — a redesign
   for Road Rash (AeroGauge's touch steering is the reference).
3. **Controller Pak saves**: a Road Rash-specific runtime task; desktop
   has none today.
4. **Turnip fallback**: if a device fails `setup()` with
   `GraphicsDeviceNotFound`, land `rr64_vulkan_loader.cpp` + flip
   `RR64_ANDROID_TURNIP` on. System driver only for v1.

## Risks (most likely to fail first)

1. **`package()` `.so` paths vs output dirs.** `ProjectOptions.cmake`
   forces library output under `bin/`; `native/CMakeLists.txt` now unsets
   those variables for Android so outputs land in each target's own binary
   dir (AeroGauge layout: game lib at the build root, SDL under `SDL/`,
   POST_BUILD assets next to the game lib). If the first build puts a
   `.so` elsewhere, fix `package()` to look there — do not move the game
   lib. Note the trap this avoids: pointing the output dir at the build
   root would also move SDL's library out of `SDL/`.
2. **`cmake/Android.cmake` root paths.** Fixed by deriving the root from
   the file's location; if configure fails at the `file_to_c` existence
   check or the SDL `add_subdirectory`, that fix did not take.
3. **`SDL_main` vs `SDL2main`.** The probe proves `SDL_main` + no
   `SDL2main` for the probe's link set. The game links more (recompui /
   librecomp / ultramodern, and RT64's CMake may add `SDL2main` to a link
   list). If the native link fails on a duplicate/undefined entry point,
   mirror AeroGauge's `SDL2main` handling for `ANDROID`.
4. **Replay workers.** `ReplayWorkers.cmake` generates sources from the
   recompiled funcs at build time; they are only used by `--replay-case`
   but are compiled into the game. If they fail to cross-compile, they
   are droppable for Android.
5. **Voice chat / mic.** The game runs a voice-chat service thread; whether
   it opens the mic at startup (no `RECORD_AUDIO` permission in the
   manifest) is unverified — check before first run.
6. **Desktop-first defaults.** Graphics defaults come from desktop
   (resolution/MSAA assumptions). If the title screen looks wrong, check
   what `init_recompui_config` defaults to and force sane mobile values.
7. **RT64's own `ANDROID_PLATFORM android-24` hardcode** in its
   `CMakeLists.txt` (probe README known quirk) — harmless so far, first
   place to look if the NDK build misbehaves. RT64 also builds
   `texture_hasher`/`texture_packer` executables for the target as part of
   `all`; if they fail to cross-compile, gate them out (never run at
   build time).
