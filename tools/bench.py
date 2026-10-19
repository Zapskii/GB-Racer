#!/usr/bin/env python3
"""Run build/bench.gb headless and convert its DIV tick counts to M-cycles (1 tick = 64)."""
import re, sys
from pathlib import Path
from pyboy import PyBoy
rom = Path(sys.argv[1] if len(sys.argv) > 1 else "build/bench.gb")
syms = {m.group(1): int(m.group(2), 16) for l in rom.with_suffix(".noi").read_text().splitlines()
        if (m := re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", l))}
pb = PyBoy(str(rom), window="null"); pb.set_emulation_speed(0)
for _ in range(400):
    pb.tick()
    if pb.memory[syms["_bench_done"]]: break
rd = lambda n, i=0: pb.memory[syms[n] + i]
cal = rd("_res_cal")
print(f"calibration: 8 x 1034 cycles = 8272 expected; DIV says {cal} ticks = {cal*64} cycles ({100*(cal*64-8272)/8272:+.1f}%)")
def row(name, key, n):
    v = [rd(key, k) * 64 / n for k in range(4)]
    print(f"{name:34s} " + "  ".join(f"{x:7.0f}" for x in v) + f"   | mean {sum(v)/4:7.0f} cycles = {100*sum(v)/4/17556:4.1f}% of a frame")
print(f"{'':34s} " + "  ".join(f"{c:>7s}" for c in ("cam0", "+15000", "-15000", "+5000")))
row("C builder (step-1 maths)", "_res_c", 1)
row("asm builder + C param setup", "_res_fast", 5)
row("asm builder alone", "_res_asm", 5)
row("sprites_update (rivals far -> near)", "_res_spr", 3)
row("sprites_update, collision test off", "_res_spr1", 3)
row("game_update (coast/A/A+R/B+L)", "_res_game", 16)
hi, hf = rd("_res_hud_idle") * 64 / 16, rd("_res_hud_full") * 64 / 16
print(f"{'hud_update idle / all fields change':34s} {hi:7.0f}  {hf:7.0f}   cycles ({100*hi/17556:.1f}% / {100*hf/17556:.1f}% of a frame)")
print(f"{'audio_update average / row frame':34s} {rd('_res_audio') * 64 / 63:7.0f}  {rd('_res_audio_row') * 64:7.0f}   cycles (row frame resolution is one DIV tick = 64)")
print("raw ticks:", {k: [rd(k, i) for i in range(4)] for k in ("_res_c", "_res_fast", "_res_asm", "_res_spr")})
pb.stop(save=False)
