"""
PyMixer Discord-dark settings UI (pywebview).

Falls back gracefully if pywebview is missing — open config_gui.py instead
from the tray menu.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

# Make sure we can import sibling modules when launched as a script
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import config_store
import app_catalog
import volume_read

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
    """Backward-compatible flat list: audio sessions first, then filtered running. """
    cat = app_catalog.build_app_catalog()
    values = [e["value"] for e in cat["audio"]]
    seen = {v.lower() for v in values}
    for e in cat["running"]:
        if e["value"].lower() not in seen:
            values.append(e["value"])
            seen.add(e["value"].lower())
    return values


def _port_seems_open(port: str) -> bool:
    """Best-effort: True if the COM port exists on this machine."""
    if not port:
        return False
    return port in _list_ports()


class Api:
    def __init__(self, config_file: Optional[str] = None):
        self.config_file = config_file or config_store.config_path(HERE)
        self.live_file = None  # live levels read via pycaw in this process
        self._window = None

    def bind_window(self, window) -> None:
        self._window = window

    def get_state(self) -> Dict[str, Any]:
        cfg = config_store.load_config(self.config_file)
        ports = _list_ports()
        catalog = app_catalog.build_app_catalog()
        return {
            "config": cfg,
            "ports": ports,
            "apps": _list_apps(),
            "app_catalog": catalog,
            "connected": _port_seems_open(str(cfg.get("SERIAL_PORT", ""))),
            "live": volume_read.live_levels_from_config(cfg),
        }

    def get_live_levels(self) -> Dict[str, Any]:
        """Polled by the UI (~150 ms). Reads current Windows volumes via pycaw."""
        cfg = config_store.load_config(self.config_file)
        # Prefer in-flight mappings from the UI if passed later; base on disk for now
        return volume_read.live_levels_from_config(cfg)

    def get_live_levels_for(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Same as get_live_levels but uses the caller's unsaved mappings."""
        if not isinstance(cfg, dict):
            cfg = config_store.load_config(self.config_file)
        else:
            base = config_store.load_config(self.config_file)
            base.update(cfg)
            cfg = base
        return volume_read.live_levels_from_config(cfg)

    def get_app_catalog(self) -> Dict[str, Any]:
        """Fresh audio-session / running-app lists for the dark app picker."""
        return app_catalog.build_app_catalog()

    def browse_for_app(self) -> Optional[str]:
        """Native file dialog for picking an .exe / .lnk to launch from a button."""
        try:
            import app_launch

            return app_launch.browse_for_app()
        except Exception as exc:
            print(f"browse_for_app: {exc}")
            return None


    def save_config(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(cfg, dict):
            raise ValueError("config must be an object")
        current = config_store.load_config(self.config_file)
        current.update(cfg)
        try:
            config_store.save_config(current, self.config_file)
        except config_store.ConfigSaveError as exc:
            return {"ok": False, "error": getattr(exc, "user_message", str(exc))}
        except OSError:
            return {
                "ok": False,
                "error": "Could not save settings. Close other PyMixer windows and try again.",
            }
        saved = config_store.load_config(self.config_file)
        saved["ok"] = True
        return saved

    def switch_profile(self, name: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        current = config_store.load_config(self.config_file)
        if isinstance(cfg, dict):
            current.update(cfg)
            config_store.sync_active_into_profiles(current)
        current = config_store.switch_profile(current, name)
        try:
            config_store.save_config(current, self.config_file)
        except config_store.ConfigSaveError as exc:
            return {"ok": False, "error": getattr(exc, "user_message", str(exc))}
        except OSError:
            return {
                "ok": False,
                "error": "Could not save settings. Close other PyMixer windows and try again.",
            }
        saved = config_store.load_config(self.config_file)
        saved["ok"] = True
        return saved

    def add_profile(self, name: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        current = config_store.load_config(self.config_file)
        if isinstance(cfg, dict):
            current.update(cfg)
            config_store.sync_active_into_profiles(current)
        current = config_store.add_profile(current, name, clone_active=True)
        try:
            config_store.save_config(current, self.config_file)
        except config_store.ConfigSaveError as exc:
            return {"ok": False, "error": getattr(exc, "user_message", str(exc))}
        except OSError:
            return {
                "ok": False,
                "error": "Could not save settings. Close other PyMixer windows and try again.",
            }
        saved = config_store.load_config(self.config_file)
        saved["ok"] = True
        return saved

    def rename_profile(
        self, old: str, new: str, cfg: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        current = config_store.load_config(self.config_file)
        if isinstance(cfg, dict):
            current.update(cfg)
            config_store.sync_active_into_profiles(current)
        current = config_store.rename_profile(current, old, new)
        try:
            config_store.save_config(current, self.config_file)
        except config_store.ConfigSaveError as exc:
            return {"ok": False, "error": getattr(exc, "user_message", str(exc))}
        except OSError:
            return {
                "ok": False,
                "error": "Could not save settings. Close other PyMixer windows and try again.",
            }
        saved = config_store.load_config(self.config_file)
        saved["ok"] = True
        return saved

    def delete_profile(self, name: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        current = config_store.load_config(self.config_file)
        if isinstance(cfg, dict):
            current.update(cfg)
            config_store.sync_active_into_profiles(current)
        current = config_store.delete_profile(current, name)
        try:
            config_store.save_config(current, self.config_file)
        except config_store.ConfigSaveError as exc:
            return {"ok": False, "error": getattr(exc, "user_message", str(exc))}
        except OSError:
            return {
                "ok": False,
                "error": "Could not save settings. Close other PyMixer windows and try again.",
            }
        saved = config_store.load_config(self.config_file)
        saved["ok"] = True
        return saved


def run(config_file: Optional[str] = None) -> None:
    try:
        import webview
    except ImportError:
        print("pywebview is not installed. Falling back to the classic Tk GUI.")
        print("Install with: pip install pywebview")
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
        height=700,
        min_size=(960, 620),
        background_color="#1E1F22",
    )
    api.bind_window(window)
    # Native Windows frame only — no frameless / no custom close bridge.
    webview.start(debug=False)


if __name__ == "__main__":
    run()
