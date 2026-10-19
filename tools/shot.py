#!/usr/bin/env python3
"""Run the ROM headless in PyBoy and save screenshots.  Usage: shot.py <rom> <out_dir>"""
import sys
from pathlib import Path
from pyboy import PyBoy

rom, out = sys.argv[1], Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)

pb = PyBoy(rom, window="null")
pb.set_emulation_speed(0)

def run(n):
    for _ in range(n):
        pb.tick()

run(120)
pb.screen.image.save(out / "shot_straight_a.png")

run(37)
pb.screen.image.save(out / "shot_straight_b.png")

# hold A (straighten) + steer right, then left
pb.button_press("a")
pb.button_press("right")
run(60)
pb.screen.image.save(out / "shot_steer_right.png")
pb.button_release("right")
pb.button_press("left")
run(120)
pb.screen.image.save(out / "shot_steer_left.png")
pb.button_release("left")
pb.button_release("a")

# let the sine curve run
run(40)
pb.screen.image.save(out / "shot_curve_a.png")
run(60)
pb.screen.image.save(out / "shot_curve_b.png")
pb.stop(save=False)
print("saved", sorted(p.name for p in out.glob("*.png")))
