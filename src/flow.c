/*
 * Race flow: TITLE -> COUNTDOWN (3, 2, 1, GO) -> RACE (N laps) -> FINISHING (flag, coast to a stop)
 * -> RESULTS -> TITLE.  The physics and lap logic are in game.c; this file owns the screens and timing
 * between the states.
 */
#include <gb/gb.h>
#include "game.h"
#include "hud.h"
#include "sprites.h"
#include "audio.h"
#include "audio_data.h"
#include "flow.h"

static uint8_t last_lap_seen = 1;
static uint8_t last_place = 3;      /* race position last frame, for the OVERTAKEN! / PASSED! banner */
static uint8_t ban_tick;            /* frames of banner left */
static uint8_t pause_sel;           /* pause menu item 0..3 */

void flow_show_title(void)
{
    g_state = ST_TITLE;
    HIDE_SPRITES;
    road_enable(0);
    SWITCH_ROM_MBC1(1);             /* hud_title/hud_title_laps live in bank 1 */
    hud_title();
}

static void start_race(void)
{
    sram_save();                                /* remember the track / laps / level choice */
    game_start_race();
    sprites_reset();
    hud_race_screen();
    hud_banner("   GET READY  3");
    SHOW_SPRITES;
    road_set_track(g_track);
    road_enable(1);
    audio_sfx(SFX_BEEP);
    last_lap_seen = 1;
    last_place = 3;
    ban_tick = 0;
}

void flow_menu(uint8_t pressed)
{
    if (g_state == ST_TITLE) {
        /* bank 1 is already mapped by flow_show_title(): hud_title_laps is in bank 1 */
        if ((pressed & J_UP) && g_track > 0)                       { g_track--; hud_title_laps(); }
        if ((pressed & J_DOWN) && g_track < N_TRACKS - 1)          { g_track++; hud_title_laps(); }
        if ((pressed & J_LEFT) && g_laps_sel > 0)                  { g_laps_sel--; hud_title_laps(); }
        if ((pressed & J_RIGHT) && g_laps_sel < N_LAP_OPTIONS - 1) { g_laps_sel++; hud_title_laps(); }
        if ((pressed & J_SELECT)) { g_level = g_level == N_LEVELS - 1 ? 0 : g_level + 1; hud_title_laps(); }
        if (pressed & J_START)
            start_race();
    } else if (g_state == ST_RESULTS) {
        if (pressed & J_START)
            flow_show_title();
    }
}

uint8_t flow_keys(uint8_t keys)
{
    if (g_state == ST_COUNTDOWN) return 0;
    if (g_state == ST_FINISHING) return J_B;
    return keys;
}

void flow_after_update(void)
{
    if (g_state == ST_COUNTDOWN) {
        if (++g_cd_tick >= COUNT_STEP) {
            g_cd_tick = 0;
            if (g_cd > 0) g_cd--;
            if (g_cd == 0) {                    /* GO */
                g_state = ST_RACE;
                hud_banner("      GO!");
                audio_sfx(SFX_GO);
            } else {
                hud_banner(g_cd == 2 ? "   GET READY  2" : "   GET READY  1");
                audio_sfx(SFX_BEEP);
            }
        }
    } else if (g_state == ST_RACE) {
        if (g_cd_tick < 255) g_cd_tick++;       /* frames since GO */
        if (g_cd_tick == 45)                    /* the GO banner stays for 3/4 s, then the normal HUD */
            hud_request_race_screen();
        if (ban_tick) {                         /* the place banner shows for 3/4 s, then the normal HUD comes back */
            if (--ban_tick == 0) hud_request_race_screen();
        } else if (g_cd_tick >= 60 && g_place != last_place && !g_paused) {
            hud_banner(g_place > last_place ? "     OVERTAKEN!" : "      PASSED!");
            audio_sfx(SFX_BEEP);
            ban_tick = 45;
        }
        last_place = g_place;
        if (g_lap != last_lap_seen) {
            last_lap_seen = g_lap;
            audio_sfx(SFX_LAP);
        }
    } else if (g_state == ST_FINISHING) {
        if (g_fin_tick == 0) {
            hud_banner("    FINISH!");
            audio_sfx(SFX_FINISH);
        }
        if (++g_fin_tick >= FINISH_COAST) {
            road_enable(0);                         /* first: the save is banked, and the ISR reads the mapped bank */
            game_finish_record();
            SWITCH_ROM_MBC1(1);     /* hud_results lives in bank 1 */
            hud_results();
            HIDE_SPRITES;
            g_state = ST_RESULTS;
        }
    }
}

/* START during a race opens the pause menu.  Returns 1 while paused (the main loop then skips the whole update:
   the picture, tables and audio state stay as they were).  Item 3 is the sound toggle, so 0..3 wraps. */
uint8_t flow_pause(uint8_t pressed)
{
    if (g_state != ST_RACE) { g_paused = 0; return 0; }

    if (!g_paused) {
        if (pressed & J_START) {
            g_paused = 1;
            pause_sel = 0;
            hud_pause_menu(pause_sel, g_sound_on);
            return 1;
        }
        return 0;
    }

    if (pressed & J_UP) {
        pause_sel = pause_sel ? pause_sel - 1 : 3;
        hud_pause_menu(pause_sel, g_sound_on);
    } else if (pressed & J_DOWN) {
        pause_sel = pause_sel == 3 ? 0 : pause_sel + 1;
        hud_pause_menu(pause_sel, g_sound_on);
    }

    if (pressed & (J_A | J_START)) {
        if (pause_sel == 0) {                   /* RESUME */
            g_paused = 0;
            hud_request_race_screen();
            return 0;
        }
        if (pause_sel == 1) {                   /* RESTART */
            g_paused = 0;
            start_race();
            return 1;
        }
        if (pause_sel == 2) {                   /* QUIT */
            g_paused = 0;
            flow_show_title();
            return 1;
        }
        g_sound_on ^= 1;                        /* SOUND ON / OFF */
        hud_pause_menu(pause_sel, g_sound_on);
    } else if (pressed & J_B) {                 /* B resumes from anywhere in the menu */
        g_paused = 0;
        hud_request_race_screen();
        return 0;
    }
    return 1;
}
