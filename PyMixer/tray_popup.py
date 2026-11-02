"""
Frameless Discord-dark tray popup for PyMixer.

Opened from the tray icon's left-click (pystray default action). Right-click
keeps the native pystray menu as a fallback. Positions itself in the bottom-
right of the Windows work area (above the taskbar).
"""

from __future__ import annotations

import atexit
import os
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import config_store

POPUP_WIDTH = 280
POPUP_HEIGHT = 420
POPUP_MARGIN = 12
LOCK_NAME = "pymixer_tray_popup.lock"
SHOW_NAME = "pymixer_tray_popup.show"
QUIT_FLAG = "pymixer_tray_quit.flag"
RECONNECT_FLAG = "pymixer_tray_reconnect.flag"
OPEN_SETTINGS_FLAG = "pymixer_tray_open_settings.flag"


def _runtime_dir() -> str:
    return HERE


def lock_path() -> str:
    return os.path.join(_runtime_dir(), LOCK_NAME)


def show_path() -> str:
    return os.path.join(_runtime_dir(), SHOW_NAME)


def quit_flag_path() -> str:
    return os.path.join(_runtime_dir(), QUIT_FLAG)


def reconnect_flag_path() -> str:
    return os.path.join(_runtime_dir(), RECONNECT_FLAG)


def open_settings_flag_path() -> str:
    return os.path.join(_runtime_dir(), OPEN_SETTINGS_FLAG)


def work_area_rect() -> Tuple[int, int, int, int]:
    """
    Return (left, top, right, bottom) of the Windows work area.
    Falls back to a 1920x1080-ish rect on non-Windows / errors.
    """
    if sys.platform != "win32":
        return (0, 0, 1280, 720)
    try:
        import ctypes
        from ctypes import wintypes

        SPI_GETWORKAREA = 0x0030
        rect = wintypes.RECT()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
        )
        if not ok:
            raise OSError("SystemParametersInfo failed")
        return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    except Exception:
        return (0, 0, 1280, 720)


def popup_position(
    width: int = POPUP_WIDTH,
    height: int = POPUP_HEIGHT,
    margin: int = POPUP_MARGIN,
    work_area: Optional[Tuple[int, int, int, int]] = None,
) -> Tuple[int, int]:
    """Bottom-right of the work area, above the taskbar."""
    left, top, right, bottom = work_area if work_area is not None else work_area_rect()
    x = right - width - margin
    y = bottom - height - margin
    # Clamp into work area
    x = max(left + margin, x)
    y = max(top + margin, y)
    return int(x), int(y)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_lock_pid() -> Optional[int]:
    path = lock_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return None


def _write_lock() -> None:
    with open(lock_path(), "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))


def _clear_lock() -> None:
    try:
        os.unlink(lock_path())
    except OSError:
        pass


def request_show() -> bool:
    """
    Ask an existing popup to raise, or report that a new one should start.
    Returns True if an existing popup was signaled.
    """
    pid = _read_lock_pid()
    if pid and _pid_alive(pid):
        try:
            with open(show_path(), "w", encoding="utf-8") as f:
                f.write(str(time.time()))
            return True
        except OSError:
            return False
    return False


def launch_popup_process() -> None:
    """Spawn the popup in a separate process (non-blocking for the tray)."""
    if request_show():
        return
    python_executable = sys.executable
    if sys.platform == "win32" and "python.exe" in python_executable:
        pythonw = os.path.join(os.path.dirname(python_executable), "pythonw.exe")
        if os.path.exists(pythonw):
            python_executable = pythonw
    script = os.path.join(HERE, "tray_popup.py")
    try:
        subprocess.Popen(
            [python_executable, script],
            cwd=HERE,
            close_fds=True,
        )
    except Exception as exc:
        print(f"Could not launch tray popup: {exc}")


class PopupApi:
    def __init__(self, config_file: Optional[str] = None):
        self.config_file = config_file or config_store.config_path(HERE)
        self.live_file = config_store.live_levels_path(HERE)
        self._window = None

    def bind_window(self, window) -> None:
        self._window = window

    def get_popup_state(self) -> Dict[str, Any]:
        cfg = config_store.load_config(self.config_file)
        ports_ok = False
        try:
            import serial.tools.list_ports

            ports = {p.device for p in serial.tools.list_ports.comports()}
            ports_ok = str(cfg.get("SERIAL_PORT", "")) in ports
        except Exception:
            ports_ok = False
        live = config_store.read_live_levels(self.live_file)
        # Prefer live.connected when fresh
        connected = (not live.get("stale")) or ports_ok
        return {
            "active": cfg.get("ACTIVE_PROFILE", "Default"),
            "profiles": config_store.list_profile_names(cfg),
            "icons": cfg.get("PROFILE_ICONS") or {},
            "connected": bool(connected),
            "live": live,
        }

    def get_live(self) -> Dict[str, Any]:
        return config_store.read_live_levels(self.live_file)

    def switch_profile(self, name: str) -> Dict[str, Any]:
        cfg = config_store.load_config(self.config_file)
        cfg = config_store.switch_profile(cfg, name)
        config_store.save_config(cfg, self.config_file)
        return self.get_popup_state()

    def open_settings(self) -> None:
        # Signal the tray process; also launch settings directly as a backup.
        try:
            with open(open_settings_flag_path(), "w", encoding="utf-8") as f:
                f.write(str(time.time()))
        except OSError:
            pass
        gui = os.path.join(HERE, "config_gui_web.py")
        if not os.path.exists(gui):
            gui = os.path.join(HERE, "config_gui.py")
        python_executable = sys.executable
        if sys.platform == "win32" and "python.exe" in python_executable:
            pythonw = os.path.join(os.path.dirname(python_executable), "pythonw.exe")
            if os.path.exists(pythonw):
                python_executable = pythonw
        try:
            subprocess.Popen([python_executable, gui], cwd=HERE, close_fds=True)
        except Exception as exc:
            print(f"Could not open settings: {exc}")

    def reconnect(self) -> Dict[str, Any]:
        try:
            with open(reconnect_flag_path(), "w", encoding="utf-8") as f:
                f.write(str(time.time()))
        except OSError:
            pass
        return self.get_popup_state()

    def quit_app(self) -> None:
        try:
            with open(quit_flag_path(), "w", encoding="utf-8") as f:
                f.write(str(time.time()))
        except OSError:
            pass
        self.close()

    def close(self) -> None:
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass


def run() -> int:
    try:
        import webview
    except ImportError:
        print("pywebview is not installed; tray popup unavailable.")
        return 2

    # Singleton lock
    existing = _read_lock_pid()
    if existing and _pid_alive(existing) and existing != os.getpid():
        request_show()
        return 0

    _write_lock()
    atexit.register(_clear_lock)

    api = PopupApi()
    x, y = popup_position()
    index = os.path.join(HERE, "ui", "tray_popup.html")
    window = webview.create_window(
        "PyMixer",
        index,
        js_api=api,
        width=POPUP_WIDTH,
        height=POPUP_HEIGHT,
        x=x,
        y=y,
        frameless=True,
        on_top=True,
        easy_drag=False,
        background_color="#1E1F22",
        shadow=True,
    )
    api.bind_window(window)

    def _poll_show():
        # If another left-click asks us to show while still open, re-assert on top.
        last = 0.0
        while True:
            time.sleep(0.25)
            try:
                if os.path.exists(show_path()):
                    mtime = os.path.getmtime(show_path())
                    if mtime > last:
                        last = mtime
                        try:
                            window.show()
                            window.on_top = True
                        except Exception:
                            pass
                        try:
                            os.unlink(show_path())
                        except OSError:
                            pass
            except Exception:
                pass

    import threading

    threading.Thread(target=_poll_show, daemon=True).start()
    webview.start(debug=False)
    _clear_lock()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
