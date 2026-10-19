#ifndef HUD_H
#define HUD_H
#include <stdint.h>

/* The HUD is the window layer.  In a race it covers lines 128..143:
 *   row 0:  SPD 000  LAP 01/03
 *   row 1:  TIME 0:00.0 B 0:00.0        (B = best lap, dashes until a lap is finished)
 * The title and results pages move the window to line 0 so it covers the whole screen (all black, white text).
 * hud_init: LCD must be off.  hud_update: once per frame in a race, right after VBlank starts; it only
 * rewrites the tiles whose value changed. */
void hud_init(void);
void hud_update(void);
void hud_race_screen(void);          /* race layout (resets the cached values), window at line 128 */
void hud_banner(const char *text);   /* replaces row 0 (<= 20 chars) until hud_race_screen(); drawn by the next hud_update */
void hud_request_race_screen(void);  /* hud_race_screen() at the next hud_update (VBlank), for use mid-frame */
void hud_title(void);                /* title page, window at line 0 (bank 1) */
void hud_title_laps(void);           /* redraw the lap selector and best time after the choice changed (bank 1) */
void hud_results(void);              /* results page from g_race_tenths, g_best_tenths, g_new_record (bank 1) */
void hud_pause_menu(uint8_t sel, uint8_t sound);   /* race pause menu, two 20-char rows in the bottom window */

#endif
