/*
 * One recorded clip, held in PSRAM, served three ways over HTTP.
 *
 * The capture task owns the writer side (clip_begin / clip_write / clip_end).
 * The HTTP task owns the reader side (clip_wav_build). A mutex covers both,
 * but no path holds it for long: the reader copies the clip into a WAV scratch
 * buffer under the lock and releases it before it starts pushing bytes at the
 * socket, so a slow browser can never stall the I2S read loop into an overrun.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

#define AUDIO_SAMPLE_RATE   16000
#define CLIP_MAX_MS         10000
#define CLIP_MAX_FRAMES     (AUDIO_SAMPLE_RATE / 1000 * CLIP_MAX_MS)

/* Mic A (L/R strapped to GND) lands in the left slot, mic B (strapped to 3V3)
 * in the right slot. Keep the names the stream protocol already uses. */
typedef struct { int16_t primary; int16_t reference; } frame_t;

typedef enum {
    CLIP_LEFT,      /* mono, mic A only */
    CLIP_RIGHT,     /* mono, mic B only */
    CLIP_BOTH,      /* stereo, mic A left channel + mic B right channel */
} clip_ch_t;

esp_err_t clip_init(void);

/* Writer side, capture task only. clip_begin() caps the request at
 * CLIP_MAX_MS; clip_write() closes the clip by itself once it is full. */
bool   clip_begin(uint32_t ms);
void   clip_write(const frame_t *f, size_t n);
void   clip_end(void);
bool   clip_recording(void);

/* Reader side. frames/ms/peaks describe the last finished clip. */
size_t clip_frames(void);
void   clip_peaks(int *left, int *right);

/* Bumped every time a clip is finished, whatever started it. The page watches
 * this to tell a new recording from the one it is already holding. */
uint32_t clip_id(void);

/* Builds the WAV into the scratch buffer and returns its length, 0 if there is
 * nothing to serve or a recording is in progress. The returned pointer stays
 * valid until the next call - the HTTP server runs one handler at a time. */
size_t clip_wav_build(clip_ch_t ch, const uint8_t **out);
