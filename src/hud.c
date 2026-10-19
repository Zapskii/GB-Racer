#include <gb/gb.h>
#include <string.h>
#include "road_data.h"          /* SKY_TILE_COUNT: font tiles go right after the sky tiles at $8800 */
#include "hud_data.h"
#include "game.h"
#include "hud.h"

#define HUD_TILE0   (128 + SKY_TILE_COUNT)          /* BG tile id of glyph 0 (signed addressing, $8800 block) */
#define GT(f)       ((uint8_t)(HUD_TILE0 + (f)))
#define DIGIT(n)    GT(F_DIGIT0 + (n))
#define WIN_MAP     ((uint8_t *)0x9C00)

static uint8_t last_speed, last_lap, last_place, banner_on;
static uint16_t last_tenths, last_best;

static uint8_t glyph(char c)
{
    uint8_t i;
    for (i = 0; hud_chars[i]; i++)
        if (hud_chars[i] == c)
            return i;
    return F_SPACE;
}

static void put_text(uint8_t x, uint8_t y, const char *s)
{
    uint8_t t[20], n = 0;
    while (*s) t[n++] = GT(glyph(*s++));
    set_win_tiles(x, y, n, 1, t);
}

static void draw_number(uint8_t x, uint8_t y, uint8_t v, uint8_t digits)
{
    uint8_t t[3], h = 0, d = 0;
    while (v >= 100) { v -= 100; h++; }
    while (v >= 10)  { v -= 10;  d++; }
    if (digits == 3) { t[0] = DIGIT(h); t[1] = DIGIT(d); t[2] = DIGIT(v); }
    else             { t[0] = DIGIT(d); t[1] = DIGIT(v); }
    set_win_tiles(x, y, digits, 1, t);
}

/* m:ss.t from tenths of a second; saturates at 9:59.9 */
static void draw_time(uint8_t x, uint8_t y, uint16_t tenths)
{
    uint8_t t[6], m = 0, s10 = 0, s1 = 0;
    if (tenths > 5999) tenths = 5999;
    while (tenths >= 600) { tenths -= 600; m++; }
    while (tenths >= 100) { tenths -= 100; s10++; }
    while (tenths >= 10)  { tenths -= 10;  s1++; }
    t[0] = DIGIT(m); t[1] = GT(F_COLON); t[2] = DIGIT(s10); t[3] = DIGIT(s1);
    t[4] = GT(F_DOT); t[5] = DIGIT(tenths);
    set_win_tiles(x, y, 6, 1, t);
}

/* mm:ss.t for whole races; saturates at 99:59.9 */
static void draw_total(uint8_t x, uint8_t y, uint16_t tenths)
{
    uint8_t t[7], m10 = 0, m1 = 0, s10 = 0, s1 = 0;
    if (tenths > 59999u) tenths = 59999u;
    while (tenths >= 6000) { tenths -= 6000; m10++; }
    while (tenths >= 600)  { tenths -= 600;  m1++; }
    while (tenths >= 100)  { tenths -= 100;  s10++; }
    while (tenths >= 10)   { tenths -= 10;   s1++; }
    t[0] = DIGIT(m10); t[1] = DIGIT(m1); t[2] = GT(F_COLON); t[3] = DIGIT(s10); t[4] = DIGIT(s1);
    t[5] = GT(F_DOT); t[6] = DIGIT(tenths);
    set_win_tiles(x, y, 7, 1, t);
}

static void clear_rows(uint8_t y0, uint8_t y1)
{
    uint8_t row[20];
    memset(row, GT(F_SPACE), 20);
    for (; y0 < y1; y0++)
        set_win_tiles(0, y0, 20, 1, row);
}

void hud_init(void)
{
    LCDC_REG |= 0x60;               /* window on, window map at $9C00 - BEFORE any set_win_tiles: it picks the map
                                       from this bit, so doing it later wrote labels into the background map */
    memcpy((void *)(0x8800 + SKY_TILE_COUNT * 16), hud_font, HUD_GLYPHS * 16);
    memset(WIN_MAP, GT(F_SPACE), 32 * 32);          /* the whole window map starts black */
    WX_REG = 7;                     /* window starts at the left edge ... */
    hud_race_screen();
}

void hud_race_screen(void)
{
    clear_rows(0, 2);                /* the window shows two rows during a race; the title/results pages clear their own */
    put_text(0, 0, "SPD 000 LAP 01/");
    draw_number(15, 0, g_laps_total, 2);
    put_text(18, 0, "P");                  /* P1 / P2 / P3: race position, digit at column 19 */
    put_text(0, 1, "TIME 0:00.0 B -:--.-");
    WY_REG = 128;                   /* ... and at line 128 */
    last_speed = 255; last_lap = 255; last_place = 255; last_tenths = 0xFFFF; last_best = 0xFFFF;
    banner_on = 0;
}

/* Banner and race-screen changes asked for from the main loop are only recorded here and drawn at the start of
 * the next frame's VBlank (hud_update), where VRAM is writable; drawing in the middle of the frame stalls on the
 * LCD's VRAM lock and made the loop miss a frame. */
static char    pend_text[21];
static uint8_t pend;                /* 0 nothing, 1 banner, 2 race screen */

void hud_banner(const char *text)
{
    uint8_t i = 0;
    while (i < 20 && text[i]) { pend_text[i] = text[i]; i++; }
    while (i < 20) pend_text[i++] = ' ';
    pend_text[20] = 0;
    pend = 1;
    banner_on = 1;                  /* hud_update leaves row 0 alone from now on */
}

void hud_request_race_screen(void)
{
    pend = 2;
}

void hud_update(void)
{
    uint8_t sp = (uint8_t)(((uint16_t)g_speed * 5) >> 1);     /* speed 80 shows as 200 */
    if (pend) {
        uint8_t k = pend;
        pend = 0;
        if (k == 1) put_text(0, 0, pend_text);
        else        hud_race_screen();
    }
    if (banner_on) return;                                    /* a banner owns row 0 until hud_race_screen() */
    if (sp != last_speed) { draw_number(4, 0, sp, 3); last_speed = sp; }
    if (g_lap != last_lap) { draw_number(12, 0, g_lap > 99 ? 99 : g_lap, 2); last_lap = g_lap; }
    if (g_place != last_place) {
        uint8_t t = DIGIT(g_place);
        set_win_tiles(19, 0, 1, 1, &t);
        last_place = g_place;
    }
    if (g_tenths != last_tenths) { draw_time(5, 1, g_tenths); last_tenths = g_tenths; }
    if (g_best_tenths != last_best) {
        if (g_best_tenths) draw_time(14, 1, g_best_tenths);
        last_best = g_best_tenths;
    }
}

/* ---- full-screen pages: the window covers the whole display ---- */
static void put_track_name(uint8_t x, uint8_t y)
{
    char t[9];
    uint8_t i = 0;
    const char *n = track_name[g_track];
    while (n[i]) { t[i] = n[i]; i++; }
    while (i < 8) t[i++] = ' ';
    t[8] = 0;
    put_text(x, y, t);
}

void hud_title_laps(void)
{
    char t[9];
    uint8_t i = 0;
    const char *n = level_name[g_level];
    put_text(3, 4, "TRACK");
    put_track_name(9, 4);
    put_text(5, 6, "LAPS <");
    draw_number(12, 6, lap_options[g_laps_sel], 2);
    put_text(14, 6, " >");
    put_text(3, 8, "LEVEL");
    while (n[i]) { t[i] = n[i]; i++; }
    while (i < 8) t[i++] = ' ';
    t[8] = 0;
    put_text(9, 8, t);
    put_text(4, 10, "BEST");
    if (g_best_total[g_level][g_track][g_laps_sel])
        draw_total(9, 10, g_best_total[g_level][g_track][g_laps_sel]);
    else
        put_text(9, 10, "--:--.-");
}

void hud_title(void)
{
    clear_rows(0, 18);
    put_text(6, 2, "GB RACER");
    put_text(3, 12, "UP DOWN TRACK");
    put_text(3, 13, "LEFT RIGHT LAPS");
    put_text(3, 14, "SELECT LEVEL");
    put_text(3, 15, "A GAS  B BRAKE");
    put_text(4, 17, "PRESS START");
    hud_title_laps();
    WY_REG = 0;
}

void hud_results(void)
{
    clear_rows(0, 18);
    put_text(6, 3, "FINISH!");
    put_track_name(6, 4);
    put_text(3, 6, "TIME");
    draw_total(9, 6, g_race_tenths);
    put_text(3, 8, "BEST LAP");
    draw_time(12, 8, g_best_tenths);
    put_text(4, 10, "PLACE   OF 3");
    { uint8_t t = DIGIT(g_place); set_win_tiles(10, 10, 1, 1, &t); }
    if (g_place == 1)
        put_text(6, 12, "YOU WIN!");
    if (g_new_record)
        put_text(4, 13, "NEW RECORD!");
    put_text(4, 15, "PRESS START");
    WY_REG = 0;
}
