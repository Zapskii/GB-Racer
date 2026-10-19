#ifndef AUDIO_H
#define AUDIO_H
#include <stdint.h>

void audio_init(void);
/* Once per frame, after game_update/sprites_update.  A changed `hits` count is a crash. */
void audio_update(int16_t speed, uint8_t offroad, uint8_t hits);
/* Start a jingle on channel 2 (SFX_LAP, SFX_BEEP, SFX_GO, SFX_FINISH from audio_data.h); replaces one playing. */
void audio_sfx(uint8_t id);

#ifdef PROFILE
extern uint8_t dbg_audio_music_off;   /* tests: non-zero silences the music (engine/effects only) */
extern uint8_t dbg_audio_solo;        /* tests: mask ANDed into NR51 every frame, to listen to one channel */
extern uint8_t dbg_audio_last_hits;   /* tests: the hits argument the last audio_update saw (must track g_hits) */
#endif
#endif
