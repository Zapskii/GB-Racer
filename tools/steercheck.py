#!/usr/bin/env python3
"""
Steering-ramp grace check (build/prof_race.gb, AUTOSTART race).

Holding a direction for half a second ramps the turn rate up by 50%.  A short release
or direction-neutral gap must not throw that away; the old code reset the ramp the
moment the key was released.

At each game_update entry the hook records the previous frame's g_cam (the applied
steering), then zeroes cam/speed/curve/offset and the race state, and injects:
  40 frames RIGHT, 2 frames neutral, then RIGHT.
The re-press frame must apply a ramped turn (>500, about 592); the old instant-reset
code applies 400.  The last frame before the gap must also be ramped.

  steercheck.py <prof_race.gb>
"""
import re
import sys
from pathlib import Path
from pyboy import PyBoy

rom = Path(sys.argv[1])
syms = {m.group(1): int(m.group(2), 16)
        for l in rom.with_suffix(".noi").read_text().splitlines()
        if (m := re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", l))}

RACE, RIGHT = 2, 1
HOLD, GAP = 40, 2

pb = PyBoy(str(rom), window="null")
pb.set_emulation_speed(0)
mem = pb.memory


def wr16(name, v):
    mem[syms[name]] = v & 0xFF
    mem[syms[name] + 1] = (v >> 8) & 0xFF


def rds(name):
    v = mem[syms[name]] | (mem[syms[name] + 1] << 8)
    return v - 0x10000 if v > 0x7FFF else v


S = {"n": 0, "before": None, "gap": [], "after": None}


def on_update(_):
    cam = rds("_g_cam")                         # the previous frame's applied steering
    n = S["n"] = S["n"] + 1
    if n == HOLD + 1:
        S["before"] = cam
    elif n in (HOLD + 2, HOLD + 3):
        S["gap"].append(cam)
    elif n == HOLD + GAP + 2:
        S["after"] = cam
    wr16("_g_cam", 0)
    wr16("_g_speed", 60)
    wr16("_g_curve", 0)
    wr16("_g_vcurve", 0)
    mem[syms["_g_offroad"]] = 0
    mem[syms["_g_state"]] = RACE
    pb.register_file.A = RIGHT if (n <= HOLD or n >= HOLD + GAP + 1) else 0


pb.hook_register(0, syms["_game_update"], on_update, None)
for _ in range(2000):
    pb.tick()
    if S["after"] is not None:
        break
pb.stop(save=False)

print(f"steering delta on the last frame before the gap: {S['before']}")
print(f"steering deltas during the {GAP}-frame neutral gap: {S['gap']}")
print(f"steering delta on the re-press frame:             {S['after']}")
ok = S["before"] is not None and S["after"] is not None and S["before"] > 500 and S["after"] > 500
print("RESULT:", "PASS (the ramp survives a short release)" if ok else "FAIL (the ramp resets on release)")
sys.exit(0 if ok else 1)
