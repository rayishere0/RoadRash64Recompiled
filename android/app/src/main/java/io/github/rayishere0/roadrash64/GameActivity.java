package io.github.rayishere0.roadrash64;

import android.app.AlertDialog;
import android.os.Bundle;
import android.os.Looper;
import android.system.Os;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.Toast;
import org.libsdl.app.SDLActivity;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;

/**
 * Game host activity for the Road Rash 64 Android port.
 *
 * This is the SDL activity only — it is NOT the launcher. The real
 * LauncherActivity (ROM picker, ROM import, driver import) lands in a later
 * step; until then the manifest launches this activity directly and the ROM
 * is staged manually (see docs/ANDROID_GAME_BUILD.md). No touch controls
 * yet either: keyboard/gamepad only in this phase.
 *
 * Adapted from AeroGauge's GameActivity.java (same N64Recomp stack), minus
 * touch controls, motion rotation and the Turnip driver import — the probe
 * passed on the system driver, so v1 runs system-only.
 */
public final class GameActivity extends SDLActivity {
    static native void nativeBackground(boolean background);
    static native void nativeRequestQuit();

    private boolean librariesReady;
    private boolean resumed;

    @Override protected String[] getLibraries() {
        // Exactly the probe's proven set (ProbeActivity.java).
        return new String[]{"c++_shared", "SDL2", "main"};
    }

    @Override public void loadLibraries() {
        try {
            // The ROM path the native side auto-starts from
            // (RR64_ANDROID_ROM_PATH). Later the launcher writes this file;
            // in this phase it is staged manually with adb (see
            // docs/ANDROID_GAME_BUILD.md). The native side only uses it when
            // the file exists and falls back to the stored ROM otherwise.
            Os.setenv("RR64_ANDROID_ROM_PATH",
                new File(getFilesDir(), "Road Rash 64 (USA).z64").getAbsolutePath(), true);
            super.loadLibraries();
            librariesReady = true;
        } catch (Exception error) {
            try {
                Files.write(new File(getFilesDir(), "startup-error.txt").toPath(),
                    ("Cannot start graphics: " + error.getMessage()).getBytes(StandardCharsets.UTF_8));
            } catch (Exception ignored) { }
            throw new IllegalStateException("Cannot start graphics: " + error.getMessage(), error);
        }
    }

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        if (!librariesReady) { finish(); return; }
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        try {
            copyAssetsIfNeeded();
        } catch (Exception error) {
            Toast.makeText(this, "Cannot prepare game files: " + error.getMessage(), Toast.LENGTH_LONG).show();
            finish();
            return;
        }
        immersive();
    }

    // Copies the APK's assets/ (fonts, RmlUi stylesheet, launcher art) into
    // internal storage once per install, where RecompFrontend resolves them
    // relative to the working directory. Stamped by lastUpdateTime so an app
    // update re-copies. Adapted from AeroGauge's LauncherActivity.
    private void copyAssetsIfNeeded() throws Exception {
        long packageStamp = getPackageManager().getPackageInfo(getPackageName(), 0).lastUpdateTime;
        android.content.SharedPreferences preferences = getSharedPreferences("player", 0);
        File assets = new File(getFilesDir(), "assets");
        if (preferences.getLong("assets_stamp", 0) == packageStamp && assets.isDirectory()) return;
        copyAsset("assets");
        preferences.edit().putLong("assets_stamp", packageStamp).apply();
    }

    private void copyAsset(String path) throws Exception {
        String[] children = getAssets().list(path);
        File destination = new File(getFilesDir(), path);
        if (children != null && children.length > 0) {
            if (!destination.isDirectory() && !destination.mkdirs()) throw new IOException("Cannot prepare game files.");
            for (String child : children) copyAsset(path + "/" + child);
        } else {
            try (InputStream input = getAssets().open(path)) {
                Files.copy(input, destination.toPath(), StandardCopyOption.REPLACE_EXISTING);
            }
        }
    }

    private void immersive() {
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN
            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
            | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
    }

    @Override public void onWindowFocusChanged(boolean focus) {
        super.onWindowFocusChanged(focus);
        if (focus) immersive();
    }

    @Override protected void onResume() {
        super.onResume();
        resumed = true;
        if (librariesReady) nativeBackground(false);
        immersive();
    }

    @Override protected void onPause() {
        resumed = false;
        if (librariesReady) nativeBackground(true);
        super.onPause();
    }

    @Override public void onBackPressed() { showActions(); }

    public void showActions() {
        if (Looper.myLooper() != Looper.getMainLooper()) {
            runOnUiThread(this::showActions);
            return;
        }
        nativeBackground(true);
        new AlertDialog.Builder(this).setTitle("Road Rash 64")
            .setOnDismissListener(dialog -> { if (resumed) nativeBackground(false); })
            .setItems(new String[]{"Resume", "Graphics & enhancements", "Exit to launcher"}, (dialog, which) -> {
                if (which == 1) {
                    // Opens the RecompFrontend settings screen; free, no native work.
                    onNativeKeyDown(KeyEvent.KEYCODE_ESCAPE);
                    new android.os.Handler(getMainLooper()).postDelayed(() -> onNativeKeyUp(KeyEvent.KEYCODE_ESCAPE), 80);
                } else if (which == 2) nativeRequestQuit();
            }).show();
    }
}
