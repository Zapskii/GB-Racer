#ifndef GAME_H
#define GAME_H
#include <stdint.h>

#define SPEED_MAX      80          /* 1/16 depth-units per frame (the stripe scroll speed) */
#define OFFROAD_PX     58          /* |road centre offset at the bottom line| beyond this = on the grass */
#define CAM_LIMIT      22528       /* (OFFROAD_PX + 30) * 256: how far onto the grass you can go */
#ifndef STEER_BASE
#define STEER_BASE     160         /* sideways speed at a standstill, 1/256 px per frame ... */
#define STEER_GAIN     4           /* ... plus this per speed unit: 160 + 4*80 = 480 = 1.9 px/frame flat out (was 80 + 2*speed) */
#endif
#ifdef LEGACY_PHYSICS              /* the original handling: kept so the old reference ROM and the sprite/hill/audio checks stay comparable */
#define SPEED_OFFROAD  18          /* speed cap on the grass */
#define ACCEL_FAST     0           /* gains 1 speed per 2 frames at every speed */
#define GRASS_DRAG     2           /* speed lost per frame while over the grass cap */
#else
#define SPEED_OFFROAD  8           /* speed cap on the grass */
#define ACCEL_FAST     48          /* below this speed the car gains 1 per frame, above it 1 per 2 frames */
#define GRASS_DRAG     8           /* speed lost per frame while over the grass cap */
#endif
#define LEAD_FRAMES    48          /* the road bends this many frames of driving before the push starts (not in LEGACY_PHYSICS builds); game.c hard-codes 48 = 32 + 16 */
#define VIS_EASE       4           /* the drawn curvature eases twice as fast as the real one: the bend shows up in ~20 frames */
#define PUSH_MAX       1600        /* the most a bend can push the car sideways in one frame, 1/256 px (about 6 px; uncapped a hairpin at full speed pushed 10 px a frame) */
#define STEER_RAMP     32          /* frames of held steering that add (frames/64) to the turn rate: up to +50% */
#define WARN_MIN       40          /* bends at least this sharp get a sign */
#define INVULN_FRAMES  60
#define BUMP_PX        6           /* a collision shoves the player this far sideways (and the rival twice as far in lane units) */
#define COUNT_STEP     50          /* frames per countdown number */
#define FINISH_COAST   70          /* frames of automatic braking after the flag before the results screen */
#define DIFF_MAX       4           /* difficulty level cap: lap 5 and later */
#define HILL_MIN       (-48)       /* g_hill range, 1/8 line: climbing pitches the view down to -6 lines ... */
#define HILL_MAX       24          /* ... descending lifts the horizon up to +3 lines (limit: road row 0 must stay at line >= 43) */

/* Race flow: title -> countdown -> race (N laps) -> finishing (coast to a stop) -> results -> title */
enum { ST_TITLE, ST_COUNTDOWN, ST_RACE, ST_FINISHING, ST_RESULTS };
#define N_LAP_OPTIONS 3
#define N_TRACKS      3
#define N_LEVELS      3            /* EASY, NORMAL, HARD: the AI's pace and how early it blocks you */
extern const char * const track_name[N_TRACKS];   /* "OVAL", "CANYON", "ALPINE" */
extern const uint8_t lap_options[N_LAP_OPTIONS];   /* 3, 5, 10 */

/* All plain globals so the emulator tests can read them by symbol. */
extern int16_t  g_cam;             /* road offset at the bottom line, 1/256 px (right = positive) */
extern int16_t  g_curve;           /* current road curvature (eased towards the segment's value)   */
extern int16_t  g_vcurve;          /* the curvature that is DRAWN: g_curve, but ahead of it (see LEAD_FRAMES) */
extern int8_t   g_warn;            /* upcoming sharp bend: sign = direction (+ right), magnitude 1..3 = chevrons, 0 = none */
extern uint8_t  g_warn_hot;        /* ... and you are too fast for it: the sign flashes */
extern int16_t  g_speed;
extern uint16_t g_zacc;            /* depth scroll accumulator; stripe phase = (g_zacc >> 4) & 15  */
extern uint8_t  g_steer;           /* 0 straight, 1 left, 2 right (player sprite frame)            */
extern uint8_t  g_offroad;
extern uint8_t  g_invuln;          /* frames of collision immunity left */
extern uint8_t  g_lap;             /* 1-based */
extern uint16_t g_tenths;          /* current lap time, 0.1 s */
extern uint16_t g_best_tenths;     /* best lap, 0 = none yet  */
extern uint8_t  g_state;           /* ST_* */
extern uint8_t  g_laps_sel;        /* index into lap_options, chosen on the title screen */
extern uint8_t  g_laps_total;      /* laps in the current race */
extern uint8_t  g_place;           /* race position, 1 = leading (set by the main loop from sprites_place) */
extern uint8_t  g_diff;            /* difficulty level 0..DIFF_MAX = min(lap - 1, DIFF_MAX) */
extern uint8_t  g_cd;              /* countdown number 3,2,1 then 0 = GO */
extern uint8_t  g_cd_tick;         /* frames into the current countdown number */
extern uint8_t  g_fin_tick;        /* frames since the flag */
extern uint16_t g_race_tenths;     /* total race time, valid when finished */
extern uint8_t  g_track;           /* selected track 0..N_TRACKS-1 (title screen: UP/DOWN) */
extern const char * const level_name[N_LEVELS];   /* "EASY", "NORMAL", "HARD" */
extern uint8_t  g_level;           /* 0 easy, 1 normal, 2 hard (title screen: SELECT) */
extern uint8_t  g_paused;          /* START during a race toggles it */
extern int16_t  g_hit_dx;          /* screen x of the rival that last hit the player, relative to the player (sign = side) */
extern uint16_t g_best_total[N_LEVELS][N_TRACKS][N_LAP_OPTIONS];   /* best race time per level, track and race length, 0 = none; saved in battery RAM */
extern uint8_t  g_new_record;      /* the race just finished beat g_best_total */
extern int8_t   g_hill;            /* eased hill pitch, 1/8 line units, HILL_MIN..HILL_MAX */
extern int8_t   g_pitch;           /* g_hill >> 3: whole lines the picture is scrolled up (SCY) */
extern uint8_t  g_hits;            /* collisions so far (wraps)           */
extern uint8_t  g_speed_before_hit;

void game_init(void);
void game_start_race(void);       /* reset the race (keeps records and the lap choice), state = COUNTDOWN, g_cd = 3 */
void game_finish_record(void);    /* results bookkeeping when the finish screen is entered */
void game_update(uint8_t keys);    /* once per frame, before the road tables are built */
void game_hit(void);               /* sprites_update reported a collision with a rival */


/* battery-backed records (src/sram.c): magic + version + checksum, anything else resets to "no records" */
void sram_load(void);              /* fills g_best_total and the title selections from cartridge RAM, or clears them */
void sram_save(void);

#endif
