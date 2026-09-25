"""Draws clicker.ico (a small version of the speed dial). Needs Pillow. Run: python make_icon.py"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((8, 8, S - 8, S - 8), radius=52, fill="#242a31")
box = (40, 40, S - 40, S - 40)
# Pillow angles run clockwise from 3 o'clock; the dial sweeps 270 degrees from lower left to lower right.
d.arc(box, start=135, end=405, fill="#353c45", width=26)
d.arc(box, start=135, end=135 + 270 * 0.62, fill="#4aa3ff", width=26)
a = math.radians(135 + 270 * 0.62)
c, ring = S / 2, (S - 80) / 2 - 13
tx, ty = c + ring * math.cos(a), c + ring * math.sin(a)
d.ellipse((tx - 22, ty - 22, tx + 22, ty + 22), fill="#e6e9ec", outline="#4aa3ff", width=8)
d.ellipse((c - 30, c - 30, c + 30, c + 30), fill="#e6e9ec")
img.save(Path(__file__).with_name("clicker.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save(Path(__file__).with_name("docs").joinpath("icon.png"))
print("wrote clicker.ico")
