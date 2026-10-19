#!/usr/bin/env python3
"""
Menu/pause audio-state check (build/prof_flow.gb).

audio_update() treats any change of `hits` as a collision.  g_hits deliberately persists across
races, so the title/results and pause call sites must pass g_hits, not 0; 0 made the game play a
crash burst when a paused/results/title frame followed a race with collisions, and again on the
first frame of the next race.

The PROFILE build exposes dbg_audio_last_hits (the hits argument the last call saw).  This checks
that it tracks g_hits on the title screen and while paused.

  audiostatecheck.py <prof_flow.gb>
"""
import re
import sys
from pathlib import Path
from pyboy import PyBoy

rom = Path(sys.argv[1])
syms = {m.group(1): int(m.group(2), 16)
        for l in rom.with_suffix(".noi").read_text().splitlines()
        if (m := re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", l))}

TITLE, RACE = 0, 2
pb = PyBoy(str(rom), window="null")
pb.set_emulation_speed(0)
mem = pb.memory
rd = lambda n: mem[syms[n]]


def run(n):
    for _ in range(n):
        pb.tick()


fails = []
def check(name, ok, info=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"  {info}" if info else ""))
    if not ok:
        fails.append(name)


run(150)
check("boots to the title", rd("_g_state") == TITLE, f"state={rd('_g_state')}")

# ---- title/results call site -------------------------------------------------
mem[syms["_g_hits"]] = 7
run(3)
check("title: hits argument tracks g_hits",
      rd("_dbg_audio_last_hits") == rd("_g_hits") == 7,
      f"last={rd('_dbg_audio_last_hits')} g_hits={rd('_g_hits')}")

# ---- pause call site ---------------------------------------------------------
pb.button_press("start"); run(6); pb.button_release("start")
n = 0
while rd("_g_state") != RACE and n < 500:
    run(1); n += 1
started = rd("_g_state") == RACE
check("race starts", started, f"state={rd('_g_state')}")

if started:
    mem[syms["_g_hits"]] = 9
    run(2)                                  # let the race path sync last_hits
    pb.button_press("start"); run(6)
    paused = rd("_g_paused") == 1
    hits = rd("_g_hits")
    check("pause branch reached", paused, f"g_paused={rd('_g_paused')}")
    check("pause: hits argument tracks g_hits",
          rd("_dbg_audio_last_hits") == hits,
          f"last={rd('_dbg_audio_last_hits')} g_hits={hits}")
    pb.button_release("start")

pb.stop(save=False)
print("RESULT:", "PASS" if not fails else f"FAIL ({', '.join(fails)})")
sys.exit(0 if not fails else 1)
