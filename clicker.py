"""
Clicker - small desktop auto-clicker with a safety.

1. Pick a mode: Auto click (repeated clicks at the dial's speed) or Hold down (holds the button).
2. Pick the mouse button (Left, Middle, Right) and, for Auto click, when to stop (a click count or No limit).
3. Click Activate. Nothing happens yet: the clicker is armed and F4 now belongs to it.
4. Press F4 to start, F4 again to stop. F4 does nothing here while the clicker is not activated.
Deactivate, changing mode or button, or closing the window always stops and releases the mouse.

Windows only. No dependencies beyond Python's standard library.
"""
import ctypes
import ctypes.wintypes as wt
import json
import math
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
winmm = ctypes.windll.winmm

VK_F4 = 0x73
MOD_NOREPEAT = 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
HOTKEY_ID = 0xC11C
BUTTON_FLAGS = {"left": (0x0002, 0x0004), "middle": (0x0020, 0x0040), "right": (0x0008, 0x0010)}  # (down, up)

MIN_CPS, MAX_CPS = 1, 1000
MAX_LIMIT = 1_000_000
SPIN = 0.002  # seconds; gaps shorter than this are timed by spinning instead of sleeping

FROZEN = getattr(sys, "frozen", False)  # running as the PyInstaller .exe
RESOURCES = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
ICON = RESOURCES / "clicker.ico"
SETTINGS = Path(os.environ.get("APPDATA") or Path.home()) / "Clicker" / "settings.json"

BG = "#1b1f24"
PANEL = "#242a31"
TEXT = "#e6e9ec"
MUTED = "#8a939c"
ACCENT = "#4aa3ff"
GREEN = "#3fb950"
AMBER = "#d29922"
TRACK = "#353c45"
FONT = "Segoe UI"


def mouse_down(button):
    user32.mouse_event(BUTTON_FLAGS[button][0], 0, 0, 0, 0)


def mouse_up(button):
    user32.mouse_event(BUTTON_FLAGS[button][1], 0, 0, 0, 0)


def f4_down():
    return bool(user32.GetAsyncKeyState(VK_F4) & 0x8000)


class ClickEngine:
    """Runs clicking on a background thread. press/release take a button name and are injectable for tests."""

    def __init__(self, press=mouse_down, release=mouse_up):
        self.press, self.release = press, release
        self.cps = 10
        self.mode = "auto"  # "auto" or "hold"
        self.button = "left"
        self.limit = 0  # clicks before stopping by itself; 0 = no limit
        self.count = 0
        self.finished = False  # True when the last run stopped because it reached the limit
        self._stop = threading.Event()
        self._thread = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self.count, self.finished = 0, False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        self._thread = None

    def _run(self):
        button = self.button  # fixed for the whole run; the UI stops the engine before changing it
        winmm.timeBeginPeriod(1)  # 1 ms timer resolution so high speeds stay accurate
        try:
            if self.mode == "hold":
                self.press(button)
                try:
                    self._stop.wait()
                finally:
                    self.release(button)
                return
            next_at = time.perf_counter()
            while not self._stop.is_set():
                self.press(button)
                self.release(button)
                self.count += 1
                if self.limit and self.count >= self.limit:
                    self.finished = True
                    break
                next_at += 1 / max(MIN_CPS, min(MAX_CPS, self.cps))
                delay = next_at - time.perf_counter()
                if delay <= 0:
                    next_at = time.perf_counter()  # fell behind; don't burst to catch up
                    continue
                if delay > SPIN:
                    self._stop.wait(delay - SPIN)  # sleep most of the gap
                while time.perf_counter() < next_at and not self._stop.is_set():
                    time.sleep(0)  # spin the last stretch: sleep alone can't hit sub-millisecond gaps
        finally:
            winmm.timeEndPeriod(1)


class HotkeyListener:
    """Registers F4 as a Windows hotkey while armed. Windows then delivers F4 only here,
    so it no longer reaches the program you're in. Alt+F4 is a different combination and still works."""

    exclusive = True

    def __init__(self):
        self.presses = 0
        self.ok = False
        self._tid = None
        self._thread = None
        self._ready = threading.Event()

    def start(self):
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(1)
        return self.ok

    def _run(self):
        msg = wt.MSG()
        self._tid = kernel32.GetCurrentThreadId()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # make sure this thread has a message queue
        self.ok = bool(user32.RegisterHotKey(None, HOTKEY_ID, MOD_NOREPEAT, VK_F4))
        self._ready.set()
        if not self.ok:
            return
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self.presses += 1
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)

    def stop(self):
        if self._thread and self._thread.is_alive():
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(timeout=1)
        self._thread = None


class PollingListener:
    """Fallback when another program already owns F4: sees the key but can't keep it from other programs."""

    exclusive = False

    def __init__(self):
        self.presses = 0
        self._was_down = False

    def start(self):
        self._was_down = f4_down()
        return True

    def poll(self):
        down = f4_down()
        if down and not self._was_down:  # act on the press, not while held
            self.presses += 1
        self._was_down = down

    def stop(self):
        pass


def default_listener():
    hotkey = HotkeyListener()
    if hotkey.start():
        return hotkey
    fallback = PollingListener()
    fallback.start()
    return fallback


def desktop_dir():
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf)  # CSIDL_DESKTOPDIRECTORY, follows OneDrive
    return Path(buf.value)


def make_desktop_shortcut(folder=None):
    """Create (or replace) Clicker.lnk. Points at the .exe when frozen, otherwise at pythonw + this script."""
    if FROZEN:
        target, args, workdir, icon = sys.executable, "", str(Path(sys.executable).parent), sys.executable
    else:
        script = Path(__file__).resolve()
        pyw = Path(sys.executable).with_name("pythonw.exe")
        target, args, workdir, icon = str(pyw if pyw.exists() else sys.executable), f'"{script}"', str(script.parent), str(ICON)
    lnk = Path(folder or desktop_dir()) / "Clicker.lnk"
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:CL_LNK);$s.TargetPath=$env:CL_TGT;"
          "$s.Arguments=$env:CL_ARGS;$s.WorkingDirectory=$env:CL_WD;$s.IconLocation=$env:CL_ICO;"
          "$s.Description='Clicker';$s.Save()")
    env = dict(os.environ, CL_LNK=str(lnk), CL_TGT=target, CL_ARGS=args, CL_WD=workdir, CL_ICO=icon)
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env,
                       capture_output=True, creationflags=0x08000000)  # CREATE_NO_WINDOW
    return lnk if r.returncode == 0 and lnk.exists() else None


class Dial(tk.Canvas):
    """Rotary knob bound to an IntVar. Drag to turn, mouse wheel to nudge.
    The scale is logarithmic (1 -> ~32 at the top -> 1000) so slow speeds stay easy to pick."""

    SWEEP_START, SWEEP = 225, 270  # degrees, clockwise from the lower left

    def __init__(self, master, var, lo, hi, size=180):
        super().__init__(master, width=size, height=size, bg=PANEL, highlightthickness=0)
        self.var, self.lo, self.hi, self.size = var, lo, hi, size
        self.enabled = True
        self.bind("<B1-Motion>", self._drag)
        self.bind("<Button-1>", self._drag)
        self.bind("<MouseWheel>", lambda e: self._step(1 if e.delta > 0 else -1))
        var.trace_add("write", lambda *a: self.draw())
        self.draw()

    def set_enabled(self, on):
        self.enabled = on
        self.draw()

    def _value(self):
        try:
            return max(self.lo, min(self.hi, int(self.var.get())))
        except (tk.TclError, ValueError):
            return self.lo

    def _frac(self, v):
        return math.log(v / self.lo) / math.log(self.hi / self.lo)

    def _from_frac(self, f):
        return round(self.lo * (self.hi / self.lo) ** f)

    def _step(self, d):
        if self.enabled:
            v = self._value()
            self.var.set(max(self.lo, min(self.hi, v + d * max(1, round(v * 0.05)))))  # ~5% per notch

    def _drag(self, e):
        if not self.enabled:
            return
        c = self.size / 2
        ang = math.degrees(math.atan2(c - e.y, e.x - c)) % 360  # 0 = right, counter-clockwise
        along = (self.SWEEP_START - ang) % 360  # clockwise distance from the start of the sweep
        if along > self.SWEEP:  # dead zone at the bottom: snap to the nearer end
            along = 0 if along > self.SWEEP + (360 - self.SWEEP) / 2 else self.SWEEP
        self.var.set(self._from_frac(along / self.SWEEP))

    def draw(self):
        self.delete("all")
        s, pad = self.size, 14
        v = self._value()
        frac = self._frac(v)
        color = ACCENT if self.enabled else TRACK
        box = (pad, pad, s - pad, s - pad)
        self.create_arc(*box, start=self.SWEEP_START, extent=-self.SWEEP, style="arc", outline=TRACK, width=10)
        if frac > 0:
            self.create_arc(*box, start=self.SWEEP_START, extent=-self.SWEEP * frac, style="arc", outline=color, width=10)
        c = s / 2
        ring, r = c - pad, c - pad - 20  # thumb rides the ring; the face sits inside it
        a = math.radians(self.SWEEP_START - self.SWEEP * frac)
        tx, ty = c + ring * math.cos(a), c - ring * math.sin(a)
        self.create_oval(tx - 9, ty - 9, tx + 9, ty + 9, fill=TEXT if self.enabled else TRACK, outline=color, width=3)
        self.create_oval(c - r, c - r, c + r, c + r, fill=BG, outline=TRACK, width=1)
        self.create_text(c, c - 7, text=str(v), fill=TEXT if self.enabled else MUTED, font=(FONT, 20, "bold"))
        self.create_text(c, c + 20, text="clicks / sec", fill=MUTED, font=(FONT, 7))


class Segmented(tk.Frame):
    """A row of buttons where exactly one is selected."""

    def __init__(self, master, options, command, font_size=9):
        super().__init__(master, bg=PANEL)
        self.buttons = {}
        for key, label in options:
            b = tk.Button(self, text=label, relief="flat", bd=0, padx=8, pady=4, font=(FONT, font_size, "bold"),
                          cursor="hand2", command=lambda k=key: command(k))
            b.pack(side="left", expand=True, fill="x", padx=2)
            self.buttons[key] = b

    def select(self, key):
        for k, b in self.buttons.items():
            on = k == key
            b.configure(bg=ACCENT if on else TRACK, fg="#ffffff" if on else MUTED,
                        activebackground=ACCENT if on else TRACK, activeforeground="#ffffff")


def spinbox(master, var, lo, hi, width, digits):
    root = master.winfo_toplevel()
    return tk.Spinbox(master, from_=lo, to=hi, textvariable=var, width=width, justify="center", font=(FONT, 11),
                      bg=BG, fg=TEXT, buttonbackground=TRACK, insertbackground=TEXT, disabledbackground=BG,
                      disabledforeground=TRACK, relief="flat", validate="key",
                      validatecommand=(root.register(lambda s: s == "" or s.isdigit() and len(s) <= digits), "%P"))


class App:
    def __init__(self, root, listener_factory=default_listener):
        self.root, self.engine = root, ClickEngine()
        self.listener_factory = listener_factory
        self.listener = None
        self._seen_presses = 0
        self._was_running = False
        self.note = ""
        saved = self._load()

        root.title("Clicker")
        root.configure(bg=BG)
        root.resizable(False, False)
        if ICON.exists():
            try:
                root.iconbitmap(default=str(ICON))
            except tk.TclError:
                pass

        self.cps = tk.IntVar(value=saved.get("cps", 10))
        self.mode = tk.StringVar(value=saved.get("mode", "auto"))
        self.button = tk.StringVar(value=saved.get("button", "left"))
        self.limit = tk.IntVar(value=saved.get("limit", 100))
        self.unlimited = tk.BooleanVar(value=saved.get("unlimited", True))
        self.on_top = tk.BooleanVar(value=saved.get("on_top", True))
        root.attributes("-topmost", self.on_top.get())

        panel = tk.Frame(root, bg=PANEL, padx=16, pady=14)
        panel.pack(padx=10, pady=10, fill="both")

        self.mode_seg = Segmented(panel, (("auto", "Auto click"), ("hold", "Hold down")), self._set_mode)
        self.mode_seg.pack(fill="x")
        self.button_seg = Segmented(panel, (("left", "Left"), ("middle", "Middle"), ("right", "Right")),
                                    self._set_button, font_size=8)
        self.button_seg.pack(fill="x", pady=(6, 0))

        self.dial = Dial(panel, self.cps, MIN_CPS, MAX_CPS)
        self.dial.pack(pady=(10, 4))

        speed_row = tk.Frame(panel, bg=PANEL)
        speed_row.pack()
        self.spin = spinbox(speed_row, self.cps, MIN_CPS, MAX_CPS, 5, 4)
        self.spin.pack(side="left")
        self.spin.bind("<FocusOut>", lambda e: self._clamp(self.cps, MIN_CPS, MAX_CPS))
        self.spin.bind("<Return>", lambda e: self._clamp(self.cps, MIN_CPS, MAX_CPS))
        tk.Label(speed_row, text=" per second", bg=PANEL, fg=MUTED, font=(FONT, 9)).pack(side="left")

        limit_row = tk.Frame(panel, bg=PANEL)
        limit_row.pack(pady=(10, 0))
        self.limit_label = tk.Label(limit_row, text="Stop after ", bg=PANEL, fg=MUTED, font=(FONT, 9))
        self.limit_label.pack(side="left")
        self.limit_spin = spinbox(limit_row, self.limit, 1, MAX_LIMIT, 8, 7)
        self.limit_spin.pack(side="left")
        self.limit_spin.bind("<FocusOut>", lambda e: self._clamp(self.limit, 1, MAX_LIMIT))
        self.limit_spin.bind("<Return>", lambda e: self._clamp(self.limit, 1, MAX_LIMIT))
        self.unlimited_box = tk.Checkbutton(limit_row, text="No limit", variable=self.unlimited,
                                            command=self._limit_changed, bg=PANEL, fg=MUTED, selectcolor=BG,
                                            activebackground=PANEL, activeforeground=TEXT, font=(FONT, 9))
        self.unlimited_box.pack(side="left", padx=(6, 0))

        self.activate = tk.Button(panel, relief="flat", bd=0, pady=8, font=(FONT, 11, "bold"), cursor="hand2",
                                  command=self._toggle_armed)
        self.activate.pack(fill="x", pady=(14, 8))

        self.status = tk.Label(panel, bg=PANEL, font=(FONT, 9), height=3, wraplength=300, justify="center")  # fixed height: the window never jumps
        self.status.pack()

        bottom = tk.Frame(panel, bg=PANEL)
        bottom.pack(fill="x", pady=(10, 0))
        tk.Checkbutton(bottom, text="Stay on top", variable=self.on_top, command=self._on_top_changed, bg=PANEL,
                       fg=MUTED, selectcolor=BG, activebackground=PANEL, activeforeground=TEXT,
                       font=(FONT, 8)).pack(side="left")
        tk.Button(bottom, text="Add desktop shortcut", relief="flat", bd=0, padx=6, pady=2, bg=TRACK, fg=MUTED,
                  activebackground=ACCENT, activeforeground="#ffffff", font=(FONT, 8), cursor="hand2",
                  command=self._add_shortcut).pack(side="right")

        root.protocol("WM_DELETE_WINDOW", self._close)
        # Traces go on only once every widget exists (creating a Spinbox writes its variable).
        self.cps.trace_add("write", lambda *a: self._cps_changed())
        self.limit.trace_add("write", lambda *a: self._limit_changed())
        self._set_mode(self.mode.get())
        self._set_button(self.button.get())
        self._cps_changed()
        self._limit_changed()
        self._refresh()
        self._poll()

    # --- state changes -------------------------------------------------------------------------
    def _set_mode(self, key):
        self.engine.stop()  # never switch mid-click; a held button is released here
        self.mode.set(key)
        self.engine.mode = key
        self.mode_seg.select(key)
        auto = key == "auto"
        self.dial.set_enabled(auto)
        self.spin.configure(state="normal" if auto else "disabled")
        self.unlimited_box.configure(state="normal" if auto else "disabled")
        self.limit_label.configure(fg=MUTED if auto else TRACK)
        self._limit_changed()
        self._refresh()
        self._save()

    def _set_button(self, key):
        self.engine.stop()
        self.button.set(key)
        self.engine.button = key
        self.button_seg.select(key)
        self._refresh()
        self._save()

    def _toggle_armed(self):
        if self.listener:
            self.engine.stop()
            self.listener.stop()
            self.listener, self.note = None, ""
        else:
            self.listener = self.listener_factory()
            self._seen_presses = self.listener.presses
            self.note = "" if self.listener.exclusive else "F4 is shared with another program."
        self._refresh()

    @property
    def armed(self):
        return self.listener is not None

    def _toggle_clicking(self):
        if self.engine.running:
            self.engine.stop()
        else:
            self.engine.start()
        self._refresh()

    def _cps_changed(self):
        try:
            v = int(self.cps.get())
        except (tk.TclError, ValueError):
            return  # mid-typing (empty box); _clamp fixes it on Enter / focus-out
        self.engine.cps = max(MIN_CPS, min(MAX_CPS, v))
        self._refresh()
        self._save()

    def _limit_changed(self):
        unlimited = self.unlimited.get()
        auto = self.mode.get() == "auto"
        self.limit_spin.configure(state="normal" if auto and not unlimited else "disabled")
        try:
            n = max(1, min(MAX_LIMIT, int(self.limit.get())))
        except (tk.TclError, ValueError):
            return
        self.engine.limit = 0 if unlimited else n  # applies live, even mid-run
        self._refresh()
        self._save()

    def _clamp(self, var, lo, hi):
        try:
            v = int(var.get())
        except (tk.TclError, ValueError):
            v = lo
        var.set(max(lo, min(hi, v)))

    def _on_top_changed(self):
        self.root.attributes("-topmost", self.on_top.get())
        self._save()

    def _add_shortcut(self):
        lnk = make_desktop_shortcut()
        self.note = "Shortcut added to your desktop." if lnk else "Couldn't create the shortcut."
        self._refresh()

    def _poll(self):
        if self.listener:
            if hasattr(self.listener, "poll"):
                self.listener.poll()
            while self._seen_presses < self.listener.presses:  # one toggle per F4 press
                self._seen_presses += 1
                self._toggle_clicking()
        running = self.engine.running
        if running or running != self._was_running:  # live count while running; catch runs that end on their own
            self._refresh()
        self._was_running = running
        self.root.after(15, self._poll)

    def _refresh(self):
        e = self.engine
        btn = e.button.capitalize()
        if not self.armed:
            self.activate.configure(text="Activate", bg=TRACK, fg=TEXT, activebackground=ACCENT)
            text, color = "Off.\nClick Activate to arm it.", MUTED
        elif e.running:
            self.activate.configure(text="Deactivate", bg=GREEN, fg="#0b1a0f", activebackground=AMBER)
            if e.mode == "hold":
                text = f"Holding the {e.button} button.\nF4 to release."
            else:
                done = f"{e.count:,} of {e.limit:,}" if e.limit else f"{e.count:,} clicks"
                text = f"{btn} clicking at {e.cps}/s · {done}\nF4 to stop."
            color = GREEN
        else:
            self.activate.configure(text="Deactivate", bg=AMBER, fg="#1a1405", activebackground=TRACK)
            text = f"Done: {e.count:,} clicks.\nF4 to run again." if e.finished else "Armed.\nPress F4 to start."
            color = AMBER
        if self.note:
            text += "\n" + self.note
        self.status.configure(text=text, fg=color)

    def _close(self):
        self.engine.stop()
        if self.listener:
            self.listener.stop()
        self._save()
        self.root.destroy()

    # --- settings ------------------------------------------------------------------------------
    def _load(self):
        try:
            return json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS.write_text(json.dumps({
                "cps": self.engine.cps, "mode": self.engine.mode, "button": self.engine.button,
                "limit": int(self.limit.get()), "unlimited": self.unlimited.get(), "on_top": self.on_top.get(),
            }), encoding="utf-8")
        except (OSError, AttributeError, tk.TclError, ValueError):
            pass  # settings are a convenience; never block clicking on them


def main():
    if "--desktop-shortcut" in sys.argv:  # make the shortcut without opening the window, e.g. after a build
        lnk = make_desktop_shortcut()
        sys.exit(0 if lnk else 1)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on high-DPI screens
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
