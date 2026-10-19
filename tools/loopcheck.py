#!/usr/bin/env python3
"""Main-loop headroom (PROFILE build): per-iteration length in scanlines over a long varied run, init excluded.
   Prints max / mean / 99th percentile and the number of iterations over LIMIT lines (a frame is 154)."""
import re, sys
from pathlib import Path
from pyboy import PyBoy
rom = Path(sys.argv[1]); limit = int(sys.argv[2]) if len(sys.argv) > 2 else 140
syms = {}
for l in rom.with_suffix(".noi").read_text().splitlines():
    m = re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", l)
    if m: syms[m.group(1)] = int(m.group(2), 16)
pb = PyBoy(str(rom), window="null"); pb.set_emulation_speed(0)
mem = pb.memory
vals = []; n = [0]
def on_update(_):
    n[0] += 1
    if n[0] > 60: vals.append(mem[syms["_dbg_loop_lines"]])
    k = 0x10
    c = n[0]
    if (c // 90) % 3 == 1: k |= 1
    if (c // 90) % 3 == 2: k |= 2
    pb.register_file.A = k
pb.hook_register(0, syms["_game_update"], on_update, None)
while n[0] < 12000: pb.tick()
vals.sort()
print(f"{len(vals)} iterations: max {vals[-1]}, mean {sum(vals)/len(vals):.1f}, p99 {vals[int(len(vals)*0.99)]}, over {limit} lines: {sum(1 for v in vals if v > limit)}")
