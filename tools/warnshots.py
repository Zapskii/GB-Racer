#!/usr/bin/env python3
"""Screenshots of the corner warning: build/prof_race.gb on ALPINE, flat out; saves the frames around the first sharp bends.
   warnshots.py <rom> <out_dir>"""
import re, sys
from pathlib import Path
from pyboy import PyBoy
rom = Path(sys.argv[1]); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
syms = {}
for l in rom.with_suffix(".noi").read_text().splitlines():
    m = re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", l)
    if m: syms[m.group(1)] = int(m.group(2), 16)
track = int(sys.argv[3]) if len(sys.argv) > 3 else 2
pb = PyBoy(str(rom), window="null"); pb.set_emulation_speed(0)
mem = pb.memory
s16 = lambda v: ((v + 0x8000) & 0xFFFF) - 0x8000
rd16 = lambda n: mem[syms[n]] | (mem[syms[n] + 1] << 8)
st = dict(calls=0, shots=0, last_w=0, since=0)
def on_update(_):
    if st["calls"] == 0:
        mem[syms["_g_track"]] = track; mem[syms["_g_laps_total"]] = 99
    st["calls"] += 1
    cam = s16(rd16("_g_cam"))
    pb.register_file.A = 0x10 | (2 if cam > 1500 else (1 if cam < -1500 else 0))
    w = mem[syms["_g_warn"]]; w = w - 256 if w > 127 else w
    st["w"] = w
pb.hook_register(0, syms["_game_update"], on_update, None)
want = [(0, 0), (1, 0), (1, 10), (1, 24), (1, 40)]       # (kind, frames after the sign first appears); kind 1 = sign phase
shot_at = {}
f = 0; phase = 0; t0 = None; n = 0
while n < 6 and f < 5000:
    pb.tick(); f += 1
    if f < 400: continue
    w = st.get("w", 0)
    if w and t0 is None: t0 = f
    if t0 is not None and w == 0 and f - t0 > 5: t0 = None
    if t0 is not None and (f - t0) in (0, 12, 30) and abs(w) >= 2:
        pb.screen.image.convert("RGB").resize((480, 432)).save(out / f"warn_{n}_{f - t0:02d}_w{w}.png"); n += 1
print(sorted(p.name for p in out.glob("warn_*.png")))
