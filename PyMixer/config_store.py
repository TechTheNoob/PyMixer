"""
Shared config load / save / profile helpers for PyMixer.

Keeps config.py backward compatible: older builds that only know about
SERIAL_PORT / APP_MAPPINGS / etc. still work. Profiles are stored as:

    PROFILES = {
        "Default": {
            "APP_MAPPINGS": {...},
            "SLIDER_REVERSE": {...},
            "SLIDER_SENSITIVITY": {...},
        },
        ...
    }
    ACTIVE_PROFILE = "Default"

On load, if PROFILES is missing, the existing top-level mappings are migrated
into a "Default" profile. Top-level APP_MAPPINGS / SLIDER_* always mirror the
active profile so the serial reader keeps working unchanged.
"""

from __future__ import annotations

import os
import sys
import tempfile
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_NUM_KNOBS = 5
DEFAULT_NUM_BUTTONS = 10

SPECIAL_KNOB_ACTIONS = {
    "focused_app": "Focused Application",
    "explorer.exe": "Master Volume",
}

SPECIAL_BUTTON_ACTIONS = {
    "toggle_mic_mute": "Toggle Microphone Mute",
    "toggle_master_mute": "Toggle Master Mute",
    "lock_pc": "Lock PC",
    "next_profile": "Next Profile",
}

# Button values that are treated as "open URL" when they look like a URL
# (start with http, or contain a dot and no .exe). Stored as the raw string.


def default_config() -> Dict[str, Any]:
    knobs = DEFAULT_NUM_KNOBS
    buttons = DEFAULT_NUM_BUTTONS
    mappings = {f"K{i+1}": "" for i in range(knobs)}
    mappings.update({f"B{i+1}": "" for i in range(buttons)})
    reverse = {f"K{i+1}": False for i in range(knobs)}
    sensitivity = {f"K{i+1}": 1.0 for i in range(knobs)}
    profile = {
        "APP_MAPPINGS": mappings,
        "SLIDER_REVERSE": reverse,
        "SLIDER_SENSITIVITY": sensitivity,
    }
    return {
        "SERIAL_PORT": "COM3",
        "BAUD_RATE": 115200,
        "NUM_KNOBS": knobs,
        "NUM_BUTTONS": buttons,
        "APP_MAPPINGS": deepcopy(mappings),
        "SLIDER_REVERSE": deepcopy(reverse),
        "SLIDER_SENSITIVITY": deepcopy(sensitivity),
        "PROFILES": {"Default": deepcopy(profile)},
        "ACTIVE_PROFILE": "Default",
        "PROFILE_ICONS": {"Default": "P"},
    }


def _profile_payload(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "APP_MAPPINGS": deepcopy(cfg.get("APP_MAPPINGS", {})),
        "SLIDER_REVERSE": deepcopy(cfg.get("SLIDER_REVERSE", {})),
        "SLIDER_SENSITIVITY": deepcopy(cfg.get("SLIDER_SENSITIVITY", {})),
    }


def migrate_profiles(cfg: Dict[str, Any], *, apply: bool = True) -> Dict[str, Any]:
    """Ensure PROFILES / ACTIVE_PROFILE exist; migrate legacy flat config."""
    out = deepcopy(cfg)
    profiles = out.get("PROFILES")
    if not isinstance(profiles, dict) or not profiles:
        out["PROFILES"] = {"Default": _profile_payload(out)}
        out["ACTIVE_PROFILE"] = "Default"
    else:
        # Normalize each profile to have the three keys
        normalized = {}
        for name, payload in profiles.items():
            if not isinstance(payload, dict):
                continue
            normalized[name] = {
                "APP_MAPPINGS": deepcopy(
                    payload.get("APP_MAPPINGS", out.get("APP_MAPPINGS", {}))
                ),
                "SLIDER_REVERSE": deepcopy(
                    payload.get("SLIDER_REVERSE", out.get("SLIDER_REVERSE", {}))
                ),
                "SLIDER_SENSITIVITY": deepcopy(
                    payload.get(
                        "SLIDER_SENSITIVITY", out.get("SLIDER_SENSITIVITY", {})
                    )
                ),
            }
        if not normalized:
            normalized = {"Default": _profile_payload(out)}
        out["PROFILES"] = normalized
        active = out.get("ACTIVE_PROFILE")
        if active not in out["PROFILES"]:
            out["ACTIVE_PROFILE"] = next(iter(out["PROFILES"]))
    if not isinstance(out.get("PROFILE_ICONS"), dict):
        out["PROFILE_ICONS"] = {}
    for name in out["PROFILES"]:
        out["PROFILE_ICONS"].setdefault(name, _default_icon(name))
    # Mirror active profile onto top-level keys (skip when caller already
    # pushed newer top-level edits into the active profile and wants to save).
    if apply:
        apply_active_profile(out)
    return out


def _default_icon(name: str) -> str:
    presets = {
        "Default": "P",
        "Gaming": "🎮",
        "Work": "💼",
        "Music": "🎵",
    }
    if name in presets:
        return presets[name]
    return (name[:1] or "P").upper()


def apply_active_profile(cfg: Dict[str, Any]) -> None:
    """Copy the active profile's mappings onto top-level keys (in place)."""
    profiles = cfg.get("PROFILES") or {}
    active = cfg.get("ACTIVE_PROFILE")
    if active not in profiles:
        return
    payload = profiles[active]
    cfg["APP_MAPPINGS"] = deepcopy(payload.get("APP_MAPPINGS", {}))
    cfg["SLIDER_REVERSE"] = deepcopy(payload.get("SLIDER_REVERSE", {}))
    cfg["SLIDER_SENSITIVITY"] = deepcopy(payload.get("SLIDER_SENSITIVITY", {}))


def sync_active_into_profiles(cfg: Dict[str, Any]) -> None:
    """Write current top-level mappings back into the active profile slot."""
    profiles = cfg.setdefault("PROFILES", {})
    active = cfg.get("ACTIVE_PROFILE") or "Default"
    profiles[active] = _profile_payload(cfg)
    cfg["PROFILES"] = profiles


def config_path(base_dir: Optional[str] = None) -> str:
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(base_dir, "config.py")


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    cfg = default_config()
    path = path or config_path()
    file_had_profiles = False
    if os.path.exists(path):
        try:
            local_vars: Dict[str, Any] = {}
            with open(path, "r", encoding="utf-8") as f:
                exec(f.read(), {}, local_vars)
            file_had_profiles = "PROFILES" in local_vars and isinstance(
                local_vars.get("PROFILES"), dict
            ) and bool(local_vars.get("PROFILES"))
            cfg.update(local_vars)
            # If the file was legacy (no PROFILES), drop the empty default profile
            # so migrate_profiles rebuilds Default from the top-level mappings.
            if not file_had_profiles:
                cfg["PROFILES"] = {}
                cfg["ACTIVE_PROFILE"] = "Default"
        except Exception as exc:  # noqa: BLE001 - surface parse errors to caller
            print(f"Error parsing config.py: {exc}. Using defaults where needed.")
    return migrate_profiles(cfg)


def _repr_write(value: Any) -> str:
    return repr(value)


def save_config(cfg: Dict[str, Any], path: Optional[str] = None) -> None:
    """Atomically write config.py. Always mirrors active profile to top-level."""
    path = path or config_path()
    # Normalize structure without clobbering in-memory top-level edits, then
    # push those edits into the active profile and mirror back out.
    cfg = migrate_profiles(cfg, apply=False)
    sync_active_into_profiles(cfg)
    apply_active_profile(cfg)

    lines = [
        f"SERIAL_PORT = {_repr_write(cfg['SERIAL_PORT'])}",
        f"BAUD_RATE = {_repr_write(int(cfg['BAUD_RATE']))}",
        f"NUM_KNOBS = {_repr_write(int(cfg['NUM_KNOBS']))}",
        f"NUM_BUTTONS = {_repr_write(int(cfg['NUM_BUTTONS']))}",
        f"APP_MAPPINGS = {_repr_write(cfg['APP_MAPPINGS'])}",
        f"SLIDER_REVERSE = {_repr_write(cfg['SLIDER_REVERSE'])}",
        f"SLIDER_SENSITIVITY = {_repr_write(cfg['SLIDER_SENSITIVITY'])}",
        f"PROFILES = {_repr_write(cfg['PROFILES'])}",
        f"ACTIVE_PROFILE = {_repr_write(cfg['ACTIVE_PROFILE'])}",
        f"PROFILE_ICONS = {_repr_write(cfg.get('PROFILE_ICONS', {}))}",
        "",
    ]
    text = "\n".join(lines)
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".config_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def list_profile_names(cfg: Dict[str, Any]) -> List[str]:
    cfg = migrate_profiles(cfg)
    return list(cfg["PROFILES"].keys())


def switch_profile(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:
    cfg = migrate_profiles(cfg)
    if name not in cfg["PROFILES"]:
        raise KeyError(f"Unknown profile: {name}")
    # Persist current edits into the profile we're leaving
    sync_active_into_profiles(cfg)
    cfg["ACTIVE_PROFILE"] = name
    apply_active_profile(cfg)
    return cfg


def next_profile(cfg: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    names = list_profile_names(cfg)
    if not names:
        return cfg, cfg.get("ACTIVE_PROFILE", "Default")
    current = cfg.get("ACTIVE_PROFILE", names[0])
    try:
        idx = names.index(current)
    except ValueError:
        idx = -1
    new_name = names[(idx + 1) % len(names)]
    return switch_profile(cfg, new_name), new_name


def add_profile(
    cfg: Dict[str, Any],
    name: str,
    *,
    clone_active: bool = True,
    icon: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = migrate_profiles(cfg)
    name = (name or "").strip()
    if not name:
        raise ValueError("Profile name required")
    if name in cfg["PROFILES"]:
        raise ValueError(f"Profile already exists: {name}")
    sync_active_into_profiles(cfg)
    if clone_active:
        payload = deepcopy(cfg["PROFILES"][cfg["ACTIVE_PROFILE"]])
    else:
        payload = _profile_payload(default_config())
    cfg["PROFILES"][name] = payload
    cfg.setdefault("PROFILE_ICONS", {})[name] = icon or _default_icon(name)
    cfg["ACTIVE_PROFILE"] = name
    apply_active_profile(cfg)
    return cfg


def rename_profile(cfg: Dict[str, Any], old: str, new: str) -> Dict[str, Any]:
    cfg = migrate_profiles(cfg)
    new = (new or "").strip()
    if old not in cfg["PROFILES"]:
        raise KeyError(f"Unknown profile: {old}")
    if not new:
        raise ValueError("New name required")
    if new != old and new in cfg["PROFILES"]:
        raise ValueError(f"Profile already exists: {new}")
    sync_active_into_profiles(cfg)
    cfg["PROFILES"][new] = cfg["PROFILES"].pop(old)
    icons = cfg.setdefault("PROFILE_ICONS", {})
    icons[new] = icons.pop(old, _default_icon(new))
    if cfg["ACTIVE_PROFILE"] == old:
        cfg["ACTIVE_PROFILE"] = new
    apply_active_profile(cfg)
    return cfg


def delete_profile(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:
    cfg = migrate_profiles(cfg)
    if name not in cfg["PROFILES"]:
        raise KeyError(f"Unknown profile: {name}")
    if len(cfg["PROFILES"]) <= 1:
        raise ValueError("Cannot delete the last profile")
    was_active = cfg["ACTIVE_PROFILE"] == name
    del cfg["PROFILES"][name]
    cfg.get("PROFILE_ICONS", {}).pop(name, None)
    if was_active:
        cfg["ACTIVE_PROFILE"] = next(iter(cfg["PROFILES"]))
        apply_active_profile(cfg)
    return cfg


def is_url_action(value: str) -> bool:
    if not value:
        return False
    v = value.strip()
    if v.startswith("http://") or v.startswith("https://"):
        return True
    if v.startswith("www."):
        return True
    # bare domain-ish, not an exe and not a known special
    if (
        "." in v
        and not v.lower().endswith(".exe")
        and v not in SPECIAL_KNOB_ACTIONS
        and v not in SPECIAL_BUTTON_ACTIONS
        and not v.startswith("profile:")
    ):
        return True
    return False
