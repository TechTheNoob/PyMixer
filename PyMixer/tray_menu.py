"""
Dynamic native tray menu helpers for PyMixer.

pystray re-evaluates Menu(callable) / MenuItem(text=callable, checked=callable)
when the menu is opened or when Icon.update_menu() rebuilds the HMENU on Windows.
Always read fresh state from config_store at evaluation time.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import config_store

MenuFingerprint = Tuple[Tuple[str, ...], str, str]


def menu_fingerprint(cfg: Dict[str, Any]) -> MenuFingerprint:
    names = tuple(config_store.list_profile_names(cfg))
    active = str(cfg.get("ACTIVE_PROFILE") or "Default")
    port = str(cfg.get("SERIAL_PORT") or "")
    return (names, active, port)


def header_label(cfg: Optional[Dict[str, Any]] = None, path: Optional[str] = None) -> str:
    if cfg is None:
        cfg = config_store.load_config(path)
    active = cfg.get("ACTIVE_PROFILE") or "Default"
    return f"PyMixer · {active}"


def status_label(
    cfg: Optional[Dict[str, Any]] = None,
    *,
    connected: bool = False,
    path: Optional[str] = None,
) -> str:
    if cfg is None:
        cfg = config_store.load_config(path)
    port = cfg.get("SERIAL_PORT") or "?"
    return f"{'●' if connected else '○'}  {port}"


def evaluated_profile_items(
    path: Optional[str] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Snapshot of what the Profiles submenu should show right now.
    Each item: {name, checked}.
    """
    if cfg is None:
        cfg = config_store.load_config(path)
    active = cfg.get("ACTIVE_PROFILE") or "Default"
    names = config_store.list_profile_names(cfg) or ["Default"]
    return [{"name": n, "checked": n == active} for n in names]


def profiles_changed(before: MenuFingerprint, after: MenuFingerprint) -> bool:
    return before != after


def build_pystray_menu(
    *,
    config_path: str,
    open_popup: Callable,
    open_settings: Callable,
    reload_config: Callable,
    reconnect: Callable,
    quit_app: Callable,
    make_switcher: Callable[[str], Callable],
    is_connected: Callable[[], bool],
):
    """
    Build a Menu whose visible strings and profile list are callables /
    generators, so each open / update_menu() sees current disk state.
    """
    from pystray import Menu, MenuItem

    def _cfg():
        return config_store.load_config(config_path)

    def _header_text(_item=None):
        return header_label(path=config_path)

    def _status_text(_item=None):
        return status_label(path=config_path, connected=bool(is_connected()))

    def _profiles_generator():
        snap = evaluated_profile_items(path=config_path)
        if not snap:
            snap = [{"name": "Default", "checked": True}]
        for entry in snap:
            name = entry["name"]
            yield MenuItem(
                name,
                make_switcher(name),
                checked=lambda item, n=name: (
                    config_store.load_config(config_path).get("ACTIVE_PROFILE") == n
                ),
                radio=True,
            )

    return Menu(
        MenuItem("Open PyMixer", open_popup, default=True, visible=False),
        MenuItem(_header_text, None, enabled=False),
        MenuItem(_status_text, None, enabled=False),
        Menu.SEPARATOR,
        MenuItem("⚙  Settings", open_settings),
        MenuItem("☰  Profiles", Menu(_profiles_generator)),
        Menu.SEPARATOR,
        MenuItem("↻  Reload config", reload_config),
        MenuItem("↻  Reconnect", reconnect),
        Menu.SEPARATOR,
        MenuItem("✕  Quit", quit_app),
    )
