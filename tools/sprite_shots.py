#!/usr/bin/env python3
"""Screenshot contact sheet of the running game (sprites visible).  Usage: sprite_shots.py <rom> <out.png>"""
import sys
from PIL import Image
from pyboy import PyBoy
pb = PyBoy(sys.argv[1], window="null"); pb.set_emulation_speed(0)
for _ in range(90): pb.tick()
script = [(None, 150), ("right", 40), (None, 60), ("left", 60), ("down", 60), (None, 100), ("up", 80), (None, 200)]
marks = {100, 190, 260, 330, 420, 520, 600, 690}
shots, t = [], 0
for btn, n in script:
    if btn: pb.button_press(btn)
    for _ in range(n):
        pb.tick(); t += 1
        if t in marks: shots.append(pb.screen.image.convert("RGB").copy())
    if btn: pb.button_release(btn)
pb.stop(save=False)
S, cols = 3, 4
rows = (len(shots) + cols - 1) // cols
sheet = Image.new("RGB", (cols * (160 * S + 8), rows * (144 * S + 8)), (50, 50, 50))
for i, im in enumerate(shots):
    sheet.paste(im.resize((160 * S, 144 * S), Image.NEAREST), ((i % cols) * (160 * S + 8), (i // cols) * (144 * S + 8)))
sheet.save(sys.argv[2]); print(len(shots), "frames")
