#!/usr/bin/env python3
"""
Pause menu check (build/prof_flow.gb).

START in a race opens a four-item menu in the bottom window (rows 0/1 at $9C00):
    >RESUME    RESTART
    QUIT       SOUND ON

This drives the real ROM with button presses and checks:
  1. START pauses (g_paused == 1) and the window map decodes to all four labels
  2. DOWN x3 + A toggles g_sound_on 1 -> 0 and NR51 ($FF25) -> 0; A again restores both
  3. UP x3 + A resumes (g_paused == 0, state RACE)
  4. pause + DOWN + A restarts (state COUNTDOWN)
  5. pause + DOWN x2 + A quits (state TITLE)

  pausecheck.py <prof_flow.gb>
"""
import re
import sys
from pathlib import Path
from pyboy import PyBoy

rom = Path(sys.argv[1])
root = Path(__file__).resolve().parent.parent

syms = {}
for line in rom.with_suffix(".noi").read_text().splitlines():
    m = re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", line)
    if m:
        syms[m.group(1)] = int(m.group(2), 16)

sky = int(re.search(r"SKY_TILE_COUNT\s+(\d+)", (root / "src/road_data.h").read_text()).group(1))
HUD_TILE0 = 128 + sky
CHARS = re.search(r'hud_chars\[\]\s*=\s*"([^"]*)"', (root / "src/hud_tab.c").read_text()).group(1)

TITLE, COUNTDOWN, RACE = 0, 1, 2
WIN_MAP = 0x9C00

pb = PyBoy(str(rom), window="null")
pb.set_emulation_speed(0)
mem = pb.memory
rd = lambda n: mem[syms[n]]

fails = []
def check(name, ok, info=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"  {info}" if info else ""))
    if not ok:
        fails.append(name)

def run(n):
    for _ in range(n):
        pb.tick()

def tap(button, n=6):
    pb.button_press(button)
    run(n)
    pb.button_release(button)
    run(4)

def row(y):
    out = []
    for x in range(20):
        i = mem[WIN_MAP + 32 * y + x] - HUD_TILE0
        out.append(CHARS[i] if 0 <= i < len(CHARS) else "?")
    return "".join(out)

def wait_state(state, limit=800):
    n = 0
    while rd("_g_state") != state and n < limit:
        run(1)
        n += 1
    return rd("_g_state") == state

# ---- boot and start a race ---------------------------------------------------
run(150)
check("boots to the title", rd("_g_state") == TITLE, f"state={rd('_g_state')}")
tap("start")
check("race starts", wait_state(RACE), f"state={rd('_g_state')}")

# ---- pause menu --------------------------------------------------------------
tap("start")
r0, r1 = row(0), row(1)
check("START pauses", rd("_g_paused") == 1, f"g_paused={rd('_g_paused')}")
check("menu row 0 has RESUME and RESTART", "RESUME" in r0 and "RESTART" in r0, repr(r0))
check("menu row 1 has QUIT and SOUND", "QUIT" in r1 and "SOUND" in r1, repr(r1))
check("sound starts on", rd("_g_sound_on") == 1 and mem[0xFF25] != 0,
      f"g_sound_on={rd('_g_sound_on')} NR51={mem[0xFF25]:#x}")

# ---- SOUND OFF / ON ----------------------------------------------------------
for _ in range(3):
    tap("down")
tap("a")
check("DOWN x3 + A turns the sound off", rd("_g_sound_on") == 0, f"g_sound_on={rd('_g_sound_on')}")
check("muted: NR51 is 0", mem[0xFF25] == 0, f"NR51={mem[0xFF25]:#x}")
check("row 1 now says SOUND OFF", "SOUND OFF" in row(1), repr(row(1)))

tap("a")
check("A again turns the sound on", rd("_g_sound_on") == 1, f"g_sound_on={rd('_g_sound_on')}")
check("unmuted: NR51 is not 0", mem[0xFF25] != 0, f"NR51={mem[0xFF25]:#x}")

# ---- RESUME -----------------------------------------------------------------
for _ in range(3):
    tap("up")
tap("a")
check("UP x3 + A resumes", rd("_g_paused") == 0, f"g_paused={rd('_g_paused')}")
check("resume returns to the race", rd("_g_state") == RACE, f"state={rd('_g_state')}")

# ---- RESTART ----------------------------------------------------------------
tap("start")
tap("down")
tap("a")
check("pause + DOWN + A restarts", rd("_g_paused") == 0 and rd("_g_state") == COUNTDOWN,
      f"g_paused={rd('_g_paused')} state={rd('_g_state')}")
check("countdown reaches the race", wait_state(RACE), f"state={rd('_g_state')}")

# ---- QUIT -------------------------------------------------------------------
tap("start")
tap("down")
tap("down")
tap("a")
check("pause + DOWN x2 + A quits to the title", rd("_g_paused") == 0 and rd("_g_state") == TITLE,
      f"g_paused={rd('_g_paused')} state={rd('_g_state')}")

pb.stop(save=False)
print("RESULT:", "PASS" if not fails else f"FAIL ({', '.join(fails)})")
sys.exit(0 if not fails else 1)
