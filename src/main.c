/*
 * GB racer - step 3: asm table builder + profiling.
 *
 * Screen:  lines   0..47   sky + hills       (static)
 *          lines  48..127  road, 80 lines    (HBlank ISR rewrites SCX + BGP)
 *          lines 128..143  HUD placeholder   (becomes the window layer later)
 *
 * Controls: LEFT/RIGHT steer, A or UP accelerate, B or DOWN brake  (see game.c).
 *
 * Build switches (make DEFS="-DPROFILE -DSELFTEST"):
 *   USE_C_BUILDER  use the C table builder instead of the asm one
 *   PROFILE        record per-frame cost (in scanlines) in dbg_* variables
 *   SELFTEST       at startup, compare the C and asm builders (st_* variables)
 */
#include <gb/gb.h>
#include <gb/isr.h>
#include <stdint.h>
#include <string.h>
#include "road_data.h"
#include "layout.h"
#include "sprites.h"
#include "game.h"
#include "hud.h"
#include "audio.h"
#include "flow.h"

/* BGP shade maps: bits 1-0 = colour 0 ... bits 7-6 = colour 3
 * colours: 0 grass, 1 road, 2 rumble, 3 centre line
 * (the stripe rows in ROM are generated from these values by tools/gen_road.py) */
#define BGP_BASE      0xE4             /* identity: sky white, hills dark, HUD black */
#define BGP_A         0x09             /* grass light, road dark, rumble white, line white */
#define BGP_B         0xB8             /* grass white, road dark, rumble black, line = road */
#define BGP_FOG       0x99             /* flat mid-tone for the distant lines */

/* ------------------------------------------------------- timer gating -----
 * The road ISR runs from IE.LCD-STAT, which we switch on/off from the timer
 * so it only fires for lines ~43..131 instead of all 144.
 * The timer is re-anchored every VBlank:
 *   16384 Hz tick = 64 M-cycles;  line = 114 M-cycles.
 *   start: 94 ticks after VBlank  -> ~line 43   (TIMA = 256 - 94)
 *   stop : 157 ticks later        -> ~line 131  (TMA  = 256 - 157)
 * Both land on "don't care" lines (plain sky / HUD), so +-1 line of jitter is harmless.
 */
#define TIMER_START_TIMA  162
#define TIMER_RELOAD_TMA  99

/* ---------------------------------------------------------------- tables -
 * Two page-aligned buffers (SCX page, BGP page right after it), 256 bytes
 * each, indexed by LY.  Fixed addresses so the ISR can use H as the page.   */
static uint8_t * const tbl_scx[2] = { (uint8_t *)0xD000, (uint8_t *)0xD200 };
static uint8_t * const tbl_bgp[2] = { (uint8_t *)0xD100, (uint8_t *)0xD300 };
static const uint8_t   tbl_page_of[2] = { 0xD0, 0xD2 };

extern volatile uint8_t tbl_page;          /* HRAM, defined in raster.s, read by the ISR: SCX table page */
extern volatile uint8_t bgp_page;          /* HRAM, defined in raster.s, read by the ISR: BGP row page   */
static volatile uint8_t pending_scy  = 0;      /* SCY for the next frame (hill pitch) */
static volatile uint8_t pending_page = 0xD0;
static volatile uint8_t pending_bgp   = PAT_PAGE0;
static volatile uint8_t road_on;
static volatile uint8_t road_allowed = 1;      /* 0 on the title / results pages: no scanline effect */

static volatile uint8_t bgp_sky = BGP_BASE;    /* BGP of the lines above the road (sky colour of the selected track) */

/* palette set per track: ROM bank of its pat_rows (all at $6000) and its sky shade; see tools/gen_road.py */
static const uint8_t track_bank[3] = { 2, 1, 3 };
static const uint8_t track_sky[3]  = { 0xE4, 0xE4, 0xD8 };

void road_set_track(uint8_t t)
{
    SWITCH_ROM_MBC1(track_bank[t]);
    bgp_sky = track_sky[t];
}

void road_enable(uint8_t on)
{
    road_allowed = on;
    if (!on) {
        bgp_sky = BGP_BASE;
        IE_REG &= ~LCD_IFLAG;
        road_on = 0;
    }
}

extern void road_isr(void);                /* raster.s */
ISR_VECTOR(VECTOR_STAT, road_isr)

static void vbl_isr(void)
{
    TIMA_REG = TIMER_START_TIMA;           /* timing anchor: do this first */
    IE_REG  &= ~LCD_IFLAG;                 /* road ISR off until the timer re-arms it */
    road_on  = 0;
    tbl_page = pending_page;               /* swap table buffers */
    bgp_page = pending_bgp;                /* and the stripe row  */
    SCX_REG  = SCX_BASE;                   /* line 0 starts from the base values */
    SCY_REG  = pending_scy;                /* hill pitch, applied to the whole frame */
    BGP_REG  = bgp_sky;
}

static void tim_isr(void)
{
    if (road_on) {                         /* stop (~line 131) */
        IE_REG &= ~LCD_IFLAG;
        road_on = 0;
    } else if (road_allowed) {             /* start (~line 43) */
        IF_REG &= ~LCD_IFLAG;              /* drop any stale HBlank request */
        IE_REG |= LCD_IFLAG;
        road_on = 1;
    }
}

/* ---------------------------------------------------- perspective LUT ---
 * zlut[y] = depth (arbitrary units) of road line y.  Stripes are 8 units long.
 * The trapezoid's horizon is ~4 lines above the road top, hence the +4.
 * Only the C reference builder uses this now; the asm path gets its stripes
 * from the pat_rows generated into ROM by tools/gen_road.py.                */
#if defined(USE_C_BUILDER) || defined(SELFTEST)     /* release ROMs don't carry the reference builder (saves ~200 bytes of bank 0) */
static uint16_t zlut[ROAD_LINES];

static void init_zlut(void)
{
    uint8_t y, yy;
    for (y = 0; y < ROAD_LINES; y++) {
        yy = (y < FOG_LINES) ? FOG_LINES : y;
        zlut[y] = 4096u / (uint16_t)(yy + 4);
    }
}
#endif

/* ------------------------------------------- table builder, C reference --
 *   x   : screen offset of the road centre, 1/256 px
 *   dx  : its slope, 1/4096 px per line
 *   curve: change of slope per line (1/4096 px per line^2)
 * Steering is just a different starting x/dx; a bend is a different curve.  */
#if defined(USE_C_BUILDER) || defined(SELFTEST)
static void build_tables_c(uint8_t buf, int16_t cam, int16_t curve, uint16_t zpos)
{
    uint8_t *scx = tbl_scx[buf] + IDX0;
    uint8_t *bgp = tbl_bgp[buf] + IDX0;
    int16_t  x   = -cam;
    int16_t  dx  = (int16_t)(((int32_t)cam * 16) / (ROAD_LINES - 1));  /* horizon stays put */
    uint8_t  y   = ROAD_LINES;
    uint8_t  near = g_split << 3;                 /* lines drawn with the current bend (>= 8); the rest are the next one */

    while (y--) {
        scx[y] = (uint8_t)(SCX_BASE - (x >> 8));
        x  += dx >> 4;
        dx += curve;
        if (!--near) curve = g_vcurve2;

        if (y < FOG_LINES)
            bgp[y] = BGP_FOG;
        else
            bgp[y] = (((zlut[y] + zpos) >> 3) & 1) ? BGP_B : BGP_A;
    }
}
#endif

/* ------------------------------------------ table builder, asm (raster.s) -
 * Same maths, different units: the scroll position runs as 8.8 px in HL and
 * the curve is applied once per 8-line chunk (10 chunks).  Only SCX is built
 * per frame; the stripe palette is a ROM row picked by the phase.           */
uint16_t bt_s;
int16_t  bt_ds, bt_curve;
extern int16_t bt_curve2, bt_curve3;       /* HRAM, defined in raster.s */
extern uint8_t  bt_split;
uint8_t *bt_scx;
extern void build_tables_asm(void);

static void build_tables_fast(uint8_t buf, int16_t cam, int16_t curve, uint16_t zpos)
{
    (void)zpos;                                             /* stripes are chosen by pending_bgp */
    bt_s     = (uint16_t)((int16_t)(SCX_BASE * 256) + cam);
    bt_ds    = -(int16_t)(((cam >> 4) * 13) >> 6);          /* -cam/79, no divide */
    bt_curve = -(curve >> 1);                               /* per 8 lines, 8.8 px/line */
    bt_curve2 = -(g_vmid >> 1);                             /* this bend for g_split chunks, one blended chunk, */
    bt_curve3 = -(g_vcurve2 >> 1);                          /* then the next bend                              */
    bt_split  = g_split;                                    /* >= 1: the car's own chunk is always this bend    */
    bt_ds   += (bt_curve * 7) >> 4;                         /* sample mid-chunk, not chunk start */
    bt_scx   = tbl_scx[buf] + IDX0 + ROAD_LINES - 1;
    build_tables_asm();
}

/* which BGP page the ISR should read for this frame */
#ifdef USE_C_BUILDER
#define build_tables build_tables_c
#define BGP_PAGE_FOR(buf, zpos)  (tbl_page_of[buf] + 1)     /* the C builder fills tbl_bgp[buf] */
#else
#define build_tables build_tables_fast
#define BGP_PAGE_FOR(buf, zpos)  ((uint8_t)(PAT_PAGE0 + ((zpos) & 15)))
#endif

/* ------------------------------------------------------------ profiling -*/
#ifdef PROFILE
uint8_t dbg_build_lines, dbg_build_max;    /* table builder, in scanlines (114 M-cycles each) */
uint8_t dbg_spr_lines,   dbg_spr_max;      /* sprites_update, in scanlines                    */
uint8_t dbg_loop_lines,  dbg_loop_max;     /* whole main-loop iteration up to the vsync wait  */
uint8_t dbg_frames;

static uint8_t ly_delta(uint8_t a, uint8_t b)
{
    return (b >= a) ? (uint8_t)(b - a) : (uint8_t)(b + 154 - a);
}
#endif

#ifdef SELFTEST
#ifndef SELFTEST_PERTURB
#define SELFTEST_PERTURB 0                 /* set nonzero to prove the comparison can fail */
#endif
uint8_t st_scx_maxdiff;                   /* max |asm - C| over SCX entries, px */
uint8_t st_bgp_bad;                        /* BGP entries that differ            */
uint8_t st_probe[12];                      /* per case: C[79], asm[79], C[0], asm[0] */

static void selftest(void)
{
    static const int16_t  cams[3]   = {  5000, -9000, 0  };
    static const int16_t  curves[3] = {    40,   -50, 0  };
    static const uint16_t zps[3]    = {    37,   201, 0  };
    uint8_t c, y;
    int8_t  d;

    g_split = SPLIT_CHUNKS;                 /* one bend for the whole road: compares the builders, not the look-ahead */
    for (c = 0; c < 3; c++) {
        build_tables_c   (0, cams[c], curves[c], zps[c]);
        build_tables_fast(1, cams[c], curves[c] + SELFTEST_PERTURB, zps[c]);
        st_probe[c * 4 + 0] = tbl_scx[0][IDX0 + 79];
        st_probe[c * 4 + 1] = tbl_scx[1][IDX0 + 79];
        st_probe[c * 4 + 2] = tbl_scx[0][IDX0 + 0];
        st_probe[c * 4 + 3] = tbl_scx[1][IDX0 + 0];
        for (y = 0; y < ROAD_LINES; y++) {
            d = (int8_t)(tbl_scx[0][IDX0 + y] - tbl_scx[1][IDX0 + y]);
            if (d < 0) d = -d;
            if ((uint8_t)d > st_scx_maxdiff) st_scx_maxdiff = (uint8_t)d;
            /* the C builder's BGP column vs the ROM stripe row for the same phase */
            if (tbl_bgp[0][IDX0 + y] != pat_rows[((uint16_t)(zps[c] & 15) << 8) + IDX0 + y]) st_bgp_bad++;
        }
    }
}
#endif

/* ------------------------------------------------------------------ main */
void main(void)
{
    uint8_t  b, keys, prev = 0, pressed, back = 1;
#ifdef PROFILE
    uint8_t  t_loop, t0, t1, t2, d;
#endif

    DISPLAY_OFF;
    LCDC_REG = 0x01;                       /* BG on, tiles @ $8800 (signed), map @ $9800, LCD still off */

    memcpy((void *)0x9000, road_tile_data, ROAD_TILE_COUNT * 16);   /* BG ids   0..127 */
    memcpy((void *)0x8800, sky_tile_data,  SKY_TILE_COUNT  * 16);   /* BG ids 128..255 */
    memcpy((void *)0x9800, bg_map, BG_MAP_W * BG_MAP_H);

    for (b = 0; b < 2; b++) {              /* every non-road line gets the base values */
        memset(tbl_scx[b], SCX_BASE, 256);
        memset(tbl_bgp[b], BGP_BASE, 256);
        memset(tbl_bgp[b] + IDX0, BGP_FOG, FOG_LINES);   /* fog never changes: fill once */
    }
#if defined(USE_C_BUILDER) || defined(SELFTEST)
    init_zlut();
#endif
#ifdef SELFTEST
    selftest();
#endif
    tbl_page = pending_page;               /* HRAM is not initialised by C */
    bgp_page = pending_bgp;
    sprites_init();                        /* car tiles, palettes, OAM; LCD is still off */
    game_init();
    hud_init();                            /* font tiles, window map; LCD is still off */
    audio_init();

    STAT_REG = 0x08;                       /* HBlank source on; gated by IE, never rewritten (DMG STAT-write bug) */
    TAC_REG  = 0x07;                       /* timer on, 16384 Hz */
    TMA_REG  = TIMER_RELOAD_TMA;
    TIMA_REG = TIMER_START_TIMA;
    add_VBL(vbl_isr);
    add_TIM(tim_isr);
    set_interrupts(VBL_IFLAG | TIM_IFLAG);
    enable_interrupts();
    DISPLAY_ON;
#ifndef AUTOSTART
    flow_show_title();                     /* LCD is on but this only touches the window map during the first frames */
#endif

    for (;;) {
#ifdef PROFILE
        t_loop = LY_REG;
#endif
        keys = joypad();
        pressed = keys & (uint8_t)~prev;
        prev = keys;
        if (g_state == ST_TITLE || g_state == ST_RESULTS) {
            flow_menu(pressed);            /* VBlank: VRAM is free */
            audio_update(0, 0, g_hits);    /* keep the collision counter in sync: 0 would fake a crash */
            wait_vbl_done();
            continue;
        }
        if (flow_pause(pressed)) {         /* paused: the frame stays as it is (road ISR keeps using the last tables) */
            audio_update(0, 0, g_hits);    /* same as above: pausing must not look like a collision; no hud_update:
                                              it would overwrite the pause menu */
            wait_vbl_done();
            continue;
        }
        hud_update();                      /* start of VBlank: VRAM is free; rewrites changed tiles only */
        game_update(flow_keys(keys));

#ifdef PROFILE
        t0 = LY_REG;
#endif
        build_tables(back, g_cam, g_vnear, g_zacc >> 4);
#ifdef PROFILE
        t1 = LY_REG;
        d = ly_delta(t0, t1);
        dbg_build_lines = d;
        if (d > dbg_build_max) dbg_build_max = d;
#endif
        if (sprites_update(tbl_scx[back], g_speed, g_steer, g_invuln))
            game_hit();
        if (g_state == ST_COUNTDOWN || g_state == ST_RACE)
            g_place = sprites_place();         /* frozen once the flag is out */
        audio_update(g_speed, g_offroad, g_hits);
        flow_after_update();
#ifdef PROFILE
        t2 = LY_REG;
        d = ly_delta(t1, t2);
        dbg_spr_lines = d;
        if (d > dbg_spr_max) dbg_spr_max = d;
        d = ly_delta(t_loop, t2);
        dbg_loop_lines = d;
        if (d > dbg_loop_max) dbg_loop_max = d;
        dbg_frames++;
#endif
        pending_scy  = (uint8_t)g_pitch;
        pending_page = tbl_page_of[back];
        pending_bgp  = BGP_PAGE_FOR(back, g_zacc >> 4);
        back ^= 1;
        wait_vbl_done();
    }
}
