#!/usr/bin/env python3
"""
Phase check (build/prof_race.gb): the road the player SEES must be the road the car FEELS.

The ROM applies, per frame:   cam_next = cam + lat - push
so the push can be read back from the ROM's own state without knowing its internals.
g_vcurve says which way the drawn road bends; a right-hand bend (vcurve > 0) must push
the car to the LEFT (push > 0, cam decreasing).

While the picture and the push disagree, the player steers into the bend they can see
while the car is flung the same way as their steering: the car is thrown off the OUTSIDE
of the bend it is really in.  At a "sharp left then sharp right" corner that reads as the
car running straight off the road instead of turning into the second bend.

It also drives each track with a bot that only uses what the player can SEE (the drawn
curve, the car's offset and the speed) and reports the grass time: a driver who can only
see the picture must be able to keep the car on the road.

  phasecheck.py build/prof_race.gb
"""
import re
import sys
from pathlib import Path
from pyboy import PyBoy

rom = Path(sys.argv[1])
syms = {m.group(1): int(m.group(2), 16)
        for l in rom.with_suffix(".noi").read_text().splitlines()
        if (m := re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", l))}

A, B, LEFT, RIGHT = 0x10, 0x20, 2, 1
SEGLEN = [4000, 4800, 5600]
TRACKS = ("OVAL", "CANYON", "ALPINE")
s16 = lambda v: ((v + 0x8000) & 0xFFFF) - 0x8000


def push_of(curve, speed):
    """the ROM's centrifugal push for a curvature and a speed, 1/256 px per frame"""
    p = (curve * ((min(speed, 80) ** 3) >> 11)) >> 3
    return p - (p >> 3)


def drive(track):
    """drive a lap; return (frames, grass frames, worst |cam|, frames with the push
    against the drawn bend)"""
    pb = PyBoy(str(rom), window="null")
    pb.set_emulation_speed(0)
    mem = pb.memory
    rd8 = lambda n: mem[syms[n]]
    rd16 = lambda n: mem[syms[n]] | (mem[syms[n] + 1] << 8)
    rds = lambda n: s16(rd16(n))

    S = dict(calls=0, zacc=0, dist=0, prev=None, prev_cam=None, hits=0,
             n=0, bad=0, off=0, worst=0, grass=0)

    def on_update(_):
        if S["calls"] == 0:
            mem[syms["_g_track"]] = track
            mem[syms["_g_laps_total"]] = 99
        S["calls"] += 1
        z = rd16("_g_zacc")
        if S["prev"] is not None:
            S["dist"] += (z - S["prev"]) & 0xFFFF
        S["prev"] = z

        cam = rds("_g_cam"); lat = rds("_g_lat")
        vcurve = rds("_g_vcurve"); speed = rds("_g_speed")
        off = rd8("_g_offroad"); hits = rd8("_g_hits")

        # The state read here is the one the ROM's LAST game_update left behind:
        # cam_N and lat_N.  The push that update applied is
        #     cam_N = cam_{N-1} + lat_N - push_N
        # so the push is recoverable from this frame's cam and lat and the PREVIOUS
        # frame's cam.  (Pairing this frame's lat with this frame's cam would measure
        # the tyres' grip step instead.)
        if S["prev_cam"] is not None and hits == S["hits"]:
            push = S["prev_cam"] + lat - cam
            S["n"] += 1
            S["off"] += off
            S["grass"] += off
            S["worst"] = max(S["worst"], abs(cam))
            if abs(vcurve) > 15 and abs(push) > 60 and (push > 0) != (vcurve > 0):
                S["bad"] += 1
        S["prev_cam"] = cam
        S["hits"] = hits

        # a driver that only uses the picture: the sideways rate the car needs is the
        # one that cancels the push the drawn bend implies, plus a pull to the middle
        want = push_of(vcurve, speed) - (cam >> 4)
        k = A
        if lat < want - 24:
            k |= RIGHT
        elif lat > want + 24:
            k |= LEFT
        if abs(push_of(vcurve, speed)) > (160 + 4 * speed) * 1.4:
            k = (k & ~A) | B                        # too fast for the bend: brake
        pb.register_file.A = k

    pb.hook_register(0, syms["_game_update"], on_update, None)
    # one lap of depth units, but bounded by frames too: a car that ends up on the grass
    # crawls at speed 8 and a lap would take forever
    while S["dist"] < 16 * SEGLEN[track] and S["calls"] < 4000:
        pb.tick()
    pb.stop(save=False)
    return S


ok = True
for t, name in enumerate(TRACKS):
    S = drive(t)
    badpct = 100.0 * S["bad"] / max(1, S["n"])
    grasspct = 100.0 * S["grass"] / max(1, S["n"])
    print(f"{name:8} frames {S['n']:5}  push against the drawn bend {S['bad']:4} ({badpct:4.1f}%)  "
          f"on grass {grasspct:4.1f}%  worst |cam| {S['worst'] / 256:5.1f}px")
    ok &= S["bad"] <= max(4, S["n"] * 0.02)        # the picture and the push agree
    ok &= S["grass"] <= S["n"] * 0.02              # a picture-only driver stays on the road

print("RESULT:", "PASS (the picture and the push are in phase)" if ok else "FAIL (the car is thrown off the bend it is shown)")
sys.exit(0 if ok else 1)
