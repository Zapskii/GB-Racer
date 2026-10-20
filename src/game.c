/*
 * Game state: speed, steering, the looping track, lap timing.
 *
 * Controls   A / UP : accelerate        B / DOWN : brake        LEFT / RIGHT : steer
 *
 * Track      16 segments (length per track, SEG_LEN) each; the curvature eases towards the
 *            current segment's value.  The player's distance advances at g_speed per frame, the same
 *            rate the stripes scroll, so segment changes line up with what you see.
 *            The road the player SEES and the bend that pushes the car are the same one
 *            (g_vcurve = g_curve): they must never disagree, or the car is thrown off the
 *            outside of the bend it is really in while the player steers into the one they
 *            can see.  The advance warning is the sky sign, not the road's shape.
 *
 * Physics    * steering is weaker at low speed, and the tyres take a couple of frames to
 *              build the sideways rate up (g_lat), so the car slides on and washes out
 *            * curves push the car towards the outside, in proportion to speed^3 * curvature
 *            * more than OFFROAD_PX from the road centre = on the grass: speed is capped and
 *              the steering and the slide are both throttled
 *            * the slope pulls on the speed; coasting drags harder the faster you go
 */
#include <gb/gb.h>
#include "game.h"

#define SEG_COUNT   16

/* Three tracks.  Per segment: curvature (+-100 is the most the road drawing and the car's steering cope with; hairpins use 70..90) and hill pitch in 1/8 line units
   (negative = climbing: the horizon drops, positive = descending: it rises; the allowed range is HILL_MIN..HILL_MAX),
   plus the segment length (a lap is 16 segments).  Names use only letters the HUD font has (tools/gen_hud.py). */
const char * const track_name[N_TRACKS] = { "OVAL", "CANYON", "ALPINE" };
const char * const level_name[N_LEVELS] = { "EASY", "NORMAL", "HARD" };

static const int8_t track_curve[N_TRACKS][SEG_COUNT] = {
    {   0,  20,  20,   0,   0, -20, -20,   0,       /* OVAL: two wide sweeps each way, nothing sharp */
        0,  25,  25,   0,   0, -25, -25,   0 },
#ifdef CANYON_CLASSIC                            /* the original gentler bends: the reference for tools/oamcmp.py */
    {   0,  30,   0, -40, -25,   0,  45,   0,
      -50,  20,   0, -35,  40,   0, -20,   0 },
#else
    {   0,  30,   0, -65, -25,   0,  70,   0,       /* CANYON: a mix of bends, three of them tight */
      -90,  20,   0, -35,  75,   0, -20,   0 },
#endif
    {   0,  55, -70,  50, -85,   0,  80, -60,       /* ALPINE: back-to-back hairpins */
       70, -55,   0, -90,  75, -70,  45,   0 }
};

#ifdef HILLS_OFF
static const int8_t track_hill[N_TRACKS][SEG_COUNT] = {
    { 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
    { 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
    { 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 }
};
#else
static const int8_t track_hill[N_TRACKS][SEG_COUNT] = {
    {   0,   0,   8,   8,   0,   0,  -8,  -8,       /* OVAL: almost flat */
        0,   0,  12,   0,   0,  -8,   0,   0 },
    {   0, -24, -48, -48, -16,  16,  24,   8,       /* CANYON: rolling */
      -32, -40, -12,   0,  24,  16, -24,  -8 },
    {   0, -48, -48,  24,  24, -48, -24,  24,       /* ALPINE: steep climbs, then drops */
      -40, -48,  24,   0, -48,  24,  24, -24 }
};
#endif

#ifdef SEG_LEN16                                /* test builds can force one length for every track */
#define SEG_LEN(t) ((uint16_t)SEG_LEN16)
#else
static const uint16_t seg_len[N_TRACKS] = { 4000, 4800, 5600 };      /* 1/16 depth units: laps of 64000, 76800, 89600 */
#define SEG_LEN(t) seg_len[t]
#endif

/* speed^3 >> 11 for speed 0..80 */
static const uint8_t cube_q[81] = { 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 5, 5, 6, 7, 8, 9, 10, 11, 13, 14, 16, 17, 19, 20, 22, 24, 26, 28, 31, 33, 36, 38, 41, 44, 47, 50, 54, 57, 61, 64, 68, 72, 76, 81, 85, 90, 95, 100, 105, 110, 116, 122, 128, 134, 140, 146, 153, 160, 167, 174, 182, 189, 197, 205, 214, 222, 231, 240, 250 };

const uint8_t lap_options[N_LAP_OPTIONS] = { 3, 5, 10 };
uint8_t  g_place, g_state, g_laps_sel, g_laps_total, g_diff, g_cd, g_cd_tick, g_fin_tick, g_new_record;
uint16_t g_race_tenths, g_best_total[N_LEVELS][N_TRACKS][N_LAP_OPTIONS];
uint8_t  g_level = 1, g_paused;
int16_t  g_hit_dx;
uint8_t  g_track;
int8_t   g_hill, g_pitch;
int16_t  g_cam, g_curve, g_vcurve, g_speed;
int8_t   g_warn;
uint8_t  g_warn_hot;
uint16_t g_zacc;
uint8_t  g_steer, g_offroad, g_invuln, g_lap;
uint16_t g_tenths, g_best_tenths;
uint8_t  g_hits, g_speed_before_hit;
int16_t  g_lat;                     /* the car's sideways speed, 1/256 px per frame (the tyres have to build it up) */

static uint8_t  seg, f6, accel_tick, coast_tick, peeked, steer_hold, steer_extra, steer_dir, steer_grace;
static uint16_t seg_pos;
static int16_t  hill_pull;                /* the slope's pull on the speed, Q8 (the fraction carries over) */

static void reset_race_vars(void)
{
    g_cam = g_curve = g_vcurve = g_speed = 0;
    g_lat = 0;
    hill_pull = 0;
    g_warn = g_warn_hot = peeked = steer_hold = steer_extra = steer_dir = steer_grace = 0;
    g_hill = g_pitch = 0;
    g_zacc = 0;
    g_steer = g_offroad = g_invuln = g_speed_before_hit = 0;
    g_lap = 1;
    g_tenths = g_best_tenths = 0;
    g_race_tenths = 0;
    g_diff = 0;
    g_place = 3;
    seg = f6 = accel_tick = coast_tick = 0;
    seg_pos = 0;
}

void game_init(void)
{
    reset_race_vars();
    g_hits = 0;
    g_laps_sel = 0;
    g_laps_total = lap_options[0];
    g_new_record = 0;
    g_track = 0;
    g_level = 1;
    g_paused = 0;
    sram_load();                                /* records and the last title selections, if the cartridge has a valid save */
    g_laps_total = lap_options[g_laps_sel];
    g_state = ST_TITLE;
    g_cd = g_cd_tick = g_fin_tick = 0;
#ifdef AUTOSTART                                /* test builds: straight into an endless race, no title/countdown */
    g_laps_total = 99;
    g_track = 1;                                /* the CANYON: the track the sprite/hill/audio checks were written against */
    g_state = ST_RACE;
#endif
}

void game_start_race(void)
{
    reset_race_vars();                          /* g_hits keeps counting: the audio watches it for crashes */
    g_laps_total = lap_options[g_laps_sel];
    g_new_record = 0;
    g_state = ST_COUNTDOWN;
    g_cd = 3;
    g_cd_tick = 0;
    g_fin_tick = 0;
}

void game_finish_record(void)
{
    g_new_record = 0;
    if (g_best_total[g_level][g_track][g_laps_sel] == 0 || g_race_tenths < g_best_total[g_level][g_track][g_laps_sel]) {
        g_best_total[g_level][g_track][g_laps_sel] = g_race_tenths;
        g_new_record = 1;
        sram_save();
    }
}

static void set_diff(void)
{
#ifndef DIFF_OFF
    g_diff = g_lap - 1 > DIFF_MAX ? DIFF_MAX : (uint8_t)(g_lap - 1);
#endif
}

static void lap_done(void)
{
    if (g_best_tenths == 0 || g_tenths < g_best_tenths)
        g_best_tenths = g_tenths;
    g_race_tenths += g_tenths;
    if (g_lap >= g_laps_total) {                /* the flag: g_tenths keeps the last lap's time */
        g_state = ST_FINISHING;
        g_fin_tick = 0;
        return;
    }
    g_lap++;
    set_diff();
    g_tenths = 0;
    f6 = 0;
}

static int16_t ease(int16_t v, int16_t t, int16_t d)   /* one frame of easing towards a curvature target, d per frame */
{
    if (v < t)      { v += d; if (v > t) v = t; }
    else if (v > t) { v -= d; if (v < t) v = t; }
    return v;
}

static void clamp_cam(void)
{
    if (g_cam >  CAM_LIMIT) g_cam =  CAM_LIMIT;
    if (g_cam < -CAM_LIMIT) g_cam = -CAM_LIMIT;
}

void game_update(uint8_t keys)
{
    int16_t cap = g_offroad ? SPEED_OFFROAD : SPEED_MAX;
    int16_t st, target, off, push;

    /* ---- speed ---- */
    if (keys & (J_B | J_DOWN)) {                /* the brake wins: you can slow for a bend without releasing the gas */
        g_speed -= 2;
    } else if (keys & (J_A | J_UP)) {
        ++accel_tick;                           /* pick-up is quick up to 48 (a bend costs less to re-accelerate from), slower above */
        if ((g_speed < ACCEL_FAST || (accel_tick & 1) == 0) && g_speed < cap)
            g_speed++;
    } else if (((++coast_tick) & 7) == 0 && g_speed > 0) {
        g_speed -= 1 + (g_speed >> COAST_SHIFT);   /* coasting: the drag grows with the speed */
    }
#ifndef HILLS_OFF
    /* the slope pulls on the speed: climbing (g_hill < 0) bleeds it off, descending gives it back.
       The pull is Q8 and the fraction carries over, so a gentle slope costs a little and a steep
       one costs a lot.  g_hill is last frame's pitch, so the pull lags the road by a frame. */
    hill_pull += (int16_t)g_hill * HILL_PULL;
    if (hill_pull >= 256)      { g_speed++; hill_pull -= 256; }
    else if (hill_pull <= -256) { g_speed--; hill_pull += 256; }
#endif
    if (g_speed < 0) g_speed = 0;
    if (g_speed > cap) {                        /* e.g. just drove onto the grass */
        g_speed -= GRASS_DRAG;                  /* the grass drags hard */
        if (g_speed < cap) g_speed = cap;
    }

    /* ---- steering: weak when slow ---- */
    st = STEER_BASE + g_speed * STEER_GAIN;
#ifndef LEGACY_PHYSICS
    /* the longer you hold a direction the harder the car turns in: +1/64 per frame held, up to +STEER_RAMP/64 (50%) after half a second */
    {
        uint8_t dir;
        if (keys & J_RIGHT) dir = 2;
        else if (keys & J_LEFT) dir = 1;
        else dir = 0;
        if (dir) {
            if (dir == steer_dir) {
                if (steer_hold < STEER_RAMP) { steer_hold++; steer_extra += st >> 6; }   /* (adds st/64 per frame held: no multiplication in the loop) */
            } else {
                steer_hold = steer_extra = 0; steer_dir = dir;
            }
            steer_grace = STEER_GRACE + 1;
        } else if (steer_grace && !--steer_grace) {
            steer_dir = 0;                 /* the release lasted longer than the grace: the next press starts fresh */
        }
        st += steer_extra;
    }
    if (g_offroad) st >>= 4;                    /* on the grass the car steers at a sixteenth rate: leaving it costs more than the old push spiral */
    if (g_offroad) g_lat >>= 4;                /* the grass throttles the slide too: without this the momentum lets the car wash back onto the road for free */
#endif
    g_steer = 0;
    if (keys & J_LEFT)  { g_steer = 1; }
    if (keys & J_RIGHT) { g_steer = 2; }
#ifdef LEGACY_PHYSICS
    if (g_steer == 1)  g_cam -= st;
    if (g_steer == 2)  g_cam += st;
#else
    /* ---- lateral momentum: the tyres have to build the sideways rate up, and it bleeds off ----
       g_lat is the car's sideways speed in 1/256 px per frame, signed: positive = sliding right.
       The wheel asks for +st (right) or -st (left); the tyres close on that rate at GRIP per
       frame, and with the wheel centred the rate decays by LAT_DECAY.  The car slides when the
       wheel is released (it keeps going, then washes out) and a bend is held by counter-steering
       into the slide, not by the car being a cursor the bend pushes around. */
    {
        int16_t want = 0;
        if (g_steer == 2) want = st;
        else if (g_steer == 1) want = -st;
        if (want) {                              /* the tyres close on the asked-for rate */
            if (g_lat < want) { g_lat += GRIP; if (g_lat > want) g_lat = want; }
            else              { g_lat -= GRIP; if (g_lat < want) g_lat = want; }
        } else {                                 /* the wheel is centred: the car washes out */
            g_lat += (g_lat > 0) ? -LAT_DECAY : LAT_DECAY;
            if (g_lat >= -LAT_DECAY && g_lat <= LAT_DECAY) g_lat = 0;
        }
        g_cam += g_lat;
    }
#endif

    /* ---- track position and curvature ---- */
    seg_pos += (uint16_t)g_speed;
    if (seg_pos >= SEG_LEN(g_track)) {
        seg_pos -= SEG_LEN(g_track);
        peeked = 0;
        if (++seg == SEG_COUNT) {
            seg = 0;
            if (g_state == ST_RACE)
                lap_done();
        }
    }
#ifdef LEGACY_PHYSICS
    g_curve = ease(g_curve, track_curve[g_track][seg], 2);
    g_vcurve = g_curve;
#else
    /* One curvature for the road and for the car.  The picture and the push must agree:
       if the drawn road bends one way and the push acts the other way, the car is thrown
       off the outside of the bend the player is looking at, and a "sharp left then sharp
       right" corner is felt as a straight run off the road.  Pole Position (1982) works
       the same way: the curve is sampled at the car's own position and the visual road
       uses the same data, so the picture and the physics are in phase.  The road's shape
       eases in over ~45 frames (CURVE_EASE per frame), so the bend is seen before it is
       fully felt.

       Advance warning lives in the SIGN, not in the road's shape: the sky sign shows the
       next segment's bend once it is LEAD_FRAMES frames of driving away, and keeps
       showing it (braking does not make the bend "unwind").  It flashes while you are
       faster than the bend allows (g_warn: +- 1..3 chevrons, 0 none). */
    if (!peeked && seg_pos + (uint16_t)((g_speed << 5) + (g_speed << 4)) >= SEG_LEN(g_track))
        peeked = 1;
    target = track_curve[g_track][peeked ? (seg + 1) & (SEG_COUNT - 1) : seg];
    g_warn = 0;
    if (peeked && (target >= WARN_MIN || target <= -WARN_MIN)) {
        uint8_t m = (uint8_t)(target < 0 ? -target : target);
        uint8_t n = m < 55 ? 1 : (m < 75 ? 2 : 3);
        g_warn_hot = g_speed > (n == 1 ? 72 : (n == 2 ? 62 : 52));
        g_warn = target < 0 ? -(int8_t)n : (int8_t)n;
    }
    g_curve = ease(g_curve, track_curve[g_track][seg], CURVE_EASE);
    g_vcurve = g_curve;                        /* the picture and the push are the same bend */
#endif

    /* ---- hill pitch: ease towards the segment's value, one step per frame ---- */
    if (g_hill < track_hill[g_track][seg])      g_hill++;
    else if (g_hill > track_hill[g_track][seg]) g_hill--;
    g_pitch = g_hill >> 3;

    /* ---- curves push the car outwards (right-hand bend: curve > 0 pushes left) ---- */
#ifdef LEGACY_PHYSICS                              /* the original law: the reference for tools/oamcmp.py */
    push = (g_curve * g_speed) >> 5;
    push += (push * g_diff) >> 2;                /* harder laps: the bends push up to twice as hard */
#else
    /* centrifugal: grows with the CUBE of the speed (push = curve * speed^3 / 16384, from a table), so a tight bend cannot be held
       flat out.  The steering answers 160 + 4*speed (480 at 80).  A curve of 90 pushes 2,800 at speed 80, six times that: off the road in
       a few frames; the best line rides the road's width and slows to ~50 there, ~60 for a 70, ~70 for a 50.  30 and below can be taken
       flat out.  Later laps push harder (x1.5 by lap 5).  The level scales it too: EASY 0.75x, NORMAL 1x, HARD 1.25x.  The table is
       indexed by the grass cap off road, so the push vanishes once that cap applies. */
    push = (g_curve * cube_q[g_speed > cap ? (uint8_t)cap : (uint8_t)g_speed]) >> 3;
    push -= push >> 3;                           /* toned down by an eighth: bends were too violent, but held steering now turns harder (STEER_RAMP) */
    push += (push * g_diff) >> 3;
    push += (push * ((int8_t)g_level - 1)) >> 2;
    if (push >  PUSH_MAX) push =  PUSH_MAX;      /* a hairpin taken far too fast used to fling the car ~10 px a frame: now it slides out over a second */
    if (push < -PUSH_MAX) push = -PUSH_MAX;
#endif
    g_cam -= push;
    clamp_cam();

    off = g_cam >> 8;
    g_offroad = (off > OFFROAD_PX || off < -OFFROAD_PX);

    g_zacc += (uint16_t)g_speed;

    /* ---- timers ---- */
    if (g_state == ST_RACE && ++f6 == 6) { f6 = 0; g_tenths++; }
    if (g_invuln) g_invuln--;
}

void game_hit(void)
{
    g_hits++;
    g_speed_before_hit = (uint8_t)g_speed;
    g_speed >>= 1;
    g_invuln = INVULN_FRAMES;
#ifndef TRAFFIC                                 /* bump: the cars shove each other apart (sprites.c moves the rival) */
    g_cam += g_hit_dx > 0 ? -BUMP_PX * 256 : BUMP_PX * 256;
    clamp_cam();
#endif
}
