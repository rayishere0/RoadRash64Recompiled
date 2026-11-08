cmake_minimum_required(VERSION 3.20)
project(RoadRash64Recompiled LANGUAGES C CXX)

# Keep the entry point a build-order map; each module owns one responsibility.
include(cmake/ProjectOptions.cmake)
if(ANDROID)
    # Android native-dependency config (SDL/FreeType from source, host DXC,
    # Turnip gating). Must precede Dependencies.cmake: its Android branches
    # FATAL_ERROR without RR64_ANDROID_SDL2_INCLUDE_DIRS / RR64_HOST_DXC.
    include(${CMAKE_CURRENT_SOURCE_DIR}/../cmake/Android.cmake)
    # ProjectOptions forces all library output under bin/; build_android.py
    # package() expects the AeroGauge layout instead: each target in its own
    # binary dir (game lib at the build root, SDL under SDL/, assets staged
    # next to the game lib by the POST_BUILD copy in Application.cmake).
    # Unset — do not point at the build root — or SDL's library would land
    # there too instead of under SDL/.
    unset(CMAKE_LIBRARY_OUTPUT_DIRECTORY)
    unset(CMAKE_RUNTIME_OUTPUT_DIRECTORY)
    foreach(CONFIG DEBUG RELEASE RELWITHDEBINFO MINSIZEREL)
        unset(CMAKE_LIBRARY_OUTPUT_DIRECTORY_${CONFIG})
        unset(CMAKE_RUNTIME_OUTPUT_DIRECTORY_${CONFIG})
    endforeach()
endif()
include(cmake/Dependencies.cmake)
include(cmake/ReplayWorkers.cmake)
include(cmake/Application.cmake)

# ON preserves existing verification scripts. Ordinary source builds can omit
# offline fixture generation with -DRR64_BUILD_TESTS=OFF.
option(RR64_BUILD_TESTS "Configure the ROM-free/offline regression targets" ON)
if(RR64_BUILD_TESTS)
    include(cmake/OfflineTests.cmake)
endif()
