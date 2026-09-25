# Clicker

A small desktop auto-clicker with a safety.

![states](docs/clicker_states.png)

## Get it running

- **Easiest:** double-click `Clicker.exe`. Nothing to install. If you don't have it, run `build.bat` once to make it.
- **From source:** double-click `run.bat` (needs Python 3.10+).
- **Desktop shortcut:** click **Add desktop shortcut** in the window. From the .exe it points at the .exe; from source it points at the script.
  `Clicker.exe --desktop-shortcut` does the same without opening the window.

## Use it

1. Pick a mode:
   - **Auto click**: clicks over and over at the speed on the dial (1 to 1000 per second).
   - **Hold down**: presses the button and keeps it held. Speed and click count grey out because they don't apply.
2. Pick the mouse button: **Left**, **Middle** or **Right**.
3. Set the speed with the dial or the number box. The dial is stretched so slow speeds are easy to pick: 10 sits a third of the
   way round, about 30 at the top, 1000 at the end. The mouse wheel nudges it about 5% per notch. For an exact number, type it in the box.
4. Set when to stop: **Stop after** a number of clicks (up to 1,000,000), or tick **No limit** to keep going until you press F4.
5. Click **Activate**. Nothing clicks yet. The clicker is armed and the button turns amber.
6. Press **F4** to start, **F4** again to stop. The button turns green while it's clicking and the status shows the count.
   When a click limit is reached it stops by itself and says **Done**; F4 runs another batch.

**The safety:** F4 does nothing until you click Activate. While it's activated, F4 belongs to Clicker: Windows stops sending
it to the program you're in, so it won't also open your browser's address list or repeat an action in Excel. Deactivate and
F4 goes back to normal. Alt+F4 is a different key combination and still closes windows.

Clicking **Deactivate**, switching mode or button, or closing the window always stops and lets go of a held button.
You can change the speed and the click limit while it's running.

Clicks land wherever the mouse pointer is. The window stays on top of other windows unless you untick **Stay on top**.
Your choices are saved in `%APPDATA%\Clicker\settings.json`.

Some antivirus tools are suspicious of small unsigned .exe files that control the mouse. If yours flags `Clicker.exe`,
that's a false alarm on this kind of program. You can rebuild it yourself from the source with `build.bat`.

## For developers

- `clicker.py`, all in one file:
  - `ClickEngine`: clicks on a background thread; button, speed, click limit and live count.
  - `HotkeyListener`: registers F4 with `RegisterHotKey` on its own thread while armed, so Windows delivers F4 only to Clicker.
    If another program already owns F4, `PollingListener` (`GetAsyncKeyState`) takes over; it sees F4 but can't keep it from
    other programs, and the status says so.
  - `Dial`: the logarithmic rotary knob (a tkinter Canvas). `Segmented`: the mode and button pickers.
  - `App`: the window, arm and start state, and a 15 ms poll that reads F4 presses and live status.
  - `make_desktop_shortcut`: writes `Clicker.lnk` through PowerShell and WScript.Shell, so there are no extra packages.
- Clicks go out through `user32.mouse_event` (about 0.09 ms per click, so 1000/s has plenty of headroom).
- Timing: it sleeps most of each gap and spins the last 2 ms (`SPIN`), because Windows sleep can't hit sub-millisecond gaps.
  At high speeds that keeps one CPU core busy while clicking; it idles again the moment you stop.
- `build.bat`: PyInstaller one-file, windowed, with the icon bundled. A one-file .exe runs as two processes: a small launcher and the app.
- `make_icon.py` redraws `clicker.ico` (needs Pillow).
- Tests: `python -m unittest test_clicker -v` (24 tests). The mouse is always a fake. The window tests fake F4.
  `HotkeyTests` registers the real F4 hotkey and sends a real F4 press, which the hotkey swallows. `ShortcutTests` writes a
  shortcut into a temp folder.
