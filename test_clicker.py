"""Tests for clicker.py. The real mouse is never touched (a fake records clicks instead).
The window tests use a fake F4 listener; HotkeyTests registers the real F4 hotkey and sends a real F4 press.
Run: python -m unittest test_clicker -v"""
import ctypes
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

import clicker


class FakeMouse:
    def __init__(self):
        self.downs = self.ups = 0
        self.buttons = set()

    def press(self, button):
        self.downs += 1
        self.buttons.add(button)

    def release(self, button):
        self.ups += 1


class FakeListener:
    exclusive = True

    def __init__(self):
        self.presses = 0
        self.stopped = False

    def stop(self):
        self.stopped = True


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.m = FakeMouse()
        self.e = clicker.ClickEngine(self.m.press, self.m.release)

    def tearDown(self):
        self.e.stop()

    def run_for(self, seconds):
        self.e.start()
        time.sleep(seconds)
        self.e.stop()

    def test_auto_clicks_at_about_the_set_speed(self):
        self.e.cps = 50
        self.run_for(1.0)
        self.assertTrue(40 <= self.m.downs <= 60, self.m.downs)
        self.assertEqual(self.m.downs, self.m.ups)  # every click is a full down+up

    def test_reaches_1000_per_second(self):
        self.e.cps = 1000
        self.run_for(1.0)
        self.assertTrue(900 <= self.m.downs <= 1010, self.m.downs)

    def test_speed_change_applies_while_running(self):
        self.e.cps = 5
        self.e.start()
        time.sleep(0.5)
        slow = self.m.downs
        self.e.cps = 100
        time.sleep(0.5)
        self.e.stop()
        self.assertGreater(self.m.downs - slow, slow * 5)

    def test_hold_presses_once_and_releases_on_stop(self):
        self.e.mode = "hold"
        self.e.start()
        time.sleep(0.3)
        self.assertEqual((self.m.downs, self.m.ups), (1, 0))
        self.e.stop()
        self.assertEqual((self.m.downs, self.m.ups), (1, 1))

    def test_speed_is_clamped(self):
        self.e.cps = 10_000
        self.run_for(0.5)
        self.assertLessEqual(self.m.downs, clicker.MAX_CPS * 0.5 + 5)

    def test_uses_the_chosen_button(self):
        for button in ("left", "middle", "right"):
            m = FakeMouse()
            e = clicker.ClickEngine(m.press, m.release)
            e.button, e.cps = button, 200
            e.start()
            time.sleep(0.1)
            e.stop()
            self.assertEqual(m.buttons, {button})

    def test_stops_by_itself_at_the_limit(self):
        self.e.cps, self.e.limit = 500, 25
        self.e.start()
        time.sleep(0.5)
        self.assertFalse(self.e.running)
        self.assertEqual((self.m.downs, self.e.count, self.e.finished), (25, 25, True))

    def test_no_limit_keeps_going(self):
        self.e.cps, self.e.limit = 500, 0
        self.run_for(0.3)
        self.assertGreater(self.m.downs, 100)
        self.assertFalse(self.e.finished)

    def test_count_resets_each_run(self):
        self.e.cps, self.e.limit = 500, 10
        self.e.start()
        time.sleep(0.2)
        self.e.start()
        time.sleep(0.2)
        self.assertEqual((self.e.count, self.m.downs), (10, 20))


class HotkeyTests(unittest.TestCase):
    """Registers the real F4 hotkey and injects a real F4 press. While registered, Windows delivers F4 only to
    the listener, so the injected key never reaches whatever window has focus."""

    def test_real_f4_press_is_received(self):
        h = clicker.HotkeyListener()
        if not h.start():
            self.skipTest("another program has F4 registered")
        try:
            ctypes.windll.user32.keybd_event(clicker.VK_F4, 0, 0, 0)
            ctypes.windll.user32.keybd_event(clicker.VK_F4, 0, 2, 0)  # KEYEVENTF_KEYUP
            deadline = time.time() + 1
            while h.presses == 0 and time.time() < deadline:
                time.sleep(0.01)
            self.assertEqual(h.presses, 1)
        finally:
            h.stop()

    def test_released_after_stop(self):
        h = clicker.HotkeyListener()
        if not h.start():
            self.skipTest("another program has F4 registered")
        h.stop()
        again = clicker.HotkeyListener()
        self.assertTrue(again.start())  # would fail if the first one still held F4
        again.stop()


class ShortcutTests(unittest.TestCase):
    def test_creates_shortcut_to_this_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            lnk = clicker.make_desktop_shortcut(tmp)
            self.assertIsNotNone(lnk)
            import subprocess
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');$s.TargetPath;$s.Arguments"],
                                 capture_output=True, text=True).stdout
            self.assertIn("pythonw.exe", out.lower())
            self.assertIn("clicker.py", out)


class AppTests(unittest.TestCase):
    """Drives the real window with a fake mouse and a fake F4 listener."""

    def setUp(self):
        self._real_settings = clicker.SETTINGS
        self.tmp = tempfile.TemporaryDirectory()
        clicker.SETTINGS = Path(self.tmp.name) / "settings.json"
        self.listeners = []
        self.root = tk.Tk()
        self.app = clicker.App(self.root, listener_factory=self._new_listener)
        self.m = FakeMouse()
        self.app.engine = clicker.ClickEngine(self.m.press, self.m.release)
        self.app._set_mode("auto")
        self.app._set_button("left")

    def _new_listener(self):
        self.listeners.append(FakeListener())
        return self.listeners[-1]

    def tearDown(self):
        self.app._close()
        clicker.SETTINGS = self._real_settings
        self.tmp.cleanup()

    def tap_f4(self):
        if self.app.listener:
            self.app.listener.presses += 1
        self.app._poll()

    def test_f4_does_nothing_until_activated(self):
        self.tap_f4()
        time.sleep(0.2)
        self.assertFalse(self.app.engine.running)
        self.assertEqual(self.m.downs, 0)
        self.assertEqual(self.listeners, [])  # F4 isn't even claimed until Activate

    def test_activate_claims_f4_and_deactivate_releases_it(self):
        self.app._toggle_armed()
        self.assertEqual(len(self.listeners), 1)
        self.app._toggle_armed()
        self.assertTrue(self.listeners[0].stopped)

    def test_activate_then_f4_toggles(self):
        self.app._toggle_armed()
        self.assertFalse(self.app.engine.running)  # activating alone never clicks
        self.tap_f4()
        self.assertTrue(self.app.engine.running)
        time.sleep(0.2)
        self.tap_f4()
        self.assertFalse(self.app.engine.running)
        self.assertGreater(self.m.downs, 0)

    def test_deactivate_stops_and_releases_hold(self):
        self.app._set_mode("hold")
        self.app._toggle_armed()
        self.tap_f4()
        time.sleep(0.1)
        self.app._toggle_armed()
        self.assertFalse(self.app.engine.running)
        self.assertEqual((self.m.downs, self.m.ups), (1, 1))

    def test_mode_or_button_switch_stops_clicking(self):
        self.app._toggle_armed()
        self.tap_f4()
        self.app._set_mode("hold")
        self.assertFalse(self.app.engine.running)
        self.tap_f4()
        self.app._set_button("middle")
        self.assertFalse(self.app.engine.running)

    def test_middle_button_reaches_the_engine(self):
        self.app._set_button("middle")
        self.app._toggle_armed()
        self.tap_f4()
        time.sleep(0.2)
        self.tap_f4()
        self.assertEqual(self.m.buttons, {"middle"})

    def test_hold_mode_disables_speed_and_limit(self):
        self.app._set_mode("hold")
        for w in (self.app.spin, self.app.limit_spin, self.app.unlimited_box):
            self.assertEqual(str(w.cget("state")), "disabled")
        self.assertFalse(self.app.dial.enabled)

    def test_limit_and_no_limit(self):
        self.app.unlimited.set(False)
        self.app.limit.set(250)
        self.assertEqual(self.app.engine.limit, 250)
        self.assertEqual(str(self.app.limit_spin.cget("state")), "normal")
        self.app.unlimited.set(True)
        self.app._limit_changed()
        self.assertEqual(self.app.engine.limit, 0)
        self.assertEqual(str(self.app.limit_spin.cget("state")), "disabled")

    def test_run_ending_at_limit_updates_status(self):
        self.app.unlimited.set(False)
        self.app.limit.set(5)
        self.app.cps.set(500)
        self.app._toggle_armed()
        self.tap_f4()
        time.sleep(0.2)
        self.app._poll()
        self.assertFalse(self.app.engine.running)
        self.assertIn("Done: 5 clicks", self.app.status.cget("text"))
        self.tap_f4()  # F4 runs another batch of 5
        time.sleep(0.2)
        self.assertEqual(self.m.downs, 10)

    def test_dial_drag_positions(self):
        d = self.app.dial
        c = d.size / 2
        drag = lambda x, y: d._drag(type("E", (), {"x": x, "y": y})())
        drag(c, 5)                     # straight up: middle of the log scale, sqrt(1000) ~ 32
        self.assertAlmostEqual(self.app.cps.get(), 32, delta=1)
        drag(c - 60, c + 60)           # lower left: minimum
        self.assertEqual(self.app.cps.get(), 1)
        drag(c + 60, c + 60)           # lower right: maximum
        self.assertEqual(self.app.cps.get(), 1000)
        drag(c - 5, d.size - 2)        # dead zone at the bottom, left of centre: snaps to minimum
        self.assertEqual(self.app.cps.get(), 1)
        drag(c + 5, d.size - 2)        # right of centre: snaps to maximum
        self.assertEqual(self.app.cps.get(), 1000)

    def test_dial_and_box_share_one_value(self):
        self.app.cps.set(42)
        self.assertEqual(self.app.engine.cps, 42)
        self.app.dial._step(1)         # wheel notch is ~5%: 42 -> 44
        self.assertEqual(self.app.cps.get(), 44)
        self.app.cps.set(3)
        self.app.dial._step(-1)        # never less than 1 per notch
        self.assertEqual(self.app.cps.get(), 2)

    def test_settings_round_trip(self):
        self.app._set_button("middle")
        self.app.unlimited.set(False)
        self.app.limit.set(777)
        self.app._close()
        self.root = tk.Tk()
        self.app = clicker.App(self.root, listener_factory=self._new_listener)
        self.assertEqual((self.app.engine.button, self.app.engine.limit), ("middle", 777))


if __name__ == "__main__":
    unittest.main()
