"""
Shared config load / save / profile helpers for PyMixer.

Keeps config.py backward compatible: older builds that only know about
SERIAL_PORT / APP_MAPPINGS / etc. still work. Profiles are stored as:

    PROFILES = {
        "Default": {
            "APP_MAPPINGS": {...},
            "SLIDER_REVERSE": {...},
            "SLIDER_SENSITIVITY": {...},
            "SLIDER_CURVE": {...},
        },
        ...
    }
    ACTIVE_PROFILE = "Default"

On load, if PROFILES is missing, the existing top-level mappings are migrated
into a "Default" profile. Top-level APP_MAPPINGS / SLIDER_* always mirror the
active profile so the serial reader keeps working unchanged.
"""

from __future__ import annotations

import json
import os
import errno
import sys
import tempfile
import time
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

# Response curve: volume = x ** exponent (more travel at the low end).
CURVE_EXPONENTS = {
    "linear": 1.0,
    "gentle": 1.8,
    "strong": 3.0,
}
DEFAULT_CURVE = "linear"
VALID_CURVES = tuple(CURVE_EXPONENTS.keys())

# Legacy live-levels helpers (tests only). Live faders now read Windows volumes
# via pycaw in the settings/popup process (volume_read). Paths resolve under TEMP.
LIVE_LEVELS_FILENAME = "live_levels.json"
LIVE_LEVELS_STALE_SECONDS = 2.0


def normalize_curve(value: Any) -> str:
    if isinstance(value, str) and value.lower() in CURVE_EXPONENTS:
        return value.lower()
    return DEFAULT_CURVE


def apply_curve(normalized: float, curve: str = DEFAULT_CURVE) -> float:
    """Map 0..1 slider position through the response curve."""
    x = max(0.0, min(1.0, float(normalized)))
    exp = CURVE_EXPONENTS.get(normalize_curve(curve), 1.0)
    if exp == 1.0:
        return x
    return x ** exp


def live_levels_path(base_dir: Optional[str] = None) -> str:
    """
    Path for a legacy live_levels.json.
    Prefer %TEMP%/PyMixer (or /tmp/PyMixer). Explicit base_dir still honored
    (used by unit tests with a temp folder).
    """
    if base_dir is not None:
        return os.path.join(base_dir, LIVE_LEVELS_FILENAME)
    tmp = os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir()
    folder = os.path.join(tmp, "PyMixer")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        folder = tmp
    return os.path.join(folder, LIVE_LEVELS_FILENAME)


def write_live_levels(
    knobs: Dict[str, Dict[str, Any]],
    path: Optional[str] = None,
    *,
    connected: bool = True,
) -> None:
    """Atomically write live knob levels for the settings UI to poll."""
    path = path or live_levels_path()
    payload = {
        "ts": time.time(),
        "connected": bool(connected),
        "knobs": knobs,
    }
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".live_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        # Non-fatal for the audio path — swallow after cleanup.


def read_live_levels(
    path: Optional[str] = None,
    *,
    stale_after: float = LIVE_LEVELS_STALE_SECONDS,
) -> Dict[str, Any]:
    """Read live levels. Marks stale when older than stale_after seconds."""
    path = path or live_levels_path()
    empty = {
        "ts": 0.0,
        "connected": False,
        "stale": True,
        "knobs": {},
        "age": None,
    }
    if not os.path.exists(path):
        return empty
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return empty
        ts = float(data.get("ts") or 0.0)
        age = max(0.0, time.time() - ts) if ts else None
        stale = age is None or age > stale_after
        knobs = data.get("knobs") if isinstance(data.get("knobs"), dict) else {}
        return {
            "ts": ts,
            "connected": bool(data.get("connected", True)) and not stale,
            "stale": stale,
            "knobs": knobs,
            "age": age,
        }
    except Exception:
        return empty


def default_config() -> Dict[str, Any]:
    knobs = DEFAULT_NUM_KNOBS
    buttons = DEFAULT_NUM_BUTTONS
    mappings = {f"K{i+1}": "" for i in range(knobs)}
    mappings.update({f"B{i+1}": "" for i in range(buttons)})
    reverse = {f"K{i+1}": False for i in range(knobs)}
    sensitivity = {f"K{i+1}": 1.0 for i in range(knobs)}
    curve = {f"K{i+1}": DEFAULT_CURVE for i in range(knobs)}
    profile = {
        "APP_MAPPINGS": mappings,
        "SLIDER_REVERSE": reverse,
        "SLIDER_SENSITIVITY": sensitivity,
        "SLIDER_CURVE": curve,
    }
    return {
        "SERIAL_PORT": "COM3",
        "BAUD_RATE": 115200,
        "NUM_KNOBS": knobs,
        "NUM_BUTTONS": buttons,
        "APP_MAPPINGS": deepcopy(mappings),
        "SLIDER_REVERSE": deepcopy(reverse),
        "SLIDER_SENSITIVITY": deepcopy(sensitivity),
        "SLIDER_CURVE": deepcopy(curve),
        "PROFILES": {"Default": deepcopy(profile)},
        "ACTIVE_PROFILE": "Default",
        "PROFILE_ICONS": {"Default": "D"},
    }


def _ensure_curve_map(raw: Any, num_knobs: int, fallback: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    out: Dict[str, str] = {}
    src = raw if isinstance(raw, dict) else {}
    fb = fallback if isinstance(fallback, dict) else {}
    for i in range(num_knobs):
        key = f"K{i+1}"
        if key in src:
            out[key] = normalize_curve(src[key])
        elif key in fb:
            out[key] = normalize_curve(fb[key])
        else:
            out[key] = DEFAULT_CURVE
    return out


def _profile_payload(cfg: Dict[str, Any]) -> Dict[str, Any]:
    num_knobs = int(cfg.get("NUM_KNOBS") or DEFAULT_NUM_KNOBS)
    return {
        "APP_MAPPINGS": deepcopy(cfg.get("APP_MAPPINGS", {})),
        "SLIDER_REVERSE": deepcopy(cfg.get("SLIDER_REVERSE", {})),
        "SLIDER_SENSITIVITY": deepcopy(cfg.get("SLIDER_SENSITIVITY", {})),
        "SLIDER_CURVE": _ensure_curve_map(cfg.get("SLIDER_CURVE"), num_knobs),
    }


def migrate_profiles(cfg: Dict[str, Any], *, apply: bool = True) -> Dict[str, Any]:
    """Ensure PROFILES / ACTIVE_PROFILE / SLIDER_CURVE exist; migrate legacy flat config."""
    out = deepcopy(cfg)
    num_knobs = int(out.get("NUM_KNOBS") or DEFAULT_NUM_KNOBS)
    # Top-level curve migration
    out["SLIDER_CURVE"] = _ensure_curve_map(out.get("SLIDER_CURVE"), num_knobs)

    profiles = out.get("PROFILES")
    if not isinstance(profiles, dict) or not profiles:
        out["PROFILES"] = {"Default": _profile_payload(out)}
        out["ACTIVE_PROFILE"] = "Default"
    else:
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
                "SLIDER_CURVE": _ensure_curve_map(
                    payload.get("SLIDER_CURVE"),
                    num_knobs,
                    out.get("SLIDER_CURVE"),
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
    if "VIRTUAL_CONTROLLER_ENABLED" not in out:
        out["VIRTUAL_CONTROLLER_ENABLED"] = False
    else:
        out["VIRTUAL_CONTROLLER_ENABLED"] = bool(out.get("VIRTUAL_CONTROLLER_ENABLED"))
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
    num_knobs = int(cfg.get("NUM_KNOBS") or DEFAULT_NUM_KNOBS)
    cfg["APP_MAPPINGS"] = deepcopy(payload.get("APP_MAPPINGS", {}))
    cfg["SLIDER_REVERSE"] = deepcopy(payload.get("SLIDER_REVERSE", {}))
    cfg["SLIDER_SENSITIVITY"] = deepcopy(payload.get("SLIDER_SENSITIVITY", {}))
    cfg["SLIDER_CURVE"] = _ensure_curve_map(
        payload.get("SLIDER_CURVE"), num_knobs, cfg.get("SLIDER_CURVE")
    )


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


def _read_config_text(path: str) -> str:
    """Read config.py bytes and close the handle immediately before parsing."""
    with open(path, "rb") as f:
        raw = f.read()
    return raw.decode("utf-8")


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    cfg = default_config()
    path = path or config_path()
    file_had_profiles = False
    if os.path.exists(path):
        try:
            local_vars: Dict[str, Any] = {}
            source = _read_config_text(path)  # handle closed before exec
            exec(source, {}, local_vars)
            file_had_profiles = "PROFILES" in local_vars and isinstance(
                local_vars.get("PROFILES"), dict
            ) and bool(local_vars.get("PROFILES"))
            cfg.update(local_vars)
            if not file_had_profiles:
                cfg["PROFILES"] = {}
                cfg["ACTIVE_PROFILE"] = "Default"
        except Exception as exc:  # noqa: BLE001 - surface parse errors to caller
            print(f"Error parsing config.py: {exc}. Using defaults where needed.")
    return migrate_profiles(cfg)


def _repr_write(value: Any) -> str:
    return repr(value)


def save_config(cfg: Dict[str, Any], path: Optional[str] = None) -> None:
    """
    Atomically write config.py with cross-process locking and WinError 5/32 retries.

    On Windows, antivirus / indexer / another PyMixer process can briefly lock the
    destination so os.replace fails with Access Denied. We retry with backoff, then
    fall back to in-place truncate+write, and always clean up the .tmp file.
    """
    path = path or config_path()
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
        f"SLIDER_CURVE = {_repr_write(cfg['SLIDER_CURVE'])}",
        f"PROFILES = {_repr_write(cfg['PROFILES'])}",
        f"ACTIVE_PROFILE = {_repr_write(cfg['ACTIVE_PROFILE'])}",
        f"PROFILE_ICONS = {_repr_write(cfg.get('PROFILE_ICONS', {}))}",
        f"VIRTUAL_CONTROLLER_ENABLED = {_repr_write(bool(cfg.get('VIRTUAL_CONTROLLER_ENABLED', False)))}",
        "",
    ]
    body = "\n".join(lines)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    try:
        with _ConfigWriteLock(path):
            _atomic_write_text(path, body, directory=directory)
    except ConfigSaveError:
        raise
    except OSError as exc:
        raise ConfigSaveError(
            "Could not save settings. Close other PyMixer windows and try again."
        ) from exc


def _is_sharing_violation(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError):
        win = getattr(exc, "winerror", None)
        if win in (5, 32):  # ACCESS_DENIED, SHARING_VIOLATION
            return True
        if getattr(exc, "errno", None) in (errno.EACCES, errno.EPERM, errno.EBUSY):
            return True
    return False


def _atomic_write_text(
    path: str,
    body: str,
    *,
    directory: Optional[str] = None,
    replace_attempts: int = 10,
    replace_fn=None,
) -> None:
    """
    Write body via temp + os.replace with retries; fall back to in-place write.

    replace_fn is injectable for tests (defaults to os.replace).
    """
    directory = directory or (os.path.dirname(path) or ".")
    replace = replace_fn or os.replace
    fd, tmp = tempfile.mkstemp(prefix=".config_", suffix=".tmp", dir=directory)
    wrote_tmp = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        wrote_tmp = True

        last_err: Optional[BaseException] = None
        for attempt in range(replace_attempts):
            try:
                replace(tmp, path)
                return
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if not _is_sharing_violation(exc):
                    break
                # ~2s total: 0.05, 0.1, 0.15 ... capped
                time.sleep(min(0.05 * (attempt + 1), 0.35))

        # Fallback: write in place (truncate + write + flush + fsync)
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(body)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            return
        except Exception as exc:  # noqa: BLE001
            if last_err is not None:
                raise exc from last_err
            raise
    finally:
        if wrote_tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


class ConfigSaveError(OSError):
    """Raised when config.py cannot be saved after retries + fallback."""

    def __init__(self, message: str = "Could not save settings. Close other PyMixer windows and try again."):
        super().__init__(message)
        self.user_message = message


class _ConfigWriteLock:
    """
    Cross-process lock around config.py writes.
    Windows: msvcrt.locking on a sibling .lock file.
    Else: fcntl.flock. Falls back to O_EXCL lockfile with stale timeout.
    """

    STALE_SECONDS = 15.0

    def __init__(self, config_path: str):
        self.lock_path = config_path + ".lock"
        self._fh = None
        self._mode = None  # 'msvcrt' | 'fcntl' | 'excl'

    def __enter__(self):
        deadline = time.time() + 5.0
        last_err = None
        while time.time() < deadline:
            try:
                self._acquire_once()
                return self
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(0.05)
        raise ConfigSaveError(
            "Could not save settings (busy). Close other PyMixer windows and try again."
        ) from last_err

    def _acquire_once(self) -> None:
        # Prefer platform locks
        try:
            if sys.platform == "win32":
                import msvcrt  # type: ignore

                self._fh = open(self.lock_path, "a+b")
                self._fh.seek(0)
                # lock 1 byte
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                self._mode = "msvcrt"
                return
            else:
                import fcntl  # type: ignore

                self._fh = open(self.lock_path, "a+b")
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._mode = "fcntl"
                return
        except Exception:
            # Fall through to O_EXCL
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:
                    pass
                self._fh = None

        # O_EXCL lockfile with stale timeout
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
            self._mode = "excl"
            self._fh = None
            return
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(self.lock_path)
            except OSError:
                age = 0
            if age > self.STALE_SECONDS:
                try:
                    os.unlink(self.lock_path)
                except OSError:
                    pass
            raise

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._mode == "msvcrt" and self._fh is not None:
                import msvcrt  # type: ignore

                try:
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
            elif self._mode == "fcntl" and self._fh is not None:
                import fcntl  # type: ignore

                try:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
            elif self._mode == "excl":
                try:
                    os.unlink(self.lock_path)
                except OSError:
                    pass
        finally:
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:
                    pass
            self._fh = None
        return False



def list_profile_names(cfg: Dict[str, Any]) -> List[str]:
    cfg = migrate_profiles(cfg)
    return list(cfg["PROFILES"].keys())


def switch_profile(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:
    cfg = migrate_profiles(cfg)
    if name not in cfg["PROFILES"]:
        raise KeyError(f"Unknown profile: {name}")
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
    if (
        "." in v
        and not v.lower().endswith(".exe")
        and v not in SPECIAL_KNOB_ACTIONS
        and v not in SPECIAL_BUTTON_ACTIONS
        and not v.startswith("profile:")
    ):
        return True
    return False
