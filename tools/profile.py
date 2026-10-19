#!/usr/bin/env python3
"""
Run a PROFILE/SELFTEST ROM headless in PyBoy and report the dbg_* / st_* counters.
Usage: profile.py <rom.gb> [screenshot.png]
Symbol addresses come from the .noi file lcc writes next to the ROM (-Wl-j).
"""
import re
import sys
from pathlib import Path
from pyboy import PyBoy

rom = Path(sys.argv[1])
shot = sys.argv[2] if len(sys.argv) > 2 else None

syms = {}
for line in rom.with_suffix(".noi").read_text().splitlines():
    m = re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", line)
    if m:
        syms[m.group(1)] = int(m.group(2), 16)

def rd(pb, name):
    return pb.memory[syms[name]] if name in syms else None

def has(*names):
    return all(n in syms for n in names)

pb = PyBoy(str(rom), window="null")
pb.set_emulation_speed(0)

def run(n):
    for _ in range(n):
        pb.tick()

def report(tag):
    build = (f"build: last {rd(pb,'_dbg_build_lines')} lines, worst {rd(pb,'_dbg_build_max')} | "
             if has('_dbg_build_lines', '_dbg_build_max') else "")
    loop = (f"main loop: last {rd(pb,'_dbg_loop_lines')} lines, worst {rd(pb,'_dbg_loop_max')} "
            f"(frame = 154 lines, 114 M-cycles each) | "
            if has('_dbg_loop_lines', '_dbg_loop_max') else "")
    print(f"  [{tag}] {build}{loop}iterations {rd(pb,'_dbg_frames')}")

print(rom.name)
run(180)        # PyBoy plays its boot-ROM animation for the first ~80 frames
fails = []
if has("_st_scx_maxdiff", "_st_bgp_bad"):
    scx, bgp = rd(pb, "_st_scx_maxdiff"), rd(pb, "_st_bgp_bad")
    print(f"  selftest: max SCX diff asm-vs-C = {scx} px, "
          f"BGP mismatches = {bgp} (of 240)")
    if scx > 2:
        fails.append(f"SCX diff {scx} > 2 px")
    if bgp != 0:
        fails.append(f"BGP mismatches {bgp} != 0")
report("idle   ")
pb.button_press("right"); pb.button_press("up")
run(120)
report("steer  ")
pb.button_release("right"); pb.button_release("up")
run(120)
report("curving")
loop_max = rd(pb, "_dbg_loop_max")
if shot:
    pb.screen.image.save(shot)
pb.stop(save=False)
if loop_max is not None and loop_max > 140:
    fails.append(f"loop max {loop_max} > 140 lines")
if fails:
    print(f"RESULT: FAIL ({'; '.join(fails)})")
    sys.exit(1)
print("RESULT: PASS")
