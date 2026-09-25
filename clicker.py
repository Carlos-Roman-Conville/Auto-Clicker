"""
Clicker - small desktop auto-clicker with a safety.

1. Pick a mode: Auto click (repeated clicks at the dial's speed) or Hold down (holds the left button).
2. Click Activate. Nothing happens yet: the clicker is armed.
3. Press F4 to start, F4 again to stop. F4 does nothing while the clicker is not activated.
Deactivate, changing mode, or closing the window always stops and releases the mouse.

Windows only. No dependencies beyond Python's standard library.
"""
import ctypes
import json
import math
import threading
import time
import tkinter as tk
from pathlib import Path

user32 = ctypes.windll.user32
winmm = ctypes.windll.winmm

VK_F4 = 0x73
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

MIN_CPS, MAX_CPS = 1, 1000
SPIN = 0.002  # seconds; gaps shorter than this are timed by spinning instead of sleeping
SETTINGS = Path(__file__).with_name("settings.json")

BG = "#1b1f24"
PANEL = "#242a31"
TEXT = "#e6e9ec"
MUTED = "#8a939c"
ACCENT = "#4aa3ff"
GREEN = "#3fb950"
AMBER = "#d29922"
TRACK = "#353c45"


def left_down():
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)


def left_up():
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def f4_down():
    return bool(user32.GetAsyncKeyState(VK_F4) & 0x8000)


class ClickEngine:
    """Runs clicking on a background thread. press/release are injectable for tests."""

    def __init__(self, press=left_down, release=left_up):
        self.press, self.release = press, release
        self.cps = 10
        self.mode = "auto"  # "auto" or "hold"
        self._stop = threading.Event()
        self._thread = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        self._thread = None

    def _run(self):
        winmm.timeBeginPeriod(1)  # 1 ms timer resolution so high speeds stay accurate
        try:
            if self.mode == "hold":
                self.press()
                try:
                    self._stop.wait()
                finally:
                    self.release()
                return
            next_at = time.perf_counter()
            while not self._stop.is_set():
                self.press()
                self.release()
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
        self.create_text(c, c - 7, text=str(v), fill=TEXT if self.enabled else MUTED, font=("Segoe UI", 20, "bold"))
        self.create_text(c, c + 20, text="clicks / sec", fill=MUTED, font=("Segoe UI", 7))


class App:
    def __init__(self, root):
        self.root, self.engine = root, ClickEngine()
        self.armed = False
        self._f4_was_down = False
        saved = self._load()

        root.title("Clicker")
        root.configure(bg=BG)
        root.resizable(False, False)
        root.attributes("-topmost", saved.get("on_top", True))

        self.cps = tk.IntVar(value=saved.get("cps", 10))
        self.mode = tk.StringVar(value=saved.get("mode", "auto"))
        self.on_top = tk.BooleanVar(value=saved.get("on_top", True))

        panel = tk.Frame(root, bg=PANEL, padx=16, pady=14)
        panel.pack(padx=10, pady=10, fill="both")

        modes = tk.Frame(panel, bg=PANEL)
        modes.pack(fill="x")
        self.mode_buttons = {}
        for key, label in (("auto", "Auto click"), ("hold", "Hold down")):
            b = tk.Button(modes, text=label, relief="flat", bd=0, padx=10, pady=5, font=("Segoe UI", 9, "bold"),
                          cursor="hand2", command=lambda k=key: self._set_mode(k))
            b.pack(side="left", expand=True, fill="x", padx=2)
            self.mode_buttons[key] = b

        self.dial = Dial(panel, self.cps, MIN_CPS, MAX_CPS)
        self.dial.pack(pady=(12, 4))

        spin_row = tk.Frame(panel, bg=PANEL)
        spin_row.pack()
        self.spin = tk.Spinbox(spin_row, from_=MIN_CPS, to=MAX_CPS, textvariable=self.cps, width=5, justify="center",
                               font=("Segoe UI", 11), bg=BG, fg=TEXT, buttonbackground=TRACK, insertbackground=TEXT,
                               disabledbackground=BG, disabledforeground=TRACK, relief="flat", validate="key",
                               validatecommand=(root.register(lambda s: s == "" or s.isdigit() and len(s) <= 4), "%P"))
        self.spin.pack(side="left")
        self.spin.bind("<FocusOut>", lambda e: self._clamp())
        self.spin.bind("<Return>", lambda e: self._clamp())
        tk.Label(spin_row, text=" per second", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")

        self.activate = tk.Button(panel, relief="flat", bd=0, pady=8, font=("Segoe UI", 11, "bold"), cursor="hand2",
                                  command=self._toggle_armed)
        self.activate.pack(fill="x", pady=(14, 8))

        self.status = tk.Label(panel, bg=PANEL, font=("Segoe UI", 9), wraplength=220, justify="center")
        self.status.pack()

        tk.Checkbutton(panel, text="Stay on top", variable=self.on_top, command=self._on_top_changed, bg=PANEL,
                       fg=MUTED, selectcolor=BG, activebackground=PANEL, activeforeground=TEXT,
                       font=("Segoe UI", 8)).pack(pady=(8, 0))

        root.protocol("WM_DELETE_WINDOW", self._close)
        self.cps.trace_add("write", lambda *a: self._cps_changed())  # only once every widget exists
        self._set_mode(self.mode.get())
        self._cps_changed()
        self._refresh()
        self._poll_f4()

    # --- state changes -------------------------------------------------------------------------
    def _set_mode(self, key):
        self.engine.stop()  # never switch modes mid-click; a held button is released here
        self.mode.set(key)
        self.engine.mode = key
        for k, b in self.mode_buttons.items():
            on = k == key
            b.configure(bg=ACCENT if on else TRACK, fg="#ffffff" if on else MUTED,
                        activebackground=ACCENT if on else TRACK, activeforeground="#ffffff")
        auto = key == "auto"
        self.dial.set_enabled(auto)
        self.spin.configure(state="normal" if auto else "disabled")
        self._refresh()
        self._save()

    def _toggle_armed(self):
        self.armed = not self.armed
        if not self.armed:
            self.engine.stop()
        self._refresh()

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

    def _clamp(self):
        try:
            v = int(self.cps.get())
        except (tk.TclError, ValueError):
            v = self.engine.cps
        self.cps.set(max(MIN_CPS, min(MAX_CPS, v)))

    def _on_top_changed(self):
        self.root.attributes("-topmost", self.on_top.get())
        self._save()

    def _poll_f4(self):
        down = f4_down()
        if down and not self._f4_was_down and self.armed:  # act on the press, not while held
            self._toggle_clicking()
        self._f4_was_down = down
        self.root.after(15, self._poll_f4)

    def _refresh(self):
        if not self.armed:
            self.activate.configure(text="Activate", bg=TRACK, fg=TEXT, activebackground=ACCENT)
            text, color = "Off. Click Activate to arm it.", MUTED
        elif self.engine.running:
            self.activate.configure(text="Deactivate", bg=GREEN, fg="#0b1a0f", activebackground=AMBER)
            text = (f"Clicking {self.engine.cps}x per second. F4 to stop." if self.engine.mode == "auto"
                    else "Holding the left button. F4 to release.")
            color = GREEN
        else:
            self.activate.configure(text="Deactivate", bg=AMBER, fg="#1a1405", activebackground=TRACK)
            text, color = "Armed. Press F4 to start.", AMBER
        self.status.configure(text=text, fg=color)

    def _close(self):
        self.engine.stop()
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
            SETTINGS.write_text(json.dumps({"cps": self.engine.cps, "mode": self.engine.mode,
                                            "on_top": self.on_top.get()}), encoding="utf-8")
        except (OSError, AttributeError):
            pass  # settings are a convenience; never block clicking on them


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on high-DPI screens
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
