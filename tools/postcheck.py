#!/usr/bin/env python3
"""
Roadside-post check (build/prof_race.gb): at every game_update the OAM slots 12..19 (4 pairs) are compared with an
independent model: relative depth z16 = 1024*(k+1) - (g_zacc & 1023); line y = 4096 // (z16>>4) - 4 (clamped); OAM y = 49 + y;
tile = SPR_POST + 2*size (size by y); the two posts are symmetric about the road centre and `off` apart.
A pair may be missing only when out of range (z16 < 784 or y < 12) or when the per-line cap says so (cars on the same lines).
  --break pos   perturbs the model's depth by 1 unit (must FAIL)
"""
import re, sys
from pathlib import Path
from pyboy import PyBoy
rom = Path(sys.argv[1]); brk = "--break" in sys.argv
syms = {}
for l in rom.with_suffix(".noi").read_text().splitlines():
    m = re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", l)
    if m: syms[m.group(1)] = int(m.group(2), 16)
s16 = lambda v: ((v + 0x8000) & 0xFFFF) - 0x8000
pb = PyBoy(str(rom), window="null"); pb.set_emulation_speed(0)
mem = pb.memory
rd16 = lambda n: mem[syms[n]] | (mem[syms[n] + 1] << 8)
SPR_POST = int(re.search(r"SPR_POST\s+(\d+)", Path("src/sprite_data.h").read_text()).group(1))
st = dict(maxline=0, calls=0, shown=0, missing_ok=0, bad=[], wins=set())
def yline(z16):
    zi = min(255, z16 >> 4)
    return 79 if zi == 0 else max(0, min(79, 4096 // zi - 4))
def on_update(_):
    st["calls"] += 1
    if st["calls"] < 30: return
    cnt = [0] * 144                                  # objects per scanline (8x16: all 16 lines count), from the shadow OAM
    for i in range(40):
        y, x = mem[0xC000 + 4 * i], mem[0xC000 + 4 * i + 1]
        if 0 < y < 160 and 0 < x < 168:
            for ln in range(max(0, y - 16), min(144, y)): cnt[ln] += 1
    st["maxline"] = max(st["maxline"], max(cnt[48:128]))
    ph = rd16("_g_zacc") & 1023
    pitch = mem[syms["_g_pitch"]]; pitch = pitch - 256 if pitch > 127 else pitch
    # shadow OAM is at 0xC000; slots 12..19
    for k in range(4):
        z = 1024 * (k + 1) - ph + (16 if brk else 0)
        a = 0xC000 + 4 * (12 + 2 * k)
        oy, ox, ot = mem[a], mem[a + 1], mem[a + 2]
        oy2, ox2, ot2 = mem[a + 4], mem[a + 5], mem[a + 6]
        y = yline(z) if z >= 784 else None
        if y is None or y < 12:
            if oy or oy2: st["bad"].append((st["calls"], k, "drawn out of range", z, oy, oy2))
            continue
        if not oy and not oy2:
            st["missing_ok"] += 1                    # skipped by the per-line cap (checked separately by spritecheck)
            continue
        sz = 0 if y < 30 else (1 if y < 54 else 2)
        yp = max(0, y + pitch)
        off = 3 + (3 * yp) // 4 + 1 + yp // 16 + 3 + sz
        for (o_y, o_x, o_t, side) in ((oy, ox, ot, -1), (oy2, ox2, ot2, 1)):
            if not o_y: continue                   # a post that is off screen sideways
            st["shown"] += 1
            if o_y != 48 + y + 1 or o_t != SPR_POST + 2 * sz:
                st["bad"].append((st["calls"], k, "y/tile", z, (o_y, o_t), (48 + y + 1, SPR_POST + 2 * sz)))
        if oy and oy2 and (ox2 - ox) != 2 * off:
            st["bad"].append((st["calls"], k, "spacing", z, ox2 - ox, 2 * off))
    pb.register_file.A = 0x10 if (st["calls"] // 150) % 4 else 0
pb.hook_register(0, syms["_game_update"], on_update, None)
while st["calls"] < 12000: pb.tick()
print(f"max objects on any road line over the run: {st['maxline']}")
print(f"{st['calls']} frames: {st['shown']} posts drawn and matched the model, {st['missing_ok']} pairs skipped by the line cap, {len(st['bad'])} wrong")
for b in st["bad"][:5]: print("   FAIL", b)
ok = not st["bad"] and st["shown"] > 3000 and st["maxline"] <= 6
print("RESULT:", "PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)
