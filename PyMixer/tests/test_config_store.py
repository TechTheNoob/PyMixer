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


class ConfigStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "config.py")
        self.live_path = os.path.join(self.tmpdir.name, "live_levels.json")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_migrate_legacy_flat_config(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(
                "SERIAL_PORT = 'COM5'\n"
                "BAUD_RATE = 115200\n"
                "NUM_KNOBS = 5\n"
                "NUM_BUTTONS = 10\n"
                "APP_MAPPINGS = {'K1': 'focused_app', 'K2': '', 'B1': 'chrome.exe'}\n"
                "SLIDER_REVERSE = {'K1': True}\n"
                "SLIDER_SENSITIVITY = {'K1': 1.0}\n"
            )
        cfg = config_store.load_config(self.path)
        self.assertIn("PROFILES", cfg)
        self.assertEqual(cfg["ACTIVE_PROFILE"], "Default")
        self.assertEqual(cfg["APP_MAPPINGS"]["K1"], "focused_app")
        self.assertEqual(cfg["PROFILES"]["Default"]["APP_MAPPINGS"]["K1"], "focused_app")
        # Curves migrate to linear defaults
        self.assertEqual(cfg["SLIDER_CURVE"]["K1"], "linear")
        self.assertEqual(cfg["PROFILES"]["Default"]["SLIDER_CURVE"]["K1"], "linear")

    def test_migrate_profiles_missing_curve_key(self):
        cfg = config_store.default_config()
        # Simulate an older profile payload without SLIDER_CURVE
        cfg["PROFILES"]["Default"].pop("SLIDER_CURVE", None)
        cfg.pop("SLIDER_CURVE", None)
        cfg["APP_MAPPINGS"]["K2"] = "Discord.exe"
        migrated = config_store.migrate_profiles(cfg)
        self.assertEqual(migrated["SLIDER_CURVE"]["K2"], "linear")
        self.assertEqual(
            migrated["PROFILES"]["Default"]["SLIDER_CURVE"]["K1"], "linear"
        )

    def test_save_roundtrip_and_profile_switch(self):
        cfg = config_store.default_config()
        cfg["SERIAL_PORT"] = "COM7"
        cfg["APP_MAPPINGS"]["K1"] = "Discord.exe"
        cfg["SLIDER_CURVE"]["K1"] = "gentle"
        config_store.save_config(cfg, self.path)

        loaded = config_store.load_config(self.path)
        self.assertEqual(loaded["SERIAL_PORT"], "COM7")
        self.assertEqual(loaded["APP_MAPPINGS"]["K1"], "Discord.exe")
        self.assertEqual(loaded["SLIDER_CURVE"]["K1"], "gentle")
        self.assertIn("Default", loaded["PROFILES"])

        loaded = config_store.add_profile(loaded, "Gaming", clone_active=True)
        loaded["APP_MAPPINGS"]["K1"] = "firefox.exe"
        loaded["SLIDER_CURVE"]["K1"] = "strong"
        config_store.sync_active_into_profiles(loaded)
        config_store.save_config(loaded, self.path)

        loaded = config_store.load_config(self.path)
        self.assertEqual(loaded["ACTIVE_PROFILE"], "Gaming")
        self.assertEqual(loaded["APP_MAPPINGS"]["K1"], "firefox.exe")
        self.assertEqual(loaded["SLIDER_CURVE"]["K1"], "strong")

        loaded = config_store.switch_profile(loaded, "Default")
        config_store.save_config(loaded, self.path)
        loaded = config_store.load_config(self.path)
        self.assertEqual(loaded["ACTIVE_PROFILE"], "Default")
        self.assertEqual(loaded["APP_MAPPINGS"]["K1"], "Discord.exe")
        self.assertEqual(loaded["SLIDER_CURVE"]["K1"], "gentle")

    def test_next_profile_cycles(self):
        cfg = config_store.default_config()
        cfg = config_store.add_profile(cfg, "Work")
        cfg = config_store.add_profile(cfg, "Music")
        cfg, name = config_store.next_profile(cfg)
        self.assertEqual(name, "Default")
        cfg, name = config_store.next_profile(cfg)
        self.assertEqual(name, "Work")

    def test_delete_last_profile_rejected(self):
        cfg = config_store.default_config()
        with self.assertRaises(ValueError):
            config_store.delete_profile(cfg, "Default")

    def test_rename_and_delete(self):
        cfg = config_store.default_config()
        cfg = config_store.add_profile(cfg, "Gaming")
        cfg = config_store.rename_profile(cfg, "Gaming", "Stream")
        self.assertIn("Stream", cfg["PROFILES"])
        self.assertNotIn("Gaming", cfg["PROFILES"])
        cfg = config_store.delete_profile(cfg, "Stream")
        self.assertNotIn("Stream", cfg["PROFILES"])
        self.assertEqual(cfg["ACTIVE_PROFILE"], "Default")

    def test_is_url_action(self):
        self.assertTrue(config_store.is_url_action("www.youtube.com"))
        self.assertTrue(config_store.is_url_action("https://example.com"))
        self.assertFalse(config_store.is_url_action("chrome.exe"))
        self.assertFalse(config_store.is_url_action("next_profile"))

    def test_apply_curve_exponents(self):
        self.assertAlmostEqual(config_store.apply_curve(0.5, "linear"), 0.5)
        self.assertAlmostEqual(config_store.apply_curve(0.5, "gentle"), 0.5 ** 1.8)
        self.assertAlmostEqual(config_store.apply_curve(0.5, "strong"), 0.5 ** 3.0)
        # Low end: strong keeps volume lower than linear for same physical pos
        self.assertLess(config_store.apply_curve(0.3, "strong"), config_store.apply_curve(0.3, "linear"))
        self.assertEqual(config_store.apply_curve(-1, "linear"), 0.0)
        self.assertEqual(config_store.apply_curve(2, "linear"), 1.0)
        self.assertEqual(config_store.normalize_curve("nope"), "linear")

    def test_live_levels_write_read_stale(self):
        config_store.write_live_levels(
            {"K1": {"raw": 512, "volume": 0.5, "pct": 50}},
            self.live_path,
            connected=True,
        )
        live = config_store.read_live_levels(self.live_path, stale_after=2.0)
        self.assertFalse(live["stale"])
        self.assertTrue(live["connected"])
        self.assertEqual(live["knobs"]["K1"]["pct"], 50)

        # Force stale by rewinding timestamp
        import json

        with open(self.live_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["ts"] = time.time() - 5
        with open(self.live_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        live = config_store.read_live_levels(self.live_path, stale_after=2.0)
        self.assertTrue(live["stale"])
        self.assertFalse(live["connected"])

        missing = config_store.read_live_levels(
            os.path.join(self.tmpdir.name, "nope.json")
        )
        self.assertTrue(missing["stale"])


class ProfilePersistenceE2ETests(unittest.TestCase):
    """End-to-end: each profile keeps its own mappings / reverse / sens / curve."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "config.py")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _save(self, cfg):
        config_store.save_config(cfg, self.path)
        return config_store.load_config(self.path)

    def test_profiles_persist_all_knob_and_button_settings(self):
        cfg = config_store.default_config()
        # --- Default profile settings ---
        cfg["APP_MAPPINGS"]["K1"] = "focused_app"
        cfg["APP_MAPPINGS"]["K3"] = "Discord.exe"
        cfg["APP_MAPPINGS"]["B1"] = "chrome.exe"
        cfg["APP_MAPPINGS"]["B3"] = "www.youtube.com"
        cfg["SLIDER_REVERSE"]["K1"] = True
        cfg["SLIDER_SENSITIVITY"]["K1"] = 1.5
        cfg["SLIDER_CURVE"]["K1"] = "gentle"
        cfg = self._save(cfg)

        # Add Gaming (clone), then change everything
        cfg = config_store.add_profile(cfg, "Gaming", clone_active=True)
        cfg["APP_MAPPINGS"]["K1"] = "explorer.exe"
        cfg["APP_MAPPINGS"]["K3"] = "firefox.exe"
        cfg["APP_MAPPINGS"]["B1"] = "spotify.exe"
        cfg["APP_MAPPINGS"]["B3"] = "next_profile"
        cfg["SLIDER_REVERSE"]["K1"] = False
        cfg["SLIDER_SENSITIVITY"]["K1"] = 0.5
        cfg["SLIDER_CURVE"]["K1"] = "strong"
        cfg = self._save(cfg)

        # Add Work with yet another set
        cfg = config_store.add_profile(cfg, "Work", clone_active=True)
        cfg["APP_MAPPINGS"]["K1"] = "Code.exe"
        cfg["SLIDER_CURVE"]["K1"] = "linear"
        cfg["APP_MAPPINGS"]["B2"] = "lock_pc"
        cfg = self._save(cfg)

        # Switch back to Default — original settings must return
        cfg = config_store.switch_profile(cfg, "Default")
        cfg = self._save(cfg)
        self.assertEqual(cfg["ACTIVE_PROFILE"], "Default")
        self.assertEqual(cfg["APP_MAPPINGS"]["K1"], "focused_app")
        self.assertEqual(cfg["APP_MAPPINGS"]["K3"], "Discord.exe")
        self.assertEqual(cfg["APP_MAPPINGS"]["B1"], "chrome.exe")
        self.assertEqual(cfg["APP_MAPPINGS"]["B3"], "www.youtube.com")
        self.assertTrue(cfg["SLIDER_REVERSE"]["K1"])
        self.assertEqual(cfg["SLIDER_SENSITIVITY"]["K1"], 1.5)
        self.assertEqual(cfg["SLIDER_CURVE"]["K1"], "gentle")

        # Gaming still has its own
        cfg = config_store.switch_profile(cfg, "Gaming")
        cfg = self._save(cfg)
        self.assertEqual(cfg["APP_MAPPINGS"]["K1"], "explorer.exe")
        self.assertEqual(cfg["APP_MAPPINGS"]["B3"], "next_profile")
        self.assertFalse(cfg["SLIDER_REVERSE"]["K1"])
        self.assertEqual(cfg["SLIDER_SENSITIVITY"]["K1"], 0.5)
        self.assertEqual(cfg["SLIDER_CURVE"]["K1"], "strong")

        # Rename Gaming → Stream; settings follow
        cfg = config_store.rename_profile(cfg, "Gaming", "Stream")
        cfg = self._save(cfg)
        self.assertEqual(cfg["ACTIVE_PROFILE"], "Stream")
        self.assertNotIn("Gaming", cfg["PROFILES"])
        self.assertEqual(cfg["APP_MAPPINGS"]["K1"], "explorer.exe")
        self.assertEqual(cfg["SLIDER_CURVE"]["K1"], "strong")

        # Delete active Stream → falls back safely
        cfg = config_store.delete_profile(cfg, "Stream")
        cfg = self._save(cfg)
        self.assertNotIn("Stream", cfg["PROFILES"])
        self.assertIn(cfg["ACTIVE_PROFILE"], cfg["PROFILES"])
        # Active mappings match the fallback profile payload
        active = cfg["ACTIVE_PROFILE"]
        self.assertEqual(
            cfg["APP_MAPPINGS"], cfg["PROFILES"][active]["APP_MAPPINGS"]
        )
        self.assertEqual(
            cfg["SLIDER_CURVE"], cfg["PROFILES"][active]["SLIDER_CURVE"]
        )

        # Last-profile guard
        while len(cfg["PROFILES"]) > 1:
            victim = next(n for n in cfg["PROFILES"] if n != cfg["ACTIVE_PROFILE"])
            cfg = config_store.delete_profile(cfg, victim)
        with self.assertRaises(ValueError):
            config_store.delete_profile(cfg, cfg["ACTIVE_PROFILE"])


class TrayRuntimeSimulationTests(unittest.TestCase):
    """
    Simulate the tray app's in-memory config + 5s reload + button actions
    without importing Windows-only modules (pycaw / serial / win32).
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "config.py")
        self.live_path = os.path.join(self.tmpdir.name, "live_levels.json")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _boot_tray_config(self):
        """Like PyMixer.load_config() at startup."""
        return config_store.load_config(self.path)

    def _apply_profile_switch(self, memory_cfg, name=None, cycle=False):
        """Mirrors PyMixer.apply_profile_switch — immediate in-memory update."""
        cfg = config_store.load_config(self.path)
        # Preserve any unsaved memory edits into the profile we're leaving
        # (tray button path reloads from disk first, same as production).
        if cycle:
            cfg, name = config_store.next_profile(cfg)
        else:
            cfg = config_store.switch_profile(cfg, name)
        config_store.save_config(cfg, self.path)
        return cfg, cfg.get("ACTIVE_PROFILE")

    def _handle_button(self, memory_cfg, command):
        """Mirrors the button branch in serial_reader_thread."""
        if command == "next_profile":
            return self._apply_profile_switch(memory_cfg, cycle=True)
        if isinstance(command, str) and command.startswith("profile:"):
            return self._apply_profile_switch(
                memory_cfg, name=command.split(":", 1)[1]
            )
        return memory_cfg, memory_cfg.get("ACTIVE_PROFILE")

    def _compute_volume(self, raw, reverse, curve):
        scaled = 1023.0 - raw if reverse else float(raw)
        normalized = max(0.0, min(1.0, scaled / 1023.0))
        return config_store.apply_curve(normalized, curve)

    def test_button_next_profile_and_named_switch_immediate(self):
        cfg = config_store.default_config()
        cfg["APP_MAPPINGS"]["K1"] = "Discord.exe"
        cfg["SLIDER_CURVE"]["K1"] = "gentle"
        config_store.save_config(cfg, self.path)

        cfg = config_store.load_config(self.path)
        cfg = config_store.add_profile(cfg, "Gaming", clone_active=True)
        cfg["APP_MAPPINGS"]["K1"] = "firefox.exe"
        cfg["SLIDER_CURVE"]["K1"] = "strong"
        config_store.sync_active_into_profiles(cfg)
        cfg = config_store.add_profile(cfg, "Work", clone_active=True)
        cfg["APP_MAPPINGS"]["K1"] = "Code.exe"
        config_store.sync_active_into_profiles(cfg)
        config_store.save_config(cfg, self.path)

        # Tray boots
        memory = self._boot_tray_config()
        self.assertEqual(memory["ACTIVE_PROFILE"], "Work")

        # Button: next_profile → cycles immediately (no restart)
        memory, name = self._handle_button(memory, "next_profile")
        self.assertEqual(name, "Default")
        self.assertEqual(memory["APP_MAPPINGS"]["K1"], "Discord.exe")
        self.assertEqual(memory["SLIDER_CURVE"]["K1"], "gentle")

        # Button: profile:Gaming → jump
        memory, name = self._handle_button(memory, "profile:Gaming")
        self.assertEqual(name, "Gaming")
        self.assertEqual(memory["APP_MAPPINGS"]["K1"], "firefox.exe")
        self.assertEqual(memory["SLIDER_CURVE"]["K1"], "strong")

        # Simulate 5s reload from disk (GUI may have saved) — still Gaming
        memory = self._boot_tray_config()
        self.assertEqual(memory["ACTIVE_PROFILE"], "Gaming")
        self.assertEqual(memory["APP_MAPPINGS"]["K1"], "firefox.exe")

    def test_tray_menu_lists_all_profiles(self):
        cfg = config_store.default_config()
        config_store.save_config(cfg, self.path)
        cfg = config_store.load_config(self.path)
        cfg = config_store.add_profile(cfg, "Gaming")
        cfg = config_store.add_profile(cfg, "Music")
        config_store.save_config(cfg, self.path)

        memory = self._boot_tray_config()
        names = config_store.list_profile_names(memory)
        self.assertEqual(names, ["Default", "Gaming", "Music"])

        # Switching via "tray submenu" updates live config
        memory, _ = self._apply_profile_switch(memory, name="Music")
        self.assertEqual(memory["ACTIVE_PROFILE"], "Music")
        memory, _ = self._apply_profile_switch(memory, name="Default")
        self.assertEqual(memory["ACTIVE_PROFILE"], "Default")

    def test_volume_path_uses_reverse_and_curve(self):
        raw = 307  # ~30% physical
        linear = self._compute_volume(raw, reverse=False, curve="linear")
        strong = self._compute_volume(raw, reverse=False, curve="strong")
        self.assertAlmostEqual(linear, raw / 1023.0, places=4)
        self.assertLess(strong, linear)

        # Reverse: high raw → low volume
        rev = self._compute_volume(900, reverse=True, curve="linear")
        self.assertLess(rev, 0.2)

    def test_live_levels_published_for_settings_ui(self):
        # Tray writes; settings UI reads (separate process simulation)
        knobs = {}
        for i, raw in enumerate([100, 400, 700, 900, 50], start=1):
            key = f"K{i}"
            vol = self._compute_volume(raw, reverse=True, curve="gentle")
            knobs[key] = {"raw": raw, "volume": round(vol, 4), "pct": int(round(vol * 100))}
        config_store.write_live_levels(knobs, self.live_path, connected=True)

        # Settings-side poll
        live = config_store.read_live_levels(self.live_path)
        self.assertFalse(live["stale"])
        self.assertIn("K3", live["knobs"])
        self.assertEqual(live["knobs"]["K1"]["raw"], 100)

    def test_gui_save_picked_up_on_reload(self):
        """Settings process saves; tray 5s reload picks up new active profile data."""
        cfg = config_store.default_config()
        cfg["APP_MAPPINGS"]["K1"] = "Discord.exe"
        config_store.save_config(cfg, self.path)
        memory = self._boot_tray_config()

        # GUI process writes a different mapping + curve
        gui = config_store.load_config(self.path)
        gui["APP_MAPPINGS"]["K1"] = "spotify.exe"
        gui["SLIDER_CURVE"]["K1"] = "strong"
        config_store.save_config(gui, self.path)

        # Tray reload (same as the 5s timer)
        memory = self._boot_tray_config()
        self.assertEqual(memory["APP_MAPPINGS"]["K1"], "spotify.exe")
        self.assertEqual(memory["SLIDER_CURVE"]["K1"], "strong")


class ApiBridgeTests(unittest.TestCase):
    """Exercise config_gui_web.Api against a temp config (no pywebview)."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "config.py")
        cfg = config_store.default_config()
        config_store.save_config(cfg, self.path)
        # Import after path setup
        import config_gui_web

        self.api = config_gui_web.Api(config_file=self.path)
        # Point live file into tmpdir
        self.api.live_file = os.path.join(self.tmpdir.name, "live_levels.json")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_get_state_and_profile_ops(self):
        state = self.api.get_state()
        self.assertEqual(state["config"]["ACTIVE_PROFILE"], "Default")
        self.assertIn("live", state)

        cfg = state["config"]
        cfg["APP_MAPPINGS"]["K1"] = "Discord.exe"
        cfg["SLIDER_CURVE"]["K1"] = "gentle"
        saved = self.api.save_config(cfg)
        self.assertEqual(saved["APP_MAPPINGS"]["K1"], "Discord.exe")

        updated = self.api.add_profile("Gaming", saved)
        self.assertEqual(updated["ACTIVE_PROFILE"], "Gaming")
        updated["APP_MAPPINGS"]["K1"] = "firefox.exe"
        updated["SLIDER_CURVE"]["K1"] = "strong"
        updated = self.api.save_config(updated)

        updated = self.api.switch_profile("Default", updated)
        self.assertEqual(updated["APP_MAPPINGS"]["K1"], "Discord.exe")
        self.assertEqual(updated["SLIDER_CURVE"]["K1"], "gentle")

        updated = self.api.rename_profile("Gaming", "Stream", updated)
        self.assertIn("Stream", updated["PROFILES"])
        updated = self.api.delete_profile("Stream", updated)
        self.assertNotIn("Stream", updated["PROFILES"])

    def test_get_live_levels(self):
        live = self.api.get_live_levels()
        self.assertTrue(live["stale"])
        config_store.write_live_levels(
            {"K1": {"raw": 10, "volume": 0.01, "pct": 1}},
            self.api.live_file,
        )
        live = self.api.get_live_levels()
        self.assertFalse(live["stale"])
        self.assertEqual(live["knobs"]["K1"]["pct"], 1)


class TrayPopupTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "config.py")
        self.live = os.path.join(self.tmpdir.name, "live_levels.json")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_popup_position_bottom_right(self):
        import tray_popup

        x, y = tray_popup.popup_position(
            width=280, height=420, margin=12, work_area=(0, 0, 1920, 1040)
        )
        self.assertEqual(x, 1920 - 280 - 12)
        self.assertEqual(y, 1040 - 420 - 12)

    def test_popup_position_clamps_to_work_area(self):
        import tray_popup

        x, y = tray_popup.popup_position(
            width=500, height=500, margin=8, work_area=(100, 50, 400, 300)
        )
        self.assertEqual(x, 100 + 8)
        self.assertEqual(y, 50 + 8)

    def test_popup_api_state_and_switch(self):
        import tray_popup

        cfg = config_store.default_config()
        cfg["APP_MAPPINGS"]["K1"] = "Discord.exe"
        config_store.save_config(cfg, self.path)
        cfg = config_store.load_config(self.path)
        cfg = config_store.add_profile(cfg, "Gaming", clone_active=True)
        cfg["APP_MAPPINGS"]["K1"] = "firefox.exe"
        config_store.sync_active_into_profiles(cfg)
        config_store.save_config(cfg, self.path)

        api = tray_popup.PopupApi(config_file=self.path)
        api.live_file = self.live
        state = api.get_popup_state()
        self.assertEqual(state["active"], "Gaming")
        self.assertIn("Default", state["profiles"])
        self.assertIn("Gaming", state["profiles"])

        state = api.switch_profile("Default")
        self.assertEqual(state["active"], "Default")
        loaded = config_store.load_config(self.path)
        self.assertEqual(loaded["ACTIVE_PROFILE"], "Default")
        self.assertEqual(loaded["APP_MAPPINGS"]["K1"], "Discord.exe")

        config_store.write_live_levels(
            {"K1": {"raw": 100, "volume": 0.1, "pct": 10}}, self.live
        )
        live = api.get_live()
        self.assertFalse(live["stale"])
        self.assertEqual(live["knobs"]["K1"]["pct"], 10)




class DynamicTrayMenuTests(unittest.TestCase):
    """Profiles submenu / header must re-evaluate from disk every time."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "config.py")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_add_rename_delete_and_switch_update_evaluated_menu(self):
        import tray_menu

        cfg = config_store.default_config()
        config_store.save_config(cfg, self.path)

        items = tray_menu.evaluated_profile_items(path=self.path)
        self.assertEqual([i["name"] for i in items], ["Default"])
        self.assertTrue(items[0]["checked"])
        self.assertEqual(tray_menu.header_label(path=self.path), "PyMixer · Default")
        fp1 = tray_menu.menu_fingerprint(config_store.load_config(self.path))

        cfg = config_store.load_config(self.path)
        cfg = config_store.add_profile(cfg, "Gaming")
        config_store.save_config(cfg, self.path)
        items = tray_menu.evaluated_profile_items(path=self.path)
        names = [i["name"] for i in items]
        self.assertIn("Gaming", names)
        self.assertIn("Default", names)
        self.assertEqual(tray_menu.header_label(path=self.path), "PyMixer · Gaming")
        checked = {i["name"]: i["checked"] for i in items}
        self.assertTrue(checked["Gaming"])
        self.assertFalse(checked["Default"])
        fp2 = tray_menu.menu_fingerprint(config_store.load_config(self.path))
        self.assertTrue(tray_menu.profiles_changed(fp1, fp2))

        cfg = config_store.load_config(self.path)
        cfg = config_store.rename_profile(cfg, "Gaming", "Stream")
        config_store.save_config(cfg, self.path)
        items = tray_menu.evaluated_profile_items(path=self.path)
        names = [i["name"] for i in items]
        self.assertIn("Stream", names)
        self.assertNotIn("Gaming", names)
        self.assertEqual(tray_menu.header_label(path=self.path), "PyMixer · Stream")

        cfg = config_store.load_config(self.path)
        cfg = config_store.switch_profile(cfg, "Default")
        config_store.save_config(cfg, self.path)
        items = tray_menu.evaluated_profile_items(path=self.path)
        checked = {i["name"]: i["checked"] for i in items}
        self.assertTrue(checked["Default"])
        self.assertFalse(checked["Stream"])
        self.assertEqual(tray_menu.header_label(path=self.path), "PyMixer · Default")

        cfg = config_store.load_config(self.path)
        cfg = config_store.delete_profile(cfg, "Stream")
        config_store.save_config(cfg, self.path)
        items = tray_menu.evaluated_profile_items(path=self.path)
        self.assertEqual([i["name"] for i in items], ["Default"])
        fp3 = tray_menu.menu_fingerprint(config_store.load_config(self.path))
        self.assertTrue(tray_menu.profiles_changed(fp2, fp3))


class TrayPopupDismissTests(unittest.TestCase):
    def tearDown(self):
        import tray_popup
        tray_popup._window = None
        tray_popup._closing = False
        tray_popup._hidden = False
        tray_popup._shown_at = 0.0

    def test_safe_dismiss_hides_once_and_skips_double(self):
        import tray_popup

        class FakeWin:
            def __init__(self):
                self.hidden = 0
                self.destroyed = 0

            def hide(self):
                self.hidden += 1

            def destroy(self):
                self.destroyed += 1

        win = FakeWin()
        tray_popup._window = win
        tray_popup._hidden = False
        tray_popup._closing = False
        tray_popup._shown_at = 0.0  # outside grace

        r1 = tray_popup.safe_dismiss(hide_only=True)
        self.assertTrue(r1["ok"])
        self.assertEqual(r1["action"], "hide")
        self.assertFalse(r1["skipped"])
        self.assertEqual(win.hidden, 1)
        self.assertEqual(win.destroyed, 0)
        self.assertTrue(tray_popup._hidden)

        r2 = tray_popup.safe_dismiss(hide_only=True)
        self.assertTrue(r2["skipped"])
        self.assertEqual(win.hidden, 1)

    def test_blur_grace_skips_dismiss(self):
        import tray_popup
        import time as _time

        class FakeWin:
            def hide(self):
                raise AssertionError("should not hide during grace")

        tray_popup._window = FakeWin()
        tray_popup._hidden = False
        tray_popup._shown_at = _time.time()
        r = tray_popup.safe_dismiss(hide_only=True)
        self.assertTrue(r["skipped"])
        self.assertEqual(r.get("reason"), "blur_grace")

    def test_hard_quit_destroys_once(self):
        import tray_popup

        class FakeWin:
            def __init__(self):
                self.destroyed = 0

            def destroy(self):
                self.destroyed += 1

        win = FakeWin()
        tray_popup._window = win
        tray_popup._closing = False
        r1 = tray_popup.safe_dismiss(hide_only=False)
        self.assertEqual(r1["action"], "destroy")
        self.assertEqual(win.destroyed, 1)
        r2 = tray_popup.safe_dismiss(hide_only=False)
        self.assertTrue(r2["skipped"])
        self.assertEqual(win.destroyed, 1)


if __name__ == "__main__":
    unittest.main()
