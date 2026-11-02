"""
Frameless Discord-dark tray popup for PyMixer.

Left-click opens this (warm process). Prefer hide-over-destroy on blur so
WinForms/WebView2 does not throw .NET dialogs. Esc / action / blur share one
safe dismiss path. Quit still ends the process after the webview loop returns.
"""

from __future__ import annotations

import atexit
import os
import subprocess
import sys
import threading
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
REFRESH_FLAG = "pymixer_tray_refresh.flag"

# Process-local dismiss / visibility state
_window = None
_closing = False  # hard quit in progress
_hidden = False
_shown_at = 0.0
_BLUR_GRACE_S = 0.45  # ignore blur right after show (tray click race)


def lock_path() -> str:
    return os.path.join(HERE, LOCK_NAME)


def show_path() -> str:
    return os.path.join(HERE, SHOW_NAME)


def quit_flag_path() -> str:
    return os.path.join(HERE, QUIT_FLAG)


def reconnect_flag_path() -> str:
    return os.path.join(HERE, RECONNECT_FLAG)


def open_settings_flag_path() -> str:
    return os.path.join(HERE, OPEN_SETTINGS_FLAG)


def refresh_flag_path() -> str:
    return os.path.join(HERE, REFRESH_FLAG)


def _touch(path: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def work_area_rect() -> Tuple[int, int, int, int]:
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
    left, top, right, bottom = work_area if work_area is not None else work_area_rect()
    x = max(left + margin, right - width - margin)
    y = max(top + margin, bottom - height - margin)
    return int(x), int(y)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
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
    pid = _read_lock_pid()
    if pid and _pid_alive(pid):
        _touch(show_path())
        return True
    return False


def launch_popup_process() -> None:
    if request_show():
        return
    python_executable = sys.executable
    if sys.platform == "win32" and "python.exe" in python_executable:
        pythonw = os.path.join(os.path.dirname(python_executable), "pythonw.exe")
        if os.path.exists(pythonw):
            python_executable = pythonw
    script = os.path.join(HERE, "tray_popup.py")
    try:
        subprocess.Popen([python_executable, script], cwd=HERE, close_fds=True)
    except Exception as exc:
        print(f"Could not launch tray popup: {exc}")


def _suppress_dotnet_crash_dialogs() -> None:
    """Best-effort: hide Windows critical-error / GPF boxes as a backstop."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        SEM_FAILCRITICALERRORS = 0x0001
        SEM_NOGPFAULTERRORBOX = 0x0002
        SEM_NOOPENFILEERRORBOX = 0x8000
        ctypes.windll.kernel32.SetErrorMode(
            SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
        )
    except Exception:
        pass


def safe_dismiss(*, hide_only: bool = True) -> Dict[str, Any]:
    """
    Single close path used by blur / Esc / action clicks.

    Default: hide the window and keep the process warm (avoids WebView2
    destroy-from-blur crashes). Pass hide_only=False only for hard quit.
    """
    global _closing, _hidden, _window
    result = {"ok": True, "action": "hide" if hide_only else "destroy", "skipped": False}

    if hide_only:
        # Debounce: blur immediately after show (tray icon click) — ignore
        if (time.time() - _shown_at) < _BLUR_GRACE_S:
            result["skipped"] = True
            result["reason"] = "blur_grace"
            return result
        if _hidden or _window is None:
            result["skipped"] = True
            result["reason"] = "already_hidden"
            return result
        try:
            _window.hide()
            _hidden = True
        except Exception as exc:
            result["ok"] = False
            result["error"] = str(exc)
        return result

    # Hard quit — destroy once, then let webview loop exit
    if _closing:
        result["skipped"] = True
        result["reason"] = "already_closing"
        return result
    _closing = True
    try:
        if _window is not None:
            try:
                _window.destroy()
            except Exception as exc:
                result["ok"] = False
                result["error"] = str(exc)
    finally:
        _window = None
    return result


def safe_show() -> None:
    global _hidden, _shown_at, _window
    if _window is None or _closing:
        return
    try:
        x, y = popup_position()
        try:
            _window.move(x, y)
        except Exception:
            pass
        _window.show()
        try:
            _window.on_top = True
        except Exception:
            pass
        _hidden = False
        _shown_at = time.time()
    except Exception as exc:
        print(f"safe_show failed: {exc}")


class PopupApi:
    def __init__(self, config_file: Optional[str] = None):
        self.config_file = config_file or config_store.config_path(HERE)
        self.live_file = config_store.live_levels_path(HERE)

    def bind_window(self, window) -> None:
        global _window
        _window = window

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
        _touch(refresh_flag_path())
        return self.get_popup_state()

    def open_settings(self) -> None:
        _touch(open_settings_flag_path())
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
        self.dismiss()

    def reconnect(self) -> Dict[str, Any]:
        _touch(reconnect_flag_path())
        self.dismiss()
        return self.get_popup_state()

    def quit_app(self) -> None:
        _touch(quit_flag_path())
        # Hard close — tray will exit; end this process after destroy
        safe_dismiss(hide_only=False)

    def dismiss(self) -> Dict[str, Any]:
        """JS blur / Esc / after-action — hide, keep warm."""
        return safe_dismiss(hide_only=True)

    # Back-compat aliases used by older JS
    def close(self) -> Dict[str, Any]:
        return self.dismiss()


def run() -> int:
    _suppress_dotnet_crash_dialogs()
    try:
        import webview
    except ImportError:
        print("pywebview is not installed; tray popup unavailable.")
        return 2

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
    global _shown_at, _hidden
    _shown_at = time.time()
    _hidden = False

    def _on_closed():
        # If the host closed us unexpectedly, just clear lock — don't panic.
        _clear_lock()

    try:
        window.events.closed += _on_closed
    except Exception:
        pass

    def _poll_show():
        last = 0.0
        while not _closing:
            time.sleep(0.2)
            try:
                if os.path.exists(show_path()):
                    mtime = os.path.getmtime(show_path())
                    if mtime > last:
                        last = mtime
                        try:
                            os.unlink(show_path())
                        except OSError:
                            pass
                        safe_show()
            except Exception:
                pass

    threading.Thread(target=_poll_show, daemon=True).start()
    webview.start(debug=False)
    _clear_lock()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
