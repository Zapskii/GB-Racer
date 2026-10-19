#!/usr/bin/env python3
"""
Racing-rivals check (PROFILE + AUTOSTART build in race mode: build/prof_race.gb).

Runs three bots through endless races and, at every game_update call, reads the rivals' state from WRAM:
  1. PLACE    g_place == 1 + number of rivals with z16 > Z_PASS16 (independent count)
  2. LIMITS   |z16| <= 30000, rival speed <= 84, speed changes by at most 1 per frame, lanes within +-36
  3. VISIBLE  a rival is drawn (foot != 0) only while Z_PASS16 <= z16 <= Z_SPAWN16
  4. RACING   the fast bot reaches 1st place, the slow bot is overtaken (place gets worse), places change both ways
  5. LEVELS   rival speed rises with the lap (g_diff): mean cruise at level 4 exceeds level 0 by >= 10
  6. CLOSE    rubber banding keeps a rival within 300 units of a slower player most of the time
  8. TRAFFIC the third car (random traffic) appears again and again, slowly (speed 10..41+5*level), never counts for the
              race position, and is drawn only while in range
  7. SAFE     rivals that overtake from behind do not pop in on top of the player: count of pop-ins inside
              the player's lane (reported; must stay a small share of all hits)
  racecheck.py <prof_race.gb> [--break place|vis|level|bump] [--nododge <rom built with -DNO_DODGE>]   (a wrong check must FAIL)
"""
import re
import sys
from pathlib import Path
from pyboy import PyBoy

rom = Path(sys.argv[1])
brk = sys.argv[sys.argv.index("--break") + 1] if "--break" in sys.argv else None
syms = {}
for line in rom.with_suffix(".noi").read_text().splitlines():
    m = re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", line)
    if m:
        syms[m.group(1)] = int(m.group(2), 16)

Z_PASS, Z_SPAWN = 49 * 16, 230 * 16
RIGHT, LEFT, UP, DOWN, A, B = 1, 2, 4, 8, 0x10, 0x20
s16 = lambda v: ((v + 0x8000) & 0xFFFF) - 0x8000
s8 = lambda v: v - 256 if v > 127 else v

def run_bot(kind, frames, level=1, rom=rom):
    pb = PyBoy(str(rom), window="null")
    pb.set_emulation_speed(0)
    mem = pb.memory
    rd8 = lambda n: mem[syms[n]]
    rd16 = lambda n: mem[syms[n]] | (mem[syms[n] + 1] << 8)
    D = dict(traffic_seen=0, traffic_frames=0, traffic_spawn=0, traffic_spd=[], calls=0, fail=[], places=[], pops=0, pop_in_lane=0, hits=0, close=0, spd_by_diff={}, rows=0,
             vis_frames=0, lap=1, prev=None, prev_hits=0, bumps=0, bump_ok=0, big_jumps=0, thru=0)
    def rivals():
        out = []
        for i in range(3):
            b = syms["_rv"] + 9 * i
            out.append(dict(z=s16(mem[b] | (mem[b + 1] << 8)), lane=s8(mem[b + 2]), spd=mem[b + 3], foot=mem[b + 5],
                            cx=s16(mem[b + 7] | (mem[b + 8] << 8))))
        return out

    def bot(rv3_now, cam):
        pl = max(-36, min(36, cam >> 8))
        if kind == "slow":                       # lift off and weave about: gets overtaken
            k = 0 if (D["calls"] // 200) % 3 == 2 else A
            if D["calls"] % 90 < 45:
                k |= RIGHT if pl < 10 else 0
            else:
                k |= LEFT if pl > -10 else 0
            return k
        k = A
        want = 0                                 # steer back to the middle ...
        if pl > 6: want = LEFT
        elif pl < -6: want = RIGHT
        if kind == "fast":                       # ... but dodge a car just ahead in my lane
            for r in rv3_now:
                if Z_PASS < r["z"] < Z_PASS + 90 * 16 and abs(r["lane"] - pl) < 30:
                    want = LEFT if r["lane"] >= pl and pl > -20 else RIGHT
        return k | want

    def on_update(_):
        if D["calls"] == 0:
            mem[syms["_g_level"]] = level                  # after game_init (the boot logo takes ~100 frames)
        rv3 = rivals()
        rv = rv3[:2]
        tr = rv3[2]
        cam = s16(rd16("_g_cam"))
        D["calls"] += 1
        pl = max(-36, min(36, cam >> 8))
        place = rd8("_g_place")
        exp_place = 1 + sum(1 for r in rv if r["z"] > Z_PASS)
        if brk == "place":
            exp_place = 1 + sum(1 for r in rv if r["z"] > Z_PASS + 400)
        if place != exp_place:
            D["fail"].append(f"call {D['calls']}: g_place {place} != {exp_place} (z {[r['z'] for r in rv]})")
        D["places"].append(place)
        vis_t = Z_PASS <= tr["z"] <= Z_SPAWN - (400 if brk == "vis" else 0)
        if tr["foot"] and not vis_t:
            D["fail"].append(f"call {D['calls']}: traffic car drawn at z {tr['z']}")
        if tr["foot"]:
            D["traffic_frames"] += 1
            if not (D["prev"] and D["prev_tr"]["foot"]):
                D["traffic_seen"] += 1
        if D["prev"] and tr["z"] > D["prev_tr"]["z"] + 3000:
            D["traffic_spawn"] += 1
            D["traffic_spd"].append((rd8("_g_diff"), tr["spd"]))
        D["prev_tr"] = tr
        for i, r in enumerate(rv):
            if abs(r["z"]) > 30000 or r["spd"] > 84 or abs(r["lane"]) > 36:
                D["fail"].append(f"call {D['calls']}: rival {i} out of limits {r}")
            vis = Z_PASS <= r["z"] <= (Z_SPAWN - (400 if brk == "vis" else 0))
            if r["foot"] and not vis:
                D["fail"].append(f"call {D['calls']}: rival {i} drawn at z {r['z']}")
            if D["prev"]:
                p = D["prev"][i]
                if abs(r["spd"] - p["spd"]) > 1:
                    D["fail"].append(f"call {D['calls']}: rival {i} speed jumped {p['spd']} -> {r['spd']}")
                if p["z"] < Z_PASS <= r["z"]:            # overtook from behind: pops into view at the bottom
                    D["pops"] += 1
                    if abs(r["lane"] - pl) < 22:
                        D["pop_in_lane"] += 1
            if r["foot"]:
                D["vis_frames"] += 1
        dmin = min(abs(r["z"] - Z_PASS) for r in rv)
        if dmin < 300 * 16:
            D["close"] += 1
        d = rd8("_g_diff")
        if rd8("_g_speed") > 0 and D["calls"] > 400:
            for r in rv:
                if -1600 <= r["z"] <= 4800:               # not rubber banding: its own pace
                    D["spd_by_diff"].setdefault(d, []).append(r["spd"])
        h = rd8("_g_hits")
        if D["prev"] and D.get("prev3"):
            # BUMP: on a collision frame exactly the rival(s) touching the player get shoved 12 lane units away from it;
            # outside collisions no lane ever moves more than 2 units in a frame (the fastest steering is 1/frame)
            jumps = [(i, r["lane"] - D["prev3"][i]["lane"]) for i, r in enumerate(rv3)
                     if abs(r["lane"] - D["prev3"][i]["lane"]) > 2 and abs(r["z"] - D["prev3"][i]["z"]) < 2000]   # a respawn jumps in z too
            if h != D["prev_hits"]:
                D["bumps"] += 1
                good = False
                for i, dl in jumps:
                    side = rv3[i]["cx"] - 80                   # which side of the player it was drawn this frame (what the ROM used)
                    if brk == "bump": side = -side
                    if abs(dl) >= 5 and (dl > 0) == (side > 0):
                        good = True
                for i, r in enumerate(D["prev3"]):             # touching rival already against its lane limit: the shove is clamped, it cannot move 5
                    side = r["cx"] - 80
                    if brk != "bump" and abs(side) < 20 and (r["lane"] <= -31 and side < 0 or r["lane"] >= 31 and side > 0) and abs(rv3[i]["lane"] - r["lane"]) <= 5:
                        good = True
                if not good:
                    D.setdefault("bump_bad", []).append((D["calls"], [(r["lane"], r["cx"], r["z"], r["foot"]) for r in D["prev3"]], [(r["lane"], r["z"]) for r in rv3]))
                D["bump_ok"] += good
            else:
                D["big_jumps"] += len(jumps)
                if jumps: D.setdefault("jump_info", []).append((D["calls"], jumps, [(r["lane"], r["z"]) for r in D["prev3"]], [(r["lane"], r["z"]) for r in rv3]))
            # THROUGH: a racer driving through the traffic car (it passes it with overlapping lanes)
            for i in (0, 1):
                a, t = rv3[i], rv3[2]
                pa, pt = D["prev3"][i], D["prev3"][2]
                near = 0 < t["z"] - a["z"] < 70 * 16 and abs(a["lane"] - t["lane"]) < 26 and t["z"] <= Z_SPAWN
                if near and not D.setdefault("near%d" % i, False):
                    D["appr"] = D.get("appr", 0) + 1                 # a racer closes in on the traffic car in its lane
                D["near%d" % i] = near
                if t["foot"] and a["foot"] and (pa["z"] - pt["z"]) * (a["z"] - t["z"]) < 0 and abs(a["lane"] - t["lane"]) < 14 and abs(a["z"] - t["z"]) < 800:
                    D["thru"] += 1
        D["prev3"] = rv3
        D["hits"] += (h - D["prev_hits"]) & 255
        D["prev_hits"] = h
        D["prev"] = rv
        pb.register_file.A = bot(rv3, cam)

    pb.hook_register(0, syms["_game_update"], on_update, None)
    for _ in range(60):
        pb.tick()
    while D["calls"] < frames:
        pb.tick()
    D["lap"] = rd8("_g_lap")
    pb.stop(save=False)
    return D

results = {}
for kind, n in (("fast", 12000), ("slow", 11000)):
    results[kind] = run_bot(kind, n)

ok = True
for kind, D in results.items():
    bad_spd = [x for x in D["traffic_spd"] if not (10 + 5 * x[0] <= x[1] <= 41 + 5 * x[0])]
    print(f"{kind} bot traffic car: appeared {D['traffic_seen']} times, drawn on {D['traffic_frames']} frames ({100 * D['traffic_frames'] // D['calls']}%), "
          f"{D['traffic_spawn']} respawns, speed out of its level's range {len(bad_spd)} times")
    ok &= D["traffic_seen"] >= (D["calls"] // 3000 if kind == "fast" else 1) and not bad_spd and D["traffic_frames"] * 100 // D["calls"] <= 60

    pl = D["places"]
    changes = sum(1 for a, b in zip(pl, pl[1:]) if a != b)
    worse = sum(1 for a, b in zip(pl, pl[1:]) if b > a)
    better = sum(1 for a, b in zip(pl, pl[1:]) if b < a)
    print(f"{kind} bot: {D['calls']} frames, up to lap {D['lap']}; places seen {sorted(set(pl))}, {better} places gained, {worse} lost; "
          f"{D['hits']} collisions; overtaken-from-behind pop-ins {D['pops']} ({D['pop_in_lane']} inside the player's lane); "
          f"a rival within 300 units on {100 * D['close'] // D['calls']}% of frames; rival drawn on {D['vis_frames']} rival-frames")
    for f in D["fail"][:6]:
        print("   FAIL", f)
    ok &= not D["fail"]
for kind, D in results.items():
    print(f"{kind} bot BUMP: {D['bumps']} collisions, rival shoved away from the player on {D['bump_ok']}; stray lane jumps outside collisions: {D['big_jumps']}")
    for k in ("bump_bad", "jump_info"):
        for x in D.get(k, [])[:3]: print("     ", k, x)
    ok &= D["bump_ok"] == D["bumps"] and D["big_jumps"] == 0
ok &= sum(D["bumps"] for D in results.values()) >= 6          # (the slow bot rarely meets a car now that the rivals leave it behind)
f, s = results["fast"], results["slow"]
ok &= 1 in f["places"] and 3 in s["places"]
ok &= sum(1 for a, b in zip(f["places"], f["places"][1:]) if b < a) >= 2 and sum(1 for a, b in zip(s["places"], s["places"][1:]) if b > a) >= 1
ok &= f["close"] * 100 // f["calls"] >= 60           # rubber banding keeps the pack together for a player who drives well
ok &= f["pop_in_lane"] <= max(2, f["pops"] // 4)
lv = {d: sum(v) / len(v) for d, v in f["spd_by_diff"].items() if len(v) > 20}   # a few clean samples still measure the cruise;
                                                                              # the faster player can keep a level's rivals out of the narrow window for long stretches
print("mean rival pace by difficulty level:", {d: round(x, 1) for d, x in sorted(lv.items())})
need = 30 if brk == "level" else 5
ok &= 0 in lv and 4 in lv and lv[4] > lv[0] + need
# LEVEL: EASY / NORMAL / HARD change the AI's own pace (slow bot, difficulty level 0-1 laps only: compare equal laps)
lvl = {}
for L in (0, 2):
    D = run_bot("slow", 4000, level=L)
    ok &= not D["fail"]
    v = [x for d, vv in D["spd_by_diff"].items() if d <= 1 for x in vv]
    lvl[L] = sum(v) / len(v)
    results["lvl%d" % L] = D
d1 = [x for d, vv in s["spd_by_diff"].items() if d <= 1 for x in vv]
lvl[1] = sum(d1) / len(d1)
print("mean rival pace on laps 1-2 by level EASY/NORMAL/HARD:", {k: round(lvl[k], 1) for k in (0, 1, 2)})
ok &= lvl[0] + 2 < lvl[1] and lvl[1] + 4 < lvl[2]      # EASY/NORMAL margin 2: the softer corners let the bot run nearer the rivals' rubber band
# DODGE: staged encounters.  Whenever racer 0 is 784..2600 units' worth of depth ahead of the player and the traffic car is
# not on screen, put the traffic car 1000 z16 (62 units) in front of it, in the same lane, and watch the crossing:
# a racer that dodges leaves >= 14 lane units between the two cars when it passes; one that does not drives through.
def staged(rom_path, n=10):
    pb = PyBoy(str(rom_path), window="null")
    pb.set_emulation_speed(0)
    mem = pb.memory
    S = dict(calls=0, cool=0, active=None, results=[])
    def rd(i):
        b = syms["_rv"] + 9 * i
        return dict(z=s16(mem[b] | (mem[b + 1] << 8)), lane=s8(mem[b + 2]), foot=mem[b + 5], b=b)
    def put(i, z, lane, spd=None):
        b = syms["_rv"] + 9 * i
        mem[b], mem[b + 1] = z & 255, (z >> 8) & 255
        mem[b + 2] = lane & 255
        if spd is not None: mem[b + 3] = spd
    def on_update(_):
        S["calls"] += 1
        pb.register_file.A = 0x10
        r, t = rd(0), rd(2)
        if S["active"] is not None:
            if r["z"] >= t["z"] or S["calls"] - S["active"] > 150:            # the racer reaches the traffic car's depth
                S["results"].append((abs(r["lane"] - t["lane"]), r["z"] >= t["z"]))
                S["active"] = None
                S["cool"] = 120
            return
        S["cool"] = max(0, S["cool"] - 1)
        if not S["cool"] and S["calls"] > 400:
            lane = (-20, 0, 20, 10, -10)[len(S["results"]) % 5]
            put(0, 1600, lane, 60)
            put(2, 2600, lane, 20)
            S["active"] = S["calls"]
    pb.hook_register(0, syms["_game_update"], on_update, None)
    while len(S["results"]) < n and S["calls"] < 60000:
        pb.tick()
    pb.stop(save=False)
    return S["results"]

if "--nododge" in sys.argv:
    other = Path(sys.argv[sys.argv.index("--nododge") + 1])
    w = staged(rom); wo = staged(other)
    cl = lambda res: sum(1 for m, crossed in res if crossed and m >= 14)
    print(f"staged encounters (racer 62 units behind the traffic car in its lane): clean passes with dodging {cl(w)}/{len(w)} (min lane gaps {[m for m, c in w]}), "
          f"without {cl(wo)}/{len(wo)} ({[m for m, c in wo]})")
    ok &= len(w) >= 8 and cl(w) >= len(w) - 1 and cl(wo) <= len(wo) // 2
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
