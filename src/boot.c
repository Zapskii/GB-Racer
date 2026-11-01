/*
 * Start-up video, run once from main() before the interrupts are set up.  It lives in ROM bank 1
 * next to the tile data it copies, which keeps it out of bank 0 (full); nothing here runs while
 * the road ISR is on, so mapping another bank is safe.
 */
#pragma bank 1

#include <gb/gb.h>
#include <stdint.h>
#include <string.h>
#include "boot.h"
#include "sgb_boot.h"
#include "road_data.h"
#include "layout.h"

void boot_video(void) BANKED
{
    sgb_boot();                            /* first: the border transfer overwrites VRAM (bank 4, does nothing on a plain GB) */
    DISPLAY_OFF;
    LCDC_REG = 0x01;                       /* BG on, tiles @ $8800 (signed), map @ $9800, LCD still off */

    memcpy((void *)0x9000, road_tile_data, ROAD_TILE_COUNT * 16);   /* BG ids   0..127 */
    memcpy((void *)0x8800, sky_tile_data,  SKY_TILE_COUNT  * 16);   /* BG ids 128..255 */
    memcpy((void *)0x9800, bg_map, BG_MAP_W * BG_MAP_H);

    memset(TBL_SCX0, SCX_BASE, 256);       /* every non-road line gets the base values ... */
    memset(TBL_SCX1, SCX_BASE, 256);
    memset(TBL_BGP0, BGP_BASE, 256);
    memset(TBL_BGP1, BGP_BASE, 256);
    memset(TBL_BGP0 + IDX0, BGP_FOG, FOG_LINES);   /* ... and the fog never changes: fill once */
    memset(TBL_BGP1 + IDX0, BGP_FOG, FOG_LINES);
}
