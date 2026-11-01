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

The push eases from one bend to the next (CURVE_EASE per frame), so for the few frames after an S-bend
flips direction it still points the old way; those frames are skipped, and only after them must the push
and the picture agree.

LOOK-AHEAD: the road is drawn as two bends, the current one up to the line where the next
segment starts (g_split chunks from the bottom) and the next one beyond it.  That line must
only come DOWN the screen while the car is in a segment, and must have reached the car
(g_split <= 1) on the frame the car starts feeling the new bend (g_vcurve changes), so the
bend the player feels is always one they watched arrive.

It also drives each track with a bot that only uses what the player can SEE (the drawn
curve, the car's offset and the speed) and reports the grass time: a driver who can only
see the picture must be able to keep the car on the road.

  phasecheck.py build/prof_race.gb
"""
import re
import sys
from pathlib import Path
from pyboy import PyBoy


def cube_q(speed, cap):
    """the ROM's speed term: speed^2/32, times speed /64, less an eighth (8-bit steps, as game.c)"""
    s = min(speed, cap)
    q = ((s * s) >> 5) * s >> 6
    return q - (q >> 3)

rom = Path(sys.argv[1])
syms = {m.group(1): int(m.group(2), 16)
        for l in rom.with_suffix(".noi").read_text().splitlines()
        if (m := re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", l))}

A, B, LEFT, RIGHT = 0x10, 0x20, 2, 1
CURVE_EASE = 8      # game.h: the push eases from the old bend to the new one at this rate per frame
SEGLEN = [4000, 4800, 5600]
TRACKS = ("OVAL", "CANYON", "ALPINE")
s16 = lambda v: ((v + 0x8000) & 0xFFFF) - 0x8000


def push_of(curve, speed):
    """the ROM's centrifugal push for a curvature and a speed, 1/256 px per frame"""
    return (curve * cube_q(speed, 80)) >> 3


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
             n=0, bad=0, off=0, worst=0, grass=0,
             vc=None, split=None, arrive_bad=0, rise=0, arrivals=0, easing=0)

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
        vcurve = (rd8("_g_vcurve") ^ 0x80) - 0x80; speed = rds("_g_speed")
        off = rd8("_g_offroad"); hits = rd8("_g_hits")
        split = rd8("_g_split")
        if S["vc"] is not None:
            if vcurve != S["vc"]:                      # a new segment: its bend must have reached the car
                S["arrivals"] += 1
                # the push sweeps from the old bend to the new one over |change| / CURVE_EASE frames
                # (+2: the state read here lags the ROM's update by one frame); only after that must they agree
                S["easing"] = -(-abs(vcurve - S["vc"]) // CURVE_EASE) + 2
                if S["split"] > 1:
                    S["arrive_bad"] += 1
            elif split > S["split"] > 1:               # within a segment the split line only comes down
                                                       # (from <= 1 it wraps: the next segment has begun)
                S["rise"] += 1
        S["vc"], S["split"] = vcurve, split

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
            if S["easing"]:
                S["easing"] -= 1
            elif abs(vcurve) > 15 and abs(push) > 60 and (push > 0) != (vcurve > 0):
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
    print(f"{'':8} look-ahead: {S['arrivals']} bend changes, {S['arrive_bad']} felt before they reached the car, "
          f"{S['rise']} frames the split line went back up")
    ok &= S["arrivals"] > 0 and S["arrive_bad"] == 0 and S["rise"] == 0

print("RESULT:", "PASS (the picture and the push are in phase)" if ok else "FAIL (the car is thrown off the bend it is shown)")
sys.exit(0 if ok else 1)
