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

# --- GLOBAL VARIABLES ---
ser = None
running = True
config = {}
_APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
config_file_path = os.path.join(_APP_DIR, 'config.py')
live_levels_file_path = os.path.join(_APP_DIR, config_store.LIVE_LEVELS_FILENAME)
_last_live_write = 0.0
LIVE_WRITE_INTERVAL = 0.12  # seconds — throttle disk writes

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

def get_audio_session(process_name):
    """
    Finds the audio session for a given process name.
    """
    sessions = AudioUtilities.GetAllSessions()
    for session in sessions:
        if session.Process and session.Process.name() == process_name:
            return session
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

def set_master_volume(volume_level):
    """
    Sets the master system volume.
    """
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume_interface = cast(interface, POINTER(IAudioEndpointVolume))
    volume_interface.SetMasterVolumeLevelScalar(volume_level, None)

def toggle_master_mute():
    """
    Toggles the mute state of the master audio device.
    """
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume_interface = cast(interface, POINTER(IAudioEndpointVolume))
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
        devices = AudioUtilities.GetMicrophone()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume_interface = cast(interface, POINTER(IAudioEndpointVolume))
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
    return cfg.get('ACTIVE_PROFILE')


# --- SERIAL COMMUNICATION THREAD ---

def serial_reader_thread():
    """
    Function to run in a separate thread, continuously reading serial data.
    """
    global ser, running, config, _last_live_write
    last_button_state = {}
    last_knob_value = {}
    last_config_load_time = time.time()

    pythoncom.CoInitialize()

    try:
        while running:
            if not ser or not ser.is_open:
                time.sleep(1)
                continue

            # Reload config every 5 seconds to pick up changes from the GUI
            if time.time() - last_config_load_time > 5:
                load_config()
                last_config_load_time = time.time()

            line = ser.readline().decode('utf-8').strip()
            if not line:
                continue

            try:
                data = [int(val) for val in line.split('|')]
            except ValueError:
                continue
            
            num_knobs = config.get('NUM_KNOBS', 4)
            num_buttons = config.get('NUM_BUTTONS', 4)

            if len(data) != num_knobs + num_buttons:
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
                if abs(knob_value - last_knob_value[key]) < 10 / sens:
                    continue

                app_name = config.get('APP_MAPPINGS', {}).get(key, '')
                if app_name:
                    if app_name == "focused_app":
                        focused_app_name = get_focused_app_process_name()
                        if focused_app_name:
                            # Check if the focused app already has a dedicated knob
                            all_mappings = config.get('APP_MAPPINGS', {})
                            other_knob_mappings = [
                                mapped_app for k, mapped_app in all_mappings.items()
                                if k.startswith('K') and k != key
                            ]

                            if focused_app_name in other_knob_mappings:
                                # This app has its own knob, so the 'focused_app' knob should ignore it.
                                pass
                            else:
                                session = get_audio_session(focused_app_name)
                                if session:
                                    set_app_volume(session, volume_level)

                    elif app_name == 'explorer.exe':
                        set_master_volume(volume_level)
                    else:
                        session = get_audio_session(app_name)
                        if session:
                            set_app_volume(session, volume_level)

                last_knob_value[key] = knob_value

            # Publish live fader positions for the settings UI (throttled).
            now = time.time()
            if now - _last_live_write >= LIVE_WRITE_INTERVAL:
                config_store.write_live_levels(
                    live_knobs,
                    live_levels_file_path,
                    connected=True,
                )
                _last_live_write = now
            
            for i, button_value in enumerate(button_values):
                key = f'B{i + 1}'
                if key in config.get('APP_MAPPINGS', {}):
                    app_command = config['APP_MAPPINGS'][key]
                    
                    if key not in last_button_state:
                        last_button_state[key] = 0

                    if button_value == 1 and last_button_state[key] == 0:
                        # Check for new button actions
                        if app_command == 'toggle_mic_mute':
                            toggle_mic_mute()
                        elif app_command == 'toggle_master_mute':
                            toggle_master_mute()
                        elif app_command == 'lock_pc':
                            lock_pc()
                        elif app_command == 'next_profile':
                            apply_profile_switch(cycle=True)
                        elif isinstance(app_command, str) and app_command.startswith('profile:'):
                            apply_profile_switch(name=app_command.split(':', 1)[1])
                        elif isinstance(app_command, str) and (app_command.startswith('http') or app_command.startswith('www.')):
                            url = app_command if app_command.startswith('http') else 'https://' + app_command
                            open_webpage(url)
                        elif app_command:
                            # Default action is to toggle mute for an application
                            session = get_audio_session(app_command)
                            if session:
                                toggle_app_mute(session)
                    
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

def open_config_gui(icon, item):
    """
    Open the configuration GUI in a new process.
    Prefers the Discord-dark pywebview UI; falls back to the classic Tk GUI
    if pywebview is not installed or the web script is missing.
    """
    try:
        python_executable = sys.executable
        if sys.platform == "win32" and "python.exe" in python_executable:
            pythonw_path = os.path.join(os.path.dirname(python_executable), "pythonw.exe")
            if os.path.exists(pythonw_path):
                python_executable = pythonw_path

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
        print("Attempting to open configuration GUI...")
        print(f"Python executable path: {python_executable}")
        print(f"GUI script path: {gui_script_path}")

        if not os.path.exists(gui_script_path):
            print(f"Error: GUI script not found at {gui_script_path}")
            return

        subprocess.Popen([python_executable, gui_script_path])
        print("Configuration GUI process started successfully.")
    except Exception as e:
        print(f"Failed to open configuration GUI. An unexpected error occurred: {e}")


def _make_profile_switcher(profile_name):
    def _switch(icon, item):
        try:
            apply_profile_switch(name=profile_name)
        except Exception as e:
            print(f"Could not switch profile: {e}")
    return _switch


def build_tray_menu():
    """Build the tray menu, including a Profiles submenu."""
    load_config()
    profile_items = []
    for name in config_store.list_profile_names(config):
        # pystray checks radio items against a callable; keep it simple with plain items
        profile_items.append(MenuItem(name, _make_profile_switcher(name)))
    if not profile_items:
        profile_items.append(MenuItem('Default', _make_profile_switcher('Default')))
    profiles_menu = Menu(*profile_items)
    return Menu(
        MenuItem('PyMixer is Running', None, enabled=False),
        MenuItem(f"Profile: {config.get('ACTIVE_PROFILE', 'Default')}", None, enabled=False),
        MenuItem('Profiles', profiles_menu),
        MenuItem('Settings', open_config_gui),
        MenuItem('Exit', exit_program),
    )

def exit_program(icon, item):
    """
    Function to stop the program and close the icon.
    """
    global running
    print("Exiting PyMixer...")
    running = False
    icon.stop()

def setup_and_run_icon():
    """
    Sets up the system tray icon and runs it in detached mode.
    """
    global ser
    load_config()
    print("Configuration loaded from config.py.")

    try:
        ser = serial.Serial(config['SERIAL_PORT'], config['BAUD_RATE'], timeout=1)
        print(f"Connected to ESP32 on port {config['SERIAL_PORT']}")
        
        thread = threading.Thread(target=serial_reader_thread)
        thread.daemon = True
        thread.start()
    except serial.SerialException as e:
        print(f"Error: Could not open serial port {config['SERIAL_PORT']}. Please check the port number.")
        print(f"Details: {e}")
        ports = serial.tools.list_ports.comports()
        for port, desc, hwid in sorted(ports):
            print(f"  {port}: {desc} [{hwid}]")
        raise

    icon_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "icon.ico")
    if not os.path.exists(icon_path):
        icon_path = "icon.ico"
    icon_image = Image.open(icon_path)
    menu = build_tray_menu()

    icon = Icon(
        name="PyMixer",
        icon=icon_image,
        title="PyMixer - ESP32 Audio Mixer",
        menu=menu
    )
    
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
