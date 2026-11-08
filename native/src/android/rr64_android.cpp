// Android bridge for the Road Rash 64 game target.
// Adapted from AeroGauge's src/android/aero_android.cpp (same N64Recomp
// stack). Kept minimal for the title-screen build: lifecycle JNI, storage
// setup, foreground wait. No touch input, no motion, no Vulkan loader
// (Turnip is Adreno-only; the probe passed on the system driver).
#include "rr64_android.h"

#include <jni.h>

#include <SDL_system.h>

#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <mutex>
#include <string>
#include <unistd.h>

namespace {
std::mutex lifecycle_mutex;
std::condition_variable foreground;
bool background = false;
} // namespace

extern "C" JNIEXPORT void JNICALL
Java_io_github_rayishere0_roadrash64_GameActivity_nativeBackground(JNIEnv*, jclass, jboolean value) {
    {
        std::lock_guard lock(lifecycle_mutex);
        background = (value == JNI_TRUE);
    }
    foreground.notify_all();
}

extern "C" JNIEXPORT void JNICALL
Java_io_github_rayishere0_roadrash64_GameActivity_nativeRequestQuit(JNIEnv*, jclass) {
    {
        std::lock_guard lock(lifecycle_mutex);
        background = false;
    }
    foreground.notify_all();
    SDL_Event event{};
    event.type = SDL_QUIT;
    SDL_PushEvent(&event);
}

namespace rr64::android {

[[noreturn]] void startup_error(const char* message) {
    if (FILE* file = std::fopen("startup-error.txt", "w")) {
        std::fputs(message, file);
        std::fclose(file);
    }
    std::fprintf(stderr, "[RR64-ANDROID] %s\n", message);
    std::_Exit(1); // Confined to the :game process; the launcher displays the error.
}

void wait_foreground() {
    std::unique_lock lock(lifecycle_mutex);
    if (!background) {
        return;
    }
    // No EEPROM/config flush exists yet (Controller Pak saves are later
    // work); the wait itself is the contract the touch phase will use.
    foreground.wait(lock, [] { return !background; });
}

bool initialize() {
    const char* storage = SDL_AndroidGetInternalStoragePath();
    if (storage == nullptr) {
        return false;
    }
    setenv("RR64_ANDROID_DATA_DIR", storage, 1);
    const std::string config = (std::filesystem::path(storage) / "RoadRash64Recompiled").string();
    setenv("APP_FOLDER_PATH", config.c_str(), 1);
    std::error_code error;
    std::filesystem::current_path(storage, error);
    if (error) {
        return false;
    }
    // Keep native diagnostics available for the later launcher's diagnostics.
    FILE* output = std::freopen("native.log", "w", stdout);
    if (output != nullptr) {
        dup2(fileno(stdout), fileno(stderr));
        setvbuf(stdout, nullptr, _IONBF, 0);
    }
    SDL_SetHint(SDL_HINT_ORIENTATIONS, "LandscapeLeft LandscapeRight");
    return true;
}

} // namespace rr64::android
