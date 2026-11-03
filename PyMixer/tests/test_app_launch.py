"""Unit tests for app_launch resolve/launch helpers (no real GUI)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_launch


class AppLaunchTests(unittest.TestCase):
    def test_normalize_strips_launch_prefix(self):
        self.assertEqual(app_launch.normalize_launch_target("launch:notepad.exe"), "notepad.exe")
        self.assertEqual(app_launch.normalize_launch_target("  chrome.exe "), "chrome.exe")

    def test_protocol_detection(self):
        self.assertTrue(app_launch.looks_like_protocol("steam://run/440"))
        self.assertTrue(app_launch.looks_like_protocol("spotify:track:abc"))
        self.assertTrue(app_launch.looks_like_protocol("https://example.com"))
        self.assertTrue(app_launch.looks_like_protocol("www.youtube.com"))
        self.assertFalse(app_launch.looks_like_protocol(r"C:\Program Files\App\app.exe"))
        self.assertFalse(app_launch.looks_like_protocol("notepad.exe"))

    def test_resolve_protocol(self):
        path, params = app_launch.resolve_target("steam://open/library")
        self.assertEqual(path, "steam://open/library")
        self.assertEqual(params, "")
        path, _ = app_launch.resolve_target("www.example.com")
        self.assertEqual(path, "https://www.example.com")

    def test_resolve_existing_file(self):
        with tempfile.TemporaryDirectory() as td:
            exe = os.path.join(td, "Cool App.exe")
            open(exe, "wb").close()
            path, params = app_launch.resolve_target(exe)
            self.assertEqual(path, exe)
            self.assertEqual(params, "")

    def test_resolve_quoted_update_exe(self):
        with tempfile.TemporaryDirectory() as td:
            upd = os.path.join(td, "Update.exe")
            open(upd, "wb").close()
            raw = f'"{upd}" --processStart Discord.exe'
            path, params = app_launch.resolve_target(raw)
            self.assertEqual(path, upd)
            self.assertIn("Discord.exe", params)

    def test_launch_app_calls_shell_for_protocol(self):
        with mock.patch.object(app_launch, "_is_windows", return_value=True), mock.patch.object(
            app_launch, "_shell_execute"
        ) as se:
            ok = app_launch.launch_app("steam://run/1")
            self.assertTrue(ok)
            se.assert_called()
            self.assertEqual(se.call_args[0][0], "steam://run/1")

    def test_launch_app_startfile_for_existing(self):
        with tempfile.TemporaryDirectory() as td:
            exe = os.path.join(td, "a.exe")
            open(exe, "wb").close()
            with mock.patch.object(app_launch, "_is_windows", return_value=True), mock.patch.object(
                app_launch, "_startfile"
            ) as sf:
                ok = app_launch.launch_app(exe)
                self.assertTrue(ok)
                sf.assert_called_with(exe)


if __name__ == "__main__":
    unittest.main()
