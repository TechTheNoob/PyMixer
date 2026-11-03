"""
Read current Windows volumes via pycaw for live fader display.

Used by the settings window and tray popup (their own processes). The tray
app no longer publishes live levels to disk or a socket — each UI polls here
while open (~150 ms). Curve/reverse are already baked into the resulting volume.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, Optional

# COM must be initialized in the calling thread before pycaw calls.


def _ensure_com() -> None:
    try:
        import pythoncom  # type: ignore

        pythoncom.CoInitialize()
    except Exception:
        try:
            import comtypes  # type: ignore

            comtypes.CoInitialize()
        except Exception:
            pass


def _endpoint_volume(device):  # type: ignore[no-untyped-def]
    """Prefer AudioDevice.EndpointVolume; fall back to IMMDevice.Activate."""
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL  # type: ignore
    from pycaw.pycaw import IAudioEndpointVolume  # type: ignore

    if device is None:
        raise RuntimeError("audio device is None")
    ep = getattr(device, "EndpointVolume", None)
    if ep is not None:
        return ep
    activate = getattr(device, "Activate", None)
    if callable(activate):
        interface = activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    inner = getattr(device, "_dev", None) or getattr(device, "device", None)
    if inner is not None and callable(getattr(inner, "Activate", None)):
        interface = inner.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    raise AttributeError(f"{type(device).__name__} has neither EndpointVolume nor Activate")


def get_master_volume() -> Optional[float]:
    try:
        from pycaw.pycaw import AudioUtilities  # type: ignore

        vol = _endpoint_volume(AudioUtilities.GetSpeakers())
        return float(vol.GetMasterVolumeLevelScalar())
    except Exception:
        return None


def get_app_volume(process_name: str) -> Optional[float]:
    """Max MasterVolume across sessions whose process name matches (case-insensitive)."""
    if not process_name:
        return None
    try:
        from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume  # type: ignore

        target = process_name.lower()
        best: Optional[float] = None
        for session in AudioUtilities.GetAllSessions():
            proc = getattr(session, "Process", None)
            if not proc:
                continue
            try:
                name = proc.name()
            except Exception:
                continue
            if not name or name.lower() != target:
                continue
            try:
                volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                level = float(volume.GetMasterVolume())
            except Exception:
                continue
            if best is None or level > best:
                best = level
        return best
    except Exception:
        return None


def get_focused_process_name() -> Optional[str]:
    try:
        import psutil  # type: ignore
        import pygetwindow as gw  # type: ignore
        import win32process  # type: ignore

        active = gw.getActiveWindow()
        if not active:
            return None
        pid = win32process.GetWindowThreadProcessId(active._hWnd)[1]
        if not pid:
            return None
        return psutil.Process(pid).name()
    except Exception:
        return None


def volume_for_mapping(mapping: str) -> Optional[float]:
    """
    Resolve a knob mapping to a 0..1 volume, or None when nothing matches.
    explorer.exe / empty-of-app master → endpoint master volume.
    """
    if not mapping:
        return None
    if mapping == "explorer.exe":
        return get_master_volume()
    if mapping == "focused_app":
        name = get_focused_process_name()
        if not name:
            return None
        return get_app_volume(name)
    # Button actions / URLs / profile switches are not volume targets
    if mapping in (
        "toggle_mic_mute",
        "toggle_master_mute",
        "lock_pc",
        "next_profile",
    ) or mapping.startswith("profile:") or mapping.startswith("http") or mapping.startswith("www."):
        return None
    if mapping.lower().endswith(".exe"):
        return get_app_volume(mapping)
    return None


def live_levels_from_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the same shape the UI already expects:
      { stale, connected, knobs: { K1: {volume, pct}, ... } }
    """
    _ensure_com()
    num = int(cfg.get("NUM_KNOBS") or 5)
    mappings = cfg.get("APP_MAPPINGS") or {}
    knobs: Dict[str, Any] = {}
    any_hit = False
    for i in range(1, num + 1):
        key = f"K{i}"
        mapping = mappings.get(key) or ""
        level = volume_for_mapping(mapping) if mapping else None
        if level is None:
            knobs[key] = {}
        else:
            any_hit = True
            pct = int(round(max(0.0, min(1.0, level)) * 100))
            knobs[key] = {"volume": round(level, 4), "pct": pct}
    return {
        "ts": 0.0,
        "connected": any_hit,
        "stale": not any_hit,
        "knobs": knobs,
        "age": 0.0,
        "source": "pycaw",
    }
