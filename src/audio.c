/*
 * Sound: a small sequencer for the tune plus engine / crash / lap effects.  No external driver:
 * the tune is a few hundred bytes of (note, rows) pairs from tools/gen_audio.py.
 *
 *   channel 1  lead melody            (pulse 25%)
 *   channel 2  harmony arpeggio       (pulse 50%), borrowed by the lap jingle
 *   channel 3  bass                   (triangle from wave RAM)
 *   channel 4  engine drone (7-bit noise, pitch follows speed), gravel hiss off the road, crash burst
 *
 * audio_update() runs once per frame from the main loop; all register writes are plain stores, none is
 * timing sensitive (the road ISR only touches SCX and BGP).
 */
#include <gb/gb.h>
#include <gb/hardware.h>
#include "audio_data.h"
#include "audio.h"

#define CRASH_FRAMES   36
#define NR51_ALL       0xFF
#define NR51_NO_CH4    0x77

typedef struct {
    const uint8_t *start, *p;
    uint8_t left;                      /* rows left in the current note */
} voice_t;

uint8_t g_sound_on = 1;                 /* pause menu: 0 mutes music and effects (runtime only, not saved) */

static voice_t lead, harm, bass;
static uint8_t row_tick;
static uint8_t nr51 = NR51_NO_CH4;      /* panning: channel 4 is switched off here when the engine is silent */
static uint8_t last_n43;
static uint8_t eng_on, crash_left, jingle_pos, jingle_tick, jingle_id, jingle_n, last_hits;

#ifdef PROFILE
uint8_t dbg_audio_music_off;
uint8_t dbg_audio_solo = 0xFF;          /* tests: NR51 channel mask (bit n and n+4 = channel n+1) */
uint8_t dbg_audio_last_hits;            /* tests: the `hits` argument the last audio_update saw */
#endif

static void voice_init(voice_t *v, const uint8_t *data)
{
    v->start = v->p = data;
    v->left = 0;
}

/* next (note, rows) of a voice; returns the note index (0 = rest) */
static uint8_t voice_next(voice_t *v)
{
    uint8_t n;
    if (*v->p == 0xFF)
        v->p = v->start;
    n = v->p[0];
    v->left = v->p[1];
    v->p += 2;
    return n;
}

static void lead_note(uint8_t n)
{
    if (n) {
        uint16_t f = pulse_freq[n];
        NR11_REG = 0x40;                       /* duty 25% */
        NR12_REG = 0xA2;                       /* volume 10, decay */
        NR13_REG = (uint8_t)f;
        NR14_REG = 0x80 | (uint8_t)(f >> 8);
    } else {
        NR12_REG = 0;                          /* DAC off: silence */
    }
}

static void harm_note(uint8_t n)
{
    if (jingle_pos)                            /* the jingle owns channel 2 */
        return;
    if (n) {
        uint16_t f = pulse_freq[n];
        NR21_REG = 0x80;
        NR22_REG = 0x62;                       /* volume 6, decay */
        NR23_REG = (uint8_t)f;
        NR24_REG = 0x80 | (uint8_t)(f >> 8);
    } else {
        NR22_REG = 0;
    }
}

static void bass_note(uint8_t n)
{
    if (n) {
        uint16_t f = wave_freq[n];
        NR32_REG = 0x20;                       /* full volume */
        NR33_REG = (uint8_t)f;
        NR34_REG = 0x80 | (uint8_t)(f >> 8);
    } else {
        NR32_REG = 0;
    }
}

static void jingle_note(void)
{
    uint16_t f = pulse_freq[sfx_notes[sfx_off[jingle_id] + jingle_pos - 1]];
    NR21_REG = 0x80;
    NR22_REG = 0xC2;                           /* volume 12, decay */
    NR23_REG = (uint8_t)f;
    NR24_REG = 0x80 | (uint8_t)(f >> 8);
}

void audio_sfx(uint8_t id)
{
    jingle_id = id;
    jingle_n = sfx_off[id + 1] - sfx_off[id];
    jingle_pos = 1;
    jingle_tick = 0;
    jingle_note();
}

void audio_init(void)
{
    uint8_t i;

    NR52_REG = 0x80;                           /* sound on */
    NR50_REG = 0x77;                           /* master volume max */
    NR51_REG = nr51 = NR51_NO_CH4;
    NR10_REG = 0;                              /* no frequency sweep */
    NR30_REG = 0;                              /* channel 3 off while the wave RAM is loaded */
    for (i = 0; i < 16; i++)
        *(volatile uint8_t *)(0xFF30 + i) = wave_ram[i];
    NR30_REG = 0x80;
    voice_init(&lead, mus_lead);
    voice_init(&harm, mus_harm);
    voice_init(&bass, mus_bass);
    row_tick = 0;
    eng_on = crash_left = jingle_pos = jingle_tick = 0;
    last_hits = 0;
    /* first row plays at the first update */
    row_tick = ROW_FRAMES - 1;
}

static void audio_step(int16_t speed, uint8_t offroad, uint8_t hits)
{
#ifdef PROFILE
    dbg_audio_last_hits = hits;
#endif
    /* ---- events ---- */
    if (hits != last_hits) {
        last_hits = hits;
        crash_left = CRASH_FRAMES;
        eng_on = 0;
        NR41_REG = 0;
        NR42_REG = 0xF3;                       /* volume 15, slow decay */
        NR43_REG = 0x73;                       /* 15-bit noise, low clock: a thud */
        NR44_REG = 0x80;
        nr51 = NR51_ALL;
    }

    /* ---- music: one row every ROW_FRAMES frames ---- */
    if (++row_tick >= ROW_FRAMES) {
        row_tick = 0;
#ifdef PROFILE
        if (dbg_audio_music_off) {
            NR12_REG = 0; if (!jingle_pos) NR22_REG = 0; NR32_REG = 0;
        } else
#endif
        {
            if (lead.left == 0) lead_note(voice_next(&lead));
            if (harm.left == 0) harm_note(voice_next(&harm));
            if (bass.left == 0) bass_note(voice_next(&bass));
            lead.left--; harm.left--; bass.left--;
        }
    }

    /* ---- lap jingle on channel 2 ---- */
    if (jingle_pos) {
        if (++jingle_tick >= (jingle_pos == jingle_n ? sfx_hold[jingle_id] : sfx_step[jingle_id])) {
            jingle_tick = 0;
            if (jingle_pos == jingle_n) {
                jingle_pos = 0;
                NR22_REG = 0;                  /* back to the harmony voice at its next note */
                harm.left = 0;
            } else {
                jingle_pos++;
                jingle_note();
            }
        }
    }

    /* ---- engine / crash on channel 4 ---- */
    if (crash_left) {
        crash_left--;
        return;                                /* the crash owns the noise channel */
    }
    if (speed <= 0) {
        if (eng_on) { nr51 = NR51_NO_CH4; eng_on = 0; }
        return;
    }
    {
        uint8_t n43 = offroad ? 0x43 : eng_nr43[((uint8_t)speed * 3) >> 5];   /* speed 0..80 -> ladder step 0..7 (no division) */
        if (!eng_on) {
            NR41_REG = 0;
            NR42_REG = 0x40;                   /* constant volume 4 */
            NR43_REG = n43;                    /* pitch before the trigger: the trigger restarts the noise generator */
            NR44_REG = 0x80;
            nr51 = NR51_ALL;
            eng_on = 1;
            last_n43 = n43;
        } else if (n43 != last_n43) {
            NR43_REG = n43;
            if ((n43 ^ last_n43) & 0x08)       /* 7-bit <-> 15-bit: restart the generator so it cannot be left in a locked state */
                NR44_REG = 0x80;
            last_n43 = n43;
        }
    }
}

void audio_update(int16_t speed, uint8_t offroad, uint8_t hits)
{
    audio_step(speed, offroad, hits);
#ifdef PROFILE
    NR51_REG = g_sound_on ? (nr51 & dbg_audio_solo) : 0;
#else
    NR51_REG = g_sound_on ? nr51 : 0;
#endif
}
