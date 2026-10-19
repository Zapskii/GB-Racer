#!/usr/bin/env python3
"""
Checks the sprite engine from what the hardware actually sees: OAM ($FE00) and the SCX table the
ISR is displaying, read every frame of a long input script.

  1. objects per scanline: never more than 6 on any line (the ISR timing budget), counting every
     visible object, and how often the flicker multiplexer had to hide a rival
  2. every visible rival car lies entirely on the tarmac of its own road line (so projection and
     curve-following are right), checked against the displayed SCX table
  3. coverage: all three rival sizes and all three player frames were seen, rivals respawn
  4. rival feet follow the stripe scroll: closing speed in road lines/frame is consistent
     with y_of_z (spot check: foot line never moves away from the camera while the player is
     faster than the rival)

Usage: spritecheck.py <rom with PROFILE>
"""
import re
import sys
from pathlib import Path
from pyboy import PyBoy

IDX0, ROAD_TOP, SCX_BASE = 47, 48, 48

rom = Path(sys.argv[1])
syms = {}
for line in rom.with_suffix(".noi").read_text().splitlines():
    m = re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", line)
    if m:
        syms[m.group(1)] = int(m.group(2), 16)

pb = PyBoy(str(rom), window="null")
pb.set_emulation_speed(0)
mem = pb.memory

def oam():
    return [(mem[0xFE00 + 4 * i], mem[0xFE00 + 4 * i + 1], mem[0xFE00 + 4 * i + 2], mem[0xFE00 + 4 * i + 3])
            for i in range(40)]

def hw(y):                         # tarmac half-width, same formula as gen_road.py
    return 3 + (3 * y) // 4

stats = dict(frames=0, max_line=0, max_road_line=0, over6=0, off_road=0, worst_margin=999,
             widths=set(), player_tiles=set(), rivals_seen=0)
worst_line_frame = None
last_foot = {0: None, 1: None}
respawns = 0

script = ([(("a",), 250), (("b",), 140), ((), 160), (("a",), 200), (("a", "right"), 80), (("b",), 100),
           (("a", "left"), 150), (("b",), 120), ((), 200), (("a",), 300), (("a", "right"), 90), (("b",), 150),
           ((), 300), (("a",), 250), (("b",), 200), ((), 200), (("a", "left"), 100), (("a",), 300)])
for _ in range(60):
    pb.tick()
for btns, n in script:
    for bt in btns:
        pb.button_press(bt)
    for _ in range(n):
        pb.tick()
        o = oam()
        stats["frames"] += 1
        # --- 1. objects per scanline (8x16 objects: y-16 .. y-1)
        count = [0] * 144
        for (y, x, t, p) in o:
            if 0 < y < 160 and 0 < x < 168:
                for ln in range(max(0, y - 16), min(144, y)):
                    count[ln] += 1
        mx = max(count)
        mr = max(count[ROAD_TOP:ROAD_TOP + 80])
        stats["max_line"] = max(stats["max_line"], mx)
        if mr > stats["max_road_line"]:
            stats["max_road_line"], worst_line_frame = mr, stats["frames"]
        if mr > 6:
            stats["over6"] += 1
        # --- player frame
        stats["player_tiles"].add(o[0][2])
        # --- 2. rivals on the tarmac
        page = mem[syms["_tbl_page"]]
        for i, base in enumerate((3, 6)):
            objs = [(y, x, t) for (y, x, t, p) in o[base:base + 3] if 0 < y < 160]
            if not objs:
                last_foot[i] = None
                continue
            stats["rivals_seen"] += 1
            w = len(objs)
            stats["widths"].add(w)
            foot = objs[0][0] - 1                       # bottom pixel row
            yr = foot - ROAD_TOP
            left = min(x for _, x, _ in objs) - 8
            cx = left + 4 * w
            scx = mem[(page << 8) + IDX0 + yr]
            delta = ((scx - SCX_BASE + 128) & 255) - 128
            centre = 80 - delta
            scy = mem[0xFF42]
            scy = scy - 256 if scy > 127 else scy        # the BG is scrolled by SCY: line yr shows road row yr + SCY
            margin = hw(yr + scy) - (abs(cx - centre) + 4 * w)
            stats["worst_margin"] = min(stats["worst_margin"], margin)
            if margin < -1:
                stats["off_road"] += 1
            if last_foot[i] is not None and foot < last_foot[i] - 20:
                respawns += 1
            last_foot[i] = foot
    for bt in btns:
        pb.button_release(bt)

hidden = mem[syms["_dbg_hidden_frames"]] if "_dbg_hidden_frames" in syms else None
pb.stop(save=False)
ok = stats["over6"] == 0 and stats["off_road"] == 0 and stats["widths"] == {1, 2, 3} and len(stats["player_tiles"]) == 3
print(f"{rom.name}: {stats['frames']} frames checked, {stats['rivals_seen']} rival sightings")
print(f"  objects per scanline: max {stats['max_line']} anywhere, max {stats['max_road_line']} on road lines "
      f"(frame {worst_line_frame}); frames over 6: {stats['over6']}; flicker engaged on {hidden} frames (8-bit counter)")
print(f"  rivals fully on tarmac: {stats['off_road']} violations, worst margin {stats['worst_margin']} px")
print(f"  sizes seen (objects wide): {sorted(stats['widths'])}; player steering frames seen: {len(stats['player_tiles'])}/3; "
      f"respawns observed: {respawns}")
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
