import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config_store


class ConfigStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "config.py")

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

    def test_save_roundtrip_and_profile_switch(self):
        cfg = config_store.default_config()
        cfg["SERIAL_PORT"] = "COM7"
        cfg["APP_MAPPINGS"]["K1"] = "Discord.exe"
        config_store.save_config(cfg, self.path)

        loaded = config_store.load_config(self.path)
        self.assertEqual(loaded["SERIAL_PORT"], "COM7")
        self.assertEqual(loaded["APP_MAPPINGS"]["K1"], "Discord.exe")
        self.assertIn("Default", loaded["PROFILES"])

        loaded = config_store.add_profile(loaded, "Gaming", clone_active=True)
        loaded["APP_MAPPINGS"]["K1"] = "firefox.exe"
        config_store.sync_active_into_profiles(loaded)
        config_store.save_config(loaded, self.path)

        loaded = config_store.load_config(self.path)
        self.assertEqual(loaded["ACTIVE_PROFILE"], "Gaming")
        self.assertEqual(loaded["APP_MAPPINGS"]["K1"], "firefox.exe")

        loaded = config_store.switch_profile(loaded, "Default")
        config_store.save_config(loaded, self.path)
        loaded = config_store.load_config(self.path)
        self.assertEqual(loaded["ACTIVE_PROFILE"], "Default")
        self.assertEqual(loaded["APP_MAPPINGS"]["K1"], "Discord.exe")

    def test_next_profile_cycles(self):
        cfg = config_store.default_config()
        cfg = config_store.add_profile(cfg, "Work")
        cfg = config_store.add_profile(cfg, "Music")
        # ACTIVE is Music (last added)
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


if __name__ == "__main__":
    unittest.main()
