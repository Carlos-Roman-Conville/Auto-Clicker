"""Tests for clicker.py. The real mouse and F4 key are never touched: both are replaced with fakes.
Run: python -m unittest test_clicker -v"""
import time
import tkinter as tk
import unittest

import clicker


class FakeMouse:
    def __init__(self):
        self.downs = self.ups = 0

    def press(self):
        self.downs += 1

    def release(self):
        self.ups += 1


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.m = FakeMouse()
        self.e = clicker.ClickEngine(self.m.press, self.m.release)

    def tearDown(self):
        self.e.stop()

    def test_auto_clicks_at_about_the_set_speed(self):
        self.e.cps = 50
        self.e.start()
        time.sleep(1.0)
        self.e.stop()
        self.assertTrue(40 <= self.m.downs <= 60, self.m.downs)
        self.assertEqual(self.m.downs, self.m.ups)  # every click is a full down+up

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

    def test_reaches_1000_per_second(self):
        self.e.cps = 1000
        self.e.start()
        time.sleep(1.0)
        self.e.stop()
        self.assertTrue(900 <= self.m.downs <= 1010, self.m.downs)

    def test_speed_is_clamped(self):
        self.e.cps = 10_000
        self.e.start()
        time.sleep(0.5)
        self.e.stop()
        self.assertLessEqual(self.m.downs, clicker.MAX_CPS * 0.5 + 5)


class AppTests(unittest.TestCase):
    """Drives the real window with a fake mouse and a fake F4 key."""

    def setUp(self):
        self.f4 = False
        self._real_f4 = clicker.f4_down
        clicker.f4_down = lambda: self.f4
        self._real_settings = clicker.SETTINGS
        clicker.SETTINGS = clicker.Path(__file__).with_name("_test_settings.json")
        self.root = tk.Tk()
        self.app = clicker.App(self.root)
        self.m = FakeMouse()
        self.app.engine = clicker.ClickEngine(self.m.press, self.m.release)

    def tearDown(self):
        self.app._close()
        clicker.f4_down = self._real_f4
        clicker.SETTINGS.unlink(missing_ok=True)
        clicker.SETTINGS = self._real_settings

    def tap_f4(self):
        self.f4 = True
        self.app._poll_f4()
        self.f4 = False
        self.app._poll_f4()

    def test_f4_does_nothing_until_activated(self):
        self.tap_f4()
        time.sleep(0.2)
        self.assertFalse(self.app.engine.running)
        self.assertEqual(self.m.downs, 0)

    def test_activate_then_f4_toggles(self):
        self.app._toggle_armed()
        self.assertFalse(self.app.engine.running)  # activating alone never clicks
        self.tap_f4()
        self.assertTrue(self.app.engine.running)
        time.sleep(0.2)
        self.tap_f4()
        self.assertFalse(self.app.engine.running)
        self.assertGreater(self.m.downs, 0)

    def test_holding_f4_counts_as_one_press(self):
        self.app._toggle_armed()
        self.f4 = True
        for _ in range(5):
            self.app._poll_f4()
        self.assertTrue(self.app.engine.running)

    def test_deactivate_stops_and_releases_hold(self):
        self.app._set_mode("hold")
        self.app.engine.mode = "hold"
        self.app._toggle_armed()
        self.tap_f4()
        time.sleep(0.1)
        self.app._toggle_armed()
        self.assertFalse(self.app.engine.running)
        self.assertEqual((self.m.downs, self.m.ups), (1, 1))

    def test_mode_switch_stops_clicking(self):
        self.app._toggle_armed()
        self.tap_f4()
        self.app._set_mode("hold")
        self.assertFalse(self.app.engine.running)

    def test_hold_mode_disables_speed_controls(self):
        self.app._set_mode("hold")
        self.assertEqual(str(self.app.spin.cget("state")), "disabled")
        self.assertFalse(self.app.dial.enabled)

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


if __name__ == "__main__":
    unittest.main()
