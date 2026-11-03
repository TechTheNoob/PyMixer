"""Board/knob mapping → pycaw SetMasterVolume with mocked sessions."""
from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_pymixer():
    """Load PyMixer.pyw as a module (Windows-only imports are stubbed)."""
    audio = mock.MagicMock(name="AudioUtilities")
    for name in (
        "serial",
        "serial.tools",
        "serial.tools.list_ports",
        "pythoncom",
        "pycaw",
        "pycaw.pycaw",
        "comtypes",
        "pystray",
        "PIL",
        "PIL.Image",
        "pygetwindow",
        "win32process",
        "psutil",
    ):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules["serial"].Serial = object
    sys.modules["serial"].SerialException = Exception
    sys.modules["serial.tools.list_ports"].comports = lambda: []
    sys.modules["pycaw.pycaw"].AudioUtilities = audio
    sys.modules["pycaw.pycaw"].ISimpleAudioVolume = object
    sys.modules["pycaw.pycaw"].IAudioEndpointVolume = types.SimpleNamespace(_iid_=object())
    sys.modules["comtypes"].CLSCTX_ALL = 0
    sys.modules["pystray"].Icon = object
    sys.modules["pystray"].Menu = object
    sys.modules["pystray"].MenuItem = object
    sys.modules["PIL.Image"].open = lambda *a, **k: None
    sys.modules["PIL.Image"].new = lambda *a, **k: None

    path = ROOT / "PyMixer.pyw"
    source = path.read_text(encoding="utf-8")
    mod = types.ModuleType("pymixer_app")
    mod.__file__ = str(path)
    sys.modules["pymixer_app"] = mod
    exec(compile(source, str(path), "exec"), mod.__dict__)
    return mod


class _FakeSimpleVolume:
    def __init__(self):
        self.levels = []

    def SetMasterVolume(self, level, _event):
        self.levels.append(float(level))

    def GetMute(self):
        return 0

    def SetMute(self, value, _event):
        pass


class _FakeEndpoint:
    def __init__(self):
        self.levels = []

    def SetMasterVolumeLevelScalar(self, level, _event):
        self.levels.append(float(level))

    def GetMute(self):
        return 0

    def SetMute(self, value, _event):
        pass


class _FakeCtl:
    def __init__(self, simple):
        self._simple = simple

    def QueryInterface(self, _iid):
        return self._simple


class _FakeProc:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _FakeSession:
    def __init__(self, proc_name, simple):
        self.Process = _FakeProc(proc_name)
        self._ctl = _FakeCtl(simple)


class VolumeApplyE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _load_pymixer()

    def setUp(self):
        self.simple = _FakeSimpleVolume()
        self.endpoint = _FakeEndpoint()
        self.session = _FakeSession("Discord.exe", self.simple)
        self.app.config = {
            "APP_MAPPINGS": {
                "K1": "discord.exe",
                "K2": "explorer.exe",
                "K3": "firefox.exe",
                "K4": "",
                "K5": "focused_app",
            }
        }
        # Reset MagicMock call history between tests
        self.app.AudioUtilities.reset_mock()

    def test_normalize_process_name(self):
        n = self.app._normalize_process_name
        self.assertEqual(n("Discord"), "discord.exe")
        self.assertEqual(n("DISCORD.EXE"), "discord.exe")
        self.assertEqual(n("master"), "explorer.exe")
        self.assertEqual(n("focused_app"), "focused_app")

    def test_get_audio_session_case_insensitive(self):
        self.app.AudioUtilities.GetAllSessions.return_value = [self.session]
        found = self.app.get_audio_session("discord.exe")
        self.assertIs(found, self.session)
        found2 = self.app.get_audio_session("Discord")
        self.assertIs(found2, self.session)

    def test_apply_knob_sets_app_session_volume(self):
        self.app.AudioUtilities.GetAllSessions.return_value = [self.session]
        ok = self.app.apply_knob_volume("Discord.exe", 0.42, key="K1")
        self.assertTrue(ok)
        self.assertEqual(self.simple.levels, [0.42])

    def test_apply_knob_master_uses_endpoint_property(self):
        """Newer pycaw: AudioDevice.EndpointVolume, no Activate()."""
        speakers = mock.MagicMock(spec=["EndpointVolume", "FriendlyName"])
        speakers.EndpointVolume = self.endpoint
        # Ensure Activate is absent so we exercise the property path
        self.app.AudioUtilities.GetSpeakers.return_value = speakers
        ok = self.app.apply_knob_volume("explorer.exe", 0.77, key="K2")
        self.assertTrue(ok)
        self.assertEqual(self.endpoint.levels, [0.77])

    def test_apply_knob_master_activate_fallback(self):
        """Older pycaw: IMMDevice.Activate(...)."""
        speakers = mock.MagicMock(spec=["Activate"])
        speakers.Activate.return_value = self.endpoint
        # No EndpointVolume attribute
        self.app.AudioUtilities.GetSpeakers.return_value = speakers
        with mock.patch.object(self.app, "cast", side_effect=lambda iface, _t: iface), mock.patch.object(
            self.app, "POINTER", return_value=object()
        ):
            ok = self.app.apply_knob_volume("explorer.exe", 0.55, key="K2")
        self.assertTrue(ok)
        self.assertEqual(self.endpoint.levels, [0.55])
        speakers.Activate.assert_called_once()

    def test_apply_knob_no_session_is_false_and_silent(self):
        self.app.AudioUtilities.GetAllSessions.return_value = []
        ok = self.app.apply_knob_volume("missing.exe", 0.5, key="K3")
        self.assertFalse(ok)
        self.assertEqual(self.simple.levels, [])

    def test_curved_board_value_reaches_setmastervolume(self):
        import config_store

        raw = 256
        reverse = True
        curve = "gentle"
        scaled = 1023.0 - raw
        normalized = scaled / 1023.0
        expected = config_store.apply_curve(normalized, curve)
        self.app.AudioUtilities.GetAllSessions.return_value = [self.session]
        ok = self.app.apply_knob_volume("discord.exe", expected, key="K1")
        self.assertTrue(ok)
        self.assertEqual(len(self.simple.levels), 1)
        self.assertAlmostEqual(self.simple.levels[0], expected, places=4)

    def test_toggle_off_path_not_applicable_in_public(self):
        """Public build has no apply_real_volume gate — applying always attempts pycaw."""
        self.assertFalse(hasattr(self.app, "DEMO_MODE") and self.app.DEMO_MODE)
        self.app.AudioUtilities.GetAllSessions.return_value = [self.session]
        self.assertTrue(self.app.apply_knob_volume("discord.exe", 0.1, key="K1"))
        self.assertEqual(self.simple.levels, [0.1])


if __name__ == "__main__":
    unittest.main()
