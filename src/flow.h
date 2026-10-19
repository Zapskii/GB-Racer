#ifndef FLOW_H
#define FLOW_H
#include <stdint.h>

/* Race flow around game.c's physics: title, countdown, finish and results screens.
 * main.c calls flow_menu() on the title/results pages and flow_after_update() after each race frame. */
void flow_show_title(void);                 /* title page: sprites and road off */
void flow_menu(uint8_t pressed);            /* title / results input (pressed = buttons that went down this frame) */
uint8_t flow_keys(uint8_t keys);            /* what the car is allowed to see: nothing in the countdown, brake after the flag */
void flow_after_update(void);               /* countdown steps, lap jingle, flag -> results timing */

uint8_t flow_pause(uint8_t pressed);       /* START toggles the pause in a race; 1 = paused this frame */
extern void road_set_track(uint8_t t);     /* main.c: select the track's palette set (ROM bank) and sky shade */
extern void road_enable(uint8_t on);        /* main.c: road scanline effect + its timer on/off */
#endif
