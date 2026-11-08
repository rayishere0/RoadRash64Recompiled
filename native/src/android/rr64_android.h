// Android bridge for the Road Rash 64 game target.
// Adapted from AeroGauge's src/android/aero_android.h (same N64Recomp stack).
// Only the pieces the title-screen build needs: lifecycle JNI, storage/env
// setup, and the foreground wait. Touch input, motion and the Vulkan loader
// (Turnip) are later steps and are deliberately NOT declared here: every
// native method declared in GameActivity.java must exist in this library.
#pragma once

#include <cstdint>

#include <SDL.h>

namespace rr64::android {

// First call in SDL_main (Android only). Resolves the app's internal storage
// path, publishes RR64_ANDROID_DATA_DIR / APP_FOLDER_PATH, chdirs there and
// redirects stdout/stderr to native.log. Returns false on failure.
bool initialize();

// Writes message to startup-error.txt in internal storage and exits the
// (separate :game) process immediately.
[[noreturn]] void startup_error(const char* message);

// Blocks until the activity returns to the foreground. Called from the game
// loop when backgrounded; holds no SDL or runtime locks. Wired by the touch
// phase; present now so the JNI side has a complete lifecycle contract.
void wait_foreground();

} // namespace rr64::android
