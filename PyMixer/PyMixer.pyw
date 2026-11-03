import serial
import serial.tools.list_ports
import time
import sys
import threading
import pythoncom
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume, IAudioEndpointVolume
from comtypes import CLSCTX_ALL
from ctypes import cast, POINTER
import ctypes  # Added for locking the PC
import webbrowser # Added for opening a webpage
from pystray import Icon, Menu, MenuItem
from PIL import Image
import os
import ast
import subprocess
import pygetwindow as gw
import psutil
import win32process
import config_store
import virtual_board
import tray_popup
import tray_menu
import app_launch

# --- GLOBAL VARIABLES ---
ser = None
running = True
config = {}
_APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
config_file_path = os.path.join(_APP_DIR, 'config.py')
# Live faders: settings/popup read Windows volumes directly via pycaw (volume_read).
_tray_icon = None
_menu_fingerprint = None

# --- CONFIGURATION FILE HANDLING ---

def load_config():
    """
    Loads the configuration from config.py into a dictionary, providing defaults
    if the file is not found or fails to parse. Applies the active profile's
    mappings onto the top-level keys the serial reader uses.
    """
    global config
    config = config_store.load_config(config_file_path)

# --- AUDIO CONTROL FUNCTIONS ---

def _normalize_process_name(name):
    """Case-fold and ensure a trailing .exe so config / pycaw names match."""
    if not name:
        return ""
    n = str(name).strip().lower()
    if n in ("explorer.exe", "master", "system", "master volume"):
        return "explorer.exe"
    if n in ("focused_app", "focused", "current"):
        return "focused_app"
    if not n.endswith(".exe") and "." not in n and n not in ("focused_app",):
        n = n + ".exe"
    return n


def get_audio_session(process_name):
    """
    Finds the audio session for a given process name.

    Matching is case-insensitive and tolerates a missing/extra .exe suffix so
    config values like Discord.exe still hit a session reported as discord.exe.
    """
    want = _normalize_process_name(process_name)
    if not want or want in ("focused_app", "explorer.exe"):
        return None
    sessions = AudioUtilities.GetAllSessions()
    for session in sessions:
        try:
            proc = session.Process
            if not proc:
                continue
            have = _normalize_process_name(proc.name())
            if have == want:
                return session
        except Exception:
            continue
    return None

def set_app_volume(session, volume_level):
    """
    Sets the volume for a specific application.
    """
    if session:
        volume = session._ctl.QueryInterface(ISimpleAudioVolume)
        volume.SetMasterVolume(volume_level, None)

def toggle_app_mute(session):
    """
    Toggles the mute state of an application.
    """
    if session:
        volume = session._ctl.QueryInterface(ISimpleAudioVolume)
        current_mute = volume.GetMute()
        volume.SetMute(not current_mute, None)
        print(f"Mute for {session.Process.name()} is now {'ON' if not current_mute else 'OFF'}")

def _endpoint_volume(device):
    """
    Resolve IAudioEndpointVolume for a pycaw AudioDevice / IMMDevice.

    Newer pycaw (2024+) wraps devices as AudioDevice with an EndpointVolume
    property and no Activate(). Older pycaw returned IMMDevice with Activate().
    Support both so Master Volume / mute keep working across versions.
    """
    if device is None:
        raise RuntimeError("audio device is None")
    ep = getattr(device, "EndpointVolume", None)
    if ep is not None:
        return ep
    activate = getattr(device, "Activate", None)
    if callable(activate):
        interface = activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    # Last resort: underlying IMMDevice on AudioDevice wrappers
    inner = getattr(device, "_dev", None) or getattr(device, "device", None)
    if inner is not None and callable(getattr(inner, "Activate", None)):
        interface = inner.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    raise AttributeError(
        f"{type(device).__name__} has neither EndpointVolume nor Activate "
        "(incompatible pycaw / comtypes)"
    )


def set_master_volume(volume_level):
    """
    Sets the master system volume.
    """
    volume_interface = _endpoint_volume(AudioUtilities.GetSpeakers())
    volume_interface.SetMasterVolumeLevelScalar(volume_level, None)

def toggle_master_mute():
    """
    Toggles the mute state of the master audio device.
    """
    volume_interface = _endpoint_volume(AudioUtilities.GetSpeakers())
    current_mute = volume_interface.GetMute()
    volume_interface.SetMute(not current_mute, None)
    print(f"Master volume mute is now {'ON' if not current_mute else 'OFF'}")

def get_focused_app_process_name():
    """
    Gets the process name of the currently focused application.
    Returns None if no focused window is found.
    """
    try:
        active_window = gw.getActiveWindow()
        if active_window:
            # Use win32process to get the PID from the window handle
            pid = win32process.GetWindowThreadProcessId(active_window._hWnd)[1]
            if pid:
                return psutil.Process(pid).name()
    except Exception as e:
        print(f"Could not get focused application: {e}")
        return None
    return None

# --- NEW BUTTON ACTION FUNCTIONS ---

def toggle_mic_mute():
    """
    Toggles the mute state of the default microphone.
    """
    try:
        volume_interface = _endpoint_volume(AudioUtilities.GetMicrophone())
        current_mute = volume_interface.GetMute()
        volume_interface.SetMute(not current_mute, None)
        print(f"Microphone mute is now {'ON' if not current_mute else 'OFF'}")
    except Exception as e:
        print(f"Could not toggle microphone mute: {e}")

def lock_pc():
    """
    Locks the computer using the Windows API.
    """
    try:
        ctypes.windll.user32.LockWorkStation()
        print("PC locked.")
    except Exception as e:
        print(f"Could not lock PC: {e}")

def open_webpage(url):
    """
    Opens a URL in the default web browser.
    """
    try:
        webbrowser.open(url)
        print(f"Opening webpage: {url}")
    except Exception as e:
        print(f"Could not open webpage: {e}")



def dispatch_button_action(app_command):
    """
    Run the configured action for a rising-edge board button.

    - Specials: mic/master mute, lock, profile switch
    - mute:<target> → toggle that app's session mute (legacy explicit)
    - http(s)/www → browser
    - Anything else (exe, .lnk, protocol, shell:AppsFolder, bare name) → launch
    """
    if not app_command:
        return
    cmd = str(app_command).strip()
    if cmd == 'toggle_mic_mute':
        toggle_mic_mute()
        return
    if cmd == 'toggle_master_mute':
        toggle_master_mute()
        return
    if cmd == 'lock_pc':
        lock_pc()
        return
    if cmd == 'next_profile':
        apply_profile_switch(cycle=True)
        return
    if cmd.startswith('profile:'):
        apply_profile_switch(name=cmd.split(':', 1)[1])
        return
    if cmd.lower().startswith('mute:'):
        target = cmd.split(':', 1)[1].strip()
        session = get_audio_session(target)
        if session:
            toggle_app_mute(session)
        else:
            print(f"mute target not found: {target}")
        return
    if cmd.startswith('http://') or cmd.startswith('https://') or cmd.startswith('www.'):
        url = cmd if cmd.startswith('http') else 'https://' + cmd
        open_webpage(url)
        return
    # General launch — works for .exe, .lnk, protocols, UWP shell: URIs, PATH names
    app_launch.launch_app(cmd)


def save_config_dict(cfg):
    """Persist a full config dict (used when cycling profiles from a button)."""
    config_store.save_config(cfg, config_file_path)


def apply_profile_switch(name=None, cycle=False):
    """Switch active profile and persist. Returns the new profile name."""
    global config
    cfg = config_store.load_config(config_file_path)
    if cycle:
        cfg, name = config_store.next_profile(cfg)
    else:
        cfg = config_store.switch_profile(cfg, name)
    save_config_dict(cfg)
    config = cfg
    print(f"Active profile: {cfg.get('ACTIVE_PROFILE')}")
    try:
        refresh_tray_menu()
    except Exception:
        pass
    if _tray_icon is not None:
        try:
            _tray_icon.title = f"PyMixer · {cfg.get('ACTIVE_PROFILE', 'Default')}"
        except Exception:
            pass
    return cfg.get('ACTIVE_PROFILE')


# --- SERIAL COMMUNICATION THREAD ---

def apply_knob_volume(app_name, volume_level, key=None):
    """
    Route one knob's curved volume to the mapped target.

    Targets:
      - focused_app → foreground process session (unless another knob owns it)
      - explorer.exe / master / system → endpoint master volume
      - <process>.exe → matching pycaw session (case-insensitive)
    """
    target = _normalize_process_name(app_name)
    if not target:
        return False
    if target == "focused_app":
        focused_app_name = get_focused_app_process_name()
        if not focused_app_name:
            return False
        all_mappings = config.get('APP_MAPPINGS', {}) if config else {}
        other = [
            _normalize_process_name(mapped)
            for k, mapped in all_mappings.items()
            if k.startswith('K') and k != key
        ]
        if _normalize_process_name(focused_app_name) in other:
            return False
        session = get_audio_session(focused_app_name)
        if session:
            set_app_volume(session, volume_level)
            return True
        return False
    if target == "explorer.exe":
        set_master_volume(volume_level)
        return True
    session = get_audio_session(target)
    if session:
        set_app_volume(session, volume_level)
        return True
    return False


def serial_reader_thread():
    """
    Function to run in a separate thread, continuously reading serial data.
    """
    global ser, running, config, _menu_fingerprint
    last_button_state = {}
    last_knob_value = {}
    last_config_load_time = time.time()
    # When curve/reverse changes on disk, re-apply current raw once (skip sensitivity).
    force_reapply = set()
    prev_curve = {}
    prev_reverse = {}

    pythoncom.CoInitialize()

    try:
        while running:
            # Reload config at most every 5s, and only if mtime/size changed,
            # so we are not opening config.py on a timer for no reason.
            if time.time() - last_config_load_time > 5:
                last_config_load_time = time.time()
                try:
                    st = os.stat(config_file_path)
                    sig = (st.st_mtime_ns, st.st_size)
                except OSError:
                    sig = None
                if sig is not None and sig == getattr(serial_reader_thread, '_cfg_sig', None):
                    pass  # unchanged on disk
                else:
                    before = tray_menu.menu_fingerprint(config) if config else None
                    load_config()
                    serial_reader_thread._cfg_sig = sig
                    after = tray_menu.menu_fingerprint(config)
                    if before is None or tray_menu.profiles_changed(before, after):
                        _menu_fingerprint = after
                        try:
                            refresh_tray_menu()
                        except Exception:
                            pass
                    else:
                        _menu_fingerprint = after
                    # Curve / reverse change → re-apply current board position immediately
                    new_curve = dict(config.get('SLIDER_CURVE') or {})
                    new_reverse = dict(config.get('SLIDER_REVERSE') or {})
                    if prev_curve or prev_reverse:
                        num = int(config.get('NUM_KNOBS') or 5)
                        for i in range(num):
                            key = f'K{i + 1}'
                            if (prev_curve.get(key) != new_curve.get(key)
                                    or bool(prev_reverse.get(key)) != bool(new_reverse.get(key))):
                                force_reapply.add(key)
                                # Apply now from last known raw (don't wait for next serial tick)
                                if key in last_knob_value:
                                    raw = last_knob_value[key]
                                    if new_reverse.get(key, False):
                                        scaled = 1023.0 - float(raw)
                                    else:
                                        scaled = float(raw)
                                    norm = max(0.0, min(1.0, scaled / 1023.0))
                                    curve_name = new_curve.get(key, 'linear')
                                    level = config_store.apply_curve(norm, curve_name)
                                    app_name = (config.get('APP_MAPPINGS') or {}).get(key, '')
                                    if app_name:
                                        try:
                                            apply_knob_volume(app_name, level, key=key)
                                        except Exception as e:
                                            print(f"force reapply {key}: {e}")
                                    force_reapply.discard(key)
                    prev_curve = new_curve
                    prev_reverse = new_reverse

            num_knobs = int(config.get('NUM_KNOBS') or 5)
            num_buttons = int(config.get('NUM_BUTTONS') or 10)
            vc_on = bool(config.get('VIRTUAL_CONTROLLER_ENABLED'))

            data = None
            from_real = False
            if ser and getattr(ser, 'is_open', False):
                try:
                    line = ser.readline().decode('utf-8').strip()
                except Exception:
                    line = ''
                if line:
                    try:
                        cand = [int(val) for val in line.split('|')]
                        if len(cand) == num_knobs + num_buttons:
                            data = cand
                            from_real = True
                            # FakeSerial / DEMO is not a physical board — skip pause latch
                            port_name = str(getattr(ser, "port", "") or "")
                            is_demo = (
                                port_name.upper() == "DEMO"
                                or bool(os.environ.get("PYMIXER_DEMO"))
                            )
                            if not is_demo:
                                try:
                                    virtual_board.note_real_board_line(line)
                                except Exception:
                                    pass
                    except ValueError:
                        pass

            if not from_real:
                try:
                    virtual_board.clear_real_board_if_quiet()
                except Exception:
                    pass

            if data is None and vc_on and not virtual_board.real_board_active():
                # Drive the same apply path from the virtual controller state
                data = virtual_board.frame_values(num_knobs, num_buttons)
                # Merge pulsed virtual buttons as rising edges this tick
                try:
                    pulsed = set(virtual_board.consume_button_events())
                except Exception:
                    pulsed = set()
                for key in pulsed:
                    try:
                        bi = int(key[1:]) - 1
                    except ValueError:
                        continue
                    if 0 <= bi < num_buttons:
                        data[num_knobs + bi] = 1

            if data is None:
                time.sleep(0.05 if vc_on else 0.25)
                continue

            knob_values = data[:num_knobs]
            button_values = data[num_knobs:]

            live_knobs = {}
            for i, knob_value in enumerate(knob_values):
                key = f'K{i + 1}'
                if key not in last_knob_value:
                    last_knob_value[key] = knob_value

                if config.get('SLIDER_REVERSE', {}).get(key, False):
                    scaled_value = 1023.0 - knob_value
                else:
                    scaled_value = float(knob_value)

                normalized = max(0.0, min(1.0, scaled_value / 1023.0))
                curve = config.get('SLIDER_CURVE', {}).get(key, 'linear')
                volume_level = config_store.apply_curve(normalized, curve)
                live_knobs[key] = {
                    'raw': int(knob_value),
                    'volume': round(volume_level, 4),
                    'pct': int(round(volume_level * 100)),
                }

                sensitivity = config.get('SLIDER_SENSITIVITY', {}).get(key, 1.0)
                try:
                    sens = float(sensitivity) if float(sensitivity) > 0 else 1.0
                except (TypeError, ValueError):
                    sens = 1.0
                forced = key in force_reapply
                if not forced and abs(knob_value - last_knob_value[key]) < 10 / sens:
                    continue
                if forced:
                    force_reapply.discard(key)

                app_name = config.get('APP_MAPPINGS', {}).get(key, '')
                if app_name:
                    try:
                        apply_knob_volume(app_name, volume_level, key=key)
                    except Exception as e:
                        # Never let one bad mapping (e.g. pycaw API drift) kill the
                        # serial reader — other knobs must keep working.
                        print(f"apply_knob_volume({app_name!r}, {key}): {e}")

                last_knob_value[key] = knob_value

            
            for i, button_value in enumerate(button_values):
                key = f'B{i + 1}'
                if key in config.get('APP_MAPPINGS', {}):
                    app_command = config['APP_MAPPINGS'][key]
                    
                    if key not in last_button_state:
                        last_button_state[key] = 0

                    if button_value == 1 and last_button_state[key] == 0:
                        try:
                            dispatch_button_action(app_command)
                        except Exception as e:
                            print(f"button {key} action {app_command!r} failed: {e}")
                    
                    last_button_state[key] = button_value
            
            time.sleep(0.01) # Small delay to prevent high CPU usage

    except Exception as e:
        print(f"An error occurred in the serial reader thread: {e}")
    finally:
        pythoncom.CoUninitialize()
        if ser and ser.is_open:
            ser.close()
            print("Serial port closed.")

# --- SYSTEM TRAY ICON FUNCTIONS ---

_tray_icon = None  # set in setup_and_run_icon for menu refresh / quit


def _pythonw_exe():
    exe = sys.executable
    if sys.platform == "win32" and exe.lower().endswith("python.exe"):
        candidate = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(candidate):
            return candidate
    return exe


def _popen_no_window(args, *, cwd=None):
    kwargs = {"cwd": cwd, "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        kwargs["stdin"] = subprocess.DEVNULL
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    return subprocess.Popen(args, **kwargs)


def open_config_gui(icon=None, item=None):
    """
    Open the configuration GUI in a new process.
    Prefers the Discord-dark pywebview UI; falls back to the classic Tk GUI
    if pywebview is not installed or the web script is missing.
    """
    try:
        python_executable = _pythonw_exe()
        main_script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        web_gui = os.path.join(main_script_dir, 'config_gui_web.py')
        tk_gui = os.path.join(main_script_dir, 'config_gui.py')

        use_web = False
        if os.path.exists(web_gui):
            try:
                import webview  # noqa: F401
                use_web = True
            except ImportError:
                use_web = False

        gui_script_path = web_gui if use_web else tk_gui
        if not os.path.exists(gui_script_path):
            print(f"Error: GUI script not found at {gui_script_path}")
            return

        _popen_no_window([python_executable, gui_script_path], cwd=main_script_dir)
    except Exception as e:
        print(f"Failed to open configuration GUI. An unexpected error occurred: {e}")


def request_show_virtual_controller():
    """
    Ensure the virtual controller process is running / shown when enabled in Settings.
    """
    try:
        if not (config or {}).get("VIRTUAL_CONTROLLER_ENABLED"):
            # Reload once in case flag watcher fired right after Save
            try:
                load_config()
            except Exception:
                pass
        if not (config or {}).get("VIRTUAL_CONTROLLER_ENABLED"):
            return
        main_script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        script = os.path.join(main_script_dir, "virtual_controller.py")
        if not os.path.exists(script):
            return
        virtual_board.touch_show_flag()
        _popen_no_window([_pythonw_exe(), script], cwd=main_script_dir)
    except Exception as e:
        print(f"request_show_virtual_controller: {e}")


def open_tray_popup(icon=None, item=None):
    """Left-click default: open the custom Discord-dark tray popup (non-blocking)."""
    try:
        import webview  # noqa: F401
    except ImportError:
        # No pywebview — fall back to settings / native menu only
        print("pywebview missing; tray popup unavailable. Opening Settings instead.")
        open_config_gui(icon, item)
        return
    threading.Thread(target=tray_popup.launch_popup_process, daemon=True).start()


def _make_profile_switcher(profile_name):
    def _switch(icon, item):
        try:
            apply_profile_switch(name=profile_name)
            refresh_tray_menu()
        except Exception as e:
            print(f"Could not switch profile: {e}")
    return _switch


def _profile_is_active(name):
    def _checked(item):
        return config.get('ACTIVE_PROFILE') == name
    return _checked


def reload_config_from_disk(icon=None, item=None):
    """Reload config.py into memory and refresh the tray menu."""
    try:
        load_config()
        refresh_tray_menu()
        print(f"Config reloaded. Active profile: {config.get('ACTIVE_PROFILE')}")
    except Exception as e:
        print(f"Reload failed: {e}")


def reconnect_serial(icon=None, item=None):
    """Close and reopen the serial port using the current config."""
    global ser
    try:
        load_config()
        if ser and getattr(ser, 'is_open', False):
            try:
                ser.close()
            except Exception:
                pass
        ser = serial.Serial(config['SERIAL_PORT'], config['BAUD_RATE'], timeout=1)
        print(f"Reconnected to {config['SERIAL_PORT']}")
        refresh_tray_menu()
    except Exception as e:
        print(f"Reconnect failed: {e}")
        ser = None
        refresh_tray_menu()


def build_tray_menu():
    """
    Native Win32 fallback menu (right-click).
    Uses pystray dynamic Menu(callable) / text=callable / checked=callable so
    every open and every update_menu() rebuild sees current config_store state.
    """
    return tray_menu.build_pystray_menu(
        config_path=config_file_path,
        open_popup=open_tray_popup,
        open_settings=open_config_gui,
        reload_config=reload_config_from_disk,
        reconnect=reconnect_serial,
        quit_app=exit_program,
        make_switcher=_make_profile_switcher,
        is_connected=lambda: bool(ser and getattr(ser, 'is_open', False)),
    )


def refresh_tray_menu():
    """Rebuild HMENU on Windows via update_menu after profile/config changes."""
    global _tray_icon, _menu_fingerprint, config
    try:
        # Keep in-memory config aligned with disk before evaluating callables
        config = config_store.load_config(config_file_path)
        _menu_fingerprint = tray_menu.menu_fingerprint(config)
    except Exception:
        pass
    if _tray_icon is not None:
        try:
            _tray_icon.menu = build_tray_menu()
            _tray_icon.update_menu()
            try:
                _tray_icon.title = tray_menu.header_label(config)
            except Exception:
                pass
        except Exception as e:
            print(f"Could not refresh tray menu: {e}")



def exit_program(icon=None, item=None):
    """Stop the program and close the icon."""
    global running
    print("Exiting PyMixer...")
    running = False
    try:
        tray_popup._clear_lock()
    except Exception:
        pass
    if icon is not None:
        icon.stop()
    elif _tray_icon is not None:
        _tray_icon.stop()


def _flag_watcher():
    """Watch for quit / reconnect / open-settings flags written by the popup."""
    global running
    seen = {
        'quit': 0.0,
        'reconnect': 0.0,
        'settings': 0.0,
        'refresh': 0.0,
        'controller': 0.0,
    }
    while running:
        time.sleep(0.35)
        try:
            q = tray_popup.quit_flag_path()
            if os.path.exists(q):
                m = os.path.getmtime(q)
                if m > seen['quit']:
                    seen['quit'] = m
                    try:
                        os.unlink(q)
                    except OSError:
                        pass
                    exit_program(_tray_icon, None)
                    return
            r = tray_popup.reconnect_flag_path()
            if os.path.exists(r):
                m = os.path.getmtime(r)
                if m > seen['reconnect']:
                    seen['reconnect'] = m
                    try:
                        os.unlink(r)
                    except OSError:
                        pass
                    reconnect_serial()
            s = tray_popup.open_settings_flag_path()
            if os.path.exists(s):
                m = os.path.getmtime(s)
                if m > seen['settings']:
                    seen['settings'] = m
                    try:
                        os.unlink(s)
                    except OSError:
                        pass
                    # settings already launched by popup; just refresh menu
                    refresh_tray_menu()
            rf = tray_popup.refresh_flag_path()
            if os.path.exists(rf):
                m = os.path.getmtime(rf)
                if m > seen['refresh']:
                    seen['refresh'] = m
                    try:
                        os.unlink(rf)
                    except OSError:
                        pass
                    load_config()
                    refresh_tray_menu()
            cf = tray_popup.show_controller_flag_path()
            if os.path.exists(cf):
                m = os.path.getmtime(cf)
                if m > seen['controller']:
                    seen['controller'] = m
                    try:
                        os.unlink(cf)
                    except OSError:
                        pass
                    request_show_virtual_controller()
        except Exception:
            pass


def load_tray_icon_image():
    """Load the bundled multi-size Discord-dark icon."""
    base = os.path.dirname(os.path.abspath(sys.argv[0]))
    for name in ('icon.ico', 'icon.png', 'icon.ico'):
        candidate = os.path.join(base, name)
        if os.path.exists(candidate):
            try:
                return Image.open(candidate)
            except Exception:
                continue
    # Last resort: generate a tiny solid icon
    img = Image.new('RGBA', (64, 64), (88, 101, 242, 255))
    return img


def setup_and_run_icon():
    """
    Sets up the system tray icon and runs it in detached mode.
    Left-click → custom popup; right-click → native menu fallback.
    """
    global ser, _tray_icon
    load_config()
    print("Configuration loaded from config.py.")


    try:
        ser = serial.Serial(config['SERIAL_PORT'], config['BAUD_RATE'], timeout=1)
        print(f"Connected to ESP32 on port {config['SERIAL_PORT']}")
    except serial.SerialException as e:
        print(f"Error: Could not open serial port {config['SERIAL_PORT']}. Please check the port number.")
        print(f"Details: {e}")
        ports = serial.tools.list_ports.comports()
        for port, desc, hwid in sorted(ports):
            print(f"  {port}: {desc} [{hwid}]")
        # Keep running so the user can open Settings / Reconnect / Virtual controller
        ser = None

    # Always run the reader: virtual controller uses the same apply path when quiet
    thread = threading.Thread(target=serial_reader_thread, daemon=True)
    thread.start()

    global _menu_fingerprint
    _menu_fingerprint = tray_menu.menu_fingerprint(config)
    icon_image = load_tray_icon_image()
    menu = build_tray_menu()

    icon = Icon(
        name="PyMixer",
        icon=icon_image,
        title=f"PyMixer · {config.get('ACTIVE_PROFILE', 'Default')}",
        menu=menu
    )
    _tray_icon = icon

    threading.Thread(target=_flag_watcher, daemon=True).start()

    # Patch apply_profile_switch callers to refresh menu: wrap after definition
    icon.run_detached()


if __name__ == "__main__":
    try:
        # Check for required libraries
        try:
            import pygetwindow
            import psutil
            import win32process
        except ImportError as e:
            print(f"\nError: A required library is not installed. Details: {e}")
            print("Please install missing libraries by running the following command in your terminal:")
            print("pip install pygetwindow psutil pywin32")
            print("The program will now exit.")
            time.sleep(10)
            sys.exit(1)
            
        setup_and_run_icon()
    except Exception as e:
        print(f"\nFATAL ERROR: The program failed to start. Details: {e}")
        print("This window will close in 10 seconds.")
        time.sleep(10)
        sys.exit()
