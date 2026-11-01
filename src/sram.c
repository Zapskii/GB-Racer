/*
 * Battery-backed save (MBC1 cartridge RAM, 8 KB at $A000, only the first 61 bytes are used):
 *
 *   0      'G'            magic
 *   1      'R'
 *   2      format version (1)
 *   3      title screen track      4: laps option     5: level
 *   6..59  best race times, 27 x uint16 little endian: [level][track][laps option]
 *   60     checksum = (sum of bytes 2..59) ^ 0xA5
 *
 * A bad magic, version, checksum or selection (a fresh cartridge, or RAM that lost its battery)
 * just means "no records": everything is cleared and the next save writes a valid block.
 */
#pragma bank 1                                  /* called rarely, with the road ISR off: bank 0 is full */
#include <gb/gb.h>
#include "game.h"

#define SRAM        ((volatile uint8_t *)0xA000)
#define SAVE_BYTES  61
#define N_REC       (N_LEVELS * N_TRACKS * N_LAP_OPTIONS)

static uint8_t checksum(void)
{
    uint8_t i, c = 0;
    for (i = 2; i < SAVE_BYTES - 1; i++)
        c += SRAM[i];
    return c ^ 0xA5;
}

static void clear_records(void)
{
    uint8_t i;
    uint16_t *p = &g_best_total[0][0][0];
    for (i = 0; i < N_REC; i++)
        p[i] = 0;
}

void sram_load(void) BANKED
{
    uint8_t i, ok;
    uint16_t *p = &g_best_total[0][0][0];

    *(volatile uint8_t *)0x0000 = 0x0A;                 /* RAM enable */
    ok = SRAM[0] == 'G' && SRAM[1] == 'R' && SRAM[2] == 1 && SRAM[SAVE_BYTES - 1] == checksum() &&
         SRAM[3] < N_TRACKS && SRAM[4] < N_LAP_OPTIONS && SRAM[5] < N_LEVELS;
    if (ok) {
        g_track    = SRAM[3];
        g_laps_sel = SRAM[4];
        g_level    = SRAM[5];
        for (i = 0; i < N_REC; i++)
            p[i] = (uint16_t)SRAM[6 + 2 * i] | ((uint16_t)SRAM[7 + 2 * i] << 8);
    } else {
        clear_records();
    }
    *(volatile uint8_t *)0x0000 = 0x00;                 /* RAM disable: protects the save from a crash or power-off */
}

void sram_save(void) BANKED
{
    uint8_t i;
    uint16_t *p = &g_best_total[0][0][0];

    *(volatile uint8_t *)0x0000 = 0x0A;
    SRAM[0] = 'G';
    SRAM[1] = 'R';
    SRAM[2] = 1;
    SRAM[3] = g_track;
    SRAM[4] = g_laps_sel;
    SRAM[5] = g_level;
    for (i = 0; i < N_REC; i++) {
        SRAM[6 + 2 * i] = (uint8_t)p[i];
        SRAM[7 + 2 * i] = (uint8_t)(p[i] >> 8);
    }
    SRAM[SAVE_BYTES - 1] = checksum();
    *(volatile uint8_t *)0x0000 = 0x00;
}
