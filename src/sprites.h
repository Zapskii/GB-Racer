#ifndef SPRITES_H
#define SPRITES_H
#include <stdint.h>

#define N_RACERS 2             /* the rivals you race */
#ifdef TRAFFIC
#define N_RIVALS 2             /* old behaviour: two oncoming cars */
#else
#define N_RIVALS 3             /* + one random traffic car */
#endif

/* OAM layout: 0-2 player car, 3-5 rival A, 6-8 rival B, 9-11 traffic car (3 objects each, 8x16 mode) */

void sprites_init(void);
void sprites_reset(void);   /* new race: the rivals go back on the starting grid */
uint8_t sprites_place(void); /* race position 1..3 = 1 + rivals ahead of the player (racing mode) */

/* Call once per frame after the SCX table for this frame is built.
 *   scx_tbl : the table just built (indexed like the ISR: entry IDX0+y is road line y)
 *   speed   : player speed, 1/16 depth-units per frame (same units as the stripe scroll)
 *   steer   : 0 straight, 1 left, 2 right (picks the player car frame)
 *   invuln  : frames of collision immunity left; the player car blinks while it is non-zero
 * Returns 1 if the player hit a rival this frame (never while invuln != 0). */
uint8_t sprites_update(const uint8_t *scx_tbl, int16_t speed, uint8_t steer, uint8_t invuln);

#ifdef PROFILE
extern uint8_t dbg_hidden_frames;   /* frames where the per-line cap hid a rival object set */
#endif

#endif
