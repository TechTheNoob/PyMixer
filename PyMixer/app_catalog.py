"""
App picker catalog helpers for the settings UI.

- Audio sessions from pycaw (preferred default list)
- Running processes via psutil, with system/helper noise filtered
- Friendly display labels while keeping the .exe as the stored value
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Obvious Windows system / helper noise to hide behind "Show all running apps…"
_NOISE_REGEXES = [
    re.compile(p, re.I)
    for p in (
        r".*Host\.exe$",
        r".*CrashHandler.*\.exe$",
        r"^svchost\.exe$",
        r"^RuntimeBroker\.exe$",
        r"^SystemSettings\.exe$",
        r"^SearchHost\.exe$",
        r"^ShellExperienceHost\.exe$",
        r"^StartMenuExperienceHost\.exe$",
        r"^TextInputHost\.exe$",
        r"^UserOOBEBroker\.exe$",
        r"^ApplicationFrameHost\.exe$",
        r"^backgroundTaskHost\.exe$",
        r"^AggregatorHost\.exe$",
        r"^AppActions\.exe$",
        r"^dllhost\.exe$",
        r"^conhost\.exe$",
        r"^sihost\.exe$",
        r"^taskhostw\.exe$",
        r"^ctfmon\.exe$",
        r"^fontdrvhost\.exe$",
        r"^dwm\.exe$",
        r"^csrss\.exe$",
        r"^smss\.exe$",
        r"^winlogon\.exe$",
        r"^services\.exe$",
        r"^lsass\.exe$",
        r"^explorer\.exe$",  # master volume uses this specially; hide from "apps"
        r"^SecurityHealthSystray\.exe$",
        r"^WidgetService\.exe$",
        r"^Widgets\.exe$",
        r"^PhoneExperienceHost\.exe$",
        r"^LockApp\.exe$",
        r"^LogonUI\.exe$",
        r"^CrossDeviceResume\.exe$",
        r"^MicrosoftEdgeUpdate\.exe$",
        r"^msedgewebview2\.exe$",
        r"^ChsIME\.exe$",
        r"^CompPkgSrv\.exe$",
        r"^smartscreen\.exe$",
        r"^WmiPrvSE\.exe$",
        r"^unsecapp\.exe$",
        r"^SearchIndexer\.exe$",
        r"^spoolsv\.exe$",
        r"^NisSrv\.exe$",
        r"^SgrmBroker\.exe$",
    )
]


def is_noise_process(name: str) -> bool:
    if not name or not isinstance(name, str):
        return True
    if not name.lower().endswith(".exe"):
        return True
    return any(rx.search(name) for rx in _NOISE_REGEXES)


def friendly_app_label(exe: str) -> str:
    """Discord.exe → Discord; keep non-.exe values as-is."""
    if not exe:
        return ""
    if not exe.lower().endswith(".exe"):
        return exe
    base = exe[:-4]
    # Light title-case for all-lower names; preserve CamelCase / mixed
    if base.islower():
        return base[:1].upper() + base[1:]
    return base


def _dedupe_sorted(names: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for n in names:
        if not n:
            continue
        key = n.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    out.sort(key=lambda s: s.lower())
    return out


def list_audio_session_exes() -> List[str]:
    """Process names that currently have a Windows audio session (pycaw)."""
    try:
        from pycaw.pycaw import AudioUtilities  # type: ignore
    except Exception:
        return []
    names: List[str] = []
    try:
        for session in AudioUtilities.GetAllSessions():
            proc = getattr(session, "Process", None)
            if not proc:
                continue
            try:
                name = proc.name()
            except Exception:
                continue
            if name and name.lower().endswith(".exe"):
                names.append(name)
    except Exception:
        return []
    return _dedupe_sorted(names)


def list_running_exes(*, include_noise: bool = False) -> List[str]:
    try:
        import psutil  # type: ignore
    except Exception:
        return []
    names: List[str] = []
    try:
        for proc in psutil.process_iter(["name"]):
            name = (proc.info or {}).get("name") or ""
            if not name.lower().endswith(".exe"):
                continue
            if not include_noise and is_noise_process(name):
                continue
            names.append(name)
    except Exception:
        return []
    return _dedupe_sorted(names)


def catalog_entries(exes: Sequence[str]) -> List[Dict[str, str]]:
    return [{"value": e, "label": friendly_app_label(e)} for e in exes]


def build_app_catalog(
    *,
    current: Optional[str] = None,
    audio: Optional[Sequence[str]] = None,
    running: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Structured catalog for the settings picker.

    audio: sessions currently playing / holding an audio session
    running: other running apps with noise filtered (for expander)
    """
    audio_list = _dedupe_sorted(audio if audio is not None else list_audio_session_exes())
    running_list = _dedupe_sorted(
        running if running is not None else list_running_exes(include_noise=False)
    )
    # Don't duplicate audio apps inside the expander list
    audio_keys = {a.lower() for a in audio_list}
    running_only = [r for r in running_list if r.lower() not in audio_keys]

    # Always surface the currently mapped value
    current_entry = None
    if current and isinstance(current, str) and current.lower().endswith(".exe"):
        all_known = audio_keys | {r.lower() for r in running_only}
        if current.lower() not in all_known:
            current_entry = {"value": current, "label": friendly_app_label(current)}

    return {
        "audio": catalog_entries(audio_list),
        "running": catalog_entries(running_only),
        "current": current_entry,
    }
