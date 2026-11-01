/*
 * Player car + rival cars.
 *
 * Projection: a rival has a depth z (1/16 depth-units) and a lane (1/64 of the road's
 * half-width).  Road line y = y_of_z[z/16] (the inverse of the stripe depth), so cars move at
 * exactly the speed the stripes scroll.  Screen x follows the road: the road centre on line y is
 * 80 - (scx[y] - SCX_BASE), plus lane * half-width(y).  Reading the SCX table that was just
 * built means cars follow curves and steering with no extra maths.
 *
 * Two modes.  Default: the rivals are RACERS.  Each keeps its true distance from the player (z16 may be
 * negative = behind you, or beyond the fog = ahead and out of sight), drives at its own cruise speed (faster
 * each lap) with a bit of rubber banding, wanders between lanes, blocks you from lap 3 and gives way when it
 * is about to pass you.  The race position is 1 + the number of rivals ahead.  -DTRAFFIC selects the old
 * oncoming-traffic behaviour (rivals respawn far away when passed), used to check the sprite engine.
 *
 * Size: three pre-drawn sizes (8, 16, 24 px wide) picked by road line.
 *
 * ISR timing: the HBlank ISR's last palette write must land before the next line's pixel
 * fetch, which gets later with more sprites on a line.  We keep <= 6 objects on any line.
 * The player (3 objects) is fixed; when two rivals plus the player would exceed 6 on a shared
 * line, the two rivals take turns being hidden on alternate frames (flicker multiplexing).
 */
#include <gb/gb.h>
#include <stdint.h>
#include "layout.h"
#include "sprite_data.h"
#include "sprites.h"
#include "game.h"

extern volatile struct OAM_item_t shadow_OAM[];   /* GBDK: copied to OAM by the VBlank DMA */

#ifndef MAX_OBJS_PER_LINE
#define MAX_OBJS_PER_LINE   6
#endif
#define PLAYER_OBJ0         0
#define PLAYER_FOOT_OAM_Y   125                   /* OAM y = bottom pixel row + 1 -> bottom row 124 */
#define PLAYER_OAM_X0       76                    /* 24 px car centred on screen x = 80 */

/* player car occupies screen rows 109..124 and 24 px (half 12) around x = 80 */
#ifndef HIT_FOOT_MIN
#define HIT_FOOT_MIN        114                   /* rival feet at least this low ... */
#define HIT_FOOT_MAX        130                   /* ... (and still on the road) */
#endif
#ifndef HIT_HALF_PLAYER
#define HIT_HALF_PLAYER     9                     /* 12 minus 3 px of slack so grazes don't count */
#endif

#define Z_SPAWN16   (230 * 16)                    /* just beyond the fog */
#define Z_PASS16    (49 * 16)                     /* depth of road line 79: car has passed the camera */
#ifndef LANE_MAX
#define LANE_MAX    36                            /* 36/64 of the half-width keeps the car on the tarmac */
#endif

typedef struct {
    int16_t z16;      /* depth, 1/16 units */
    int8_t  lane;     /* -LANE_MAX..LANE_MAX */
    uint8_t speed;    /* 1/16 depth-units per frame, same scale as the player's */
    uint8_t obj0;     /* first OAM slot */
    /* last drawn geometry, for the overlap check */
    uint8_t foot;     /* screen line of the bottom pixel row, 0 = hidden */
    uint8_t w;        /* width in objects */
    int16_t cx;       /* screen x of the car's centre */
} rival_t;

#ifdef PROFILE
rival_t rv[N_RIVALS];                 /* not static: tools/gamecheck.py reads the collision geometry */
#else
static rival_t rv[N_RIVALS];
#endif
static uint16_t rng = 0xACE1;
static uint8_t  frame_parity;

#ifdef PROFILE
uint8_t dbg_hidden_frames;
#endif

static uint8_t rnd(void)
{
    rng = (rng >> 1) ^ ((uint16_t)(-(int16_t)(rng & 1)) & 0xB400u);   /* 16-bit Galois LFSR */
    return (uint8_t)rng;
}

static void respawn(uint8_t i, uint8_t far_extra)
{
    rival_t *r = &rv[i];
    r->z16   = Z_SPAWN16 + (int16_t)far_extra * 16 + (((int16_t)(rnd() & 0x3F) * 8) >> (g_diff >> 1));   /* later laps: denser traffic */
    r->lane  = (int8_t)((int8_t)(rnd() % (2 * LANE_MAX + 1)) - LANE_MAX);
    r->speed = 10 + (rnd() & 0x1F);                     /* 10..41; the player cruises at 24 */
    if (g_diff) {                                       /* harder laps (these rnd() calls only happen from lap 2) */
        int16_t pl = g_cam >> 8;                        /* the player's lane: road offset in px ~ lane units */
        r->speed += g_diff * 5;                         /* faster traffic stays in your way longer */
        if ((rnd() & 7) <= g_diff) {                    /* sometimes spawn in the player's lane: you must weave */
            pl += (int16_t)(rnd() & 7) - 4;
            r->lane = pl > LANE_MAX ? LANE_MAX : (pl < -LANE_MAX ? -LANE_MAX : (int8_t)pl);
        }
    }
    if (i && (int8_t)(r->lane - rv[0].lane) < 30 && (int8_t)(rv[0].lane - r->lane) < 30)
        r->lane = -rv[0].lane;                          /* don't spawn in the same lane */
}

#ifdef TRAFFIC
uint8_t sprites_place(void) { return 1; }     /* traffic mode has no race */
#else
/* ---- racing rivals ---- */
#define Z_GRID16(i)     ((65 + 20 * (i)) * 16)  /* starting grid: just ahead of the player, staggered */
#define Z_NEAR_FAR16    (-1600)                 /* more than 100 units behind: catch-up bonus */
#define Z_FAR_AHEAD16   4800                    /* more than 300 units ahead (out of sight): ease off */
#define Z_LIMIT16       30000                   /* clamp, so z16 never overflows */
#define CRUISE_MAX      84                      /* catch-up may exceed the player's top speed (80) */

static int8_t         tlane[N_RACERS];          /* lane the rival is heading for */
#ifdef PROFILE
uint8_t               cruise[N_RACERS];         /* not static: tools/racecheck.py reads the AI's own pace */
#else
static uint8_t        cruise[N_RACERS];         /* its speed target before rubber banding */
#endif
static uint8_t        ai_t[N_RACERS];           /* frames until it picks a new lane / pace */
static const int8_t   track_pace[3] = { -3, -16, -24 };      /* the rivals do not slow for bends, so their pace is set per track from what a player can average on it ... */
static const uint8_t  track_cap[3]  = { 76, 60, 52 };          /* ... (the best possible: OVAL ~76, CANYON ~60, ALPINE ~52).  Lap 1 they are ~15% slower than that, +4 per lap, so by lap 3 they drive as well as the track allows */
static const uint8_t  base_cruise[N_RACERS] = { 64, 58 };   /* the player averages ~70 once he has slowed for the bends */

/* the random traffic car (slot N_RACERS): slow, appears at random intervals, aims at your lane from level 1 */
static void spawn_traffic(void)
{
    respawn(N_RIVALS - 1, 0);
    rv[N_RIVALS - 1].z16 += ((int16_t)(rnd() & 0xFF) * 64) >> (g_diff >> 2);   /* a random gap of 0..1020 units (half that at the top level) */
}

static void grid(uint8_t i)
{
    rv[i].z16   = Z_GRID16(i);
    rv[i].lane  = i ? 18 : -18;
    rv[i].speed = 0;
    tlane[i]    = rv[i].lane;
    cruise[i]   = base_cruise[i];
    ai_t[i]     = 0;
}

uint8_t sprites_place(void)
{
    return 1 + (rv[0].z16 > Z_PASS16) + (rv[1].z16 > Z_PASS16);
}

static void ai_step(uint8_t i)
{
    rival_t *r = &rv[i];
    int16_t  pl = g_cam >> 8;                   /* the player's lane: road offset in px ~ lane units */
    int16_t  z = r->z16, target;
    uint8_t  fast = 0;                          /* move a whole lane unit per frame instead of half */

    if (g_state == ST_COUNTDOWN) { r->speed = 0; return; }              /* on the grid */
    if (pl >  LANE_MAX) pl =  LANE_MAX;
    if (pl < -LANE_MAX) pl = -LANE_MAX;

    if (ai_t[i] == 0) {
        ai_t[i]   = 30 + (rnd() & 31);
        {
            int16_t c = base_cruise[i] + g_diff * 4 + (rnd() & 7) + ((int8_t)g_level - 1) * 6 + track_pace[g_track];   /* harder every lap; EASY -6, HARD +6 */
            int16_t cap = track_cap[g_track] + ((int8_t)g_level - 1) * 6;
            cruise[i] = (uint8_t)(c > cap ? cap : c);
        }
        tlane[i]  = (int8_t)((int8_t)(rnd() % (2 * LANE_MAX + 1)) - LANE_MAX);
        if (g_diff + g_level >= 3 && z > Z_PASS16 && z < Z_PASS16 + 120 * 16)
            tlane[i] = (int8_t)pl;                                      /* ahead of you: block your lane */
        if (i && (int8_t)(tlane[i] - rv[0].lane) < 30 && (int8_t)(rv[0].lane - tlane[i]) < 30)
            tlane[i] = -rv[0].lane;                                     /* the two rivals keep apart */
    } else {
        ai_t[i]--;
    }
#ifndef NO_DODGE
    if (rv[2].z16 <= Z_SPAWN16 && rv[2].z16 > z && rv[2].z16 - z < 70 * 16 &&       /* the slow traffic car just ahead: go round it */
        r->lane - rv[2].lane < 26 && rv[2].lane - r->lane < 26) {
        int16_t t = rv[2].lane > 0 ? rv[2].lane - 40 : rv[2].lane + 40;
        tlane[i] = (int8_t)(t > LANE_MAX ? LANE_MAX : (t < -LANE_MAX ? -LANE_MAX : t));
        fast = 1;
    }
#endif
    if (z < Z_PASS16 && z > Z_PASS16 - 110 * 16 &&                      /* about to pass you: take a free lane, */
        (int8_t)(r->lane - (int8_t)pl) < 28 && (int8_t)((int8_t)pl - r->lane) < 28) {   /* never pop out of your own car */
        int16_t t = pl > 0 ? pl - 40 : pl + 40;
        tlane[i] = (int8_t)(t > LANE_MAX ? LANE_MAX : (t < -LANE_MAX ? -LANE_MAX : t));
        fast = 1;                                                       /* and quickly: it appears right at your bumper */
    }
    if (fast || !(ai_t[i] & 1)) {                                               /* half a lane unit per frame */
        if (r->lane < tlane[i]) r->lane++;
        else if (r->lane > tlane[i]) r->lane--;
    }

    target = cruise[i];
    if (z < Z_NEAR_FAR16) target += 12;                                 /* far behind: hunt you down */
    else if (z > Z_FAR_AHEAD16) target -= 12;                           /* far ahead: let you catch up */
    if (target > CRUISE_MAX) target = CRUISE_MAX;
    if (r->speed < target) { if (!(ai_t[i] & 1)) r->speed++; }
    else if (r->speed > target) r->speed--;
}
#endif

static void hide(uint8_t obj0)
{
    shadow_OAM[obj0].y = 0;
    shadow_OAM[obj0 + 1].y = 0;
    shadow_OAM[obj0 + 2].y = 0;
}

void sprites_reset(void)
{
    uint8_t i;
    for (i = 0; i < N_RIVALS; i++) {
        hide(rv[i].obj0);
        rv[i].foot = 0;
#ifdef TRAFFIC
        respawn(i, i * 60);
#else
        if (i < N_RACERS) grid(i); else spawn_traffic();
#endif
    }
}

void sprites_init(void)
{
    uint8_t i;

    set_sprite_data(0, SPR_TILE_COUNT, spr_tile_data);
    OBP0_REG = 0xE0;                    /* player: body white, detail dark, outline black */
    OBP1_REG = 0xE4;                    /* rivals: body light grey                         */
    for (i = 0; i < 40; i++)
        shadow_OAM[i].y = 0;
    for (i = 0; i < 3; i++) {
        shadow_OAM[PLAYER_OBJ0 + i].y    = PLAYER_FOOT_OAM_Y;
        shadow_OAM[PLAYER_OBJ0 + i].x    = PLAYER_OAM_X0 + 8 * i;
        shadow_OAM[PLAYER_OBJ0 + i].tile = SPR_PLAYER + 2 * i;
        shadow_OAM[PLAYER_OBJ0 + i].prop = 0;           /* OBP0, above BG */
    }
    for (i = 0; i < N_RIVALS; i++) {
        rv[i].obj0 = 3 + 3 * i;
        rv[i].foot = 0;
#ifdef TRAFFIC
        respawn(i, i * 60);
#else
        if (i < N_RACERS) grid(i); else spawn_traffic();
#endif
        shadow_OAM[rv[i].obj0].prop = shadow_OAM[rv[i].obj0 + 1].prop = shadow_OAM[rv[i].obj0 + 2].prop = S_PALETTE;
    }
    SPRITES_8x16;
    SHOW_SPRITES;
}

/* draw_rival() is in src/draw.s: projection, size, OAM writes (~1,000 cycles per rival in C, a third of that
   in assembly).  It uses these tile bases and the layout constants checked below. */
const uint8_t draw_tiles[3] = { SPR_R1, SPR_R2, SPR_R3 };
typedef char layout_matches_draw_s[(IDX0 == 47 && ROAD_TOP == 48 && SCX_BASE == 48) ? 1 : -1];
/* GBDK declares shadow_OAM volatile; the update is the only writer between DMAs, so drop it for better code */
#define OAM ((OAM_item_t *)shadow_OAM)
extern void draw_rival(rival_t *r, const uint8_t *scx_tbl);

/* One rival's per-frame step.  A macro on the fixed array slots, not a loop over a pointer: SDCC
   addresses rv[0]/rv[1] directly, which avoids the stack-heavy pointer code a loop produces. */
#ifdef TRAFFIC
#define STEP_RIVAL(i)                                                              \
    do {                                                                           \
        rv[i].z16 -= speed - (int16_t)rv[i].speed;                                 \
        if (rv[i].z16 < Z_PASS16 || rv[i].z16 > Z_SPAWN16 + 200 * 16)              \
            respawn(i, 0);                  /* passed, or left far behind */       \
        draw_rival(&rv[i], scx_tbl);                                               \
    } while (0)
#else
#define STEP_RIVAL(i)                                                              \
    do {                                                                           \
        ai_step(i);                                                                \
        rv[i].z16 -= speed - (int16_t)rv[i].speed;                                 \
        if (rv[i].z16 >  Z_LIMIT16) rv[i].z16 =  Z_LIMIT16;                        \
        if (rv[i].z16 < -Z_LIMIT16) rv[i].z16 = -Z_LIMIT16;                        \
        if (rv[i].z16 < Z_PASS16 || rv[i].z16 > Z_SPAWN16) {                       \
            hide(rv[i].obj0);               /* behind you or out of sight */       \
            rv[i].foot = 0;                                                        \
        } else                                                                     \
            draw_rival(&rv[i], scx_tbl);                                           \
    } while (0)
/* the traffic car: drifts towards you, respawns somewhere far ahead after you pass it */
#define STEP_TRAFFIC(i)                                                            \
    do {                                                                           \
        rv[i].z16 -= speed - (int16_t)rv[i].speed;                                 \
        if (rv[i].z16 < Z_PASS16 || rv[i].z16 > Z_SPAWN16 + 1500 * 16)             \
            spawn_traffic();                                                       \
        if (rv[i].z16 > Z_SPAWN16) {                                               \
            hide(rv[i].obj0);               /* still on its way: out of sight */   \
            rv[i].foot = 0;                                                        \
        } else                                                                     \
            draw_rival(&rv[i], scx_tbl);                                           \
    } while (0)
#endif

#ifndef TRAFFIC
/* the player was hit by rival i: shove it sideways, away from the player (the player's own bump is in game_hit) */
static void bump(uint8_t i)
{
    int16_t l;
    g_hit_dx = rv[i].cx - 80;
    l = rv[i].lane + (g_hit_dx > 0 ? 2 * BUMP_PX : -2 * BUMP_PX);
    if (l >  LANE_MAX) l =  LANE_MAX;
    if (l < -LANE_MAX) l = -LANE_MAX;
    rv[i].lane = (int8_t)l;
    if (i < N_RACERS) tlane[i] = (int8_t)l;
}
#endif

#ifndef TRAFFIC
/* ---- roadside posts: a speed cue ----
 * Pairs of banded posts stand at the road edges every 64 depth units of the track and scroll with the stripes
 * (relative depth = k * 1024 - (g_zacc & 1023), in 1/16 units).  One 8x16 object per post, three sizes by road line.
 * They are the lowest priority: a pair is skipped on any frame where its lines would carry more than 6 objects
 * with the cars (the ISR-timing limit), so cars and the player are never affected. */
#define N_POST_PAIRS  4
#define POST_OBJ0     12
extern const uint8_t y_of_z[256];
extern const uint8_t post_off[96];      /* generated: 3 + 3y/4 + 1 + y/16 + 3 (no divisions at run time) */

/* One pair, unrolled per k so every OAM address is a constant (a loop over pointers cost ~1,200 cycles a pair). */
#define POST_LOAD(i)  if (rv[i].foot && rv[i].foot + 15 >= top && rv[i].foot <= foot + 15) load += rv[i].w
#define POST_PREV(j)  if (pf##j && pf##j + 15 >= top && pf##j <= foot + 15) load += 2
#define POST(k, chk)                                                                       \
    do {                                                                                 \
        uint16_t z = 1024u * ((k) + 1) - ph;                                             \
        uint8_t  y, sz, hh, foot, top, load, yp, ob;                                     \
        int16_t  cx, l;                                                                  \
        OAM[POST_OBJ0 + 2 * (k)].y = 0;                                                  \
        OAM[POST_OBJ0 + 2 * (k) + 1].y = 0;                                              \
        if (z >= Z_PASS16 && (y = y_of_z[z >= 4080 ? 255 : (uint8_t)(z >> 4)]) >= 12) { \
            if (y < 30)      { sz = 0; hh = 4; }                                         \
            else if (y < 54) { sz = 1; hh = 8; }                                         \
            else             { sz = 2; hh = 14; }                                        \
            foot = ROAD_TOP + y;                                                         \
            top  = foot - 15;                                                            \
            load = 2;                                                                    \
            POST_LOAD(0); POST_LOAD(1); POST_LOAD(2); chk;                               \
            if (foot >= 109 && top <= 124) load += 3;       /* (an 8x16 object counts on all 16 of its lines, drawn or not) */                                    \
            if (load <= MAX_OBJS_PER_LINE) {                                             \
                pf##k = foot;                                                            \
                yp = y + g_pitch; if ((int8_t)yp < 0) yp = 0;                            \
                ob = post_off[yp] + sz;                                                  \
                cx = 128 - (int16_t)scx_tbl[IDX0 + y];                                   \
                l = cx - ob - 4;                                                         \
                if (l >= -7 && l <= 159) {                                               \
                    OAM[POST_OBJ0 + 2 * (k)].y = foot + 1;                               \
                    OAM[POST_OBJ0 + 2 * (k)].x = (uint8_t)(l + 8);                       \
                    OAM[POST_OBJ0 + 2 * (k)].tile = SPR_POST + 2 * sz;                   \
                    OAM[POST_OBJ0 + 2 * (k)].prop = S_PALETTE;                           \
                }                                                                        \
                l = cx + ob - 4;                                                         \
                if (l >= -7 && l <= 159) {                                               \
                    OAM[POST_OBJ0 + 2 * (k) + 1].y = foot + 1;                           \
                    OAM[POST_OBJ0 + 2 * (k) + 1].x = (uint8_t)(l + 8);                   \
                    OAM[POST_OBJ0 + 2 * (k) + 1].tile = SPR_POST + 2 * sz;               \
                    OAM[POST_OBJ0 + 2 * (k) + 1].prop = S_PALETTE;                       \
                }                                                                        \
            }                                                                            \
        }                                                                                \
    } while (0)

static void posts_update(const uint8_t *scx_tbl)
{
    uint16_t ph = g_zacc & 1023;
    uint8_t  pf0 = 0, pf1 = 0, pf2 = 0, pf3 = 0;        /* feet of the pairs drawn so far this frame: pairs closer than 16 lines would stack */
    POST(0, (void)0);
    POST(1, POST_PREV(0));
    POST(2, POST_PREV(0); POST_PREV(1));
    POST(3, POST_PREV(0); POST_PREV(1); POST_PREV(2));
    (void)pf3;
}
#endif

/* collision: feet inside the player's rows and overlapping him horizontally (|dx| < 9 + half width) */
#define HIT_TEST(i)                                                                \
    (rv[i].foot >= HIT_FOOT_MIN && rv[i].foot <= HIT_FOOT_MAX &&                   \
     (int16_t)(rv[i].cx - 80 + HIT_HALF_PLAYER + 4 * (int16_t)rv[i].w) > 0 &&     \
     (int16_t)(rv[i].cx - 80 - HIT_HALF_PLAYER - 4 * (int16_t)rv[i].w) < 0)

#ifndef LEGACY_PHYSICS
/* ---- corner-warning sign: 1..3 chevrons in the sky (screen rows 20..35), nothing else is ever on those lines ---- */
#define WARN_OBJ0  20
static void sign_update(void)
{
    static uint8_t shown;                                       /* the sign's objects are on: they need hiding again */
    uint8_t n = (uint8_t)(g_warn < 0 ? -g_warn : g_warn), k;
    uint8_t x, t, on;
    if (!n && !shown) return;                                   /* nothing to draw or to undo (most frames) */
    x = 88 - 4 * n;                                             /* OAM x of the left chevron: centred on screen x = 80 */
    t = SPR_SIGN + (g_warn < 0 ? 0 : 2);
    on = n && (!g_warn_hot || (g_tenths & 2));                  /* flashes (12 frames on, 12 off) while you are too fast */
    shown = on;
    for (k = 0; k < 3; k++) {
        OAM_item_t *q = &OAM[WARN_OBJ0 + k];
        if (on && k < n) { q->y = 36; q->x = x + 8 * k; q->tile = t; q->prop = 0; }
        else q->y = 0;
    }
}
#endif

uint8_t sprites_update(const uint8_t *scx_tbl, int16_t speed, uint8_t steer, uint8_t invuln)
{
    OAM_item_t *o = OAM;
    uint8_t py   = (invuln & 4) ? 0 : PLAYER_FOOT_OAM_Y;        /* blink while invulnerable */
    uint8_t tile = SPR_PLAYER + steer * 6;

    /* player frame and blink (three objects, unrolled) */
    o[0].tile = tile;      o[0].y = py;
    o[1].tile = tile + 2;  o[1].y = py;
    o[2].tile = tile + 4;  o[2].y = py;

#ifndef LEGACY_PHYSICS
    sign_update();
#endif
    STEP_RIVAL(0);
    STEP_RIVAL(1);
#ifndef TRAFFIC
    STEP_TRAFFIC(2);
#endif

    /* per-line cap: player (3 objects, lines 109..124) + both rivals on a shared line */
    frame_parity ^= 1;
    if (rv[0].foot && rv[1].foot) {
        uint8_t f0 = rv[0].foot, f1 = rv[1].foot;
        uint8_t d  = f0 > f1 ? f0 - f1 : f1 - f0;
        if (d < 16) {
            uint8_t load = rv[0].w + rv[1].w;
            uint8_t lo = f0 < f1 ? f0 : f1;
            uint8_t hi = f0 < f1 ? f1 : f0;
            if (hi >= 109 && lo <= 140) load += 3;      /* the shared band reaches the player car */
            if (load > MAX_OBJS_PER_LINE) {
                uint8_t h = frame_parity ? 0 : 1;
                hide(rv[h].obj0);
                rv[h].foot = 0;             /* not drawn: cannot be hit either */
#ifdef PROFILE
                dbg_hidden_frames++;
#endif
            }
        }
    }

#ifndef TRAFFIC
    if (rv[2].foot) {                   /* the traffic car yields: hidden when the shared lines would carry > 6 objects */
        uint8_t f2 = rv[2].foot, load = rv[2].w, d;
        if (rv[0].foot) { d = f2 > rv[0].foot ? f2 - rv[0].foot : rv[0].foot - f2; if (d < 16) load += rv[0].w; }
        if (rv[1].foot) { d = f2 > rv[1].foot ? f2 - rv[1].foot : rv[1].foot - f2; if (d < 16) load += rv[1].w; }
        if (f2 >= 109 && f2 <= 140) load += 3;
        if (load > MAX_OBJS_PER_LINE) {
            hide(rv[2].obj0);
            rv[2].foot = 0;             /* not drawn: cannot be hit either */
#ifdef PROFILE
            dbg_hidden_frames++;
#endif
        }
    }
#ifndef NO_POSTS
    posts_update(scx_tbl);
#endif
    if (!invuln) {
        if (HIT_TEST(0)) { bump(0); return 1; }
        if (HIT_TEST(1)) { bump(1); return 1; }
        if (HIT_TEST(2)) { bump(2); return 1; }
    }
#else
    if (!invuln && (HIT_TEST(0) || HIT_TEST(1)))
        return 1;
#endif
    return 0;
}
