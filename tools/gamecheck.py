#!/usr/bin/env python3
"""
Game-logic check, run from hooks on the real ROM (PROFILE build).

At every entry of game_update() (keys read from register A):
  1. STATE   all g_* globals equal an independent Python model of game_update/game_hit
             (the model includes the lateral momentum, the coasting drag and the slope's pull)
  2. HIT     game_hit() was called on the previous loop iff the rival geometry (rv[] in WRAM) overlaps
             the player and the player was not invulnerable; every hit also overlaps for real
             (rival body within the player car's rows and columns, no slack)
  3. HUD     the window map at $9C00 reads exactly "SPD sss  LAP ll" / "TIME m:ss.t B m:ss.t" for the state
  4. LAPS    lap length measured from g_zacc deltas is one SEG_LEN (64000/76800/89600 depth units),
             lap time ~ frames/6, best lap = minimum lap time, both independently of the model
  5. LIMITS  |g_cam| <= CAM_LIMIT, speed <= 80, speed <= 18 once settled off the road
A bot steers toward the road centre / drives onto the grass / brakes, to reach all of these.

  6. FLOW    title page -> lap choice -> START -> 3-2-1-GO countdown (keys ignored) -> N laps -> flag -> coast
             -> results page; three races (10, 3, 3 laps): model reset on start, difficulty rises by lap and
             pushes the car harder in bends, race total = sum of the lap times, records only when beaten,
             title / countdown / GO / FINISH / results pages decoded from the window map, rival respawns get
             faster and aim at the player's lane as the difficulty rises
Run on a PROFILE build WITHOUT -DAUTOSTART (make variants -> prof_flow.gb).

  gamecheck.py <prof_flow rom> [--break speed|hit|hud|lap|hill|diff|flow|record|bump|push|banner]   (a deliberately wrong model must FAIL)
"""
import re
import sys
from pathlib import Path
from pyboy import PyBoy

rom = Path(sys.argv[1])
brk = sys.argv[sys.argv.index("--break") + 1] if "--break" in sys.argv else None
syms = {}
for line in rom.with_suffix(".noi").read_text().splitlines():
    m = re.match(r"DEF\s+(\S+)\s+0x([0-9A-Fa-f]+)", line)
    if m:
        syms[m.group(1)] = int(m.group(2), 16)

SPEED_MAX, SPEED_OFF, OFFROAD_PX, CAM_LIMIT, INVULN = 80, 8, 58, 22528, 60
GRASS_DRAG = 8
SEG_LENS = [4000, 4800, 5600]
LAP_OPTS = [3, 5, 10]
TITLE, COUNTDOWN, RACE, FINISHING, RESULTS = range(5)
TRACK_NAMES = ["OVAL", "CANYON", "ALPINE"]
TRACKS = [
    [0, 20, 20, 0, 0, -20, -20, 0, 0, 25, 25, 0, 0, -25, -25, 0],
    [0, 30, 0, -65, -25, 0, 70, 0, -90, 20, 0, -35, 75, 0, -20, 0],
    [0, 55, -70, 50, -85, 0, 80, -60, 70, -55, 0, -90, 75, -70, 45, 0],
]
TRACK_HILLS = [
    [0, 0, 8, 8, 0, 0, -8, -8, 0, 0, 12, 0, 0, -8, 0, 0],
    [0, -24, -48, -48, -16, 16, 24, 8, -32, -40, -12, 0, 24, 16, -24, -8],
    [0, -48, -48, 24, 24, -48, -24, 24, -40, -48, 24, 0, -48, 24, 24, -24],
]
RIGHT, LEFT, UP, DOWN, A, B = 1, 2, 4, 8, 0x10, 0x20
HUD_TILE0 = 128 + int(re.search(r"SKY_TILE_COUNT\s+(\d+)", (Path(__file__).resolve().parent.parent / "src/road_data.h").read_text()).group(1))
CHARS = " 0123456789SPDLATIMEB:.-GRCNWHFOUYVK!/<>"     # tile index = position (tools/gen_hud.py)

def s16(v):
    return ((v + 0x8000) & 0xFFFF) - 0x8000


class Model:
    def __init__(s):
        s.cam = s.curve = s.speed = 0
        s.zacc = 0
        s.lat = 0
        s.steer = s.offroad = s.invuln = s.hits = s.before = s.hit_dx = s.hold = s.extra = 0
        s.steer_dir = s.grace = 0
        s.lap = 1
        s.tenths = s.best = 0
        s.seg = s.f6 = s.accel = s.coast = 0
        s.seg_pos = 0
        s.hill = s.pitch = 0
        s.hill_pull = 0
        s.level = 1
        s.track = 1
        s.state, s.laps_total, s.diff, s.cd, s.cd_tick, s.fin_tick, s.race_tenths = COUNTDOWN, 3, 0, 3, 0, 0, 0
        s.ban_tick, s.ban_text, s.last_place, s.race_iter = 0, None, 3, False

    def place_step(s, place):
        """the OVERTAKEN! / PASSED! banner: one step per race iteration, with that iteration's g_place"""
        if s.ban_tick:
            s.ban_tick -= 1
        elif s.cd_tick >= 60 and place != s.last_place:
            s.ban_text = "     OVERTAKEN!" if place > s.last_place else "      PASSED!"
            if brk == "banner": s.ban_text = "      PASSED!"
            s.ban_tick = 45
        s.last_place = place

    def lap_done(s):
        if s.best == 0 or s.tenths < s.best:
            s.best = s.tenths
        s.race_tenths = (s.race_tenths + s.tenths) & 0xFFFF
        if s.lap >= s.laps_total:
            s.state, s.fin_tick = FINISHING, 0
            return
        s.lap = (s.lap + 1) & 255
        if brk != "diff":
            s.diff = min(s.lap - 1, 4)
        s.tenths = 0
        s.f6 = 0

    def flow(s):
        s.race_iter = (s.state == RACE)
        if s.state == COUNTDOWN:
            s.cd_tick += 1
            if s.cd_tick >= (49 if brk == "flow" else 50):
                s.cd_tick = 0
                if s.cd > 0:
                    s.cd -= 1
                if s.cd == 0:
                    s.state = RACE
        elif s.state == RACE:
            if s.cd_tick < 255:
                s.cd_tick += 1
        elif s.state == FINISHING:
            s.fin_tick += 1
            if s.fin_tick >= 70:
                s.state = RESULTS

    def update(s, keys):
        cap = SPEED_OFF if s.offroad else SPEED_MAX
        if keys & (B | DOWN):
            s.speed -= 2
        elif keys & (A | UP):
            s.accel = (s.accel + 1) & 255
            if (s.speed < 48 or s.accel & 1 == 0) and s.speed < cap:
                s.speed += 1
        else:
            s.coast = (s.coast + 1) & 255
            if (s.coast & (6 if brk == "speed" else 7)) == 0 and s.speed > 0:
                s.speed -= 1 + (s.speed >> 5)                        # coasting: the drag grows with the speed
        s.hill_pull += s.hill                                        # the slope pulls on the speed, Q8 (g_hill is last frame's pitch)
        if s.hill_pull >= 256:
            s.speed += 1
            s.hill_pull -= 256
        elif s.hill_pull <= -256:
            s.speed -= 1
            s.hill_pull += 256
        if s.speed < 0:
            s.speed = 0
        if s.speed > cap:
            s.speed -= GRASS_DRAG
            if s.speed < cap:
                s.speed = cap
        st = (80 if brk == "steer" else 160) + s.speed * (2 if brk == "steer" else 4)
        d = 2 if keys & RIGHT else (1 if keys & LEFT else 0)         # holding a direction turns harder: +1/64 per frame, up to 32
        if d:
            if d == s.steer_dir:
                if s.hold < 32:
                    s.hold += 1
                    s.extra += st >> 6
            else:
                s.hold = s.extra = 0
                s.steer_dir = d
            s.grace = 7                                              # STEER_GRACE + 1: 6 neutral frames still continue the ramp
        elif s.grace:
            s.grace -= 1                                             # keep the ramp across a short release
            if not s.grace:
                s.steer_dir = 0                                      # the gap outlasted the grace: the next press starts fresh
        if brk != "ramp":
            st += s.extra
        if s.offroad:
            st >>= 4
            s.lat >>= 4                                        # the grass throttles the slide too (the ROM does the same)
        s.steer = 0
        if keys & LEFT:
            s.steer = 1
        if keys & RIGHT:
            s.steer = 2
        want = st if s.steer == 2 else (-st if s.steer == 1 else 0)
        if want:                                                     # the tyres close on the asked-for sideways rate
            if s.lat < want:
                s.lat += 256
                if s.lat > want:
                    s.lat = want
            else:
                s.lat -= 256
                if s.lat < want:
                    s.lat = want
        else:                                                        # the wheel is centred: the car washes out
            s.lat += -48 if s.lat > 0 else 48
            if -48 <= s.lat <= 48:
                s.lat = 0
        s.cam += s.lat
        s.seg_pos = (s.seg_pos + s.speed) & 0xFFFF
        if s.seg_pos >= SEG_LENS[s.track]:
            s.seg_pos -= SEG_LENS[s.track]
            s.seg += 1
            if s.seg == 16:
                s.seg = 0
                if s.state == RACE:
                    s.lap_done()
        t = TRACKS[1 if brk == "track" else s.track][s.seg]
        if s.curve < t:
            s.curve = min(s.curve + 2, t)
        elif s.curve > t:
            s.curve = max(s.curve - 2, t)
        th = TRACK_HILLS[s.track][s.seg]
        if s.hill < th:
            s.hill += 1
        elif s.hill > th:
            s.hill -= 1
        s.pitch = s.hill >> (2 if brk == "hill" else 3)
        if brk == "push":                       # the old linear law: must be caught
            push = (s.curve * s.speed) >> 5
            push += (push * s.diff) >> 2
        else:                                   # centrifugal: curve * speed^2, up to x1.5 on later laps
            push = (s.curve * ((min(s.speed, cap) ** 3) >> 11)) >> 3
            push -= push >> 3
            push += (push * s.diff) >> 3
            push += (push * (s.level - 1)) >> 2
            push = max(-1600, min(1600, push))
        s.cam -= push
        s.cam = max(-CAM_LIMIT, min(CAM_LIMIT, s.cam))
        off = s.cam >> 8
        s.offroad = int(off > OFFROAD_PX or off < -OFFROAD_PX)
        s.zacc = (s.zacc + s.speed) & 0xFFFF
        if s.state == RACE:
            s.f6 += 1
            if s.f6 == 6:
                s.f6 = 0
                s.tenths = (s.tenths + 1) & 0xFFFF
        if s.invuln:
            s.invuln -= 1
        s.flow()

    def hit(s):
        s.hits = (s.hits + 1) & 255
        s.before = s.speed
        s.speed >>= 1
        s.invuln = INVULN
        if brk != "bump":                        # the bump: shoved 6 px away from the rival that hit
            s.cam += -6 * 256 if s.hit_dx > 0 else 6 * 256
            s.cam = max(-CAM_LIMIT, min(CAM_LIMIT, s.cam))


pb = PyBoy(str(rom), window="null")
pb.set_emulation_speed(0)
mem = pb.memory
rd8 = lambda n: mem[syms[n]]
rd16 = lambda n: mem[syms[n]] | (mem[syms[n] + 1] << 8)
rds = lambda n: s16(rd16(n))
rds8 = lambda n: rd8(n) - 256 if rd8(n) > 127 else rd8(n)

def actual():
    return dict(cam=rds("_g_cam"), curve=rds("_g_curve"), speed=rds("_g_speed"), zacc=rd16("_g_zacc"),
                lat=rds("_g_lat"),
                steer=rd8("_g_steer"), offroad=rd8("_g_offroad"), invuln=rd8("_g_invuln"), lap=rd8("_g_lap"),
                tenths=rd16("_g_tenths"), best=rd16("_g_best_tenths"), hits=rd8("_g_hits"),
                before=rd8("_g_speed_before_hit"), hill=rds8("_g_hill"), pitch=rds8("_g_pitch"), state=rd8("_g_state"), laps_total=rd8("_g_laps_total"),
                diff=rd8("_g_diff"), cd=rd8("_g_cd"), cd_tick=rd8("_g_cd_tick"), fin_tick=rd8("_g_fin_tick"),
                race_tenths=rd16("_g_race_tenths"), place=rd8("_g_place"), track=rd8("_g_track"))

def rivals():
    out = []
    for i in range(3):                       # two racers + the random traffic car
        b = syms["_rv"] + 9 * i
        out.append(dict(foot=mem[b + 5], w=mem[b + 6], cx=s16(mem[b + 7] | (mem[b + 8] << 8))))
    return out

def expected_hit(inv):
    if inv:
        return False
    thr = 5 if brk == "hit" else 9
    return any(114 <= r["foot"] <= 130 and abs(r["cx"] - 80) < thr + 4 * r["w"] for r in rivals())

def really_overlaps(r):                      # no slack: car rows 109..124, 24 px wide centred on 80
    return 109 <= r["foot"] <= 139 and abs(r["cx"] - 80) < 12 + 4 * r["w"]   # rival rows foot-15..foot

def hud_rows():
    def row(y):
        return [mem[0x9C00 + 32 * y + x] for x in range(20)]
    return [row(y) for y in range(18)]

def text(t):
    return [HUD_TILE0 + CHARS.index(c) for c in t.ljust(20)]

def fmt_time(tn):
    tn = min(tn, 5999)
    return f"{tn // 600}:{(tn // 100) % 6:d}{(tn // 10) % 10:d}.{tn % 10}"

def fmt_total(tn):
    tn = min(tn, 59999)
    return f"{tn // 600:02d}:{(tn % 600) // 10:02d}.{tn % 10}"

def expect_banner(m):
    """row 0 text while a banner owns it, else None"""
    if m.state == COUNTDOWN:
        return "   GET READY  %d" % m.cd
    if m.state == RACE and m.cd_tick < 45:
        return "      GO!"
    if m.state == FINISHING:
        return "    FINISH!"
    if m.state == RACE and m.ban_tick:
        return m.ban_text
    return None

PLACE_NOW = [3]

def expect_hud(m):
    ban = expect_banner(m)
    if ban:
        return text(ban), None                      # row 1 is frozen while a banner shows: not checked
    sp = ((m.speed * 5) >> 1) & 255
    if brk == "hud":
        sp += 1
    r0 = f"SPD {sp:03d} LAP {min(m.lap, 99):02d}/{m.laps_total:02d} P{PLACE_NOW[0]}"
    r1 = "TIME " + fmt_time(m.tenths) + " B " + (fmt_time(m.best) if m.best else "-:--.-")
    return text(r0), text(r1)


m = Model()
fails = []
def fail(kind, msg):
    if len(fails) < 12:
        fails.append(f"{kind}: {msg}")
    st["fail_" + kind] = st.get("fail_" + kind, 0) + 1

st = dict(calls=0, hits=0, hit_overlap_real=0, laps=0, maxspeed=0, offroad_frames=0, offroad_max_settled=0,
          cam_min=0, cam_max=0, pitch_min=0, pitch_max=0, hud_checks=0, lap_lengths=[], hit_cases=0,
          races=0, banner_frames=0, diff_seen=set(), place_checks=0, places_seen=set(), last_place=None)
ctl = dict(hit_fired=False, hit_inv=0, hit_rivals=None, prev_zacc=0, dist=0, total=0, lap_frames=0, lap_times=[],
           prev_tenths=0, prev_lap=1, prev_state=COUNTDOWN, offroad_run=0, first=True, race_no=0, lap_len=16 * SEG_LENS[1],
           started=False)

def on_start(_):
    """game_start_race(): a new race begins; the model restarts and the measurements with it"""
    global m
    m = Model()
    ctl.update(dist=0, total=0, lap_frames=0, lap_times=[], prev_tenths=0, prev_lap=1, prev_state=COUNTDOWN,
               first=True, hit_fired=False, started=False, prev_zacc=0)
    st["last_place"] = None
    sel = rd8("_g_laps_sel")
    m.laps_total = LAP_OPTS[sel]
    m.ban_tick, m.ban_text, m.last_place, m.race_iter = 0, None, 3, False
    m.track = rd8("_g_track")
    m.level = rd8("_g_level")
    ctl["lap_len"] = 16 * SEG_LENS[m.track]
    m.hits = rd8("_g_hits")                      # collisions keep counting across races (the audio watches the counter)
    st["races"] += 1
    ctl["race_no"] += 1
    ctl["poked"] = False

def on_hit(_):
    ctl["hit_fired"] = True
    ctl["hit_inv"] = rd8("_g_invuln")
    ctl["hit_rivals"] = rivals()
    m.hit_dx = rds("_g_hit_dx")
    # the shove direction must come from a rival that really overlaps the player
    ctl["hit_dx_ok"] = ctl.get("hit_dx_ok", 0) + (1 if any(r["foot"] and r["cx"] - 80 == m.hit_dx
                                                           for r in ctl["hit_rivals"]) else 0)
    m.hit()

def on_update(_):
    keys = pb.register_file.A
    a = actual()
    st["calls"] += 1
    # 1. state vs model
    exp = dict(cam=m.cam, curve=m.curve, speed=m.speed, zacc=m.zacc, lat=m.lat, steer=m.steer, offroad=m.offroad,
               invuln=m.invuln, lap=m.lap, tenths=m.tenths, best=m.best, hits=m.hits, before=m.before,
               hill=m.hill, pitch=m.pitch, state=m.state, laps_total=m.laps_total, diff=m.diff, cd=m.cd,
               cd_tick=m.cd_tick, fin_tick=m.fin_tick, race_tenths=m.race_tenths, track=m.track, place=a["place"])
    bad = [k for k in exp if exp[k] != a[k]]
    if bad:
        fail("state", f"call {st['calls']} keys={keys:#x} " + ", ".join(f"{k}: rom {a[k]} model {exp[k]}" for k in bad))
    if m.race_iter and m.state == RACE:                  # the previous iteration's flow step, now that its g_place is known
        m.place_step(a["place"])
        m.race_iter = False
    if ctl["race_no"] == 5 and a["state"] == RACE and a["lap"] == a["laps_total"] and not ctl.get("poked"):
        # coverage of the "YOU WIN!" results page: the bots are not good enough to lead on their own, so on the last lap of race 5
        # both rivals are put 29,000 z16 (1,800 units) behind (their catch-up speed is under 20 z16 a frame: the finish comes first)
        for i_ in range(2):
            b_ = syms["_rv"] + 9 * i_
            mem[b_], mem[b_ + 1] = (-29000) & 255, ((-29000) >> 8) & 255
        ctl["poked"] = True
        ctl["skip_place"] = True                     # g_place is recomputed after this call
    # keys the game was given: none in the countdown, only the brake after the flag
    if a["state"] == COUNTDOWN and keys != 0:
        fail("flow", f"keys {keys:#x} reached game_update during the countdown")
    if a["state"] == FINISHING and keys != B:
        fail("flow", f"keys {keys:#x} during the finish coast (want brake only)")
    st["diff_seen"].add(a["diff"])
    ahead = 1 + sum(1 for i_ in range(2) if s16(mem[syms["_rv"] + 9 * i_] | (mem[syms["_rv"] + 9 * i_ + 1] << 8)) > 49 * 16 + (400 if brk == "place" else 0))
    if a["state"] in (COUNTDOWN, RACE):
        st["place_checks"] += 1
        st["places_seen"].add(a["place"])
        skip_ = ctl.pop("skip_place", False)
        if a["place"] != ahead and not skip_:
            fail("place", f"call {st['calls']} g_place {a['place']} but {ahead - 1} rivals are ahead")
        st["last_place"] = a["place"]
    elif a["state"] == FINISHING and a["place"] != st["last_place"]:
        fail("frozen", f"call {st['calls']} place changed after the flag: {st['last_place']} -> {a['place']}")
    # 2. collision
    if not ctl["first"]:
        inv = ctl["hit_inv"] if ctl["hit_fired"] else a["invuln"]
        want = expected_hit(inv)
        if want != ctl["hit_fired"]:
            fail("hit", f"call {st['calls']} fired={ctl['hit_fired']} expected={want} inv={inv} rivals={rivals()}")
        if ctl["hit_fired"]:
            st["hits"] += 1
            if any(really_overlaps(r) for r in ctl["hit_rivals"]):
                st["hit_overlap_real"] += 1
    ctl["first"] = False
    ctl["hit_fired"] = False
    # 3. HUD
    PLACE_NOW[0] = a["place"]
    rows = hud_rows()
    e0, e1 = expect_hud(m)
    st["hud_checks"] += 1
    if expect_banner(m):
        st["banner_frames"] += 1
    if rows[0] != e0 or (e1 is not None and rows[1] != e1):
        fail("hud", f"call {st['calls']} state {m.state} rows {rows[0]} {rows[1]} != {e0} {e1}")
    # 3b. hill range
    st["pitch_min"], st["pitch_max"] = min(st["pitch_min"], a["pitch"]), max(st["pitch_max"], a["pitch"])
    scy = mem[0xFF42]
    scy = scy - 256 if scy > 127 else scy
    if not (-6 <= scy <= 3) or not (-6 <= a["pitch"] <= 3):
        fail("hill", f"pitch {a['pitch']} SCY {scy} outside -6..3")
    # 4. laps, measured independently of the model (from the first frame after GO)
    if a["state"] == RACE and not ctl["started"]:
        ctl.update(started=True, dist=0, total=0, lap_frames=0, prev_zacc=a["zacc"], prev_tenths=a["tenths"], prev_lap=a["lap"])
    if ctl["started"]:
        d = (a["zacc"] - ctl["prev_zacc"]) & 0xFFFF
        ctl["dist"] += d
        ctl["total"] += d
        ctl["prev_zacc"] = a["zacc"]
        ctl["lap_frames"] += 1
        closed = a["lap"] != ctl["prev_lap"] or (a["state"] == FINISHING and ctl["prev_state"] == RACE)
        if closed:
            lt = ctl["prev_tenths"]
            n = len(ctl["lap_times"]) + 1
            ctl["lap_times"].append(lt)
            st["laps"] += 1
            st["lap_lengths"].append(ctl["dist"])
            base = ctl["lap_len"] - 400 if brk == "lap" else ctl["lap_len"]
            if not (n * base <= ctl["total"] < n * base + SPEED_MAX):
                fail("lap", f"lap {n} total distance {ctl['total']}")
            frames = ctl["lap_frames"] - 1
            if frames and abs(lt - frames / 6) > 1.01:
                fail("lap", f"lap time {lt} vs {frames} frames")
            if a["best"] != min(ctl["lap_times"]):
                fail("lap", f"best {a['best']} != min {min(ctl['lap_times'])}")
            ctl["dist"] = 0
            ctl["lap_frames"] = 1
        ctl["prev_lap"] = a["lap"]
        ctl["prev_tenths"] = a["tenths"]
    ctl["prev_state"] = a["state"]
    # 5. limits
    st["maxspeed"] = max(st["maxspeed"], a["speed"])
    st["cam_min"], st["cam_max"] = min(st["cam_min"], a["cam"]), max(st["cam_max"], a["cam"])
    if abs(a["cam"]) > CAM_LIMIT or a["speed"] > SPEED_MAX or a["speed"] < 0:
        fail("limit", f"cam {a['cam']} speed {a['speed']}")
    if a["offroad"]:
        st["offroad_frames"] += 1
        ctl["offroad_run"] += 1
        if ctl["offroad_run"] > 40 and a["state"] == RACE:
            st["offroad_max_settled"] = max(st["offroad_max_settled"], a["speed"])
            if a["speed"] > SPEED_OFF:
                fail("limit", f"off road at speed {a['speed']}")
    else:
        ctl["offroad_run"] = 0
    m.update(keys)

pb.hook_register(0, syms["_game_update"], on_update, None)
pb.hook_register(0, syms["_game_hit"], on_hit, None)
pb.hook_register(0, syms["_game_start_race"], on_start, None)

btn_state = set()
def hold(want):
    for b in btn_state - want:
        pb.button_release(b)
    for b in want - btn_state:
        pb.button_press(b)
    btn_state.clear()
    btn_state.update(want)

def run(n):
    for _ in range(n):
        pb.tick()

def tap(b, n=8):
    hold({b}); run(n); hold(set()); run(6)

def bot(mode):
    cam = rds("_g_cam") >> 8
    want = set()
    if mode == "centre":                # accelerate and steer back to the middle of the road
        want.add("a")
        if cam > 6:
            want.add("left")
        elif cam < -6:
            want.add("right")
    elif mode == "right_grass":         # floor it and hold right: runs onto the grass
        want |= {"a", "right"}
    elif mode == "left_grass":
        want |= {"up", "left"}
    elif mode == "brake":
        want.add("b")
    elif mode == "coast":
        pass
    elif mode == "coast_centre":        # lift off at speed and let it roll down (exercises the coast branch)
        if cam > 6:
            want.add("left")
        elif cam < -6:
            want.add("right")
    elif mode == "weave":               # wobble across the road at speed
        want.add("a")
        want.add("left" if (rd16("_g_zacc") >> 9) & 1 else "right")
    elif mode == "dodge":               # a good driver: brakes for bends (best line rides the road width), steers round cars ahead
        sp_ = rd16("_g_speed")
        w_ = abs(TRACKS[m.track][m.seg])
        if m.seg_pos > SEG_LENS[m.track] // 2:
            w_ = max(w_, abs(TRACKS[m.track][(m.seg + 1) % 16]))
        vs_ = 80
        while vs_ > 20 and (w_ * ((vs_ ** 3) >> 11) >> 3) > 1.5 * (160 + 4 * vs_):
            vs_ -= 1
        if sp_ < vs_ - 1: want.add("a")
        elif sp_ > vs_ + 1: want.add("b")
        pl = max(-36, min(36, cam))
        want |= {"left"} if pl > 6 else ({"right"} if pl < -6 else set())
        for i_ in range(3):
            b_ = syms["_rv"] + 9 * i_
            zz = s16(mem[b_] | (mem[b_ + 1] << 8))
            ln = mem[b_ + 2] - 256 if mem[b_ + 2] > 127 else mem[b_ + 2]
            if 49 * 16 < zz < 49 * 16 + 90 * 16 and abs(ln - pl) < 30:
                want -= {"left", "right"}
                want.add("left" if ln >= pl and pl > -20 else "right")
    elif mode == "down_centre":
        want.add("down" if rd8("_g_speed") > 30 else "up")
        if cam > 6:
            want.add("left")
        elif cam < -6:
            want.add("right")
    return want

def page_rows():
    return [bytes(mem[0x9C00 + 32 * y + x] for x in range(20)) for y in range(18)]

def expect_page(lines):
    """lines: {row: (x, string)} everything else blank"""
    rows = [[HUD_TILE0] * 20 for _ in range(18)]
    for y, (x, t) in lines.items():
        for k, c in enumerate(t):
            rows[y][x + k] = HUD_TILE0 + CHARS.index(c)
    return [bytes(r) for r in rows]

page_fail = []
def check_page(name, lines, wy=0):
    got, want = page_rows(), expect_page(lines)
    if got != want or mem[0xFF4A] != wy:
        bad = [y for y in range(18) if got[y] != want[y]]
        page_fail.append(f"{name}: rows {bad} differ, WY {mem[0xFF4A]}")
    st.setdefault("pages", []).append(name)

def race_until_results(plan, limit=60 * 700):
    n = 0
    while rd8("_g_state") != RESULTS and n < limit:
        for mode, k in plan:
            for _ in range(k):
                hold(bot(mode))
                pb.tick()
                n += 1
                if rd8("_g_state") == RESULTS:
                    break
            if rd8("_g_state") == RESULTS:
                break
    hold(set())
    return n

PLAN_FAST = [("centre", 1500), ("right_grass", 150), ("centre", 900), ("coast_centre", 200), ("centre", 300), ("brake", 100),
             ("left_grass", 150), ("weave", 400), ("down_centre", 300), ("centre", 2500)]
PLAN_SLOW = [("centre", 200), ("brake", 120), ("coast_centre", 150), ("weave", 200)]
def title_lines(track, sel, best):
    return {2: (6, "GB RACER"), 4: (3, "TRACK"), 6: (5, "LAPS < %02d >" % LAP_OPTS[sel]),
            8: (3, "LEVEL NORMAL"),
            10: (4, "BEST " + (fmt_total(best) if best else "--:--.-")),
            12: (3, "UP DOWN TRACK"), 13: (3, "LEFT RIGHT LAPS"), 14: (3, "SELECT LEVEL"), 15: (3, "A GAS  B BRAKE"),
            17: (4, "PRESS START")}

def check_title(name, track, sel, best):
    lines = title_lines(track, sel, best)
    lines[4] = (3, "TRACK " + TRACK_NAMES[track])
    check_page(name, lines)

def best_total(track, sel):
    return mem[syms["_g_best_total"] + 2 * ((1 * 3 + track) * 3 + sel)] | (mem[syms["_g_best_total"] + 2 * ((1 * 3 + track) * 3 + sel) + 1] << 8)   # level 1 = NORMAL

def pick(track, sel):
    """navigate the title screen to (track, laps) with real button presses"""
    for _ in range(3):
        tap("up")
    for _ in range(track):
        tap("down")
    for _ in range(3):
        tap("left")
    for _ in range(sel):
        tap("right")
    assert (rd8("_g_track"), rd8("_g_laps_sel")) == (track, sel), (rd8("_g_track"), rd8("_g_laps_sel"))

def results_lines(r):
    ln = {3: (6, "FINISH!"), 4: (6, TRACK_NAMES[r["track"]]), 6: (3, "TIME  " + fmt_total(r["total"])), 8: (3, "BEST LAP " + fmt_time(r["best"])),
          10: (4, "PLACE %d OF 3" % r["place"]), 13: (4, "NEW RECORD!"), 15: (4, "PRESS START")}
    if r["place"] == 1:
        ln[12] = (6, "YOU WIN!")
    if not r["rec"]:
        del ln[13]
    return ln

run(120)
assert rd8("_g_state") == TITLE
check_title("title", 0, 0, 0)
tap("down"); tap("down"); tap("down")                     # OVAL -> CANYON -> ALPINE, stops at the end
assert rd8("_g_track") == 2
check_title("title_alpine", 2, 0, 0)
tap("up"); tap("up"); tap("up")                           # and back to OVAL, stops at the start
assert rd8("_g_track") == 0
tap("right"); tap("right"); tap("right")                  # 3 -> 5 -> 10 laps, stops at the end
assert rd8("_g_laps_sel") == 2
check_title("title10", 0, 2, 0)

# the races: (track, laps option, bot plan, name)
RACES = [(0, 2, PLAN_FAST, "OVAL 10 laps"), (2, 0, [("dodge", 600)], "ALPINE 3 laps, driven well"),
         (2, 0, PLAN_SLOW, "ALPINE 3 laps again, slowly"), (1, 0, [("dodge", 600)], "CANYON 3 laps"),
         (0, 0, [("dodge", 600)], "OVAL 3 laps, driven well")]
race_results = []
for k, (trk, sel, plan, name) in enumerate(RACES):
    if k:
        pick(trk, sel)
        check_title("title_before_%d" % (k + 1), trk, sel, best_total(trk, sel))
    hold({"a"}); run(5)
    tap("start", 8)
    hold({"a", "right"})                                   # gas and steering held through the countdown must be ignored
    run(20)
    race_until_results(plan)
    r = dict(name=name, track=rd8("_g_track"), place=rd8("_g_place"), total=rd16("_g_race_tenths"), best=rd16("_g_best_tenths"),
             rec=rd8("_g_new_record"), laps=list(ctl["lap_times"]), sel=rd8("_g_laps_sel"), bt=best_total(trk, sel))
    race_results.append(r)
    run(2)
    check_page("results%d" % (k + 1), results_lines(r))
    tap("start"); run(20)
    assert rd8("_g_state") == TITLE
pb.stop(save=False)

# ---- flow results ----
flow_ok = True
want_laps = [10, 3, 3, 3, 3]
for k, r in enumerate(race_results):
    tot_ok = r["total"] == sum(r["laps"]) and len(r["laps"]) == want_laps[k]
    best_ok = r["best"] == min(r["laps"])
    print(f"  race {k + 1} ({r['name']}): {len(r['laps'])} laps (wanted {want_laps[k]}), lap times {r['laps']}, total {r['total']} "
          f"(= sum: {tot_ok}), best lap {r['best']}, place {r['place']}, new record {r['rec']}")
    flow_ok &= tot_ok and best_ok and r["track"] == RACES[k][0]
rr = race_results
rec_ok = (rr[0]["rec"] == 1 and rr[1]["rec"] == 1 and rr[2]["rec"] == 0 and rr[3]["rec"] == 1
          and rr[2]["bt"] == rr[1]["total"] and rr[3]["bt"] == rr[3]["total"] and rr[4]["rec"] == 1 and rr[4]["bt"] == rr[4]["total"])
if brk == "record":
    rec_ok = rr[2]["rec"] == 1
print(f"  records per track and length: OVAL/10 new={rr[0]['rec']}, ALPINE/3 new={rr[1]['rec']}, a slower ALPINE/3 new={rr[2]['rec']} "
      f"(stored best stays {rr[2]['bt']} = race 2 total {rr[1]['total']}), CANYON/3 new={rr[3]['rec']}, OVAL/3 new={rr[4]['rec']}: {rec_ok}")
flow_ok &= rec_ok
print("  pages:", ", ".join(st["pages"]), "->", "all decoded correctly" if not page_fail else page_fail)

# ---- race position ----
print(f"  race position: g_place == 1 + rivals ahead on {st['place_checks']} frames ({st.get('fail_place', 0)} wrong), frozen after the flag "
      f"({st.get('fail_frozen', 0)} wrong); places seen {sorted(st['places_seen'])}; results show {[r_['place'] for r_ in race_results]}")
places_ok = 1 in [r_["place"] for r_ in race_results] and 3 in [r_["place"] for r_ in race_results]
if not places_ok:
    print("  the five races did not give both a win and a last place, so the results page was not exercised for both")
diff_ok = (places_ok and st.get("fail_place", 0) == 0 and st.get("fail_frozen", 0) == 0 and 1 in st["places_seen"] and 3 in st["places_seen"]
           and sorted(st["diff_seen"]) == [0, 1, 2, 3, 4])
print(f"  difficulty levels reached: {sorted(st['diff_seen'])}")

print(f"{rom.name}: {st['calls']} game_update calls over {st['races']} races; max speed {st['maxspeed']}, cam {st['cam_min']}..{st['cam_max']}")
print(f"  state vs model: {st.get('fail_state', 0)} mismatching frames (incl. state machine, countdown, difficulty, flag)")
print(f"  collisions: {st['hits']} hits, {st['hit_overlap_real']} with a real (no-slack) overlap; "
      f"hit/no-hit disagreements: {st.get('fail_hit', 0)}; shove direction taken from a real rival {ctl.get('hit_dx_ok', 0)}/{st['hits']}")
print(f"  HUD: {st['hud_checks']} frames decoded from the window map ({st['banner_frames']} with a banner), {st.get('fail_hud', 0)} wrong")
print(f"  laps: {st['laps']} completed; lengths {sorted(set(st['lap_lengths']))[:3]}..; lap checks failed {st.get('fail_lap', 0)}; "
      f"flow checks failed {st.get('fail_flow', 0)}")
print(f"  hills: pitch range {st['pitch_min']}..{st['pitch_max']} lines; range failures {st.get('fail_hill', 0)}")
print(f"  off road: {st['offroad_frames']} frames, max speed once settled {st['offroad_max_settled']} (cap {SPEED_OFF}); "
      f"limit failures {st.get('fail_limit', 0)}")
for f in fails:
    print("  FAIL", f)
ok = (not fails and not page_fail and flow_ok and diff_ok and st["hits"] >= 5 and st["laps"] >= 18 and st["offroad_frames"] > 200
      and st["hit_overlap_real"] == st["hits"] and ctl.get("hit_dx_ok", 0) == st["hits"] and st["pitch_min"] <= -5 and st["pitch_max"] >= 2 and st["races"] == 5)
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
