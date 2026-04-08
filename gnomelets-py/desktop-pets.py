#!/usr/bin/env python3
"""
Desktop Pets - animated desktop companions.
Physics, animation, and AI for desktop pet companions.

Usage:
    python3 desktop-pets.py

Characters live in ./characters/<Name>/0.png .. 7.png
Frame layout (matches original exactly):
  0,1,2,3 = walk frames
  4        = idle
  5        = jump / fall
  6,7      = grabbed/drag (falls back to 1,3 if missing)
"""

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Gio

import os, sys, json, math, random, time, subprocess, cairo

# ── Constants (ported from utils.js) ─────────────────────────────────────────
UPDATE_INTERVAL_MS = 50      # ~20 FPS
GRAVITY            = 2       # px/frame²
WALK_SPEED         = 3       # px/frame
MAX_VELOCITY       = 50
HISTORY_LIMIT_MS   = 200
MOMENTUM_SCALE     = 0.25

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
CHARS_DIR     = os.path.join(BASE_DIR, "characters")
CONFIG_FILE   = os.path.expanduser("~/.config/desktop-pets/config.json")
STATE_FILE    = os.path.expanduser("~/.cache/desktop-pets-state.json")

# ── State enum ────────────────────────────────────────────────────────────────
class State:
    FALLING  = "FALLING"
    WALKING  = "WALKING"
    IDLE     = "IDLE"
    JUMPING  = "JUMPING"
    DRAGGING = "DRAGGING"

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "pet_type":  [],        # [] = all available
    "pet_count": 3,
    "pet_scale": 80,        # display height in px
    "jump_power":     14,
    "is_enabled":     True,
    "allow_interaction": True,
}

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE) as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg

def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return None

def save_state(pets):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump([g.serialize() for g in pets], f)
    except Exception:
        pass

# ── Sprite loader ─────────────────────────────────────────────────────────────
def list_characters():
    chars = []
    if os.path.isdir(CHARS_DIR):
        for name in sorted(os.listdir(CHARS_DIR)):
            p = os.path.join(CHARS_DIR, name)
            if os.path.isdir(p) and os.path.exists(os.path.join(p, "0.png")):
                chars.append(name)
    return chars

def load_character_frames(name, display_h):
    """Load frames 0..7 for a character, scaled to display_h height."""
    char_dir = os.path.join(CHARS_DIR, name)
    frames = []
    frame_w = display_h
    frame_h = display_h

    for i in range(8):
        path = os.path.join(char_dir, f"{i}.png")
        if os.path.exists(path):
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file(path)
                orig_w, orig_h = pb.get_width(), pb.get_height()
                scale = display_h / orig_h
                new_w = max(1, int(orig_w * scale))
                if orig_w != new_w or orig_h != display_h:
                    pb = pb.scale_simple(new_w, display_h, GdkPixbuf.InterpType.BILINEAR)
                if i == 0:
                    frame_w = pb.get_width()
                    frame_h = pb.get_height()
                frames.append(pb)
            except Exception as e:
                print(f"  warn: could not load {path}: {e}")
                frames.append(None)
        else:
            frames.append(None)

    return frames, frame_w, frame_h

# ── Window tracker ─────────────────────────────────────────────────────────────
class WindowTracker:
    def __init__(self):
        self._windows  = []
        self._last     = 0
        # XIDs of our own PetWindows, set by DesktopPetsApp each tick so we
        # never collide with our own transparent popup windows.
        self._own_xids = set()

    def set_own_xids(self, xids):
        self._own_xids = set(xids)

    def update(self):
        if time.time() - self._last < 0.5:
            return
        self._last = time.time()
        self._windows = []
        try:
            # wmctrl -lG columns: id  desktop  x  y  w  h  host  title
            out = subprocess.check_output(
                ["wmctrl", "-lG"], text=True, timeout=2,
                stderr=subprocess.DEVNULL
            )
            for line in out.strip().splitlines():
                parts = line.split()
                if len(parts) >= 7:
                    try:
                        xid = int(parts[0], 16)
                    except ValueError:
                        xid = 0
                    # Skip our own transparent pet popup windows
                    if xid in self._own_xids:
                        continue
                    x, y, w, h = int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])
                    # Skip minimised / off-screen / tiny windows
                    if w < 100 or h < 50:
                        continue
                    if x < -500 or y < -10 or y > 5000:
                        continue
                    self._windows.append((x, y, w, h))
        except Exception:
            pass

    def get_windows(self):
        return list(self._windows)

# ── Pet (faithful Desktop Pets) ────────────────────────────────────────
class DesktopPet:
    def __init__(self, type_name, frames, frame_w, frame_h, cfg, screen_w, screen_h):
        self.type_name  = type_name
        self.frames     = frames      # list of 8 GdkPixbuf (some may be None)
        self.frame_w    = frame_w
        self.frame_h    = frame_h
        self.cfg        = cfg

        self.screen_w   = screen_w
        self.screen_h   = screen_h
        self.display_h  = cfg["pet_scale"]
        self.display_w  = frame_w   # already scaled

        # Physics
        self.vx         = 0.0
        self.vy         = 0.0
        self.state      = State.FALLING

        # Animation
        self._frame_idx   = 0
        self._anim_timer  = 0
        self._saved_facing = random.random() > 0.5
        self._idle_timer  = 0

        # Jump params
        self._update_jump_power()

        # Position – start at top of a random x
        self.x = random.randint(0, max(1, screen_w - self.display_w))
        self.y = 0.0

        # Drag state
        self.grabbed       = False
        self._drag_history = []
        self._drop_time    = 0

    # ── Properties ──────────────────────────────────────────────────────────
    @property
    def facing_right(self):
        sign = 1 if self.vx > 0 else (-1 if self.vx < 0 else 0)
        if sign != 0:
            self._saved_facing = (sign > 0)
        return self._saved_facing

    def _update_jump_power(self):
        power = self.cfg.get("jump_power", 14)
        self._jump_velocity  = -abs(power)
        self._jump_reach_x   = (WALK_SPEED * 2) * abs(self._jump_velocity / GRAVITY)
        self._max_jump_height = (self._jump_velocity ** 2) / (2 * GRAVITY)

    # ── Serialization ────────────────────────────────────────────────────────
    def serialize(self):
        return {
            "type": self.type_name,
            "x": self.x, "y": self.y,
            "vx": self.vx, "vy": self.vy,
            "state": self.state,
            "facing": self._saved_facing,
            "idleTimer": self._idle_timer,
        }

    def deserialize(self, data):
        if not data: return
        if "x"         in data: self.x             = data["x"]
        if "y"         in data: self.y             = data["y"]
        if "vx"        in data: self.vx            = data["vx"]
        if "vy"        in data: self.vy            = data["vy"]
        if "state"     in data: self.state         = data["state"]
        if "facing"    in data: self._saved_facing = data["facing"]
        if "idleTimer" in data: self._idle_timer   = data["idleTimer"]

    # ── Drag / throw ─────────────────────────────────────────────────────────
    def on_drag_begin(self):
        self.state         = State.DRAGGING
        self.vx = self.vy  = 0
        self._drag_history = []
        self._drop_time    = 0
        self.grabbed       = True

    def on_drag_motion(self, rx, ry):
        now = time.time() * 1000  # ms
        self._drag_history.append((rx, ry, now))
        cutoff = now - HISTORY_LIMIT_MS
        self._drag_history = [(x,y,t) for x,y,t in self._drag_history if t >= cutoff]

    def on_drag_end(self):
        self.grabbed    = False
        self._drop_time = time.time() * 1000
        vx, vy          = self._calculate_momentum()
        self.vx, self.vy = vx, vy
        self.state      = State.FALLING

    def _calculate_momentum(self):
        h = self._drag_history
        if len(h) < 2: return 0, 0
        last = h[-1]
        if self._drop_time and (self._drop_time - last[2]) > 100:
            return 0, 0
        prev = h[0]
        for s in reversed(h[:-1]):
            dt = last[2] - s[2]
            if 50 <= dt <= 150:
                prev = s
                break
        dt = last[2] - prev[2]
        if dt <= 0: return 0, 0
        vx = (last[0] - prev[0]) / dt * UPDATE_INTERVAL_MS * MOMENTUM_SCALE
        vy = (last[1] - prev[1]) / dt * UPDATE_INTERVAL_MS * MOMENTUM_SCALE
        vx = max(-MAX_VELOCITY, min(MAX_VELOCITY, vx))
        vy = max(-MAX_VELOCITY, min(MAX_VELOCITY, vy))
        return vx, vy

    # ── Main update (Desktop Pets update()) ───────────────────────────
    def update(self, windows):
        if self.grabbed:
            self._update_animation()
            return

        # Gravity
        if self.state in (State.FALLING, State.JUMPING):
            self.vy += GRAVITY

        if self.state == State.IDLE:
            self.vx = 0

        prev_y  = self.y
        self.x += self.vx
        self.y += self.vy

        feet_x = self.x + self.display_w / 2
        feet_y = self.y + self.display_h

        floor_y  = self.screen_h
        ceiling_y = 0

        # Ceiling clamp
        if self.y < ceiling_y:
            self.y  = ceiling_y
            self.vy = 0

        # Walked off-screen horizontally at floor level
        on_floor_level = (self.y + self.display_h) >= floor_y - 10
        if on_floor_level:
            if self.x < -self.display_w or self.x > self.screen_w:
                self._respawn()
                return
        else:
            # Wall bounce when in air
            if self.x < 0:
                self.x  = 0
                self.vx *= -1
            elif self.x > self.screen_w - self.display_w:
                self.x  = self.screen_w - self.display_w
                self.vx *= -1

        # ── Collision detection ─────────────────────────────────────────────
        on_ground        = False
        landed_on_window = None

        if self.vy >= 0:  # only collide while falling / on ground
            for (wx, wy, ww, wh) in windows:
                prev_feet_y = prev_y + self.display_h
                in_h = wx <= feet_x <= wx + ww

                # BUG FIX 1: the old tolerance `prev_feet_y <= wy + 25` was too
                # tight — a pet falling fast would skip past it in one frame.
                # Use a generous look-ahead: was the pet ABOVE the surface last
                # frame and at-or-below it this frame?
                crossed = (prev_feet_y <= wy) and (feet_y >= wy)
                # Also catch the case where the pet spawns exactly on the surface
                # or is resting on it (feet_y within a few px of wy).
                resting = abs(feet_y - wy) <= max(self.vy + GRAVITY + 2, 6)

                if in_h and (crossed or resting):
                    self.y           = wy - self.display_h   # sit ON TOP of titlebar
                    self.vy          = 0
                    on_ground        = True
                    landed_on_window = (wx, wy, ww, wh)
                    break

            if not landed_on_window:
                if feet_y >= floor_y:
                    self.y    = floor_y - self.display_h
                    self.vy   = 0
                    on_ground = True

        # ── State machine ───────────────────────────────────────────────────
        if on_ground:
            if self.state in (State.FALLING, State.JUMPING):
                self.vy = 0
                self._pick_new_action()
        else:
            if self.state != State.JUMPING:
                jumped = False
                if self.state == State.WALKING:
                    if random.random() < 0.5:
                        self._perform_jump()
                        jumped = True
                if not jumped:
                    self.state = State.FALLING

        # ── AI behavior ─────────────────────────────────────────────────────
        if self.state == State.WALKING:
            self._idle_timer = 0
            if random.random() < 0.02:
                self.state        = State.IDLE
                self.vx           = 0
                self._idle_timer  = random.random() * 60 + 20

            # Smart jumping: look for reachable windows above
            curr_feet_y = self.y + self.display_h
            curr_feet_x = self.x + self.display_w / 2
            can_jump = False

            for (wx, wy, ww, wh) in windows:
                if landed_on_window and (wx, wy, ww, wh) == landed_on_window:
                    continue
                eff_min = wx
                eff_max = wx + ww
                if curr_feet_x < wx and self.facing_right:
                    eff_min -= self._jump_reach_x
                elif curr_feet_x > wx + ww and not self.facing_right:
                    eff_max += self._jump_reach_x
                if eff_min <= curr_feet_x <= eff_max:
                    dist = curr_feet_y - wy
                    if 0 < dist <= self._max_jump_height:
                        if wy - self.display_h >= 0:
                            can_jump = True
                            break

            if can_jump and random.random() < 0.25:
                self._perform_jump()

        elif self.state == State.IDLE:
            self.vx          = 0
            self._idle_timer -= 1
            if self._idle_timer <= 0:
                self._pick_new_action()

        self._update_animation()

    # ── AI helpers ───────────────────────────────────────────────────────────
    def _pick_new_action(self):
        if random.random() < 0.6:
            self.state = State.WALKING
            self.vx    = (1 if random.random() > 0.5 else -1) * WALK_SPEED
        else:
            self.state       = State.IDLE
            self._idle_timer = random.random() * 60 + 20

    def _perform_jump(self):
        self.state = State.JUMPING
        self.vy    = self._jump_velocity
        d          = 1 if self.facing_right else -1
        self.vx    = d * WALK_SPEED * 2

    def _respawn(self):
        self.x     = random.randint(0, max(1, self.screen_w - self.display_w))
        self.y     = 0.0
        self.vx    = 0
        self.vy    = 0
        self.state = State.FALLING

    # ── Animation (port of _updateAnimation / setFrame) ─────────────────────
    def _update_animation(self):
        self._anim_timer += 1

        if self.state == State.WALKING:
            idx = (self._anim_timer // 4) % 4  # frames 0,1,2,3
            self._set_frame(idx)
        elif self.state == State.IDLE:
            self._set_frame(4)
        elif self.state in (State.JUMPING, State.FALLING):
            self._set_frame(5)
        elif self.state == State.DRAGGING:
            # Use frames 6,7 if available else 1,3
            if self.frames[6] and self.frames[7]:
                drag_frames = [6, 7]
            else:
                drag_frames = [1, 3]
            idx = (self._anim_timer // 8) % 2
            self._set_frame(drag_frames[idx])

    def _set_frame(self, idx):
        self._frame_idx = idx

    def get_frame(self):
        """Return (pixbuf, facing_right) for current frame."""
        pb = self.frames[self._frame_idx] if self._frame_idx < len(self.frames) else None
        # Fallback to first available frame
        if pb is None:
            for f in self.frames:
                if f: pb = f; break
        return pb, self.facing_right


# ── Per-pet overlay window ─────────────────────────────────────────────────────
class PetWindow(Gtk.Window):
    def __init__(self, pet, manager):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.pet     = pet
        self.manager = manager

        sz_w = pet.display_w
        sz_h = pet.display_h

        self.set_default_size(sz_w, sz_h)
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_app_paintable(True)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)

        self.da = Gtk.DrawingArea()
        self.da.set_size_request(sz_w, sz_h)
        self.da.connect("draw", self._on_draw)
        self.add(self.da)

        self.da.set_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.BUTTON1_MOTION_MASK
        )
        self.da.connect("button-press-event",   self._on_press)
        self.da.connect("button-release-event", self._on_release)
        self.da.connect("motion-notify-event",  self._on_motion)

        self.realize()
        gdk_win = self.get_window()
        if gdk_win:
            gdk_win.set_override_redirect(True)

        self.move(int(pet.x), int(pet.y))

    def tick(self):
        self.move(int(self.pet.x), int(self.pet.y))
        self.da.queue_draw()

    def _on_draw(self, widget, cr):
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        pb, facing_right = self.pet.get_frame()
        if pb:
            w = pb.get_width()
            if not facing_right:
                cr.translate(w, 0)
                cr.scale(-1, 1)
            Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
            cr.paint()

    def _on_press(self, widget, event):
        if event.button == 1 and self.manager.cfg.get("allow_interaction", True):
            self._drag_ox = event.x
            self._drag_oy = event.y
            self.pet.on_drag_begin()

    def _on_release(self, widget, event):
        if event.button == 1 and self.pet.grabbed:
            self.pet.on_drag_end()

    def _on_motion(self, widget, event):
        if self.pet.grabbed:
            nx = event.x_root - self._drag_ox
            ny = event.y_root - self._drag_oy
            self.pet.x = nx
            self.pet.y = ny
            self.move(int(nx), int(ny))
            self.pet.on_drag_motion(event.x_root, event.y_root)


# ── Settings dialog ────────────────────────────────────────────────────────────
class SettingsDialog(Gtk.Dialog):
    def __init__(self, cfg, on_apply):
        super().__init__(title="⚙ Desktop Pets Settings",
                         flags=Gtk.DialogFlags.DESTROY_WITH_PARENT)
        self.cfg      = cfg
        self.on_apply = on_apply
        self.set_default_size(400, 420)
        self.set_resizable(False)
        self._build()

    def _build(self):
        box = self.get_content_area()
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        main.set_margin_start(20); main.set_margin_end(20)
        main.set_margin_top(16);   main.set_margin_bottom(16)

        # Title
        lbl = Gtk.Label()
        lbl.set_markup('<span font="16" weight="bold">🐾 Desktop Pets</span>')
        lbl.set_halign(Gtk.Align.START)
        main.pack_start(lbl, False, False, 0)

        main.pack_start(Gtk.Separator(), False, False, 0)

        # CHARACTER (multi-select checkboxes)
        main.pack_start(self._section("CHARACTER"), False, False, 0)
        chars = list_characters()
        selected = set(self.cfg.get("pet_type") or chars)
        self._char_checks = {}
        char_box = Gtk.FlowBox()
        char_box.set_max_children_per_line(4)
        char_box.set_selection_mode(Gtk.SelectionMode.NONE)
        char_box.set_row_spacing(4); char_box.set_column_spacing(4)
        for c in chars:
            cb = Gtk.CheckButton(label=c)
            cb.set_active(c in selected)
            self._char_checks[c] = cb
            char_box.add(cb)
        main.pack_start(char_box, False, False, 0)

        main.pack_start(Gtk.Separator(), False, False, 0)

        # COUNT
        main.pack_start(self._section("COUNT"), False, False, 0)
        adj = Gtk.Adjustment(value=self.cfg.get("pet_count",3),
                             lower=1, upper=15, step_increment=1)
        self._count_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
        self._count_scale.set_digits(0)
        self._count_scale.set_draw_value(True)
        for i in [1,5,10,15]:
            self._count_scale.add_mark(i, Gtk.PositionType.BOTTOM, str(i))
        main.pack_start(self._count_scale, False, False, 0)

        # SIZE
        main.pack_start(self._section("SIZE (px)"), False, False, 0)
        adj2 = Gtk.Adjustment(value=self.cfg.get("pet_scale",80),
                              lower=32, upper=200, step_increment=8)
        self._size_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj2)
        self._size_scale.set_digits(0)
        self._size_scale.set_draw_value(True)
        for v,l in [(32,"Tiny"),(80,"Normal"),(128,"Large"),(200,"Giant")]:
            self._size_scale.add_mark(v, Gtk.PositionType.BOTTOM, l)
        main.pack_start(self._size_scale, False, False, 0)

        # JUMP POWER
        main.pack_start(self._section("JUMP POWER"), False, False, 0)
        adj3 = Gtk.Adjustment(value=self.cfg.get("jump_power",14),
                              lower=4, upper=30, step_increment=1)
        self._jump_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj3)
        self._jump_scale.set_digits(0)
        self._jump_scale.set_draw_value(True)
        main.pack_start(self._jump_scale, False, False, 0)

        # INTERACTION toggle
        row = Gtk.Box(spacing=8)
        self._interact_sw = Gtk.Switch()
        self._interact_sw.set_active(self.cfg.get("allow_interaction", True))
        row.pack_start(Gtk.Label(label="Allow pick-up & throw"), False, False, 0)
        row.pack_end(self._interact_sw, False, False, 0)
        main.pack_start(row, False, False, 0)

        main.pack_start(Gtk.Separator(), False, False, 0)

        # Buttons
        btn_row = Gtk.Box(spacing=8)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda w: self.response(Gtk.ResponseType.CANCEL))
        apply  = Gtk.Button(label="✓  Apply & Respawn")
        apply.connect("clicked", self._apply)
        btn_row.pack_end(apply,  False, False, 0)
        btn_row.pack_end(cancel, False, False, 0)
        main.pack_start(btn_row, False, False, 0)

        box.pack_start(main, True, True, 0)
        box.show_all()

    def _section(self, text):
        lbl = Gtk.Label(label=text)
        lbl.set_halign(Gtk.Align.START)
        ctx = lbl.get_style_context()
        lbl.set_markup(f'<span font="10" weight="bold" foreground="#888888">{text}</span>')
        return lbl

    def _apply(self, *_):
        selected = [c for c, cb in self._char_checks.items() if cb.get_active()]
        if not selected:
            selected = list(self._char_checks.keys())
        self.cfg["pet_type"]    = selected
        self.cfg["pet_count"]   = int(self._count_scale.get_value())
        self.cfg["pet_scale"]   = int(self._size_scale.get_value())
        self.cfg["jump_power"]       = int(self._jump_scale.get_value())
        self.cfg["allow_interaction"] = self._interact_sw.get_active()
        save_config(self.cfg)
        if self.on_apply: self.on_apply()
        self.response(Gtk.ResponseType.APPLY)


# ── Main application ───────────────────────────────────────────────────────────
class DesktopPetsApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.desktop.Pets",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.pets   = []
        self.pet_windows = []
        self.tracker     = WindowTracker()
        self.cfg         = load_config()
        self.visible     = True
        self._timer_id   = None

    def do_activate(self):
        self.hold()   # prevent app from exiting when pet windows are temporarily destroyed
        self._spawn(load_state())
        self._timer_id = GLib.timeout_add(UPDATE_INTERVAL_MS, self._tick)
        self._build_control_bar()

    def _build_control_bar(self):
        """System tray icon using AppIndicator3, with StatusIcon fallback."""
        if not self._try_appindicator():
            self._try_statusicon()

    def _try_appindicator(self):
        try:
            gi.require_version('AppIndicator3', '0.1')
            from gi.repository import AppIndicator3
            icon_path = os.path.join(BASE_DIR, "characters", "icon.png")
            if not os.path.exists(icon_path):
                icon_path = "input-gaming"
            self._indicator = AppIndicator3.Indicator.new(
                "desktop-pets", icon_path,
                AppIndicator3.IndicatorCategory.APPLICATION_STATUS
            )
            self._indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            self._indicator.set_title("Desktop Pets")
            self._indicator.set_menu(self._build_tray_menu())
            print("✓ AppIndicator3 tray icon active")
            return True
        except Exception as e:
            print(f"  AppIndicator3 unavailable ({e}), trying StatusIcon...")
            return False

    def _try_statusicon(self):
        try:
            icon_path = os.path.join(BASE_DIR, "characters", "icon.png")
            self._status_icon = (
                Gtk.StatusIcon.new_from_file(icon_path)
                if os.path.exists(icon_path)
                else Gtk.StatusIcon.new_from_icon_name("input-gaming")
            )
            self._status_icon.set_title("Desktop Pets")
            self._status_icon.set_tooltip_text("Desktop Pets — click to toggle")
            self._status_icon.connect("activate",   self._toggle)
            self._status_icon.connect("popup-menu", self._on_statusicon_menu)
            self._status_icon.set_visible(True)
            print("✓ StatusIcon tray icon active")
        except Exception as e:
            print(f"  StatusIcon also failed: {e}")

    def _build_tray_menu(self):
        menu = Gtk.Menu()
        header = Gtk.MenuItem(label="🐾 Desktop Pets")
        header.set_sensitive(False)
        menu.append(header)
        menu.append(Gtk.SeparatorMenuItem())
        self._toggle_item = Gtk.MenuItem(label="Hide Pets")
        self._toggle_item.connect("activate", self._toggle)
        menu.append(self._toggle_item)
        settings_item = Gtk.MenuItem(label="⚙  Settings…")
        settings_item.connect("activate", self._open_settings)
        menu.append(settings_item)
        menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", self._quit)
        menu.append(quit_item)
        menu.show_all()
        return menu

    def _on_statusicon_menu(self, icon, button, time):
        menu = self._build_tray_menu()
        menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, time)

    def _toggle(self, *_):
        self.visible = not self.visible
        for pw in self.pet_windows:
            pw.show() if self.visible else pw.hide()
        if hasattr(self, '_toggle_item'):
            self._toggle_item.set_label("Show Pets" if not self.visible else "Hide Pets")

    def _quit(self, *_):
        self.quit()

    def _open_settings(self, *_):
        dlg = SettingsDialog(self.cfg, self._on_settings_applied)
        dlg.run()
        dlg.destroy()

    def _on_settings_applied(self):
        self._despawn()
        self.cfg = load_config()
        self._spawn(None)

    # ── Spawning ─────────────────────────────────────────────────────────────
    def _spawn(self, saved_state):
        screen   = Gdk.Screen.get_default()
        sw, sh   = screen.get_width(), screen.get_height()
        count    = self.cfg.get("pet_count", 3)
        scale    = self.cfg.get("pet_scale", 80)
        types    = self.cfg.get("pet_type") or []
        chars    = list_characters()

        # Resolve which types to use
        pool = [t for t in types if t in chars] if types else chars
        if not pool:
            print("No characters found in", CHARS_DIR)
            return

        # Pre-load frames for each type in pool
        resources = {}
        for t in pool:
            frames, fw, fh = load_character_frames(t, scale)
            resources[t] = (frames, fw, fh)
            print(f"  Loaded '{t}': {sum(1 for f in frames if f)}/8 frames, {fw}×{fh}px")

        for i in range(count):
            # Use saved type or pick random from pool
            type_name = None
            if saved_state and i < len(saved_state):
                saved_type = saved_state[i].get("type")
                if saved_type in resources:
                    type_name = saved_type
            if not type_name:
                type_name = random.choice(pool)

            frames, fw, fh = resources[type_name]
            g = DesktopPet(type_name, frames, fw, fh, self.cfg, sw, sh)

            if saved_state and i < len(saved_state):
                g.deserialize(saved_state[i])

            pw = PetWindow(g, self)
            pw.show_all()
            if not self.visible:
                pw.hide()

            self.pets.append(g)
            self.pet_windows.append(pw)
            self.add_window(pw)

        print(f"Spawned {len(self.pets)} desktop pet(s)")

    def _despawn(self):
        save_state(self.pets)
        for pw in self.pet_windows:
            pw.destroy()
        self.pets.clear()
        self.pet_windows.clear()

    # ── Game loop ─────────────────────────────────────────────────────────────
    def _tick(self):
        # Tell the tracker which XIDs are our own pet windows so they are
        # excluded from the collision surface list.
        own_xids = set()
        for pw in self.pet_windows:
            gdk_win = pw.get_window()
            if gdk_win:
                try:
                    own_xids.add(gdk_win.get_xid())
                except Exception:
                    pass
        self.tracker.set_own_xids(own_xids)

        self.tracker.update()
        windows = self.tracker.get_windows()
        if self.visible:
            for g in self.pets:
                g.update(windows)
            for pw in self.pet_windows:
                pw.tick()
        return True  # GLib.SOURCE_CONTINUE

    def do_shutdown(self):
        save_state(self.pets)
        if self._timer_id:
            GLib.source_remove(self._timer_id)
        self.unhold()   # balance the hold() from do_activate
        Gtk.Application.do_shutdown(self)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = DesktopPetsApp()
    sys.exit(app.run(sys.argv))
