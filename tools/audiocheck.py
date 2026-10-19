#!/usr/bin/env python3
"""
Audio check from what the emulated APU actually outputs (PyBoy sound buffer, 48 kHz), not from register
writes.  The ROM is a PROFILE build: dbg_audio_solo masks NR51 so one channel is audible at a time.

  1. music      each channel on its own, car at a standstill: the dominant frequency of every row (7 frames)
                must equal the note the tune data says plays on that row (within 3%; a semitone is 5.9%)
  2. engine     drive with a bot; channel 4 alone: silent at speed 0, and when moving the drone pitch
                follows speed through the engine ladder (autocorrelation period vs 262144 / (127 * r * 2^s))
  3. crash      a rival hit gives a loud burst on channel 4 for ~36 frames, then the engine comes back
  4. lap        a new lap plays the four-note jingle on channel 2 (C5 E5 G5 C6, 6/6/6/18 frames)

  audiocheck.py <prof rom> [--break]   (--break shifts the expected tune by a semitone: must FAIL)
"""
import re
import sys
from pathlib import Path
import numpy as np
from pyboy import PyBoy

SR = 48000
ROW_FRAMES = 7
brk = "--break" in sys.argv
rom = Path(sys.argv[1])
syms = {m.group(1): int(m.group(2), 16) for l in rom.with_suffix(".noi").read_text().splitlines()
        if (m := re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", l))}

# ---- expected tune, parsed from the generated C source (the same data the ROM was built from) ----
src = (Path(__file__).resolve().parent.parent / "src/audio_data.c").read_text()
def parse(name):
    body = re.search(name + r"\[\d+\]\s*=\s*\{([^}]*)\}", src, re.S).group(1)
    return [int(x, 16) for x in re.findall(r"0x[0-9A-Fa-f]+", body)]
NOTE0 = int(re.search(r"#define NOTE0 (\d+)", (Path(__file__).resolve().parent.parent / "src/audio_data.h").read_text()).group(1))
def rows_of(track):                    # -> list of MIDI note (0 = rest) per row
    out, i = [], 0
    while track[i] != 0xFF:
        n, r = track[i], track[i + 1]
        out += [n + NOTE0 - 1 if n else 0] * r
        i += 2
    return out
hz = lambda m: 440.0 * 2 ** ((m - 69) / 12)

def fundamental(x, lo=40, hi=2500):
    x = x - x.mean()
    w = np.hanning(len(x))
    n = 1 << 17
    sp = np.abs(np.fft.rfft(x * w, n))
    f = np.fft.rfftfreq(n, 1 / SR)
    m = (f >= lo) & (f <= hi)
    k = np.argmax(sp * m)
    if 0 < k < len(sp) - 1:                      # parabolic refinement
        a, b, c = np.log(sp[k - 1] + 1e-9), np.log(sp[k] + 1e-9), np.log(sp[k + 1] + 1e-9)
        k = k + 0.5 * (a - c) / (a - 2 * b + c)
    return k * SR / n, float(np.sqrt(np.mean(x * x)))

def acf_period_hz(x, lo=30, hi=400):
    """Period of a repeating waveform: first local maximum of the unbiased autocorrelation that is within
    3% of the best one (later multiples of the period are equally good, we want the first)."""
    x = x - x.mean()
    n = len(x)
    ac = np.correlate(x, x, "full")[n - 1:] / (n - np.arange(n))
    a, b = int(SR / hi), int(SR / lo)
    seg = ac[a:b]
    best = seg.max()
    for i in range(1, len(seg) - 1):
        if seg[i] >= 0.97 * best and seg[i] >= seg[i - 1] and seg[i] >= seg[i + 1]:
            return SR / (a + i)
    return SR / (a + int(np.argmax(seg)))

class Run:
    def __init__(self, solo):
        self.pb = PyBoy(str(rom), window="null", sound_emulated=True)
        self.pb.set_emulation_speed(0)
        self.mem = self.pb.memory
        self.audio, self.starts = [], []          # per tick: samples, and the tick each audio_update call fell in
        self.tick_no = 0
        self.calls = []                           # (tick, lap, hits, speed, offroad)
        self.solo = solo
        self.pb.hook_register(0, syms["_audio_update"], self.on_call, None)
        self.sample_pos = [0]

    def on_call(self, _):
        m = self.mem
        sp = m[syms["_g_speed"]] | (m[syms["_g_speed"] + 1] << 8)
        self.calls.append((self.tick_no, m[syms["_g_lap"]], m[syms["_g_hits"]], sp, m[syms["_g_offroad"]]))

    def tick(self):
        self.mem[syms["_dbg_audio_solo"]] = self.solo
        self.pb.tick()
        a = self.pb.sound.ndarray.astype(np.float32).mean(axis=1)
        self.audio.append(a)
        self.sample_pos.append(self.sample_pos[-1] + len(a))
        self.tick_no += 1

    def seg(self, t0, t1):                        # samples of whole ticks t0 .. t1-1
        return np.concatenate(self.audio[t0:t1])

# ---------------------------------------------------------------- 1. music
tracks = {"lead": (0x11, "mus_lead"), "harmony": (0x22, "mus_harm"), "bass": (0x44, "mus_bass")}
total = bad = 0
worst = 0.0
for name, (solo, arr) in tracks.items():
    run = Run(solo)
    for _ in range(40):
        run.tick()
    first = len(run.calls)
    for _ in range(64 * ROW_FRAMES + 30):
        run.tick()
    notes = rows_of(parse(arr))
    # call index c (counted from the first update after boot) plays row c // 7: the first call has row_tick preset
    ok_rows = 0
    for r in range(len(notes)):
        c0, c1 = r * ROW_FRAMES, (r + 1) * ROW_FRAMES
        if c1 >= len(run.calls):
            break
        t0, t1 = run.calls[c0][0] + 1, run.calls[c1][0]      # skip the tick the note starts in
        x = run.seg(t0, t1)
        f, rms = fundamental(x)
        exp = hz(notes[r] + (1 if brk else 0))
        err = abs(f / exp - 1)
        worst = max(worst, err)
        total += 1
        if err > 0.03:
            bad += 1
            if bad <= 4:
                print(f"  {name} row {r}: expected {exp:.1f} Hz (MIDI {notes[r]}), measured {f:.1f} Hz")
    run.pb.stop(save=False)
print(f"music: {total} rows over 3 channels, {bad} wrong pitch (worst error {100 * worst:.2f}%)")
music_ok = bad == 0 and total >= 180

# ---------------------------------------------------------------- 2-4. engine, crash, lap (channel 4 / 2 solo)
KEYMAP = {}
def drive(run, n, mode="centre"):
    pb, m = run.pb, run.mem
    held = set()
    for _ in range(n):
        v = m[syms["_g_cam"]] | (m[syms["_g_cam"] + 1] << 8)
        cam = (v - 65536 if v > 32767 else v) >> 8
        want = {"a"} if mode != "stop" else set()
        if mode == "centre":
            want |= {"left"} if cam > 6 else ({"right"} if cam < -6 else set())
        elif mode == "grass":
            want |= {"right"}
        for b in held - want:
            pb.button_release(b)
        for b in want - held:
            pb.button_press(b)
        held = want
        run.tick()
    for b in held:
        pb.button_release(b)

LADDER = [0x3e, 0x3d, 0x3c, 0x2e, 0x2d, 0x2c, 0x1e, 0x1d]            # regenerated below from the data file
LADDER = parse("eng_nr43")
def ladder_hz(i):
    """Pitch the autocorrelation of the *sampled* drone should show.  The 7-bit noise sequence repeats every
    127 LFSR steps = p output samples; if p is not (nearly) an integer the 48 kHz samples only repeat after k
    periods, so the smallest k with k*p near an integer gives the lag to expect (e.g. p = 232.5 -> lag 2p)."""
    v = LADDER[i]
    s, r = v >> 4, v & 7
    f = 262144 / ((0.5 if r == 0 else r) * 2 ** s * 127)
    p = SR / f
    for k in range(1, 5):
        if abs(k * p - round(k * p)) < 0.2:
            return SR / (k * p)
    return f

eng = Run(0x88)
for _ in range(30):
    eng.tick()
rms_stop = float(np.sqrt(np.mean(eng.seg(10, 30) ** 2)))
drive(eng, 700, "centre")
checked = engine_bad = 0
seen_idx = set()
for k in range(30, len(eng.calls) - 1, 3):
    t, lap, hits, sp, off = eng.calls[k]
    # window of four ticks with the same engine index and no crash around
    ts = [eng.calls[j] for j in range(max(0, k - 3), k + 1)]
    if len({(c[3] * 3) >> 5 for c in ts}) != 1 or any(c[2] != eng.calls[max(0, k - 20)][2] for c in ts) or off:
        continue
    if hits and eng.calls[k][2] != eng.calls[max(0, k - 40)][2]:
        continue
    t0, t1 = eng.calls[k - 3][0] + 1, eng.calls[k][0] + 1
    if t1 - t0 < 3 or sp <= 0:
        continue
    x = eng.seg(t0, t1)
    idx = (sp * 3) >> 5
    f = acf_period_hz(x, 25, 400)
    exp = ladder_hz(idx)
    checked += 1
    seen_idx.add(idx)
    if abs(f / exp - 1) > 0.06:
        engine_bad += 1
        if engine_bad <= 4:
            print(f"  engine: speed {sp} (step {idx}) expected {exp:.1f} Hz, measured {f:.1f} Hz")
print(f"engine: silent at standstill (rms {rms_stop:.3f}); {checked} windows checked, steps seen {sorted(seen_idx)}, {engine_bad} wrong")
engine_ok = rms_stop < 0.01 and engine_bad == 0 and len(seen_idx) >= 6

# regime switches: onto the grass (gravel hiss, 15-bit noise) and back (7-bit drone) must leave a live signal
def live(a, b):                                 # fraction of ticks with sample changes inside
    return np.mean([np.any(np.diff(eng.audio[t]) != 0) for t in range(a, b)])
eng2 = Run(0x88)
for _ in range(30):
    eng2.tick()
eng_saved, eng = eng, eng2
switch_ok = True
for cycle in range(4):
    drive(eng, 260, "grass")
    on_grass = (eng.calls[-1][4] == 1)
    g = live(eng.tick_no - 40, eng.tick_no)
    drive(eng, 260, "centre")
    r = live(eng.tick_no - 40, eng.tick_no)
    switch_ok = switch_ok and on_grass and g > 0.95 and r > 0.95
    print(f"  cycle {cycle}: on grass={on_grass}, live fraction on grass {g:.2f}, back on road {r:.2f}")
eng.pb.stop(save=False)
eng = eng_saved
print("regime switches (road <-> grass):", "ok" if switch_ok else "FAIL")
engine_ok = engine_ok and switch_ok

# crash: first rise of g_hits
crash_ok = False
ev = [i for i in range(1, len(eng.calls)) if eng.calls[i][2] != eng.calls[i - 1][2]]
if ev:
    i = ev[0]
    tc = eng.calls[i][0]
    rms = lambda a, b: float(np.sqrt(np.mean(eng.seg(a, b) ** 2)))
    before = rms(max(0, tc - 12), tc - 1)
    during = rms(tc + 2, tc + 30)
    tail = rms(tc + 50, tc + 70) if tc + 70 < len(eng.audio) else None
    crash_ok = during > 2.0 * before and during > 0.5 and (tail is None or tail > 0.02)
    print(f"crash: first hit at tick {tc}: rms before {before:.2f}, during burst {during:.2f}, engine back after {tail if tail is None else round(tail, 2)}")
else:
    print("crash: no hit happened in the run")
eng.pb.stop(save=False)

# lap jingle on channel 2 alone, music silenced so only the jingle can sound; drive until the lap changes
lap = Run(0x22)
lap.mem[syms["_dbg_audio_music_off"]] = 1
for _ in range(40):
    lap.tick()
lap_idx = None
for _ in range(1500):
    drive(lap, 1, "centre")
    if len(lap.calls) > 2 and lap.calls[-1][1] != lap.calls[-2][1]:
        lap_idx = len(lap.calls) - 1
        break
jingle_ok = False
if lap_idx is not None:
    drive(lap, 40, "centre")
    t0 = lap.calls[lap_idx][0]
    pitches = []
    for (a, b) in ((1, 6), (7, 12), (13, 18), (19, 33)):
        f, rms = fundamental(lap.seg(t0 + a, t0 + b))
        pitches.append((round(f, 1), round(rms, 2)))
    want = [hz(m) for m in (72, 76, 79, 84)]
    jingle_ok = all(abs(p[0] / w - 1) < 0.03 for p, w in zip(pitches, want))
    quiet = float(np.sqrt(np.mean(lap.seg(t0 + 39, t0 + 42) ** 2)))
    print(f"lap jingle at tick {t0}: pitches {[p[0] for p in pitches]} Hz, expected {[round(w, 1) for w in want]}; silent after: rms {quiet:.3f}")
    jingle_ok = jingle_ok and quiet < 0.05
else:
    print("lap: no lap completed in the run")
lap.pb.stop(save=False)

ok = music_ok and engine_ok and crash_ok and jingle_ok
print(f"  music {'ok' if music_ok else 'FAIL'}, engine {'ok' if engine_ok else 'FAIL'}, crash {'ok' if crash_ok else 'FAIL'}, "
      f"jingle {'ok' if jingle_ok else 'FAIL'}")
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
