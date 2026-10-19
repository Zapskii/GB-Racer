#!/usr/bin/env python3
"""
Difficulty check (build/prof_race.gb, AUTOSTART race).

The difficulty level must change the car's handling, not just the AI.  The centrifugal
push is scaled by the level: EASY 0.75x, NORMAL 1x, HARD 1.25x.

At each game_update entry the hook pins state/speed/curve/offset and the difficulty,
injects no keys, and reads g_cam on the following entry (the result of the previous
game_update).  game_update eases g_curve from 30 towards the segment's 0, so the push
uses ~28; that is identical for all three runs.

  levelcheck.py <prof_race.gb>
"""
import re
import sys
from pathlib import Path
from pyboy import PyBoy

rom = Path(sys.argv[1])
syms = {m.group(1): int(m.group(2), 16)
        for l in rom.with_suffix(".noi").read_text().splitlines()
        if (m := re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", l))}

RACE = 2


def run(level):
    pb = PyBoy(str(rom), window="null")
    pb.set_emulation_speed(0)
    mem = pb.memory

    def wr16(name, v):
        mem[syms[name]] = v & 0xFF
        mem[syms[name] + 1] = (v >> 8) & 0xFF

    S = {"phase": "arm", "cam": None}

    def on_update(_):
        if S["phase"] == "arm":
            mem[syms["_g_state"]] = RACE
            mem[syms["_g_diff"]] = 0
            mem[syms["_g_offroad"]] = 0
            mem[syms["_g_level"]] = level
            wr16("_g_cam", 0)
            wr16("_g_curve", 30)
            wr16("_g_vcurve", 30)
            wr16("_g_speed", 60)
            S["phase"] = "measure"
        elif S["phase"] == "measure":
            c = mem[syms["_g_cam"]] | (mem[syms["_g_cam"] + 1] << 8)
            S["cam"] = c - 0x10000 if c > 0x7FFF else c
            S["phase"] = "done"
        pb.register_file.A = 0

    pb.hook_register(0, syms["_game_update"], on_update, None)
    for _ in range(2000):
        pb.tick()
        if S["phase"] == "done":
            break
    pb.stop(save=False)
    return S["cam"]


cams = [run(level) for level in (0, 1, 2)]
for level, name in enumerate(("EASY", "NORMAL", "HARD")):
    print(f"{name} (level {level}): g_cam after one game_update = {cams[level]}")
ok = None not in cams and abs(cams[0]) < abs(cams[1]) < abs(cams[2])
print("RESULT:", "PASS (difficulty scales the car's push)" if ok else "FAIL (level does not change the push)")
sys.exit(0 if ok else 1)
