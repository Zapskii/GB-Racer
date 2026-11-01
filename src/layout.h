/* Screen/road layout shared by main.c and sprites.c.
 * tools/gen_road.py keeps its own copy of the same numbers (the selftest and
 * the model check would notice a mismatch). */
#ifndef LAYOUT_H
#define LAYOUT_H

#include <stdint.h>

#define ROAD_TOP      48
#define ROAD_LINES    80
#define IDX0          (ROAD_TOP - 1)   /* tbl[LY] drives line LY+1 */
#define SCX_BASE      48               /* puts map x=128 in the screen centre */
#define FOG_LINES     14               /* far lines: stripes are sub-pixel, so don't alternate */

/* BGP shade maps: bits 1-0 = colour 0 ... bits 7-6 = colour 3
 * colours: 0 grass, 1 road, 2 rumble, 3 centre line
 * (the stripe rows in ROM are generated from these values by tools/gen_road.py) */
#define BGP_BASE      0xE4             /* identity: sky white, hills dark, HUD black */
#define BGP_A         0x09             /* grass light, road dark, rumble white, line white */
#define BGP_B         0xB8             /* grass white, road dark, rumble black, line = road */
#define BGP_FOG       0x99             /* flat mid-tone for the distant lines */

/* the four road tables: page-aligned WRAM, SCX/BGP for each of the two buffers */
#define TBL_SCX0      ((uint8_t *)0xD000)
#define TBL_BGP0      ((uint8_t *)0xD100)
#define TBL_SCX1      ((uint8_t *)0xD200)
#define TBL_BGP1      ((uint8_t *)0xD300)

#endif
