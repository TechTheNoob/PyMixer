"""
Launch any Windows app from a PyMixer button mapping.

Handles:
  - plain .exe paths (including spaces)
  - .lnk Start Menu / desktop shortcuts
  - Update.exe --processStart style targets (Discord, Slack, Teams)
  - protocol URLs (steam://, spotify:, https://, …)
  - UWP / Store apps (shell:AppsFolder\\AUMID)
  - bare names via PATH, App Paths registry, and Start Menu .lnk match
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

_PROTOCOL_RE = re.compile(r"^[a-z][a-z0-9+\-.]*:", re.I)
_EXE_RE = re.compile(r"\.exe$", re.I)
_LNK_RE = re.compile(r"\.lnk$", re.I)


def _is_windows() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


def looks_like_protocol(target: str) -> bool:
    if not target:
        return False
    t = target.strip()
    if t.lower().startswith("www."):
        return True
    if _PROTOCOL_RE.match(t):
        # Exclude Windows drive letters like C:\...
        if len(t) >= 2 and t[1] == ":" and t[0].isalpha() and (len(t) == 2 or t[2] in "\\/"):
            return False
        return True
    return False


def normalize_launch_target(raw: str) -> str:
    """Strip optional launch: prefix; leave mute: alone for callers."""
    if not raw:
        return ""
    s = str(raw).strip()
    if s.lower().startswith("launch:"):
        return s[7:].strip()
    return s


def _startfile(path: str) -> None:
    os.startfile(path)  # type: ignore[attr-defined]


def _shell_execute(path: str, params: str = "") -> None:
    """ShellExecuteW — works for .lnk, protocols, shell: URIs, paths with spaces."""
    if not _is_windows():
        subprocess.Popen([path] + (params.split() if params else []), close_fds=True)
        return
    import ctypes
    from ctypes import wintypes

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    sei = SHELLEXECUTEINFO()
    sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFO)
    sei.fMask = SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb = "open"
    sei.lpFile = path
    sei.lpParameters = params or None
    sei.nShow = 1  # SW_SHOWNORMAL
    ok = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei))
    if not ok:
        # Fallback
        if params:
            subprocess.Popen([path] + _split_args(params), close_fds=True)
        else:
            _startfile(path)


def _split_args(s: str) -> List[str]:
    try:
        import shlex
        return shlex.split(s, posix=False)
    except Exception:
        return s.split()


def _app_paths_lookup(name: str) -> Optional[str]:
    if not _is_windows():
        return None
    try:
        import winreg
    except ImportError:
        return None
    key_name = name if _EXE_RE.search(name) else name + ".exe"
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\\" + key_name) as k:
                val, _ = winreg.QueryValueEx(k, None)
                if val and os.path.exists(val):
                    return val
        except OSError:
            continue
    return None


def _read_shortcut(lnk_path: str) -> Tuple[str, str, str]:
    """Return (target, arguments, working_dir) for a .lnk."""
    if not _is_windows():
        return lnk_path, "", ""
    try:
        import win32com.client  # type: ignore

        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortCut(lnk_path)
        return (str(sc.Targetpath or ""), str(sc.Arguments or ""), str(sc.WorkingDirectory or ""))
    except Exception:
        return lnk_path, "", ""


def _start_menu_roots() -> List[str]:
    roots = []
    appdata = os.environ.get("APPDATA")
    programdata = os.environ.get("PROGRAMDATA")
    if appdata:
        roots.append(os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs"))
    if programdata:
        roots.append(os.path.join(programdata, "Microsoft", "Windows", "Start Menu", "Programs"))
    return [r for r in roots if os.path.isdir(r)]


def iter_start_menu_shortcuts() -> Iterable[Dict[str, str]]:
    """Yield {value, label, target, args} for Start Menu .lnk files."""
    for root in _start_menu_roots():
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                if not _LNK_RE.search(fn):
                    continue
                full = os.path.join(dirpath, fn)
                label = os.path.splitext(fn)[0]
                target, args, _cwd = _read_shortcut(full)
                # Skip uninstallers / help noise
                low = label.lower()
                if any(x in low for x in ("uninstall", "help", "readme", "release notes")):
                    continue
                if target and "uninstall" in target.lower():
                    continue
                yield {
                    "value": full,  # launch via the .lnk itself (most reliable)
                    "label": label,
                    "target": target,
                    "args": args,
                }


def list_installed_apps(limit: int = 400) -> List[Dict[str, str]]:
    """Start Menu apps for the settings picker (value = .lnk path)."""
    seen = set()
    out: List[Dict[str, str]] = []
    try:
        for entry in iter_start_menu_shortcuts():
            key = entry["label"].lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({"value": entry["value"], "label": entry["label"]})
            if len(out) >= limit:
                break
    except Exception:
        pass
    out.sort(key=lambda e: e["label"].lower())
    return out


def find_start_menu_lnk_for_name(name: str) -> Optional[str]:
    """Best-effort: match Discord.exe / Discord to a Start Menu shortcut."""
    base = name
    if _EXE_RE.search(base):
        base = base[:-4]
    base_l = base.lower().replace(" ", "")
    best = None
    for entry in iter_start_menu_shortcuts():
        lab = entry["label"].lower().replace(" ", "")
        tgt = os.path.basename(entry.get("target") or "").lower()
        if lab == base_l or tgt == (base.lower() + ".exe") or lab.startswith(base_l):
            return entry["value"]
        if base_l in lab and best is None:
            best = entry["value"]
    return best


def resolve_target(raw: str) -> Tuple[str, str]:
    """
    Resolve a mapping string to (path_or_uri, params).
    params used when launching an .exe with arguments (Update.exe --processStart …).
    """
    target = normalize_launch_target(raw)
    if not target:
        return "", ""

    # Protocol / shell: URI
    if looks_like_protocol(target) or target.lower().startswith("shell:"):
        if target.lower().startswith("www."):
            return "https://" + target, ""
        return target, ""

    # Expand env vars
    target = os.path.expandvars(os.path.expanduser(target))

    # Quoted path + args: "C:\...\Update.exe" --processStart Discord.exe
    if target.startswith('"'):
        try:
            import shlex
            parts = shlex.split(target, posix=False)
            if parts:
                exe = parts[0].strip().strip('"')
                rest = parts[1:]
                try:
                    params = subprocess.list2cmdline(rest) if rest else ""
                except Exception:
                    params = " ".join(rest)
                return exe, params
        except Exception:
            # Manual fallback: "path with spaces" args...
            end = target.find('"', 1)
            if end > 1:
                exe = target[1:end]
                params = target[end + 1 :].strip()
                return exe, params

    # Existing file (.exe / .lnk / anything startable)
    if os.path.exists(target):
        if _LNK_RE.search(target):
            return target, ""
        return target, ""

    # Bare .exe / name → App Paths, PATH, Start Menu
    which = shutil.which(target) or shutil.which(target if _EXE_RE.search(target) else target + ".exe")
    if which:
        return which, ""
    ap = _app_paths_lookup(target)
    if ap:
        return ap, ""
    lnk = find_start_menu_lnk_for_name(target)
    if lnk:
        return lnk, ""

    # Common Update.exe --processStart pattern when only the app exe is mapped
    # and a Start Menu shortcut wasn't found: try well-known LocalAppData paths
    if _EXE_RE.search(target) or not os.path.splitext(target)[1]:
        exe_name = target if _EXE_RE.search(target) else target + ".exe"
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = []
        if local:
            # Discord / Slack style
            for folder, proc in (
                ("Discord", "Discord.exe"),
                ("slack", "slack.exe"),
                ("Microsoft\\Teams", "Teams.exe"),
            ):
                if exe_name.lower() == proc.lower():
                    upd = os.path.join(local, folder, "Update.exe")
                    if os.path.exists(upd):
                        return upd, f"--processStart {proc}"
        # fall through — still try ShellExecute on the bare name
        return exe_name, ""

    return target, ""


def launch_app(raw: str) -> bool:
    """
    Launch whatever `raw` names. Returns True if the OS accepted the request.
    Never raises to callers — prints and returns False on failure.
    """
    try:
        path, params = resolve_target(raw)
        if not path:
            print(f"launch_app: empty target from {raw!r}")
            return False
        if not _is_windows():
            if looks_like_protocol(path) or path.lower().startswith("shell:"):
                import webbrowser
                webbrowser.open(path)
                return True
            cmd = [path] + (_split_args(params) if params else [])
            subprocess.Popen(cmd, close_fds=True)
            print(f"Launched (posix): {cmd}")
            return True

        if params:
            _shell_execute(path, params)
        elif looks_like_protocol(path) or path.lower().startswith("shell:"):
            _shell_execute(path)
        elif _LNK_RE.search(path) or os.path.exists(path):
            try:
                _startfile(path)
            except OSError:
                _shell_execute(path)
        else:
            # Bare name last resort
            _shell_execute(path, params)
        print(f"Launched: {path} {params}".rstrip())
        return True
    except Exception as exc:
        print(f"Could not launch {raw!r}: {exc}")
        return False


def browse_for_app() -> Optional[str]:
    """Native file dialog; returns selected path or None. For settings UI."""
    if not _is_windows():
        return None
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Choose an app to launch",
            filetypes=[
                ("Apps & shortcuts", "*.exe *.lnk"),
                ("Executable", "*.exe"),
                ("Shortcut", "*.lnk"),
                ("All files", "*.*"),
            ],
        )
        root.destroy()
        return path or None
    except Exception as exc:
        print(f"browse_for_app failed: {exc}")
        return None
