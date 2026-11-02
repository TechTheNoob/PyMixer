"""
PyMixer Discord-dark settings UI (pywebview).

Falls back gracefully if pywebview is missing — open config_gui.py instead
from the tray menu.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from typing import Any, Dict, List, Optional

# Make sure we can import sibling modules when launched as a script
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import config_store

try:
    import serial.tools.list_ports
except ImportError:  # pragma: no cover
    serial = None  # type: ignore

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore


def _list_ports() -> List[str]:
    if serial is None:
        return []
    try:
        return sorted({p.device for p in serial.tools.list_ports.comports()})
    except Exception:  # noqa: BLE001
        return []


def _list_apps() -> List[str]:
    if psutil is None:
        return []
    names = set()
    try:
        for proc in psutil.process_iter(["name"]):
            name = proc.info.get("name") or ""
            if name.lower().endswith(".exe"):
                names.add(name)
    except Exception:  # noqa: BLE001
        pass
    return sorted(names, key=str.lower)


def _port_seems_open(port: str) -> bool:
    """Best-effort: True if the COM port exists on this machine."""
    if not port:
        return False
    return port in _list_ports()


class Api:
    def __init__(self, config_file: Optional[str] = None):
        self.config_file = config_file or config_store.config_path(HERE)
        self._window = None

    def bind_window(self, window) -> None:
        self._window = window

    def get_state(self) -> Dict[str, Any]:
        cfg = config_store.load_config(self.config_file)
        ports = _list_ports()
        return {
            "config": cfg,
            "ports": ports,
            "apps": _list_apps(),
            "connected": _port_seems_open(str(cfg.get("SERIAL_PORT", ""))),
        }

    def save_config(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(cfg, dict):
            raise ValueError("config must be an object")
        # Merge onto disk config so we don't drop unknown keys carelessly
        current = config_store.load_config(self.config_file)
        current.update(cfg)
        config_store.save_config(current, self.config_file)
        return config_store.load_config(self.config_file)

    def switch_profile(self, name: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        current = config_store.load_config(self.config_file)
        if isinstance(cfg, dict):
            current.update(cfg)
            config_store.sync_active_into_profiles(current)
        current = config_store.switch_profile(current, name)
        config_store.save_config(current, self.config_file)
        return config_store.load_config(self.config_file)

    def add_profile(self, name: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        current = config_store.load_config(self.config_file)
        if isinstance(cfg, dict):
            current.update(cfg)
            config_store.sync_active_into_profiles(current)
        current = config_store.add_profile(current, name, clone_active=True)
        config_store.save_config(current, self.config_file)
        return config_store.load_config(self.config_file)

    def rename_profile(
        self, old: str, new: str, cfg: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        current = config_store.load_config(self.config_file)
        if isinstance(cfg, dict):
            current.update(cfg)
            config_store.sync_active_into_profiles(current)
        current = config_store.rename_profile(current, old, new)
        config_store.save_config(current, self.config_file)
        return config_store.load_config(self.config_file)

    def delete_profile(self, name: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        current = config_store.load_config(self.config_file)
        if isinstance(cfg, dict):
            current.update(cfg)
            config_store.sync_active_into_profiles(current)
        current = config_store.delete_profile(current, name)
        config_store.save_config(current, self.config_file)
        return config_store.load_config(self.config_file)

    def close_window(self) -> None:
        if self._window is not None:
            self._window.destroy()


def run(config_file: Optional[str] = None) -> None:
    try:
        import webview
    except ImportError:
        print("pywebview is not installed. Falling back to the classic Tk GUI.")
        print("Install with: pip install pywebview")
        # Launch classic GUI
        import subprocess

        gui = os.path.join(HERE, "config_gui.py")
        subprocess.Popen([sys.executable, gui])
        return

    api = Api(config_file=config_file)
    index = os.path.join(HERE, "ui", "index.html")
    window = webview.create_window(
        "PyMixer Configuration",
        index,
        js_api=api,
        width=1100,
        height=680,
        min_size=(960, 600),
        background_color="#1E1F22",
    )
    api.bind_window(window)
    webview.start(debug=False)


if __name__ == "__main__":
    run()
