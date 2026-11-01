/*
 * Super Game Boy border, sent once at boot from ROM bank 4 (bank 0 is full).
 *
 * The border is tools/sgb/racer_art.py's art, packed by GB-SGB-Tooling's mkborder.py and
 * converted by png2asset into src/border_data.c (`make border`).  sgb_border.c is that
 * tool's fixed copy of GBDK's transfer code, unchanged; it is included here rather than
 * compiled on its own so that it lands in this bank with the data it reads.
 */
#pragma bank 4

#include <gb/gb.h>
#include <gb/sgb.h>
#include <stdint.h>

#include "sgb_border.c"
#include "border_data.h"
#include "sgb_boot.h"

/* PAL01: SGB palettes 0 and 1 (colour 0 shared).  Palette 0 colours the game screen: plain
   greys, so the game looks as it does on a Game Boy.  A real SGB starts with its own
   default, but some emulators (Gearboy without the SGB boot ROM) start it all black. */
static const uint8_t pal01[16] = {
    (SGB_PAL_01 << 3) | 1,
    0xFF, 0x7F,     /* white       RGB555 little-endian */
    0x94, 0x52,     /* light grey */
    0x4A, 0x29,     /* dark grey  */
    0x00, 0x00,     /* black      */
};

void sgb_boot(void) BANKED
{
    uint8_t i;

    DISPLAY_ON;
    for (i = 4; i != 0; i--) vsync();          /* a PAL SNES needs a few frames before sgb_check() answers */
    set_sgb_border(border_data_tiles, sizeof(border_data_tiles),
                   border_data_map, sizeof(border_data_map),
                   (const unsigned char *)border_data_palettes, sizeof(border_data_palettes));
    if (sgb_check())
        sgb_transfer((uint8_t *)pal01);
    DISPLAY_OFF;                               /* main() loads the game's graphics with the LCD off */
}
