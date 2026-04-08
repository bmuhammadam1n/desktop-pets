# 🐾 Desktop Pets

Animated pixel-art companions that live on your Linux desktop. They walk, jump, idle, fall, and land on top of your open windows — and you can pick them up and throw them.

![Desktop Pets in action]

---

## Features

- **Physics engine** — real gravity, momentum, wall bouncing, and surface collision
- **Window-aware** — pets walk on top of your open application windows and jump between them
- **Drag & throw** — pick up any pet with the mouse, fling it, and watch it tumble
- **6 characters** — Kitten, Puppy, Mouse, Squirrel, Tux, Santa 
- **Autostart** — optionally launches automatically when you log in
- **Persistent state** — pets remember their position between sessions

---

## Requirements

| Dependency | Purpose | Install |
|---|---|---|
| Python 3.8+ | Runtime | Usually pre-installed |
| PyGObject (python3-gi) | GTK bindings | `sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0` |
| wmctrl | Window collision detection | `sudo apt install wmctrl` |
| AppIndicator3 *(optional)* | System tray icon | `sudo apt install gir1.2-ayatanaappindicator3-0.1` |

> Without `wmctrl`, pets still run but won't land on top of windows — they only use the screen floor.  
> Without AppIndicator3, a fallback StatusIcon tray is used automatically.

---

## Installation

```bash
# 1. Extract the zip
unzip desktop-pets.zip


# 2. Run the installer
bash install.sh
```

The installer will:
- Check and install missing dependencies
- Copy files to `~/.local/share/desktop-pets/`
- Create the `desktop-pets` command at `~/.local/bin/desktop-pets`
- Add `~/.local/bin` to your `$PATH` in `~/.bashrc`, `~/.zshrc`, and `~/.profile`
- Set up autostart so pets launch on login

---

## Running

After installing, run from **any terminal, any directory**:

```bash
desktop-pets
```

> If you get `command not found` right after installing, either open a new terminal or run `source ~/.bashrc` once.

To run without installing:

```bash
cd gnomelets-py
bash run.sh
```

---

## Settings

Right-click the tray icon → **⚙ Settings** to open the settings dialog.

| Setting | Default | Range | Description |
|---|---|---|---|
| Character | All | Any combo | Which pet types to spawn |
| Count | 3 | 1 – 15 | Number of pets on screen |
| Size | 80 px | 32 – 200 px | Display height of each pet |
| Jump Power | 14 | 4 – 30 | How high pets can jump |
| Allow pick-up | On | On / Off | Enable drag-and-throw interaction |

Settings are saved to `~/.config/desktop-pets/config.json` and applied immediately on clicking **Apply & Respawn**.

---

## Tray Icon Menu

| Menu item | Action |
|---|---|
| Hide Pets / Show Pets | Toggle visibility of all pets |
| ⚙ Settings… | Open the settings dialog |
| Quit | Exit and save pet positions |

---

## Adding Custom Characters

Each character is a folder of 8 PNG frames inside `~/.local/share/desktop-pets/characters/`:

```
characters/
└── MyPet/
    ├── 0.png   ← walk frame 1
    ├── 1.png   ← walk frame 2
    ├── 2.png   ← walk frame 3
    ├── 3.png   ← walk frame 4
    ├── 4.png   ← idle
    ├── 5.png   ← jump / fall
    ├── 6.png   ← grabbed (optional, falls back to frame 1)
    └── 7.png   ← grabbed (optional, falls back to frame 3)
```

Frames can be any size — they are scaled automatically to the configured pet height. Only frame `0` is required; missing frames fall back gracefully.

After adding a folder, open Settings and select your new character.

---

## File Locations

| Path | Purpose |
|---|---|
| `~/.local/share/desktop-pets/` | Installed program files |
| `~/.local/bin/desktop-pets` | The runnable command |
| `~/.config/desktop-pets/config.json` | Settings |
| `~/.cache/desktop-pets-state.json` | Saved pet positions |
| `~/.config/autostart/desktop-pets.desktop` | Login autostart entry |

---

## Uninstalling

```bash
# Remove program files and command
rm -rf ~/.local/share/desktop-pets
rm -f  ~/.local/bin/desktop-pets

# Remove autostart
rm -f ~/.config/autostart/desktop-pets.desktop

# Remove saved config and state (optional)
rm -rf ~/.config/desktop-pets
rm -f  ~/.cache/desktop-pets-state.json
```

---

## Troubleshooting

**Pets don't fall / get stuck floating**  
Make sure `wmctrl` is installed: `sudo apt install wmctrl`. The window tracker needs it to detect open windows.

**No tray icon appears**  
Install AppIndicator3: `sudo apt install gir1.2-ayatanaappindicator3-0.1`. If your desktop doesn't support it, a fallback icon will appear instead — or the app runs silently in the background (right-click the desktop bar area).

**`command not found` after installing**  
Run `source ~/.bashrc` or open a new terminal. The installer adds `~/.local/bin` to your PATH but the current session needs to reload.

**Pets appear inside windows instead of on top**  
This is a compositor/display scaling issue. Try toggling compositing in your desktop settings, or adjust the Size setting downward.

---

## Built With

- Python 3 + GTK 3 (PyGObject)
- Cairo (transparent window rendering)
- wmctrl (X11 window geometry)
