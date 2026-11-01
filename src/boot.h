#ifndef BOOT_H
#define BOOT_H
#include <gb/gb.h>

/* Start-up video: the Super Game Boy border (if any), then the road/sky tiles, the background
   map and the road tables.  Leaves the LCD off.  Lives in ROM bank 1 with the data it copies. */
void boot_video(void) BANKED;

#endif
