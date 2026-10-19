#!/usr/bin/env python3
"""
Corner warning check (prof_race.gb: new physics + warning, track poked per run).

An independent Python model of the warning logic is run beside the ROM, frame by frame, and compared:
  * g_vcurve (the curvature that is drawn) - leads g_curve: the next segment's value once it is within 48 frames of driving, and
    stays there until you reach it, whatever the speed does (no "unwinding" when you brake)
  * g_warn / g_warn_hot - chevron count and direction of the next bend if it is >= 40 sharp, "hot" when you are too fast for it
  * the sky sign in OAM slots 20..22: y, x (centred on screen x = 80), tile ('<' or '>'), flashing 12 frames on / off while hot
Then it reports, for every bend on a flat-out lap, how many frames of warning the driver got before the push started, and
the same for a bot that brakes as soon as the sign flashes (its road must not unwind).

  warncheck.py build/prof_race.gb [--break nolead|nohyst|noflash|offcentre|nodir]
A --break option puts a deliberate fault into the MODEL; the comparison must then FAIL (it proves the check can fail).
"""
import re, sys
from pathlib import Path
from pyboy import PyBoy

rom = Path(sys.argv[1])
brk = sys.argv[sys.argv.index("--break") + 1] if "--break" in sys.argv else None
syms = {}
for l in rom.with_suffix(".noi").read_text().splitlines():
    m = re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", l)
    if m: syms[m.group(1)] = int(m.group(2), 16)

src = Path("src/game.c").read_text()
def table(name):
    body = re.search(name + r"\[N_TRACKS\]\[SEG_COUNT\] = \{(.*?)\n\};", src, re.S).group(1)
    body = re.sub(r"#ifdef CANYON_CLASSIC.*?#else", "", body, flags=re.S).replace("#endif", "")
    body = re.sub(r"/\*.*?\*/", "", body)
    return [[int(x) for x in r.split(",") if x.strip()] for r in re.findall(r"\{([^{}]*)\}", body)]
CURVES = table("track_curve")
SEG = [4000, 4800, 5600]
SPR_SIGN = int(re.search(r"SPR_SIGN\s+(\d+)", Path("src/sprite_data.h").read_text()).group(1))
LEAD = 0 if brk == "nolead" else 48
s16 = lambda v: ((v + 0x8000) & 0xFFFF) - 0x8000
A, B, LEFT, RIGHT = 0x10, 0x20, 2, 1

class Model:
    def __init__(self, track):
        self.t = track; self.seg = 0; self.pos = 0; self.peeked = False; self.v = 0; self.warn = 0; self.hot = 0
    def step(self, speed):
        t = self.t
        self.pos += speed
        if self.pos >= SEG[t]:
            self.pos -= SEG[t]; self.peeked = False; self.seg = (self.seg + 1) % 16
        if brk == "nohyst":
            self.peeked = self.pos + speed * LEAD >= SEG[t]
        elif not self.peeked and self.pos + speed * LEAD >= SEG[t]:
            self.peeked = True
        tg = CURVES[t][(self.seg + 1) % 16 if self.peeked else self.seg]
        self.v += max(-4, min(4, tg - self.v))
        self.warn = 0
        if self.peeked and abs(tg) >= 40:
            n = 1 if abs(tg) < 55 else (2 if abs(tg) < 75 else 3)
            self.hot = int(speed > (72, 62, 52)[n - 1])
            self.warn = n if (tg > 0 or brk == "nodir") else -n
        return tg

def expected_oam(warn, hot, tenths):
    n = abs(warn)
    on = n and (not hot or (tenths & 2 or brk == "noflash"))
    out = []
    for k in range(3):
        if on and k < n:
            x = 88 - 4 * n + 8 * k + (3 if brk == "offcentre" else 0)
            out.append((36, x, SPR_SIGN + (0 if warn < 0 else 2), 0))
        else:
            out.append((0,))
    return out

def drive(track, kind, frames):
    pb = PyBoy(str(rom), window="null"); pb.set_emulation_speed(0)
    mem = pb.memory
    rd8 = lambda n: mem[syms[n]]
    rd16 = lambda n: mem[syms[n]] | (mem[syms[n] + 1] << 8)
    M = Model(track)
    R = dict(n=0, bad_v=0, bad_w=0, bad_oam=0, first_bad="", signs=0, advance=[], unwind=0, braked=0, maxv=0)
    st = dict(hits=0, calls=0, prev_peek=False, peek_start=None, prev_seg=0, brake_hold=0, last_dist=None, seen_corner=set())
    def on_update(_):
        if st["calls"] == 0:
            mem[syms["_g_track"]] = track
            mem[syms["_g_laps_total"]] = 99
        st["calls"] += 1
        n = st["calls"]
        speed = s16(rd16("_g_speed")); cam = s16(rd16("_g_cam"))
        hits = rd8("_g_hits")
        if hits != st["hits"]:                      # a collision halves g_speed AFTER the update that used the full one
            st["hits"] = hits; used = rd8("_g_speed_before_hit")
        else:
            used = speed
        if n >= 2:                                  # state now = after the previous update, which used this speed
            tg = M.step(used)
            R["n"] += 1
            v = s16(rd16("_g_vcurve")); w = rd8("_g_warn"); w = w - 256 if w > 127 else w; hot = rd8("_g_warn_hot")
            bad = []
            if v != M.v: R["bad_v"] += 1; bad.append(f"vcurve rom {v} model {M.v}")
            if w != M.warn or (M.warn and hot != M.hot): R["bad_w"] += 1; bad.append(f"warn rom {w}/{hot} model {M.warn}/{M.hot}")
            oam = [tuple(mem[syms["_shadow_OAM"] + 4 * (20 + k) + j] for j in range(4)) for k in range(3)]
            exp = expected_oam(M.warn, M.hot, rd16("_g_tenths"))
            for o, e in zip(oam, exp):
                if (o[0] == 0) != (e[0] == 0) or (e[0] and o != e):
                    R["bad_oam"] += 1; bad.append(f"oam rom {oam} model {exp}"); break
            if bad and not R["first_bad"]: R["first_bad"] = f"frame {n} track {track}: " + "; ".join(bad)
            if M.warn: R["signs"] += 1
            # the lead: frames from the road starting to bend to the push starting (segment change into a bend)
            if M.peeked and not st["prev_peek"]: st["peek_start"] = n
            if M.seg != st["prev_seg"]:
                nxt = CURVES[track][M.seg]
                if st["peek_start"] is not None and abs(nxt) >= 40 and (track, M.seg) not in st["seen_corner"] and n > 120:
                    st["seen_corner"].add((track, M.seg)); R["advance"].append((M.seg, nxt, n - st["peek_start"], speed))
                st["peek_start"] = None
            st["prev_peek"] = M.peeked; st["prev_seg"] = M.seg
            if M.peeked:                            # the picture must only move towards the target, never back
                d = abs(tg - v)
                if st["last_dist"] is not None and d > st["last_dist"]: R["unwind"] += 1
                st["last_dist"] = d
            else:
                st["last_dist"] = None
        k = A
        if kind == "brake" and M.warn and M.hot:     # lifts as soon as the sign flashes, back on the gas once it stops
            k = B; R["braked"] += 1
        want = LEFT if cam > 1500 else (RIGHT if cam < -1500 else 0)
        pb.register_file.A = k | want
    pb.hook_register(0, syms["_game_update"], on_update, None)
    while st["calls"] < frames: pb.tick()
    pb.stop(save=False)
    return R

ok = True
tot = dict(n=0, bad=0, signs=0)
for t, name in enumerate(("OVAL", "CANYON", "ALPINE")):
    for kind in ("flat", "brake"):
        R = drive(t, kind, 2600 if t == 0 else 4200)
        bad = R["bad_v"] + R["bad_w"] + R["bad_oam"]
        tot["n"] += R["n"]; tot["bad"] += bad; tot["signs"] += R["signs"]
        adv = R["advance"]
        line = f"{name:7} {kind:5} frames {R['n']:5}  mismatches {bad:4} (vcurve {R['bad_v']}, warn {R['bad_w']}, sign OAM {R['bad_oam']})  sign frames {R['signs']:4}"
        if kind == "brake": line += f"  braking frames {R['braked']:4}  unwinds {R['unwind']}"
        print(line)
        if adv and kind == "flat":
            print("          bends:", ", ".join(f"seg{s}({c:+d}) {f}f@{sp}" for s, c, f, sp in adv))
            R["minadv"] = min(f for _, _, f, _ in adv)
            ok &= R["minadv"] >= 40
        if R["first_bad"] and not brk: print("   first mismatch:", R["first_bad"])
        if kind == "brake" and brk is None:
            ok &= R["unwind"] == 0
            if t > 0: ok &= R["braked"] > 0
        if t == 0 and brk is None: ok &= R["signs"] == 0           # OVAL has no bend sharp enough for a sign
        if t > 0 and brk is None: ok &= R["signs"] > 100
        if brk is None: ok &= bad == 0
if brk is not None:
    print(f"RESULT: {'FAIL (as it must: the deliberate fault was detected)' if tot['bad'] else 'PASS (UNEXPECTED: the fault was NOT detected)'}")
    sys.exit(1 if tot["bad"] else 0)
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
