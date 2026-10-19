#!/usr/bin/env python3
"""
Brake-priority check (build/prof_race.gb, AUTOSTART race).

Holding the gas and the brake together must slow the car.  The speed block used to be an
`else if` chain with the gas first, so B/DOWN was ignored while A/UP was held: you could not
slow for a bend without releasing the throttle.

The hook pins cam/curve/offroad to zero so the corner push cannot affect the measurement.

  brakecheck.py <prof_race.gb>
"""
import re
import sys
from pathlib import Path
from pyboy import PyBoy

rom = Path(sys.argv[1])
syms = {m.group(1): int(m.group(2), 16)
        for l in rom.with_suffix(".noi").read_text().splitlines()
        if (m := re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", l))}

GAS, BRAKE = 0x10, 0x20
ACCEL_FRAMES, BRAKE_FRAMES = 200, 20

pb = PyBoy(str(rom), window="null")
pb.set_emulation_speed(0)
mem = pb.memory


def wr16(name, v):
    mem[syms[name]] = v & 0xFF
    mem[syms[name] + 1] = (v >> 8) & 0xFF


S = {"phase": "accel", "n": 0, "v0": None, "v1": None}


def on_update(_):
    wr16("_g_cam", 0)
    wr16("_g_curve", 0)
    wr16("_g_vcurve", 0)
    mem[syms["_g_offroad"]] = 0
    S["n"] += 1
    if S["phase"] == "accel":
        pb.register_file.A = GAS
        if S["n"] >= ACCEL_FRAMES:
            S["v0"] = mem[syms["_g_speed"]]
            S["phase"], S["n"] = "both", 0
    elif S["phase"] == "both":
        pb.register_file.A = GAS | BRAKE
        if S["n"] >= BRAKE_FRAMES:
            S["v1"] = mem[syms["_g_speed"]]
            S["phase"] = "done"


pb.hook_register(0, syms["_game_update"], on_update, None)
for _ in range(2000):
    pb.tick()
    if S["phase"] == "done":
        break
pb.stop(save=False)

print(f"speed after {ACCEL_FRAMES} frames of gas:       {S['v0']}")
print(f"speed after {BRAKE_FRAMES} frames of gas+brake: {S['v1']}")
ok = (S["v0"] is not None and S["v1"] is not None
      and S["v0"] >= 75 and S["v1"] <= S["v0"] - 30)
print("RESULT:", "PASS" if ok else "FAIL (brake ignored while the gas is held)")
sys.exit(0 if ok else 1)
