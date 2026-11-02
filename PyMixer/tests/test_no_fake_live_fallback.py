"""Shipped UI must never invent placeholder live percentages."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NoFakeLiveFallbackTests(unittest.TestCase):
    def test_app_js_has_no_demo_drift(self):
        app = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("[55, 10, 72, 68, 59]", app)
        self.assertNotIn("Mild demo drift", app)
        self.assertNotIn("raw: 700, volume: 0.55", app)
        self.assertIn("get_live_levels", app)
        self.assertIn("offlineShell", app)
        # Stale path shows em dash
        self.assertIn('vol.textContent = "—"', app)

    def test_tray_popup_has_no_demoData(self):
        tray = (ROOT / "ui" / "tray_popup.js").read_text(encoding="utf-8")
        self.assertNotIn("function demoData", tray)
        self.assertNotIn("pct: 55", tray)
        self.assertIn("get_live", tray)
        self.assertIn('"—"', tray)


if __name__ == "__main__":
    unittest.main()
