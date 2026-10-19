#!/usr/bin/env python3
"""
Does the road demand braking?  (prof_race.gb, track poked per run.)
Two bots drive 3 laps of every track on the first lap's rules (difficulty forced to 0):
  flat    full throttle all the way, steering back to the middle
  lift    same steering, but looks one segment ahead and lifts / brakes when the coming bend would push harder than the steering can hold
Reports lap time, mean speed and the share of frames spent on the grass.  The point of the change: flat-out must lose clearly on
CANYON and ALPINE (slower, and on the grass often), while OVAL stays easy.
  cornercheck.py <prof_race.gb> [--old]   (--old: expects the linear law build; prints the same table for comparison)
"""
import re, sys
from pathlib import Path
from pyboy import PyBoy
rom = Path(sys.argv[1])
syms = {}
for l in rom.with_suffix(".noi").read_text().splitlines():
    m = re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", l)
    if m: syms[m.group(1)] = int(m.group(2), 16)
src = Path("src/game.c").read_text()
def table(name):
    body = re.search(name + r"\[N_TRACKS\]\[SEG_COUNT\] = \{(.*?)\n\};", src, re.S).group(1)
    body = re.sub(r"#ifdef CANYON_CLASSIC.*?#else", "", body, flags=re.S).replace("#endif", "")
    body = re.sub(r"/\*.*?\*/", "", body)
    rows = re.findall(r"\{([^{}]*)\}", body)
    return [[int(x) for x in r.split(",") if x.strip()] for r in rows]
CURVES = table("track_curve")
SEG = [4000, 4800, 5600]
s16 = lambda v: ((v + 0x8000) & 0xFFFF) - 0x8000
A, LEFT, RIGHT, B = 0x10, 2, 1, 0x20
LINEAR = "--old" in sys.argv

def push(curve, speed):
    return (curve * speed) >> 5 if LINEAR else (lambda p: p - (p >> 3))((curve * ((min(speed, 80) ** 3) >> 11)) >> 3)
def steer(speed): return (160 + 4 * speed) * 1.4      # held steering ramps up to +50%: a driver in a bend has ~1.4x

def drive(track, kind, laps=3):
    pb = PyBoy(str(rom), window="null"); pb.set_emulation_speed(0)
    mem = pb.memory
    rd8 = lambda n: mem[syms[n]]
    rd16 = lambda n: mem[syms[n]] | (mem[syms[n] + 1] << 8)
    S = dict(place=0, calls=0, off=0, spd=0, lap_start=0, frames=0, seg=0, segpos=0, done=False)
    def on_update(_):
        if S["calls"] == 0:
            mem[syms["_g_track"]] = track
            mem[syms["_g_laps_total"]] = 99
        S["calls"] += 1
        S["frames"] += 1
        if rd8("_g_lap") > laps: S["done"] = True
        speed = s16(rd16("_g_speed")); cam = s16(rd16("_g_cam"))
        S["place"] += rd8("_g_place")
        S["off"] += rd8("_g_offroad"); S["spd"] += speed
        # position along the track from the player's own distance
        k = A
        want = 0
        if cam > 1500: want = LEFT
        elif cam < -1500: want = RIGHT
        if kind == "lift":
            dist = S["segpos"] + speed
            S["segpos"] = dist % SEG[track]
            S["seg"] = (S["seg"] + dist // SEG[track]) % 16
            c = [CURVES[track][(S["seg"] + j) % 16] for j in (0, 1)]
            worst = max(abs(c[0]), abs(c[1]) if S["segpos"] > SEG[track] * 0.5 else 0)
            vs = 80
            while vs > 20 and push(worst, vs) > 1.5 * steer(vs): vs -= 1    # fastest speed at which the steering still holds the bend
            if speed > vs + 1: k = B
            elif speed > vs - 1: k = 0
        pb.register_file.A = k | want
    pb.hook_register(0, syms["_game_update"], on_update, None)
    while not S["done"] and S["calls"] < 60000: pb.tick()
    pb.stop(save=False)
    return S

print(f"{'track':8} {'bot':5} {'3 laps':>8} {'mean speed':>11} {'on grass':>9} {'mean place':>11}")
res = {}
for t, name in enumerate(("OVAL", "CANYON", "ALPINE")):
    for kind in ("flat", "lift"):
        S = drive(t, kind)
        res[(t, kind)] = S
        print(f"{name:8} {kind:5} {S['frames'] / 60:7.1f}s {S['spd'] / S['frames']:11.1f} {100 * S['off'] / S['frames']:8.1f}% {S['place'] / S['frames']:11.2f}")
ok = True
f, l = res[(1, "flat")], res[(1, "lift")]
ok &= f["off"] / f["frames"] > 0.04 and f["frames"] > l["frames"] * 0.97         # CANYON (middling): flat-out ends on the grass and gains little
f, l = res[(2, "flat")], res[(2, "lift")]
ok &= f["off"] / f["frames"] > 0.08                                             # ALPINE: flat-out ends on the grass ...
ok &= f["frames"] > l["frames"] * 1.05                                          # ... and loses clearly
f, l = res[(0, "flat")], res[(0, "lift")]
ok &= f["off"] / f["frames"] < 0.06                                             # the OVAL stays easy
print("RESULT:", "PASS (flat-out loses on the twisty tracks)" if ok else "FAIL (flat-out is still the best way round)")
sys.exit(0 if ok else 1)
