#!/usr/bin/env python3
"""
Equivalence check for sprite-engine rewrites: run a reference ROM and a new ROM (both PROFILE builds)
with the same bot, keyed to the game_update call count, and compare at every call
    shadow OAM (160 bytes), rival state (rv[]), and the game globals.
Stops with a mismatch report at the first difference.

  oamcmp.py <ref.gb> <new.gb> [calls]     (a --perturb flag corrupts the new ROM's OAM x on call 500 to prove the check can fail)
"""
import re
import sys
from pathlib import Path
from pyboy import PyBoy


def load(path):
    rom = Path(path)
    syms = {}
    for line in rom.with_suffix(".noi").read_text().splitlines():
        m = re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", line)
        if m:
            syms[m.group(1)] = int(m.group(2), 16)
    return rom, syms


def s16(v):
    return ((v + 0x8000) & 0xFFFF) - 0x8000


def trace(path, n, perturb=False):
    rom, syms = load(path)
    pb = PyBoy(str(rom), window="null")
    pb.set_emulation_speed(0)
    mem = pb.memory
    out = []
    plan = [("centre", 1500), ("right_grass", 150), ("centre", 1500), ("weave", 600), ("coast_centre", 200),
            ("centre", 1500), ("left_grass", 150), ("down_centre", 300), ("centre", 3000)]
    sched = []
    for mode, k in plan:
        sched += [mode] * k

    KEY = {"right": 1, "left": 2, "up": 4, "down": 8, "a": 0x10, "b": 0x20}

    def bot(mode):
        cam = s16(mem[syms["_g_cam"]] | (mem[syms["_g_cam"] + 1] << 8)) >> 8
        want = set()
        steer = lambda: {"left"} if cam > 6 else ({"right"} if cam < -6 else set())
        if mode == "centre":
            want |= {"a"} | steer()
        elif mode == "right_grass":
            want |= {"a", "right"}
        elif mode == "left_grass":
            want |= {"up", "left"}
        elif mode == "weave":
            want |= {"a", "left" if ((mem[syms["_g_zacc"] + 1]) >> 1) & 1 else "right"}
        elif mode == "coast_centre":
            want |= steer()
        elif mode == "down_centre":
            want |= {"down" if mem[syms["_g_speed"]] > 30 else "up"} | steer()
        return sum(KEY[k] for k in want)

    def on_update(_):
        # decide the keys here, from the state at this exact point, and hand them to game_update in A:
        # independent of where the emulator's frame boundary falls relative to the main loop
        k = len(out)
        pb.register_file.A = bot(sched[min(k, len(sched) - 1)])
        rv = bytes(mem[syms["_rv"] + i] for i in range(18))
        oam = bytes(mem[0xC000 + i] for i in range(160))
        if perturb and k == 500:
            oam = bytes([oam[0] ^ 1]) + oam[1:]
        glob = tuple(mem[syms[g]] for g in ("_g_speed", "_g_invuln", "_g_hits", "_g_lap"))
        out.append((oam, rv, glob))

    pb.hook_register(0, syms["_game_update"], on_update, None)
    for _ in range(60):
        pb.tick()
    while len(out) < n:
        pb.tick()
    pb.stop(save=False)
    return out[:n]


n = int(next((a for a in sys.argv[3:] if a.isdigit()), 8000))
a = trace(sys.argv[1], n)
b = trace(sys.argv[2], n, perturb="--perturb" in sys.argv)
bad = None
for i, (x, y) in enumerate(zip(a, b)):
    if x != y:
        bad = i
        break
hits = sum(1 for i in range(1, n) if a[i][2][2] != a[i - 1][2][2])
print(f"{n} game_update calls compared (OAM 160 B + rival state + speed/invuln/hits/lap); {hits} collisions in the run")
if bad is None:
    print("RESULT: IDENTICAL")
else:
    x, y = a[bad], b[bad]
    what = [nm for nm, p, q in zip(("OAM", "rv", "globals"), x, y) if p != q]
    print(f"RESULT: DIFFERENT at call {bad}: {what}")
    if "OAM" in what:
        d = [i for i in range(160) if x[0][i] != y[0][i]][:8]
        print("  first OAM bytes differing:", [(i // 4, ('y', 'x', 'tile', 'prop')[i % 4], x[0][i], y[0][i]) for i in d])
    if "rv" in what:
        print("  rv ref", list(x[1]), "\n  rv new", list(y[1]))
sys.exit(0 if bad is None else 1)
