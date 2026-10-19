#!/usr/bin/env python3
"""
End-to-end equivalence check: run the asm-builder ROM and the C-builder ROM
until each has completed the same main-loop iteration, then compare the road
SCX table entries the two builders produced from identical inputs.  (BGP is no longer in
the table page for the asm ROM - the stripes come from ROM rows - so stripes are checked by
modelcheck.py (rows) and visual_cmp.py (what actually reaches the screen).)
Usage: crosscheck.py <prof_asm.gb> <prof_c.gb>
"""
import re
import sys
from pathlib import Path
from pyboy import PyBoy

IDX0, ROAD_LINES = 47, 80

def load(rom):
    rom = Path(rom)
    syms = {}
    for line in rom.with_suffix(".noi").read_text().splitlines():
        m = re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", line)
        if m:
            syms[m.group(1)] = int(m.group(2), 16)
    pb = PyBoy(str(rom), window="null")
    pb.set_emulation_speed(0)
    pb.button_press("a"); pb.button_press("right")      # drive: with no input the car idles at speed 0
    return pb, syms

def snapshot(rom, n):
    """Tick until dbg_frames == n exactly; return scx[80] of the buffer just built."""
    pb, s = load(rom)
    for _ in range(2000):
        pb.tick()
        if pb.memory[s["_dbg_frames"]] == n:
            break
    else:
        pb.stop(save=False)
        return None
    page = 0xD2 if n % 2 else 0xD0          # build #1 goes to buffer 1, #2 to buffer 0, ...
    scx = [pb.memory[(page << 8) + IDX0 + y] for y in range(ROAD_LINES)]
    pb.stop(save=False)
    return scx

worst_scx, compared = 0, 0
snapshots = (20, 45, 70, 95, 120, 150, 200)
for n in snapshots:
    a = snapshot(sys.argv[1], n)
    c = snapshot(sys.argv[2], n)
    if a is None or c is None:
        print(f"iteration {n}: could not stop exactly, skipped")
        continue
    d = max(abs(((x - y + 128) & 255) - 128) for x, y in zip(a, c))
    spread = max(a) - min(a) if max(a) - min(a) < 128 else 255
    print(f"iteration {n:3d}: max SCX diff {d} px   (SCX spread across road {spread} px)")
    worst_scx, compared = max(worst_scx, d), compared + 1
print(f"compared {compared} snapshots: worst SCX diff {worst_scx} px")

fails = []
if compared != len(snapshots):
    fails.append(f"compared {compared}/{len(snapshots)} snapshots")
if worst_scx > 2:
    fails.append(f"worst SCX diff {worst_scx} > 2 px")
if fails:
    print(f"RESULT: FAIL ({'; '.join(fails)})")
    sys.exit(1)
print("RESULT: PASS")
