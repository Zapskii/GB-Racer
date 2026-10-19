/* Screen/road layout shared by main.c and sprites.c.
 * tools/gen_road.py keeps its own copy of the same numbers (the selftest and
 * the model check would notice a mismatch). */
#ifndef LAYOUT_H
#define LAYOUT_H

#define ROAD_TOP      48
#define ROAD_LINES    80
#define IDX0          (ROAD_TOP - 1)   /* tbl[LY] drives line LY+1 */
#define SCX_BASE      48               /* puts map x=128 in the screen centre */
#define FOG_LINES     14               /* far lines: stripes are sub-pixel, so don't alternate */

#endif
