"""
PyMixer Virtual Controller — Discord-dark pywebview window (public feature).

Closing hides the window; the process stays warm and reopens via the tray /
Settings "Show virtual controller" action.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any, Dict

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import virtual_board

_window = None


def _clear(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = k32.OpenProcess(0x1000, False, pid)
            if handle:
                k32.CloseHandle(handle)
                return True
        except Exception:
            return False
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class BoardApi:
    def get_board_state(self) -> Dict[str, Any]:
        st = virtual_board.read_state()
        real = virtual_board.real_board_active() or bool(st.get("real_board"))
        # Prefer live memory; if latch until expired, real_board_active clears
        real = virtual_board.real_board_active()
        return {
            "knobs": st.get("knobs") or {},
            "real_board": real,
            "real_board_reason": "Real board connected" if real else "",
        }

    def set_knob(self, key: str, value: int) -> bool:
        if virtual_board.real_board_active():
            return False
        try:
            virtual_board.set_knob(key, int(value))
            return True
        except Exception:
            return False

    def pulse_button(self, key: str) -> bool:
        if virtual_board.real_board_active():
            return False
        try:
            virtual_board.pulse_button(key)
            return True
        except Exception:
            return False


def _watch_show_flag() -> None:
    global _window
    last = 0.0
    while True:
        time.sleep(0.35)
        try:
            if not os.path.exists(virtual_board.SHOW_FLAG):
                continue
            m = os.path.getmtime(virtual_board.SHOW_FLAG)
            if m <= last:
                continue
            last = m
            _clear(virtual_board.SHOW_FLAG)
            if _window is None:
                continue
            try:
                _window.show()
                try:
                    _window.restore()
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass


def main() -> None:
    global _window
    try:
        import webview
    except ImportError:
        raise SystemExit("pywebview is required for the virtual controller")

    virtual_board._ensure_state()

    if os.path.exists(virtual_board.LOCK_FILE):
        alive = False
        try:
            with open(virtual_board.LOCK_FILE, "r", encoding="utf-8") as f:
                raw = (f.read() or "").strip().split()
            pid = int(raw[0]) if raw and raw[0].isdigit() else 0
            alive = _pid_alive(pid)
        except Exception:
            alive = False
        if alive:
            virtual_board.touch_show_flag()
            return
        _clear(virtual_board.LOCK_FILE)
    try:
        with open(virtual_board.LOCK_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass

    api = BoardApi()
    index = os.path.join(HERE, "ui", "virtual_board.html")
    window = webview.create_window(
        "PyMixer Virtual Controller",
        index,
        js_api=api,
        width=560,
        height=520,
        background_color="#1E1F22",
        text_select=False,
    )
    _window = window

    def on_closing():
        try:
            window.hide()
        except Exception:
            pass
        return False

    try:
        window.events.closing += on_closing
    except Exception:
        pass

    threading.Thread(target=_watch_show_flag, daemon=True).start()
    try:
        webview.start(debug=False)
    finally:
        _clear(virtual_board.LOCK_FILE)


if __name__ == "__main__":
    main()
