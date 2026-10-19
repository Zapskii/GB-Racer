#!/usr/bin/env python3
"""
Bit-exact check of the asm SCX table builder and the ROM stripe rows against an
independent Python model.

A PyBoy hook fires every time the ROM enters _build_tables_asm.  At that moment
the bt_* parameters belong to the build that is about to run, and the previous
build's tables are complete (the two buffers alternate, so the previous page is
not touched yet).  So at each entry we
  1. verify the PREVIOUS build: recompute the expected SCX table from the
     parameters captured at its entry and compare ALL 256 bytes of its page
     (stray writes are caught too);
  2. capture the parameters for the build that is starting.

Hooking the entry avoids a race a frame-boundary snapshot has: by then the main
loop may already have written the NEXT build's bt_* values.

The 16 stripe rows in ROM ($6000 + 256*phase) are checked once against the original formula
    stripe = ((4096 // (y + 4)) + phase) >> 3) & 1

Usage: modelcheck.py <rom.gb> [--break]      (--break perturbs the model: must FAIL)
"""
import re
import sys
from pathlib import Path
from pyboy import PyBoy

IDX0, ROAD_LINES, FOG = 47, 80, 14
SCX_BASE, BGP_BASE, BGP_FOG, BGP_A, BGP_B = 48, 0xE4, 0x99, 0x09, 0xB8

rom = Path(sys.argv[1])
broken = "--break" in sys.argv

syms = {}
for line in rom.with_suffix(".noi").read_text().splitlines():
    m = re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", line)
    if m:
        syms[m.group(1)] = int(m.group(2), 16)

pb = PyBoy(str(rom), window="null")
pb.set_emulation_speed(0)
mem = pb.memory

def u8(n):  return mem[syms[n]]
def u16(n): return mem[syms[n]] | (mem[syms[n] + 1] << 8)

def model(p):
    """{addr: value} for every byte the builder is expected to write."""
    s, ds, cur = p["s"], p["ds"], p["cur"]
    if broken:
        cur = (cur + 1) & 0xFFFF
    out, e = {}, p["scx"]
    for _chunk in range(10):
        for _ in range(8):
            out[e] = s >> 8
            s = (s + ds) & 0xFFFF
            e = (e & 0xFF00) | ((e - 1) & 0xFF)       # the asm only decrements E
        ds = (ds + cur) & 0xFFFF
    return out

def expected_scx(page_hi, writes):
    exp = {(page_hi << 8) + i: SCX_BASE for i in range(256)}
    exp.update({a: v for a, v in writes.items() if (a >> 8) == page_hi})
    return exp

def check_rows():
    """All 16 ROM stripe rows, all 256 entries each, against the original formula."""
    bad = 0
    for p in range(16):
        for i in range(256):
            y = i - IDX0
            if 0 <= y < FOG:
                want = BGP_FOG
            elif FOG <= y < ROAD_LINES:
                want = BGP_B if (((4096 // (y + 4)) + p) >> 3) & 1 else BGP_A
            else:
                want = BGP_BASE
            if mem[0x6000 + p * 256 + i] != want:
                bad += 1
    return bad

state = {"prev": None, "checked": 0, "bad_builds": 0, "bad_bytes": 0, "first_bad": None,
         "cams": set(), "pages": set()}

def on_entry(_ctx):
    prev = state["prev"]
    if prev is not None:
        writes = model(prev)
        page = prev["scx"] >> 8
        bad = sum(1 for a_, v in expected_scx(page, writes).items() if mem[a_] != v)
        state["checked"] += 1
        state["pages"].add(page)
        state["cams"].add(((prev["s"] - SCX_BASE * 256 + 32768) & 0xFFFF) - 32768)
        if bad:
            state["bad_builds"] += 1
            state["bad_bytes"] += bad
            state["first_bad"] = state["first_bad"] or (state["checked"], bad)
    state["prev"] = {"s": u16("_bt_s"), "ds": u16("_bt_ds"), "cur": u16("_bt_curve"),
                     "scx": u16("_bt_scx")}

pb.hook_register(0, syms["_build_tables_asm"], on_entry, None)

# input script: buttons held per segment.  A accelerates, B brakes, LEFT/RIGHT steer
# (steering authority grows with speed, so accelerate first to sweep the whole camera range)
script = ([(("a",), 200), (("a", "right"), 140), (("a", "left"), 300), (("a", "right"), 200), (("b",), 60),
           (("a", "left"), 250), (("a", "right"), 250), ((), 60), (("a",), 300), (("a", "left"), 200)])
for _ in range(60):                       # PyBoy's boot animation
    pb.tick()
for btns, n in script:
    for b in btns:
        pb.button_press(b)
    for _ in range(n):
        pb.tick()
    for b in btns:
        pb.button_release(b)
pb.stop(save=False)

row_bad = check_rows()
c = sorted(state["cams"])
print(f"{rom.name}: {state['checked']} SCX builds checked, {state['bad_builds']} with mismatches, "
      f"{state['bad_bytes']} wrong bytes (of {state['checked'] * 256}); camera {c[0]}..{c[-1]}, "
      f"both buffers: {sorted(hex(p) for p in state['pages'])}; "
      f"ROM stripe rows: {row_bad} wrong bytes (of 4096)"
      + (f"; first bad build #{state['first_bad'][0]} ({state['first_bad'][1]} bytes)" if state["first_bad"] else ""))
sys.exit(1 if (state["bad_builds"] or row_bad) else 0)
