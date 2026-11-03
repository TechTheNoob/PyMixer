"""
Virtual mixer board state for the public PyMixer app.

Knob/button values live in LOCALAPPDATA/PyMixer (not the app folder).
Writes only on user input or real-board transitions — no idle writes.
"""

from __future__ import annotations

import itertools
import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

_APP_DIR = os.path.dirname(os.path.abspath(__file__))

_REAL_QUIET_S = 3.0
_REAL_LOCK = threading.Lock()
_REAL_LAST_SEEN = 0.0
_REAL_PUBLISHED = False


def _resolve_state_path() -> str:
    env = os.environ.get("PYMIXER_VIRTUAL_STATE")
    if env:
        return os.path.abspath(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP")
        if base:
            folder = os.path.join(base, "PyMixer")
            try:
                os.makedirs(folder, exist_ok=True)
                return os.path.abspath(os.path.join(folder, "virtual_board.json"))
            except OSError:
                pass
    xdg = os.environ.get("XDG_STATE_HOME")
    home = os.path.expanduser("~")
    folder = os.path.join(xdg, "PyMixer") if xdg else os.path.join(home, ".local", "state", "PyMixer")
    try:
        os.makedirs(folder, exist_ok=True)
        return os.path.abspath(os.path.join(folder, "virtual_board.json"))
    except OSError:
        return os.path.abspath(os.path.join(_APP_DIR, "virtual_board.json"))


STATE_PATH = _resolve_state_path()
STATE_LOCK = threading.RLock()
DEFAULT_KNOBS = {f"K{i}": 512 for i in range(1, 6)}
_WRITE_COUNTER = itertools.count(1)

SHOW_FLAG = os.path.join(_APP_DIR, "pymixer_controller_show.flag")
LOCK_FILE = os.path.join(_APP_DIR, "pymixer_controller.lock")


def _is_lock_error(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) in (5, 32):
        return True
    return False


def _atomic_write(data: Dict[str, Any]) -> None:
    clean = {
        "knobs": dict(data.get("knobs") or DEFAULT_KNOBS),
        "button_events": list(data.get("button_events") or []),
        "button_seq": int(data.get("button_seq") or 0),
        "real_board": bool(data.get("real_board")),
    }
    if data.get("real_board_line"):
        clean["real_board_line"] = str(data.get("real_board_line"))
    if data.get("real_board_until") is not None:
        try:
            clean["real_board_until"] = float(data.get("real_board_until"))
        except (TypeError, ValueError):
            pass
    directory = os.path.dirname(STATE_PATH) or "."
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError:
        pass
    body = json.dumps(clean, indent=2)
    last_err: Optional[BaseException] = None
    tmp_path = None
    for attempt in range(12):
        tag = f"{os.getpid()}_{next(_WRITE_COUNTER)}_{uuid.uuid4().hex[:8]}"
        tmp_path = os.path.join(directory, f".virtual_board_{tag}.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(body)
                f.flush()
            for _ in range(8):
                try:
                    os.replace(tmp_path, STATE_PATH)
                    return
                except Exception as exc:
                    last_err = exc
                    if not _is_lock_error(exc):
                        break
                    time.sleep(0.03)
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                f.write(body)
            return
        except Exception as exc:
            last_err = exc
            if _is_lock_error(exc):
                time.sleep(0.03)
                continue
            raise
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
    if last_err:
        raise last_err


def _read_file_tolerant() -> Dict[str, Any]:
    empty = {"knobs": dict(DEFAULT_KNOBS), "button_events": [], "button_seq": 0, "real_board": False}
    for attempt in range(8):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                raw = f.read()
            if not raw.strip():
                return dict(empty)
            data = json.loads(raw)
            return data if isinstance(data, dict) else dict(empty)
        except FileNotFoundError:
            return dict(empty)
        except Exception:
            time.sleep(0.02 * (attempt + 1))
    return dict(empty)


def _ensure_state() -> Dict[str, Any]:
    with STATE_LOCK:
        if not os.path.exists(STATE_PATH):
            data = {"knobs": dict(DEFAULT_KNOBS), "button_events": [], "button_seq": 0, "real_board": False}
            _atomic_write(data)
            return data
        data = _read_file_tolerant()
        knobs = data.get("knobs")
        if not isinstance(knobs, dict):
            knobs = dict(DEFAULT_KNOBS)
        for i in range(1, 6):
            key = f"K{i}"
            try:
                knobs[key] = max(0, min(1023, int(knobs.get(key, DEFAULT_KNOBS[key]))))
            except (TypeError, ValueError):
                knobs[key] = DEFAULT_KNOBS[key]
        data["knobs"] = knobs
        if not isinstance(data.get("button_events"), list):
            data["button_events"] = []
        try:
            data["button_seq"] = int(data.get("button_seq") or 0)
        except (TypeError, ValueError):
            data["button_seq"] = 0
        data["real_board"] = bool(data.get("real_board"))
        return data


def read_state() -> Dict[str, Any]:
    return _ensure_state()


def note_real_board_line(line: Optional[str] = None) -> None:
    """Call from the tray serial thread when a valid hardware frame arrives."""
    global _REAL_LAST_SEEN, _REAL_PUBLISHED
    now = time.time()
    with _REAL_LOCK:
        _REAL_LAST_SEEN = now
        was = _REAL_PUBLISHED
        _REAL_PUBLISHED = True
    if not was:
        with STATE_LOCK:
            data = _ensure_state()
            data["real_board"] = True
            if line:
                data["real_board_line"] = line.strip()
            _atomic_write(data)


def clear_real_board_if_quiet() -> None:
    """Call periodically from the tray serial thread."""
    global _REAL_PUBLISHED
    with _REAL_LOCK:
        quiet = (time.time() - _REAL_LAST_SEEN) >= _REAL_QUIET_S
        was = _REAL_PUBLISHED
    if quiet and was:
        with _REAL_LOCK:
            _REAL_PUBLISHED = False
        with STATE_LOCK:
            data = _ensure_state()
            data["real_board"] = False
            data.pop("real_board_line", None)
            data.pop("real_board_until", None)
            _atomic_write(data)


def real_board_active() -> bool:
    with _REAL_LOCK:
        if _REAL_PUBLISHED and (time.time() - _REAL_LAST_SEEN) < _REAL_QUIET_S:
            return True
    try:
        data = _read_file_tolerant()
        until = data.get("real_board_until")
        if until is not None:
            try:
                until_f = float(until)
            except (TypeError, ValueError):
                until_f = 0.0
            if time.time() < until_f:
                return True
            # Expired cross-process latch — clear once
            if data.get("real_board") or data.get("real_board_line") or until is not None:
                with STATE_LOCK:
                    cur = _ensure_state()
                    if cur.get("real_board") or cur.get("real_board_line") or cur.get("real_board_until") is not None:
                        cur["real_board"] = False
                        cur.pop("real_board_line", None)
                        cur.pop("real_board_until", None)
                        _atomic_write(cur)
                return False
        # Tray process publishes real_board=True on hardware frames and clears after quiet
        if bool(data.get("real_board")):
            return True
    except Exception:
        pass
    return False


def simulate_real_board_for_seconds(line: str, seconds: float = 3.0) -> None:
    """Test/live helper: cross-process pause latch."""
    parts = line.strip().split("|")
    if len(parts) != 15:
        return
    with STATE_LOCK:
        data = _ensure_state()
        data["real_board"] = True
        data["real_board_line"] = line.strip()
        data["real_board_until"] = time.time() + float(seconds)
        _atomic_write(data)
    note_real_board_line(line)


def set_knob(key: str, value: int) -> None:
    if real_board_active():
        return
    if key not in DEFAULT_KNOBS:
        return
    value = max(0, min(1023, int(value)))
    with STATE_LOCK:
        data = _ensure_state()
        if int(data["knobs"].get(key, -1)) == value:
            return
        data["knobs"][key] = value
        _atomic_write(data)


def pulse_button(key: str) -> None:
    if real_board_active():
        return
    if not key.startswith("B"):
        return
    with STATE_LOCK:
        data = _ensure_state()
        seq = int(data.get("button_seq") or 0) + 1
        data["button_seq"] = seq
        events = list(data.get("button_events") or [])
        events.append({"id": seq, "key": key, "ts": time.time()})
        data["button_events"] = events[-40:]
        _atomic_write(data)


def consume_button_events() -> List[str]:
    """Return pending button keys and clear them (tray serial thread)."""
    with STATE_LOCK:
        data = _ensure_state()
        events = list(data.get("button_events") or [])
        if not events:
            return []
        data["button_events"] = []
        _atomic_write(data)
    return [str(e.get("key")) for e in events if isinstance(e, dict) and e.get("key")]


def frame_values(num_knobs: int = 5, num_buttons: int = 10) -> List[int]:
    """Build an ESP32-style frame from virtual knobs + empty buttons (events separate)."""
    state = read_state()
    knobs_map = state.get("knobs") or {}
    knobs = []
    for i in range(num_knobs):
        key = f"K{i + 1}"
        try:
            knobs.append(max(0, min(1023, int(knobs_map.get(key, 512)))))
        except (TypeError, ValueError):
            knobs.append(512)
    buttons = [0] * num_buttons
    return knobs + buttons


def touch_show_flag() -> None:
    try:
        with open(SHOW_FLAG, "a", encoding="utf-8"):
            pass
        os.utime(SHOW_FLAG, None)
    except OSError:
        pass
