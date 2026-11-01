#!/usr/bin/env python3
"""
Flicker/collision check (build/prof_race.gb).

When both rivals and the player share a 16-line band the per-line OAM budget forces one rival
to be hidden on alternate frames.  A hidden rival must be intangible too: the traffic car
already clears its `foot`, and this check keeps the two racing rivals honest.

The hook parks both rivals at the same depth (foot 121) with lanes -20/+20, freezes the game
in COUNTDOWN so the AI does not move them, and zeroes the camera/curve.  It then watches every
hit and looks up the hit rival's OAM y: y == 0 means the player was hit by an invisible car.

  flickercheck.py <prof_race.gb>
"""
import re
import sys
from pathlib import Path
from pyboy import PyBoy

rom = Path(sys.argv[1])
syms = {m.group(1): int(m.group(2), 16)
        for l in rom.with_suffix(".noi").read_text().splitlines()
        if (m := re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", l))}

pb = PyBoy(str(rom), window="null")
pb.set_emulation_speed(0)
mem = pb.memory
RV = syms["_rv"]
OAM = syms["_shadow_OAM"]
COUNTDOWN = 1


def rd16(a):
    return mem[a] | (mem[a + 1] << 8)


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def wr16(name, v):
    mem[syms[name]] = v & 0xFF
    mem[syms[name] + 1] = (v >> 8) & 0xFF


def rival(i, off):
    return RV + 9 * i + off


def oam_y(i):
    return mem[OAM + 4 * mem[rival(i, 4)]]


S = {"hits": 0, "hidden_hit": 0, "hidden_seen": 0, "bad": []}


def on_update(_):
    # COUNTDOWN freezes ai_step, so the geometry below stays put
    mem[syms["_g_state"]] = COUNTDOWN
    wr16("_g_speed", 0)
    wr16("_g_cam", 0)
    wr16("_g_curve", 0)
    mem[syms["_g_vcurve"]] = 0                 # int8
    mem[syms["_g_offroad"]] = 0
    mem[syms["_g_invuln"]] = 0
    for i, lane in ((0, -20), (1, 20), (2, 0)):
        base = RV + 9 * i
        z = 862 if i < 2 else 5000          # traffic: in range but beyond the fog, so hidden and not respawned
        mem[base] = z & 0xFF
        mem[base + 1] = (z >> 8) & 0xFF
        mem[base + 2] = lane & 0xFF
        mem[base + 3] = 0
    pb.register_file.A = 0


def on_hit(_):
    dx = s16(rd16(syms["_g_hit_dx"]))
    S["hits"] += 1
    for i in (0, 1):
        cx = s16(rd16(rival(i, 7)))
        if cx - 80 == dx:
            y = oam_y(i)
            if y == 0:
                S["hidden_hit"] += 1
                if len(S["bad"]) < 4:
                    S["bad"].append(f"hit rival {i} while hidden (dx={dx}, cx={cx})")
            return
    S["bad"].append(f"hit dx={dx} did not match a rival's cx")


pb.hook_register(0, syms["_game_update"], on_update, None)
pb.hook_register(0, syms["_game_hit"], on_hit, None)

for _ in range(600):
    pb.tick()
    if oam_y(0) == 0 or oam_y(1) == 0:
        S["hidden_seen"] += 1
    if S["hits"] >= 8:
        break
pb.stop(save=False)

print(f"hits: {S['hits']}, frames with a hidden rival: {S['hidden_seen']}, "
      f"hits on a hidden rival: {S['hidden_hit']}")
for b in S["bad"]:
    print("  FAIL", b)
ok = S["hits"] > 0 and S["hidden_seen"] > 0 and S["hidden_hit"] == 0
print("RESULT:", "PASS" if ok else "FAIL (invisible rival still collides, or geometry not exercised)")
sys.exit(0 if ok else 1)
