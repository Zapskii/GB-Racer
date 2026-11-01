#!/usr/bin/env python3
"""
How hard is each track for a person?  (prof_race.gb, track poked per run.)

A bot that drives the way a player does, from what is on screen and with a reaction delay:
  * it watches where the car sits on the road and which way it is drifting, as they were
    DELAY frames ago, and steers back towards the middle (a PD rule on the offset; it
    knows nothing of the physics or the track data)
  * full throttle, but it brakes while the sky sign flashes (you are too fast for the bend
    ahead) and when it is well off the road
Reports, per track and reaction delay, the share of frames on the grass, the mean speed, how
many times the car left the road and how long each trip lasted, over two laps, so a handling change can be judged on how it treats a person rather than on
a bot that knows the formulas.

  humancheck.py <prof_race.gb> [delay ...]       (default delays: 0 6 12)
"""
import re
import sys
from pathlib import Path
from pyboy import PyBoy

rom = Path(sys.argv[1])
delays = [int(a) for a in sys.argv[2:]] or [0, 6, 12]
syms = {m.group(1): int(m.group(2), 16)
        for l in rom.with_suffix(".noi").read_text().splitlines()
        if (m := re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", l))}
A, B, LEFT, RIGHT = 0x10, 0x20, 2, 1
s16 = lambda v: ((v + 0x8000) & 0xFFFF) - 0x8000


def drive(track, delay, laps=2):
    pb = PyBoy(str(rom), window="null")
    pb.set_emulation_speed(0)
    mem = pb.memory
    rd8 = lambda n: mem[syms[n]]
    rd16 = lambda n: mem[syms[n]] | (mem[syms[n] + 1] << 8)
    S = dict(calls=0, off=0, spd=0, n=0, hist=[], done=False, trips=0, was_off=0)

    def on_update(_):
        if S["calls"] == 0:
            mem[syms["_g_track"]] = track
            mem[syms["_g_laps_total"]] = 99
        S["calls"] += 1
        if rd8("_g_lap") > laps:
            S["done"] = True
        cam = s16(rd16("_g_cam")) / 256          # px from the road centre (+ = right)
        S["hist"].append((cam, rd8("_g_warn") != 0 and rd8("_g_warn_hot")))   # hot is only shown with a sign
        S["n"] += 1
        o = rd8("_g_offroad")
        S["off"] += o
        S["trips"] += o and not S["was_off"]
        S["was_off"] = o
        S["spd"] += s16(rd16("_g_speed"))
        h = S["hist"]
        if len(h) < delay + 3:
            pb.register_file.A = A
            return
        seen, hot = h[-1 - delay]
        drift = seen - h[-3 - delay][0]           # px per 2 frames, as it looked then
        u = seen + 6 * drift                       # where it is heading
        k = A
        if hot or abs(seen) > 50:
            k = B
        if u > 4:
            k |= LEFT
        elif u < -4:
            k |= RIGHT
        pb.register_file.A = k

    pb.hook_register(0, syms["_game_update"], on_update, None)
    while not S["done"] and S["calls"] < 20000:
        pb.tick()
    pb.stop(save=False)
    return 100.0 * S["off"] / max(1, S["n"]), S["spd"] / max(1, S["n"]), S["trips"], S["off"] / max(1, S["trips"])


print(f"{'track':8}" + "".join(f" | delay {d:2}: grass speed trips frames/trip" for d in delays))
for t, name in enumerate(("OVAL", "CANYON", "ALPINE")):
    row = f"{name:8}"
    for d in delays:
        g, v, n, f = drive(t, d)
        row += f" |          {g:5.1f}% {v:5.1f} {n:5d} {f:8.1f}"
    print(row, flush=True)
