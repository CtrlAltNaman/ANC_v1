#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "clip.h"

static const char *TAG = "clip";

typedef struct __attribute__((packed)) {
    char     riff[4];
    uint32_t riff_sz;       /* everything after this field */
    char     wave[4];
    char     fmt[4];
    uint32_t fmt_sz;        /* 16 for PCM */
    uint16_t fmt_tag;       /* 1 = PCM */
    uint16_t channels;
    uint32_t rate;
    uint32_t byte_rate;
    uint16_t block_align;
    uint16_t bits;
    char     data[4];
    uint32_t data_sz;
} wav_hdr_t;

_Static_assert(sizeof(wav_hdr_t) == 44, "canonical WAV header is 44 bytes");

#define WAV_MAX_BYTES  (sizeof(wav_hdr_t) + CLIP_MAX_FRAMES * sizeof(frame_t))

static SemaphoreHandle_t s_lock;
static frame_t *s_clip;          /* PSRAM, interleaved exactly like a stereo WAV */
static uint8_t *s_wav;           /* PSRAM scratch the HTTP handler sends from */
static size_t   s_len;           /* frames in the finished clip */
static size_t   s_cap;           /* frames this recording is allowed to take */
static size_t   s_rec;           /* frames written so far, recording only */
static bool     s_recording;
static uint32_t s_id;
static int      s_peak_l, s_peak_r;

static inline void lock(void)   { xSemaphoreTake(s_lock, portMAX_DELAY); }
static inline void unlock(void) { xSemaphoreGive(s_lock); }

esp_err_t clip_init(void)
{
    s_lock = xSemaphoreCreateMutex();
    if (!s_lock) return ESP_ERR_NO_MEM;

    s_clip = heap_caps_malloc(CLIP_MAX_FRAMES * sizeof(frame_t), MALLOC_CAP_SPIRAM);
    s_wav  = heap_caps_malloc(WAV_MAX_BYTES, MALLOC_CAP_SPIRAM);
    if (!s_clip || !s_wav) {
        ESP_LOGE(TAG, "PSRAM alloc failed (%u + %u bytes) - clip recorder disabled",
                 (unsigned)(CLIP_MAX_FRAMES * sizeof(frame_t)), (unsigned)WAV_MAX_BYTES);
        return ESP_ERR_NO_MEM;
    }
    ESP_LOGI(TAG, "recorder ready: up to %d ms (%d frames, %u KB clip + %u KB wav scratch)",
             CLIP_MAX_MS, CLIP_MAX_FRAMES,
             (unsigned)(CLIP_MAX_FRAMES * sizeof(frame_t) / 1024),
             (unsigned)(WAV_MAX_BYTES / 1024));
    return ESP_OK;
}

bool clip_begin(uint32_t ms)
{
    if (!s_clip) return false;
    if (ms == 0 || ms > CLIP_MAX_MS) ms = CLIP_MAX_MS;

    lock();
    if (s_recording) { unlock(); return false; }
    s_cap = AUDIO_SAMPLE_RATE / 1000 * ms;
    s_rec = 0;
    s_peak_l = s_peak_r = 0;
    s_recording = true;
    unlock();

    ESP_LOGI(TAG, "recording up to %u ms", (unsigned)ms);
    return true;
}

void clip_write(const frame_t *f, size_t n)
{
    if (!s_clip || !n) return;

    lock();
    if (!s_recording) { unlock(); return; }

    size_t room = s_cap - s_rec;
    bool   full = n >= room;
    if (full) n = room;

    memcpy(&s_clip[s_rec], f, n * sizeof(frame_t));
    for (size_t i = 0; i < n; i++) {
        int l = f[i].primary   < 0 ? -f[i].primary   : f[i].primary;
        int r = f[i].reference < 0 ? -f[i].reference : f[i].reference;
        if (l > s_peak_l) s_peak_l = l;
        if (r > s_peak_r) s_peak_r = r;
    }
    s_rec += n;
    unlock();

    if (full) clip_end();
}

void clip_end(void)
{
    lock();
    if (!s_recording) { unlock(); return; }
    s_recording = false;
    s_len = s_rec;
    s_id++;
    int pl = s_peak_l, pr = s_peak_r;
    size_t len = s_len;
    unlock();

    ESP_LOGI(TAG, "clip ready: %u frames (%u ms), peak L %d (%d%% FS) R %d (%d%% FS)",
             (unsigned)len, (unsigned)(len * 1000 / AUDIO_SAMPLE_RATE),
             pl, pl * 100 / 32767, pr, pr * 100 / 32767);
    if (pl == 0 || pr == 0) {
        ESP_LOGW(TAG, "one channel is flat silent - check the mic whose L/R strap "
                      "picks the %s slot", pl == 0 ? "left" : "right");
    }
}

bool clip_recording(void)
{
    lock();
    bool r = s_recording;
    unlock();
    return r;
}

size_t clip_frames(void)
{
    lock();
    size_t n = s_recording ? 0 : s_len;
    unlock();
    return n;
}

uint32_t clip_id(void)
{
    lock();
    uint32_t id = s_id;
    unlock();
    return id;
}

void clip_peaks(int *left, int *right)
{
    lock();
    if (left)  *left  = s_peak_l;
    if (right) *right = s_peak_r;
    unlock();
}

size_t clip_wav_build(clip_ch_t ch, const uint8_t **out)
{
    if (!s_clip || !s_wav) return 0;

    lock();
    if (s_recording || s_len == 0) { unlock(); return 0; }

    size_t   frames   = s_len;
    uint16_t channels = (ch == CLIP_BOTH) ? 2 : 1;
    size_t   payload  = frames * channels * sizeof(int16_t);

    wav_hdr_t h = {
        .riff = {'R','I','F','F'}, .riff_sz = (uint32_t)(payload + sizeof h - 8),
        .wave = {'W','A','V','E'},
        .fmt  = {'f','m','t',' '}, .fmt_sz = 16, .fmt_tag = 1,
        .channels    = channels,
        .rate        = AUDIO_SAMPLE_RATE,
        .byte_rate   = AUDIO_SAMPLE_RATE * channels * sizeof(int16_t),
        .block_align = channels * sizeof(int16_t),
        .bits        = 16,
        .data = {'d','a','t','a'}, .data_sz = (uint32_t)payload,
    };
    memcpy(s_wav, &h, sizeof h);

    int16_t *pcm = (int16_t *)(s_wav + sizeof h);
    if (ch == CLIP_BOTH) {
        /* The clip is already interleaved L,R - that is the stereo payload. */
        memcpy(pcm, s_clip, payload);
    } else {
        for (size_t i = 0; i < frames; i++) {
            pcm[i] = (ch == CLIP_LEFT) ? s_clip[i].primary : s_clip[i].reference;
        }
    }
    unlock();

    *out = s_wav;
    return sizeof h + payload;
}
