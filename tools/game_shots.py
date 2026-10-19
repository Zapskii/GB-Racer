#!/usr/bin/env python3
"""Contact sheet of a short drive: accelerate, steer, run onto the grass.  Usage: game_shots.py <rom> <out.png>"""
import sys
from PIL import Image
from pyboy import PyBoy
pb = PyBoy(sys.argv[1], window="null"); pb.set_emulation_speed(0)
for _ in range(90): pb.tick()
script = [("a", 150), (None, 20), ("a", 120), ("right", 70), ("a", 140), ("left", 150), ("a", 100)]
held, marks = set(), {40, 120, 200, 290, 380, 470, 560, 650}
shots, t = [], 0
for btn, n in script:
    pb.button_press(btn) if btn else None
    for _ in range(n):
        pb.tick(); t += 1
        if t in marks: shots.append(pb.screen.image.convert("RGB").copy())
    pb.button_release(btn) if btn else None
pb.stop(save=False)
S, cols = 3, 4
rows = (len(shots) + cols - 1) // cols
sheet = Image.new("RGB", (cols * (160 * S + 8), rows * (144 * S + 8)), (50, 50, 50))
for i, im in enumerate(shots):
    sheet.paste(im.resize((160 * S, 144 * S), Image.NEAREST), ((i % cols) * (160 * S + 8), (i // cols) * (144 * S + 8)))
sheet.save(sys.argv[2]); print(len(shots), "frames")
