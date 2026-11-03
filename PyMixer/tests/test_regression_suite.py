"""
Full headless regression checklist for the public PyMixer app.
Windows-only items are asserted as skipped/documented in the module docstring.

Windows-only (cannot verify on Linux CI):
- Real pycaw volume set/get against Speakers / app sessions
- Real COM port open via pyserial
- pywebview native window chrome / WebView2 stacking
- Tray left-click popup positioning against the Win32 work area edge cases
- Actual mic mute / master mute / Lock PC
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config_store
import tray_menu


def _vol(raw, reverse, curve):
    scaled = 1023.0 - raw if reverse else float(raw)
    return config_store.apply_curve(max(0.0, min(1.0, scaled / 1023.0)), curve)


class SerialBoardVolumeLogicTests(unittest.TestCase):
    """serial/board input → tray volume math (curve + reverse)."""

    def test_curve_and_reverse_on_raw_board_values(self):
        self.assertAlmostEqual(_vol(0, True, "linear"), 1.0, places=5)
        self.assertAlmostEqual(_vol(1023, True, "linear"), 0.0, places=5)
        self.assertAlmostEqual(_vol(512, False, "linear"), 512 / 1023.0, places=5)
        gentle = _vol(512, False, "gentle")
        strong = _vol(512, False, "strong")
        linear = _vol(512, False, "linear")
        # Exponents > 1 pull mid-travel down (gentle 1.8, strong 3.0)
        self.assertLess(gentle, linear)
        self.assertLess(strong, gentle)


class StatusLogicTests(unittest.TestCase):
    def test_port_seems_open_false_for_missing_com(self):
        import config_gui_web

        with mock.patch.object(config_gui_web, "_list_ports", return_value=["COM3"]):
            self.assertTrue(config_gui_web._port_seems_open("COM3"))
            self.assertFalse(config_gui_web._port_seems_open("COM99"))
            self.assertFalse(config_gui_web._port_seems_open("DEMO"))
            self.assertFalse(config_gui_web._port_seems_open(""))

    def test_get_state_connected_follows_port_list(self):
        import config_gui_web

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "config.py")
        cfg = config_store.default_config()
        cfg["SERIAL_PORT"] = "COM5"
        config_store.save_config(cfg, path)
        api = config_gui_web.Api(config_file=path)
        with mock.patch.object(config_gui_web, "_list_ports", return_value=["COM5"]):
            with mock.patch.object(config_gui_web, "_list_apps", return_value=[]):
                with mock.patch("app_catalog.build_app_catalog", return_value={"audio": [], "running": [], "current": None}):
                    with mock.patch("volume_read.live_levels_from_config", return_value={"stale": True, "connected": False, "knobs": {}}):
                        st = api.get_state()
        self.assertTrue(st["connected"])
        self.assertFalse(st.get("demo"))


class ProfileAndSaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "config.py")

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_rename_delete_switch(self):
        cfg = config_store.default_config()
        cfg = config_store.add_profile(cfg, "Gaming", clone_active=True)
        cfg = config_store.add_profile(cfg, "Work", clone_active=True)
        config_store.save_config(cfg, self.path)
        cfg = config_store.load_config(self.path)
        cfg = config_store.rename_profile(cfg, "Work", "Office")
        self.assertIn("Office", cfg["PROFILES"])
        self.assertNotIn("Work", cfg["PROFILES"])
        cfg = config_store.switch_profile(cfg, "Gaming")
        self.assertEqual(cfg["ACTIVE_PROFILE"], "Gaming")
        cfg = config_store.delete_profile(cfg, "Office")
        self.assertNotIn("Office", cfg["PROFILES"])
        config_store.save_config(cfg, self.path)

    def test_next_profile_cycles(self):
        cfg = config_store.default_config()
        cfg = config_store.add_profile(cfg, "A", clone_active=True)
        cfg = config_store.add_profile(cfg, "B", clone_active=True)
        names = config_store.list_profile_names(cfg)
        cfg = config_store.switch_profile(cfg, names[0])
        cfg2, nxt = config_store.next_profile(cfg)
        self.assertNotEqual(nxt, cfg["ACTIVE_PROFILE"])
        self.assertEqual(cfg2["ACTIVE_PROFILE"], nxt)

    def test_save_under_simulated_lock_retries(self):
        cfg = config_store.default_config()
        cfg["SERIAL_PORT"] = "COM8"
        # First replace fails with WinError-like PermissionError, then succeeds
        real_replace = os.replace
        calls = {"n": 0}

        def flaky_replace(src, dst):
            calls["n"] += 1
            if calls["n"] < 3:
                err = PermissionError(13, "Access is denied")
                raise err
            return real_replace(src, dst)

        with mock.patch("os.replace", side_effect=flaky_replace):
            config_store.save_config(cfg, self.path)
        self.assertGreaterEqual(calls["n"], 3)
        loaded = config_store.load_config(self.path)
        self.assertEqual(loaded["SERIAL_PORT"], "COM8")


class DynamicTrayMenuTests(unittest.TestCase):
    def test_menu_fingerprint_changes_with_profiles(self):
        cfg = config_store.default_config()
        a = tray_menu.menu_fingerprint(cfg)
        cfg = config_store.add_profile(cfg, "Night", clone_active=True)
        b = tray_menu.menu_fingerprint(cfg)
        self.assertNotEqual(a, b)

    def test_status_label_reflects_connected(self):
        on = tray_menu.status_label(path="x", connected=True)
        off = tray_menu.status_label(path="x", connected=False)
        self.assertIn("●", on)
        self.assertIn("○", off)


class NoIdleLiveFileWritesTests(unittest.TestCase):
    def test_legacy_live_path_not_written_by_volume_read(self):
        """volume_read must not create live_levels.json."""
        import volume_read

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        live = os.path.join(tmp.name, "live_levels.json")
        cfg = config_store.default_config()
        with mock.patch.object(volume_read, "volume_for_mapping", return_value=0.5):
            with mock.patch.object(volume_read, "_ensure_com", return_value=None):
                volume_read.live_levels_from_config(cfg)
        self.assertFalse(os.path.exists(live))


class PickerContractTests(unittest.TestCase):
    """Static contracts for the portal picker (JS inspected as text)."""

    def test_app_picker_is_body_portal_with_clamp(self):
        ui = os.path.join(ROOT, "ui")
        js = open(os.path.join(ui, "app_picker.js"), encoding="utf-8").read()
        css = open(os.path.join(ui, "style.css"), encoding="utf-8").read()
        self.assertIn("document.body.appendChild", js)
        self.assertIn("MARGIN = 8", js)
        self.assertIn("flipUp", js)
        self.assertIn("ap-panel-portal", js)
        self.assertIn("ap-panel-portal", css)
        self.assertIn("2147483000", css)

    def test_button_cards_are_whole_click_targets(self):
        app = open(os.path.join(ROOT, "ui", "app.js"), encoding="utf-8").read()
        css = open(os.path.join(ROOT, "ui", "style.css"), encoding="utf-8").read()
        self.assertIn("Click to assign", app)
        self.assertIn('role", "button"', app)
        self.assertIn("bhint", css)
        self.assertIn("sel.open(card)", app)


class SettingsPopupApiSmokeTests(unittest.TestCase):
    def test_popup_api_returns_live_shape(self):
        import tray_popup

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "config.py")
        config_store.save_config(config_store.default_config(), path)
        api = tray_popup.PopupApi(config_file=path)
        with mock.patch("volume_read.live_levels_from_config", return_value={
            "stale": False, "connected": True, "knobs": {"K1": {"volume": 0.4, "pct": 40}}, "source": "pycaw"
        }):
            st = api.get_popup_state()
        self.assertIn("live", st)
        self.assertIn("profiles", st)
        self.assertIn("connected", st)



class TestCurveForceReapplySource(unittest.TestCase):
    """v1.4.0: curve/reverse change must force one ungated volume apply."""

    def test_serial_thread_tracks_curve_and_force_flag(self):
        with open(os.path.join(ROOT, "PyMixer.pyw"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("force_reapply", src)
        self.assertIn("prev_curve", src)
        self.assertIn("prev_reverse", src)
        self.assertIn("forced = key in force_reapply", src)
        self.assertIn("force_reapply.discard(key)", src)

    def test_settings_curve_labels_are_plain_english(self):
        with open(os.path.join(ROOT, "ui", "app.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn("even all the way", js)
        self.assertIn("more control at low volume", js)
        self.assertIn("lots of control at low volume", js)
        self.assertIn("paintCurvePreview", js)
        self.assertIn("curve-preview", js)


if __name__ == "__main__":
    unittest.main()
