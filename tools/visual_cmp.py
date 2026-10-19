#!/usr/bin/env python3
"""
Compare what two PROFILE ROMs (C builder vs asm builder) put on screen at the SAME
main-loop iteration, with button presses keyed to that iteration counter so both
get identical input.  Writes a contact sheet: reference | new | differing pixels.

Usage: visual_cmp.py <ref.gb> <new.gb> <out.png>
"""
import re
import sys
from pathlib import Path
from PIL import Image, ImageChops
from pyboy import PyBoy

def symbols(rom):
    syms = {}
    for line in Path(rom).with_suffix(".noi").read_text().splitlines():
        m = re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", line)
        if m:
            syms[m.group(1)] = int(m.group(2), 16)
    return syms

# (first iteration, last iteration, button held)
HOLDS = [(60, 110, "right"), (130, 220, "left"), (240, 260, "up"), (270, 300, "a")]
MARKS = [40, 100, 125, 175, 230, 262, 290]

def run(rom):
    syms = symbols(rom)
    dbg = syms["_dbg_frames"]
    pb = PyBoy(rom, window="null")
    pb.set_emulation_speed(0)
    it, prev, held, shots = 0, pb.memory[dbg], None, {}
    for _ in range(5000):                              # safety bound
        want = next((b for lo, hi, b in HOLDS if lo <= it < hi), None)
        if want != held:
            if held: pb.button_release(held)
            if want: pb.button_press(want)
            held = want
        pb.tick()
        n = pb.memory[dbg]                             # 8-bit iteration counter, wraps at 256
        it, prev = it + ((n - prev) % 256), n
        if it in MARKS and it not in shots:
            shots[it] = pb.screen.image.convert("L").copy()
        if it >= max(MARKS):
            break
    pb.stop(save=False)
    return shots

a, b = run(sys.argv[1]), run(sys.argv[2])
S = 2
sheet = Image.new("L", (160 * S * 3 + 20, (144 * S + 6) * len(MARKS)), 60)
tot = worst = 0
for r, k in enumerate(MARKS):
    d = ImageChops.difference(a[k], b[k])
    nd = sum(1 for v in d.tobytes() if v)
    tot, worst = tot + nd, max(worst, nd)
    print(f"iteration {k:3d}: {nd:4d} of 23040 pixels differ ({100 * nd / 23040:.1f}%)")
    for c, im in enumerate((a[k], b[k], d.point(lambda v: 255 if v else 0))):
        sheet.paste(im.resize((160 * S, 144 * S), Image.NEAREST), (c * (160 * S + 10), r * (144 * S + 6)))
print(f"overall {100 * tot / (23040 * len(MARKS)):.2f}% of pixels differ, worst frame {100 * worst / 23040:.1f}%")
sheet.save(sys.argv[3])
