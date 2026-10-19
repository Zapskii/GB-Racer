/*
 * Cycle benchmark for the table builders.  Includes ../src/main.c unmodified (its
 * main() renamed) so it times exactly the shipped code, with interrupts OFF.
 * Time source: DIV register, one tick = 64 M-cycles; each window stays < 16384 cycles.
 * Results are read from the *_res variables by tools/bench.py.
 */
#define main game_main
#include "../src/main.c"
#undef main

extern void bench_cal1024(void);

uint8_t res_cal;                 /* 8 x calibration routine            */
uint8_t res_c[4];                /* build_tables_c, 1 call             */
uint8_t res_fast[4];             /* build_tables_fast (C params + asm), 5 calls */
uint8_t res_asm[4];              /* build_tables_asm only, 5 calls     */
uint8_t res_spr[4];              /* sprites_update, 3 calls, rivals far -> near */
uint8_t res_game[4];             /* game_update, 16 calls: coast / A / A+right / brake+left */
uint8_t res_hud_idle, res_hud_full;  /* hud_update, 16 calls: nothing changed / speed+time+lap+best all changed */
uint8_t res_spr1[4];             /* sprites_update with invuln set (no collision test), 3 calls */
uint8_t res_audio, res_audio_row;   /* audio_update: 7-frame average (one music row per 7 frames), and a row frame alone */
volatile uint8_t bench_done;

void main(void)
{
    static const int16_t  cams[4]   = {     0, 15000, -15000, 5000 };
    static const int16_t  curves[4] = {     0,    50,    -50,   20 };
    static const uint16_t zps[4]    = {     0,    37,    201,    5 };
    uint8_t i, k, d0, d1;

    disable_interrupts();
    for (i = 0; i < 2; i++) {
        memset(tbl_scx[i], SCX_BASE, 256);
        memset(tbl_bgp[i], BGP_BASE, 256);
    }
    init_zlut();

    d0 = DIV_REG;
    for (i = 0; i < 8; i++) bench_cal1024();
    d1 = DIV_REG;
    res_cal = (uint8_t)(d1 - d0);

    for (k = 0; k < 4; k++) {
        d0 = DIV_REG;
        build_tables_c(0, cams[k], curves[k], zps[k]);
        d1 = DIV_REG;
        res_c[k] = (uint8_t)(d1 - d0);

        d0 = DIV_REG;
        for (i = 0; i < 5; i++) build_tables_fast(1, cams[k], curves[k], zps[k]);
        d1 = DIV_REG;
        res_fast[k] = (uint8_t)(d1 - d0);

        build_tables_fast(1, cams[k], curves[k], zps[k]);     /* leaves bt_* set */
        d0 = DIV_REG;
        for (i = 0; i < 5; i++) build_tables_asm();
        d1 = DIV_REG;
        res_asm[k] = (uint8_t)(d1 - d0);
    }
    /* sprites_update: speed 0 so the rivals close in on the camera; 4 phases far -> near */
    sprites_init();
    for (k = 0; k < 4; k++) {
        for (i = 0; i < 30; i++) sprites_update(tbl_scx[1], 0, 0, 0);
        d0 = DIV_REG;
        for (i = 0; i < 3; i++) sprites_update(tbl_scx[1], 0, 0, 0);
        d1 = DIV_REG;
        res_spr[k] = (uint8_t)(d1 - d0);
    }
    /* same rival phases with the collision test skipped (invulnerable): cost of the collision loop */
    for (k = 0; k < 4; k++) {
        for (i = 0; i < 30; i++) sprites_update(tbl_scx[1], 0, 0, 1);
        d0 = DIV_REG;
        for (i = 0; i < 3; i++) sprites_update(tbl_scx[1], 0, 0, 1);
        d1 = DIV_REG;
        res_spr1[k] = (uint8_t)(d1 - d0);
    }
    /* game_update */
    {
        static const uint8_t keysets[4] = { 0, J_A, J_A | J_RIGHT, J_B | J_LEFT };
        game_init();
        g_speed = 60;
        for (k = 0; k < 4; k++) {
            d0 = DIV_REG;
            for (i = 0; i < 16; i++) { game_update(keysets[k]); if (k == 3) g_speed = 60; }
            d1 = DIV_REG;
            res_game[k] = (uint8_t)(d1 - d0);
        }
    }
    /* hud_update: idle, then worst case where every field changes every call */
    hud_init();
    hud_update();
    d0 = DIV_REG;
    for (i = 0; i < 16; i++) hud_update();
    d1 = DIV_REG;
    res_hud_idle = (uint8_t)(d1 - d0);
    d0 = DIV_REG;
    for (i = 0; i < 16; i++) {
        g_speed = (i & 1) ? 77 : 38; g_lap = i + 1; g_tenths = 1234 + i; g_best_tenths = 987 + i;
        hud_update();
    }
    d1 = DIV_REG;
    res_hud_full = (uint8_t)(d1 - d0);
    /* audio_update with the engine running; per call average over 63 calls = 9 music rows (kept under one DIV wrap: 256 ticks) */
    audio_init();
    for (i = 0; i < 30; i++) audio_update(40, 0, 0);
    d0 = DIV_REG;
    for (i = 0; i < 63; i++) audio_update(40 + (i & 31), 0, 0);
    d1 = DIV_REG;
    res_audio = (uint8_t)(d1 - d0);
    audio_init();                       /* first call after init starts a row: the worst case (three notes) */
    d0 = DIV_REG;
    audio_update(40, 0, 0);
    d1 = DIV_REG;
    res_audio_row = (uint8_t)(d1 - d0);
    bench_done = 1;
    for (;;) ;
}
