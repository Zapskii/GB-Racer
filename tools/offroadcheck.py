#!/usr/bin/env python3
"""
Off-road push check (build/prof_race.gb, AUTOSTART race).

On the grass the speed cap is 8, so the centrifugal table must be indexed by that cap
rather than SPEED_MAX: otherwise a car put on the grass at speed still gets a big push
for one frame.  The hook starts the frame off road at speed 80 in a curve of 90 and
reads g_cam on the next game_update entry.  Before the fix this was about -2461.

  offroadcheck.py <prof_race.gb>
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
        mem[syms["_g_offroad"]] = 1
        mem[syms["_g_diff"]] = 0
        wr16("_g_speed", 80)
        wr16("_g_curve", 90)
        mem[syms["_g_vcurve"]] = 90                 # int8
        wr16("_g_cam", 0)
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

print(f"g_cam after one game_update off road at speed 80 in a 90 curve: {S['cam']}")
ok = S["cam"] is not None and abs(S["cam"]) < 256
print("RESULT:", "PASS (the off-road push is gone)" if ok else "FAIL (off-road push still moves the car)")
sys.exit(0 if ok else 1)
