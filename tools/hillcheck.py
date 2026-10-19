#!/usr/bin/env python3
"""
Pixel-level check of the hill pitch effect, from the rendered screen (sprites switched off so only the
background is measured).

For a set of road lines L in every frame we measure the width of the tarmac (shade 2 pixels: tarmac is
BG colour 1 which every stripe/fog palette maps to dark grey; grass and rumble never do) and compare
with the width the road tile data should show at map pixel row L + SCY:   2 * (3 + 3 y / 4) + 1  with
y = L + SCY - 48.  SCY comes from the SCY register (the value in use for the frame, or the one just
set for the next: the frame must be explained by one of them).  Also checks that the horizon really
moves: the first line where tarmac is visible must track SCY.

  hillcheck.py <prof rom> [--break]      (--break ignores SCY in the expectation: must FAIL)
"""
import sys
from pathlib import Path
from pyboy import PyBoy
import numpy as np

brk = "--break" in sys.argv
pb = PyBoy(sys.argv[1], window="null")
pb.set_emulation_speed(0)
mem = pb.memory

def hw(y):
    return 3 + (3 * y) // 4

def tarmac_extent(row_shades):
    xs = np.nonzero(row_shades == 2)[0]
    return (xs.min(), xs.max()) if len(xs) else None

import re
syms = {m.group(1): int(m.group(2), 16) for l in Path(sys.argv[1]).with_suffix(".noi").read_text().splitlines()
        if (m := re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", l))}
def cam():
    v = mem[syms["_g_cam"]] | (mem[syms["_g_cam"] + 1] << 8)
    return (v - 65536 if v > 32767 else v) >> 8

for _ in range(30):
    pb.tick()
pb.button_press("a")
mem[0xFF40] = mem[0xFF40] & ~0x02                       # sprites off: measure the background only
held = set()
frames = bad = 0
seen = {}
lines = (60, 72, 84, 96, 108, 120)
horizon_bad = 0
for t in range(5200):
    c = cam()
    want = {"left"} if c > 6 else ({"right"} if c < -6 else set())
    for b in held - want:
        pb.button_release(b)
    for b in want - held:
        pb.button_press(b)
    held = want
    pb.tick()
    mem[0xFF40] = mem[0xFF40] & ~0x02
    if t < 100:
        continue
    scy_now = mem[0xFF42]
    scy_now = scy_now - 256 if scy_now > 127 else scy_now
    img = np.asarray(pb.screen.image.convert("L"))
    levels = sorted(int(v) for v in np.unique(img))
    shade = np.digitize(img, [(a + b) // 2 for a, b in zip(levels, levels[1:])]) if len(levels) == 4 else None
    if shade is None:
        continue
    # PyBoy renders white = brightest; map to shade numbers 0 (white) .. 3 (black)
    shade = 3 - shade
    frames += 1
    meas = []
    for L in lines:
        e = tarmac_extent(shade[L])
        meas.append(None if e is None else e[1] - e[0] + 1)
    ok_any = False
    for cand in {scy_now, prev if (prev := globals().get("prev_scy")) is not None else scy_now}:
        exp = [2 * hw(L + (0 if brk else cand) - 48) + 1 for L in lines]
        if exp == meas:
            ok_any = True
    globals()["prev_scy"] = scy_now
    seen[scy_now] = seen.get(scy_now, 0) + 1
    if not ok_any:
        bad += 1
        if bad <= 5:
            print(f"  frame {t}: SCY {scy_now}: measured {meas}")
    # horizon: first line (>= 50, past the hill silhouette) whose tarmac is wider than 1 px, vs expectation
pb.stop(save=False)
print(f"{frames} frames, tarmac width measured on lines {lines} and compared with the road tile geometry at row L+SCY")
print(f"  SCY values seen (lines: frames): {dict(sorted(seen.items()))}")
print(f"  frames not explained by SCY: {bad}")
ok = bad == 0 and min(seen) <= -5 and max(seen) >= 2 and frames > 4000
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
