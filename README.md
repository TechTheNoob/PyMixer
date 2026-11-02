# PyMixer (Discord-dark reskin)

Hardware volume mixer for an ESP32-S3 box + a Windows tray app.

**Original project by [Strafer89](https://github.com/Strafer89)** — this is a fork that adds a Discord-dark settings UI (pywebview), saved **profiles**, and a few quality-of-life hooks. Firmware and the core serial → `pycaw` volume path are unchanged.

![Settings UI](docs/settings-ui.png)

## What's new in this fork

- **Discord-dark settings window** with Rubik + Inter, thin vertical faders, round knobs, blurple Bloom glow, no borders
- **Profiles rail** (add / rename / delete / switch) — Gaming, Work, Music, or whatever you name them
- Tray **Profiles** submenu + hardware button actions `next_profile` and `profile:<Name>`
- Classic Tk settings UI is still there as a fallback if `pywebview` isn't installed
- `config.py` stays backward compatible; first launch migrates your existing mappings into a **Default** profile

## Install (Windows)

```bat
cd PyMixer
python -m pip install -r ..\requirements.txt
pythonw PyMixer.pyw
```

Or double-click `PyMixer.pyw` after the deps are installed.

### Dependencies

See `requirements.txt`: `pyserial`, `pycaw`, `comtypes`, `pystray`, `Pillow`, `pygetwindow`, `psutil`, `pywin32`, `pywebview`.

## How profiles work

Each profile stores its own knob mappings, reverse flags, and sensitivity. Serial port / baud / knob+button counts are shared.

- Switch from the **left rail** in Settings, the tray **Profiles** menu, or a hardware button set to **Next Profile**
- Map a button to `profile:Gaming` (etc.) to jump straight to a named profile
- Edits you make are written into the active profile when you hit **Save** (or when you switch profiles)

## Editing the look

The settings chrome is plain HTML/CSS/JS under `PyMixer/ui/`:

| File | What it does |
|------|----------------|
| `ui/index.html` | Layout |
| `ui/style.css` | Colors, faders, rail — tweak this for a reskin |
| `ui/app.js` | Wiring to the Python bridge |
| `ui/fonts/` | Bundled Rubik + Inter (SIL OFL) |

No need to touch `PyMixer.pyw` or the ESP32 sketch to change colors.

## Hardware

See `ESP32/Volume_Mixer.ino`. The box streams `knob|knob|…|button|button|…` over serial at 115200 baud. Default mapping expects **5 knobs + 10 buttons**.

## License

GPL-3.0 (same as upstream). Fonts under `PyMixer/ui/fonts/` are SIL OFL — see `OFL.txt` there.

## Credits

- **Strafer89** — original PyMixer hardware + Windows app ([github.com/Strafer89/PyMixer](https://github.com/Strafer89/PyMixer))
- Reskin + profiles — TechTheNoob fork
