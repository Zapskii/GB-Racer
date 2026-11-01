#ifndef SGB_BOOT_H
#define SGB_BOOT_H
#include <gb/gb.h>

/* Send the Super Game Boy border and the game-screen palette.  Call once at boot, before any
   graphics are loaded: the transfer overwrites VRAM.  Does nothing on a plain Game Boy. */
void sgb_boot(void) BANKED;

#endif
