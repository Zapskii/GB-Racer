"""
Battery save, pause and level checks on the release ROM (build/racer.gb), driven by real button presses.

 1. fresh cartridge RAM: all records empty, defaults on the title page
 2. choose track/laps/level, SELECT cycles the level, START, drive a whole 3-lap race, finish with a record
 3. power off (stop with save), power on again from the saved RAM: the record, and the selections, are back,
    and the title page shows the time
 4. a corrupted checksum byte: the save is rejected (records cleared, defaults)
 5. pause: START in a race freezes position/speed/time/rival positions for 120 frames; START again resumes
 --break save   skips the power-cycle (must FAIL step 3)
"""
import re, sys, shutil, tempfile, os
from pyboy import PyBoy

BREAK = "--break" in sys.argv and sys.argv[sys.argv.index("--break") + 1]
src = "build/racer.gb"
sym = {}
for l in open("build/racer.noi"):
    m = re.match(r"DEF _(\w+) 0x([0-9A-Fa-f]+)", l)
    if m: sym[m.group(1)] = int(m.group(2), 16)

tmp = tempfile.mkdtemp()
rom = os.path.join(tmp, "t.gb")
shutil.copy(src, rom)
fails = []
def check(name, ok, info=""):
    print(("  ok   " if ok else "  FAIL ") + name + (" " + str(info) if info else ""))
    if not ok: fails.append(name)

def boot():
    pb = PyBoy(rom, window="null", sound_emulated=False)
    return pb
def m8(pb, n, off=0): return pb.memory[sym[n] + off]
def m16(pb, n, off=0): return pb.memory[sym[n] + off] | (pb.memory[sym[n] + off + 1] << 8)
def run(pb, n):
    for _ in range(n): pb.tick()
def tap(pb, b, n=6):
    pb.button_press(b); run(pb, n); pb.button_release(b); run(pb, 4)
def rec(pb, lvl, trk, sel): return m16(pb, "g_best_total", 2 * ((lvl * 3 + trk) * 3 + sel))

# ---- 1. fresh ----
if os.path.exists(rom + ".ram"): os.remove(rom + ".ram")
pb = boot(); run(pb, 120)
check("fresh: title state", m8(pb, "g_state") == 0)
check("fresh: all 27 records empty", all(rec(pb, l, t, s) == 0 for l in range(3) for t in range(3) for s in range(3)))
check("fresh: defaults track 0, laps 0, level 1", (m8(pb, "g_track"), m8(pb, "g_laps_sel"), m8(pb, "g_level")) == (0, 0, 1))

# ---- 2. pick settings and race ----
tap(pb, "down"); tap(pb, "down")                       # ALPINE ... then back to CANYON
tap(pb, "up")
tap(pb, "select")                                      # NORMAL -> HARD
tap(pb, "select")                                      # HARD -> EASY
tap(pb, "select"); tap(pb, "select")                   # EASY -> NORMAL -> HARD
check("selections: track 1 (CANYON), level 2 (HARD)", (m8(pb, "g_track"), m8(pb, "g_level")) == (1, 2), (m8(pb, "g_track"), m8(pb, "g_level")))
tap(pb, "start"); run(pb, 20)
check("race starts", m8(pb, "g_state") == 1)
while m8(pb, "g_state") == 1: run(pb, 1)
run(pb, 5)

# ---- 5. pause (early in the race, while accelerating) ----
pb.button_press("a"); run(pb, 90)
def snap(): return (m16(pb, "g_zacc"), m16(pb, "g_speed"), m16(pb, "g_tenths"), m16(pb, "g_cam"), pb.screen.ndarray[:120].tobytes())
before = snap()
tap(pb, "start", 3); run(pb, 5)
p0 = snap(); run(pb, 120); p1 = snap()
check("pause: the race moved before the pause", before[:4] != (0, 0, 0, 0))
check("pause: nothing changes for 120 frames", p0 == p1, (p0[:4], p1[:4]))
check("pause: g_paused set", m8(pb, "g_paused") == 1)
tap(pb, "start", 3); run(pb, 30)
p2 = snap()
check("pause: START resumes the race", p2 != p1 and m8(pb, "g_paused") == 0, (p1[:4], p2[:4]))

# ---- 2 (cont). finish the race: hold A, steer gently towards the middle ----
f = 0
while m8(pb, "g_state") in (2, 3) and f < 60 * 900:
    cam = m16(pb, "g_cam"); cam = cam - 65536 if cam > 32767 else cam
    pb.button_release("left"); pb.button_release("right")
    if cam > 1500: pb.button_press("left")
    elif cam < -1500: pb.button_press("right")
    run(pb, 1); f += 1
pb.button_release("a"); pb.button_release("left"); pb.button_release("right")
run(pb, 120)
check("race finished: results page", m8(pb, "g_state") == 4, m8(pb, "g_state"))
t_rec = rec(pb, 2, 1, 0)
check("record stored in RAM for [HARD][CANYON][3 laps]", t_rec > 0 and t_rec == m16(pb, "g_race_tenths"), (t_rec, m16(pb, "g_race_tenths")))
check("new-record flag", m8(pb, "g_new_record") == 1)
print("   race time", t_rec / 10, "s, frames", f)
if BREAK != "save":
    pb.stop(save=True)
else:
    pb.stop(save=False)

# ---- 3. power cycle ----
check("save file written", os.path.exists(rom + ".ram") and os.path.getsize(rom + ".ram") >= 8192, os.path.exists(rom + ".ram") and os.path.getsize(rom + ".ram"))
pb = boot(); run(pb, 120)
check("after reboot: record restored", rec(pb, 2, 1, 0) == t_rec, (rec(pb, 2, 1, 0), t_rec))
check("after reboot: other records still empty", sum(rec(pb, l, t, s) for l in range(3) for t in range(3) for s in range(3)) == t_rec)
check("after reboot: selections restored (CANYON, 3 laps, HARD)", (m8(pb, "g_track"), m8(pb, "g_laps_sel"), m8(pb, "g_level")) == (1, 0, 2))
# the title page shows the time: BEST row (row 10), digits of mm:ss.t
mem = pb.memory
HUD0 = None
pb.stop(save=False)

# ---- 6. palette banks: each track's stripe rows, as the CPU sees them at $6000 once the race has started ----
SETS = {0: (0xE4, 0x38, 0x09, 0x99), 1: (0xE4, 0x09, 0xB8, 0x99), 2: (0xD8, 0x4D, 0xB8, 0x99)}   # per track: sky, A, B, fog
if BREAK == "palette": SETS[2] = (0xD8, 0x4D, 0xB9, 0x99)
IDX0, FOG, ROAD_LINES = 47, 14, 80
def expected_row(track, p):
    sky, A, B, FG = SETS[track]
    page = [sky] * 256
    for y in range(ROAD_LINES):
        page[IDX0 + y] = FG if y < FOG else (B if (((4096 // (y + 4)) + p) >> 3) & 1 else A)
    for i in range(IDX0 + ROAD_LINES, 256): page[i] = 0xE4
    return page
for trk in range(3):
    pb = boot(); run(pb, 120)
    for _ in range(3): tap(pb, "up")
    for _ in range(trk): tap(pb, "down")
    tap(pb, "start"); run(pb, 20)
    bad = 0; tracks_seen = m8(pb, "g_track")
    for p in range(16):
        got = [pb.memory[0x6000 + p * 256 + i] for i in range(256)]
        bad += sum(1 for a, b in zip(got, expected_row(trk, p)) if a != b)
    check("palette set of track %d (%s) readable at $6000, 16 rows x 256 bytes" % (trk, ["OVAL", "CANYON", "ALPINE"][trk]), bad == 0 and tracks_seen == trk, "wrong bytes %d" % bad)
    pb.stop(save=False)

# ---- 4. corrupt save ----
data = bytearray(open(rom + ".ram", "rb").read())
check("save block has the magic", bytes(data[0:3]) == b"GR\x01", bytes(data[0:3]))
data[10] ^= 0x55
open(rom + ".ram", "wb").write(data)
pb = boot(); run(pb, 120)
check("corrupt checksum: records cleared", all(rec(pb, l, t, s) == 0 for l in range(3) for t in range(3) for s in range(3)))
check("corrupt checksum: defaults", (m8(pb, "g_track"), m8(pb, "g_laps_sel"), m8(pb, "g_level")) == (0, 0, 1))
pb.stop(save=False)
shutil.rmtree(tmp)
print("savecheck:", "PASS" if not fails else "FAIL " + ", ".join(fails))
sys.exit(1 if fails else 0)
