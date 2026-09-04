/*
 * SIH 26052 - Phase 1 capture node.
 *
 * Two INMP441 on one shared I2S bus, PTT-gated USB stream to the Pi 5, plus a
 * small web player for bench checks (record a clip, listen to either mic or
 * both together from a phone).
 *
 *   GPIO 4  SCK  -> both mics (through 68R at this end)
 *   GPIO 5  WS   -> both mics (through 68R at this end)
 *   GPIO 6  SD   <- both mics (100k pull-down is already on the modules)
 *   GPIO 7  red LED   cathode, anode via 330R to 3V3 - powered, mic live
 *   GPIO 15 green LED cathode, anode via 330R to 3V3 - transmitting
 *   GPIO 16 PTT button to GND, internal pull-up, 100nF to GND
 *
 * Mic A has L/R strapped to GND  -> left  slot -> primary
 * Mic B has L/R strapped to 3V3  -> right slot -> reference
 *
 * The I2S peripheral never stops. PTT only gates the output path, so the mics
 * stay awake (they need tens of ms to settle after a clock restart) and the
 * noise estimator downstream stays converged between transmissions.
 */

#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2s_std.h"
#include "driver/gpio.h"
#include "driver/usb_serial_jtag.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "clip.h"
#include "web.h"

static const char *TAG = "anc";

#define PIN_I2S_SCK     GPIO_NUM_4
#define PIN_I2S_WS      GPIO_NUM_5
#define PIN_I2S_SD      GPIO_NUM_6
#define PIN_LED_RED     GPIO_NUM_7
#define PIN_LED_GREEN   GPIO_NUM_15
#define PIN_PTT         GPIO_NUM_16

/* LEDs hang off 3V3 through their series resistor and the GPIO sinks the
 * current, so a LOW level lights them. Set this to 0 if you ever rewire them
 * the other way round (GPIO -> 330R -> anode, cathode -> GND). */
#define LED_ACTIVE_LOW  1

#define SAMPLE_RATE     AUDIO_SAMPLE_RATE
#define CHUNK_MS        20
#define CHUNK_FRAMES    (SAMPLE_RATE * CHUNK_MS / 1000)     /* 320 */
#define PREROLL_MS      500
#define PREROLL_FRAMES  (SAMPLE_RATE * PREROLL_MS / 1000)   /* 8000 */
#define HANGOVER_MS     200
#define HANGOVER_CHUNKS (HANGOVER_MS / CHUNK_MS)            /* 10 */

#define DMA_DESC_NUM    10
#define DMA_FRAME_NUM   400
#define DMA_MS          (DMA_DESC_NUM * DMA_FRAME_NUM * 1000 / SAMPLE_RATE)

/* The INMP441 sends 24 bits MSB-aligned inside a 32-bit slot, so the sample
 * sits in bits 31..8 of the word we read. >>16 takes the top 16 bits at unity
 * scale. If the level is too low on the bench, drop this to 15 or 14 - each
 * step doubles the gain, and sat16() below stops it wrapping on a gunshot.
 * Do not push it so far that impulsive noise clips: clipped training data is
 * worse than quiet training data. */
#define GAIN_SHIFT      16

#define PKT_MAGIC       0x30434E41u    /* "ANC0" little-endian */
#define FLAG_PREROLL    0x0001

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint32_t seq;       /* per packet; a gap means the host missed one */
    uint16_t frames;
    uint16_t flags;
} pkt_hdr_t;

static i2s_chan_handle_t s_rx;
static frame_t  *s_preroll;      /* circular, holds history BEFORE the current chunk */
static size_t    s_head;         /* next write index */
static size_t    s_fill;         /* valid frames, saturates at PREROLL_FRAMES */
static uint32_t  s_seq;

static int32_t s_raw[CHUNK_FRAMES * 2];
static frame_t s_chunk[CHUNK_FRAMES];
static uint8_t s_tx[sizeof(pkt_hdr_t) + CHUNK_FRAMES * sizeof(frame_t)];

static inline void led(gpio_num_t pin, bool on)
{
    gpio_set_level(pin, LED_ACTIVE_LOW ? !on : on);
}

static inline int16_t sat16(int32_t v)
{
    if (v >  32767) return  32767;
    if (v < -32768) return -32768;
    return (int16_t)v;
}

/* One write per packet so a stalled host truncates at a packet boundary rather
 * than mid-payload. The host still resyncs on magic if the cable is yanked. */
static void send_frames(const frame_t *f, size_t n, uint16_t flags)
{
    pkt_hdr_t h = { .magic = PKT_MAGIC, .seq = s_seq++,
                    .frames = (uint16_t)n, .flags = flags };
    size_t payload = n * sizeof(frame_t);

    memcpy(s_tx, &h, sizeof h);
    memcpy(s_tx + sizeof h, f, payload);
    /* Short timeout on purpose: if the Pi is not draining, drop the packet and
     * keep servicing I2S. A dropped packet is a seq gap on the host; a blocked
     * read task is a DMA overflow and an audible click. */
    usb_serial_jtag_write_bytes(s_tx, sizeof h + payload, pdMS_TO_TICKS(10));
}

static void ring_write(const frame_t *src, size_t n)
{
    if (n > PREROLL_FRAMES) { src += n - PREROLL_FRAMES; n = PREROLL_FRAMES; }
    size_t first = PREROLL_FRAMES - s_head;
    if (first > n) first = n;
    memcpy(&s_preroll[s_head], src, first * sizeof(frame_t));
    if (n > first) memcpy(s_preroll, src + first, (n - first) * sizeof(frame_t));
    s_head = (s_head + n) % PREROLL_FRAMES;
    s_fill += n;
    if (s_fill > PREROLL_FRAMES) s_fill = PREROLL_FRAMES;
}

/* Flush the buffered history the moment PTT goes down, so the transmission
 * starts half a second before the thumb did. */
static void send_preroll(void)
{
    size_t start = (s_head + PREROLL_FRAMES - s_fill) % PREROLL_FRAMES;
    size_t left  = s_fill;
    while (left) {
        size_t n = (left < CHUNK_FRAMES) ? left : CHUNK_FRAMES;
        if (start + n > PREROLL_FRAMES) n = PREROLL_FRAMES - start;
        send_frames(&s_preroll[start], n, FLAG_PREROLL);
        start = (start + n) % PREROLL_FRAMES;
        left -= n;
    }
}

/* Polled once per chunk, not interrupt driven - the 100nF makes the edge slow
 * enough to retrigger an ISR. The debounce is measured in microseconds rather
 * than in chunks: when the loop is draining a DMA backlog it runs several
 * times faster than real time, and a chunk-counted debounce silently gets
 * shorter exactly when the supply is noisiest. */
#define PTT_DEBOUNCE_US  40000

static bool ptt_held(void)
{
    static int stable = 1, cand = 1;        /* 1 = released, pull-up idle high */
    static int64_t since;

    int now = gpio_get_level(PIN_PTT);
    int64_t t = esp_timer_get_time();

    if (now != cand) {
        cand  = now;
        since = t;
    } else if (cand != stable && t - since >= PTT_DEBOUNCE_US) {
        stable = cand;
    }
    return stable == 0;
}

/* ------------------------------------------------------------- bring-up */

static esp_err_t gpio_bring_up(void)
{
    esp_err_t err;

    gpio_config_t leds = {
        .pin_bit_mask = (1ULL << PIN_LED_RED) | (1ULL << PIN_LED_GREEN),
        .mode = GPIO_MODE_OUTPUT,
    };
    err = gpio_config(&leds);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "gpio: LED config failed: %s", esp_err_to_name(err));
        return err;
    }
    led(PIN_LED_RED, false);
    led(PIN_LED_GREEN, false);
    ESP_LOGI(TAG, "gpio: LEDs ok - red GPIO%d, green GPIO%d, active %s",
             PIN_LED_RED, PIN_LED_GREEN, LED_ACTIVE_LOW ? "low" : "high");

    gpio_config_t btn = {
        .pin_bit_mask = 1ULL << PIN_PTT,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    err = gpio_config(&btn);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "gpio: PTT config failed: %s", esp_err_to_name(err));
        return err;
    }

    int idle = gpio_get_level(PIN_PTT);
    ESP_LOGI(TAG, "gpio: PTT ok - GPIO%d input, pull-up on, idle level %d (%s)",
             PIN_PTT, idle, idle ? "released" : "PRESSED");
    if (idle == 0) {
        ESP_LOGW(TAG, "gpio: PTT is low at boot - button held, stuck, or the "
                      "switch is wired to GND on both sides");
    }
    return ESP_OK;
}

static esp_err_t usb_bring_up(void)
{
    usb_serial_jtag_driver_config_t usb = {
        .rx_buffer_size = 256,
        .tx_buffer_size = 8192,
    };
    esp_err_t err = usb_serial_jtag_driver_install(&usb);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "usb: driver install failed: %s", esp_err_to_name(err));
        return err;
    }
    ESP_LOGI(TAG, "usb: serial/jtag ready - rx %d B, tx %d B, %d B per packet",
             usb.rx_buffer_size, usb.tx_buffer_size, (int)sizeof s_tx);
    return ESP_OK;
}

static esp_err_t i2s_bring_up(void)
{
    esp_err_t err;

    /* ~250 ms of DMA buffering. It has to cover the burst while the 500 ms
     * pre-roll is pushed out over USB, or we overflow on every keying. */
    i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    cc.dma_desc_num  = DMA_DESC_NUM;
    cc.dma_frame_num = DMA_FRAME_NUM;

    err = i2s_new_channel(&cc, NULL, &s_rx);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s: [1/3] channel alloc FAILED: %s", esp_err_to_name(err));
        return err;
    }
    ESP_LOGI(TAG, "i2s: [1/3] rx channel on I2S_NUM_0, master, %d x %d frames "
                  "of DMA (%d ms)", DMA_DESC_NUM, DMA_FRAME_NUM, DMA_MS);

    i2s_std_config_t std = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        /* 32-bit slots are mandatory: the INMP441 needs 64 BCLK per WS frame.
         * Asking for 24 gives 48 and the mic returns garbage. */
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT,
                                                        I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,        /* INMP441 has no MCLK pin */
            .bclk = PIN_I2S_SCK,
            .ws   = PIN_I2S_WS,
            .din  = PIN_I2S_SD,
            .dout = I2S_GPIO_UNUSED,
            .invert_flags = { false, false, false },
        },
    };
    err = i2s_channel_init_std_mode(s_rx, &std);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s: [2/3] std mode init FAILED: %s - check that GPIO "
                      "%d/%d/%d are free", esp_err_to_name(err),
                 PIN_I2S_SCK, PIN_I2S_WS, PIN_I2S_SD);
        return err;
    }
    ESP_LOGI(TAG, "i2s: [2/3] std philips, %d Hz, 32-bit slots, stereo, "
                  "bclk GPIO%d / ws GPIO%d / din GPIO%d",
             SAMPLE_RATE, PIN_I2S_SCK, PIN_I2S_WS, PIN_I2S_SD);

    err = i2s_channel_enable(s_rx);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s: [3/3] enable FAILED: %s", esp_err_to_name(err));
        return err;
    }
    ESP_LOGI(TAG, "i2s: [3/3] channel enabled, clocks are running");
    return ESP_OK;
}

/* Reading the registers back only proves the peripheral accepted the config.
 * This times real traffic instead: if the bit clock is wrong the measured rate
 * drifts, and if SD is dead the samples are all zero. Returns the measured
 * sample rate, or -1 if nothing came off the bus at all.
 *
 * Two things this has to get right or it lies about working hardware:
 *
 *  - Read a whole DMA descriptor at a time. i2s_channel_read() leaves the tail
 *    of a partly consumed descriptor for the next call, so odd-sized reads make
 *    the completion times quantise to 25 ms steps - enough to turn an exact
 *    16 kHz into a "6% off" warning.
 *  - Let the mics settle first. The INMP441 needs the clock running for a while
 *    before its DC blocker converges, and that opening transient is far bigger
 *    than the audio sitting on top of it.
 */
#define PROBE_SETTLE_MS   500
#define PROBE_WINDOW_MS   1000
#define PROBE_READ_FRAMES DMA_FRAME_NUM
#define PROBE_READ_MS     (PROBE_READ_FRAMES * 1000 / SAMPLE_RATE)

static int i2s_probe(void)
{
    const size_t bytes = PROBE_READ_FRAMES * 2 * sizeof(int32_t);
    int32_t *buf = malloc(bytes);
    if (!buf) {
        ESP_LOGE(TAG, "i2s: probe buffer alloc failed (%u bytes)", (unsigned)bytes);
        return -1;
    }

    size_t got = 0;
    esp_err_t err = ESP_OK;

    ESP_LOGI(TAG, "i2s: probing - %d ms to let the mics settle, then %d ms of "
                  "timed reads", PROBE_SETTLE_MS, PROBE_WINDOW_MS);

    for (int i = 0; i < PROBE_SETTLE_MS / PROBE_READ_MS; i++) {
        err = i2s_channel_read(s_rx, buf, bytes, &got, pdMS_TO_TICKS(300));
        if (err != ESP_OK || got == 0) {
            ESP_LOGE(TAG, "i2s: PROBE FAILED - no data after %d reads (%s). The "
                          "peripheral is up but nothing is moving: check SCK "
                          "GPIO%d and WS GPIO%d, and that both mics have 3V3.",
                     i + 1, esp_err_to_name(err), PIN_I2S_SCK, PIN_I2S_WS);
            free(buf);
            return -1;
        }
    }

    /* Track the extremes and the mean separately: the mean is the DC the mic
     * is sitting on, the spread around it is the audio. */
    int32_t min_l = INT32_MAX, max_l = INT32_MIN;
    int32_t min_r = INT32_MAX, max_r = INT32_MIN;
    int64_t sum_l = 0, sum_r = 0;
    size_t  zeros_l = 0, zeros_r = 0, frames = 0;

    int64_t t0 = esp_timer_get_time();
    for (int i = 0; i < PROBE_WINDOW_MS / PROBE_READ_MS; i++) {
        err = i2s_channel_read(s_rx, buf, bytes, &got, pdMS_TO_TICKS(300));
        if (err != ESP_OK || got == 0) {
            ESP_LOGE(TAG, "i2s: PROBE FAILED - the bus stalled mid-probe (%s)",
                     esp_err_to_name(err));
            free(buf);
            return -1;
        }
        size_t n = got / (2 * sizeof(int32_t));
        for (size_t j = 0; j < n; j++) {
            /* The 24-bit sample sits in bits 31..8. */
            int32_t l = buf[2 * j]     >> 8;
            int32_t r = buf[2 * j + 1] >> 8;
            if (l == 0) zeros_l++;
            if (r == 0) zeros_r++;
            if (l < min_l) min_l = l;
            if (l > max_l) max_l = l;
            if (r < min_r) min_r = r;
            if (r > max_r) max_r = r;
            sum_l += l;
            sum_r += r;
        }
        frames += n;
    }
    int64_t us = esp_timer_get_time() - t0;
    free(buf);

    int measured = (int)(frames * 1000000LL / (us ? us : 1));
    const int full = 8388607;       /* 24-bit full scale */

    int dc_l = (int)(sum_l / (int64_t)frames);
    int dc_r = (int)(sum_r / (int64_t)frames);
    int ac_l = (max_l - dc_l > dc_l - min_l) ? max_l - dc_l : dc_l - min_l;
    int ac_r = (max_r - dc_r > dc_r - min_r) ? max_r - dc_r : dc_r - min_r;

    ESP_LOGI(TAG, "i2s: read %u frames in %d ms -> %d Hz on the wire "
                  "(configured %d Hz)",
             (unsigned)frames, (int)(us / 1000), measured, SAMPLE_RATE);
    ESP_LOGI(TAG, "i2s: left  (mic A): audio +-%d (%d%% FS), DC %+d (%d%% FS), "
                  "%u%% of samples zero",
             ac_l, ac_l * 100 / full, dc_l, dc_l * 100 / full,
             (unsigned)(zeros_l * 100 / frames));
    ESP_LOGI(TAG, "i2s: right (mic B): audio +-%d (%d%% FS), DC %+d (%d%% FS), "
                  "%u%% of samples zero",
             ac_r, ac_r * 100 / full, dc_r, dc_r * 100 / full,
             (unsigned)(zeros_r * 100 / frames));

    int drift = (measured - SAMPLE_RATE) * 100 / SAMPLE_RATE;
    if (drift > 2 || drift < -2) {
        ESP_LOGW(TAG, "i2s: measured rate is %d%% off - the master clock is not "
                      "what we asked for", drift);
    }

    /* GAIN_SHIFT throws away the bottom 16 bits, so DC that survives here eats
     * headroom in the 16-bit stream for no benefit. */
    if (dc_l > full / 20 || dc_l < -full / 20 || dc_r > full / 20 || dc_r < -full / 20) {
        ESP_LOGW(TAG, "i2s: DC offset above 5%% FS - it costs headroom in the "
                      "16-bit stream, high-pass it before this becomes training data");
    }

    if (ac_l == 0 && ac_r == 0) {
        ESP_LOGE(TAG, "i2s: PROBE WARNING - the bus is clocking but neither slot "
                      "moves. SD GPIO%d is not reaching the ESP, or neither mic "
                      "is powered.", PIN_I2S_SD);
    } else if (ac_l == 0) {
        ESP_LOGW(TAG, "i2s: left slot is flat - mic A missing, or its L/R pin "
                      "is not strapped to GND");
    } else if (ac_r == 0) {
        ESP_LOGW(TAG, "i2s: right slot is flat - mic B missing, or its L/R pin "
                      "is not strapped to 3V3");
    } else {
        ESP_LOGI(TAG, "i2s: PROBE OK - both slots carrying audio");
    }
    return measured;
}

/* Wi-Fi bring-up parks the capture task for a couple of hundred ms, and the
 * DMA keeps filling the whole time. Without this the loop opens by racing
 * through stale audio several times faster than real time, which lands a
 * discontinuity in the pre-roll and shortens any sample-counted timing. */
static void drain_dma(void)
{
    size_t got = 0, frames = 0;
    while (i2s_channel_read(s_rx, s_raw, sizeof s_raw, &got, 0) == ESP_OK && got) {
        frames += got / (2 * sizeof(int32_t));
    }
    ESP_LOGI(TAG, "i2s: dropped %u stale frames (%u ms) buffered during bring-up",
             (unsigned)frames, (unsigned)(frames * 1000 / SAMPLE_RATE));
}

/* I2S never came up: there is nothing to serve, so say so on the console and
 * on the red LED rather than pretending to be a capture node. */
static void __attribute__((noreturn)) fault_blink(void)
{
    ESP_LOGE(TAG, "capture is dead - web server NOT started. Fix the I2S fault "
                  "above and reset.");
    for (int i = 0; ; i++) {
        led(PIN_LED_RED, i & 1);
        vTaskDelay(pdMS_TO_TICKS(120));
        if (i % 40 == 0) ESP_LOGE(TAG, "still faulted, see the i2s error above");
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "=== MicRelay bring-up ===");

    ESP_LOGI(TAG, "[1/5] gpio");
    if (gpio_bring_up() != ESP_OK) fault_blink();

    ESP_LOGI(TAG, "[2/5] usb");
    if (usb_bring_up() != ESP_OK) fault_blink();

    ESP_LOGI(TAG, "[3/5] buffers");
    s_preroll = heap_caps_malloc(PREROLL_FRAMES * sizeof(frame_t), MALLOC_CAP_SPIRAM);
    if (!s_preroll) {
        ESP_LOGW(TAG, "buffers: no PSRAM, pre-roll falling back to internal RAM");
        s_preroll = heap_caps_malloc(PREROLL_FRAMES * sizeof(frame_t), MALLOC_CAP_8BIT);
    }
    if (!s_preroll) {
        ESP_LOGE(TAG, "buffers: pre-roll alloc FAILED (%u bytes)",
                 (unsigned)(PREROLL_FRAMES * sizeof(frame_t)));
        fault_blink();
    }
    ESP_LOGI(TAG, "buffers: pre-roll %d frames (%u KB) at %p",
             PREROLL_FRAMES, (unsigned)(PREROLL_FRAMES * sizeof(frame_t) / 1024),
             s_preroll);
    esp_err_t clip_err = clip_init();       /* the web player is optional... */

    ESP_LOGI(TAG, "[4/5] i2s");
    if (i2s_bring_up() != ESP_OK) fault_blink();
    int measured = i2s_probe();
    if (measured < 0) fault_blink();

    /* Red on means clocks are running and both mics are awake. It is not a
     * power LED - it deliberately comes on after I2S, so if it stays dark the
     * fault is upstream of the microphones. */
    led(PIN_LED_RED, true);

    ESP_LOGI(TAG, "[5/5] web");
    if (clip_err != ESP_OK) {
        ESP_LOGE(TAG, "web: skipped, the clip recorder has no memory");
    } else if (web_start(measured) != ESP_OK) {
        ESP_LOGE(TAG, "web: server did not start - USB streaming still works");
    }

    drain_dma();
    ESP_LOGI(TAG, "=== capture up: %d Hz stereo, %d ms pre-roll, %d ms hangover ===",
             SAMPLE_RATE, PREROLL_MS, HANGOVER_MS);

    bool sending  = false;
    bool ptt_clip = false;
    int  hangover = 0;
    uint32_t last_clip = clip_id();

    for (;;) {
        size_t got = 0;
        ESP_ERROR_CHECK(i2s_channel_read(s_rx, s_raw, sizeof s_raw, &got, portMAX_DELAY));
        size_t n = got / (2 * sizeof(int32_t));

        for (size_t i = 0; i < n; i++) {
            s_chunk[i].primary   = sat16(s_raw[2 * i]     >> GAIN_SHIFT);  /* left  = mic A */
            s_chunk[i].reference = sat16(s_raw[2 * i + 1] >> GAIN_SHIFT);  /* right = mic B */
        }

        bool held = ptt_held();

        if (held && !sending) {
            sending = true;
            led(PIN_LED_GREEN, true);
            ESP_LOGI(TAG, "ptt down (GPIO%d reads %d), flushing %u pre-roll frames",
                     PIN_PTT, gpio_get_level(PIN_PTT), (unsigned)s_fill);
            send_preroll();
            /* Hold the button to capture a clip for the web player too. */
            if (!clip_recording() && clip_begin(CLIP_MAX_MS)) ptt_clip = true;
        }

        if (sending) {
            send_frames(s_chunk, n, 0);
            if (held) {
                hangover = HANGOVER_CHUNKS;
            } else if (--hangover <= 0) {
                sending = false;
                led(PIN_LED_GREEN, false);
                ESP_LOGI(TAG, "ptt up, stream closed at seq %u", (unsigned)s_seq);
            }
        }

        /* A browser can ask for a clip at any time; the capture task is the
         * only writer, so the request is picked up here. */
        uint32_t req_ms = web_take_record_request();
        if (req_ms && !clip_recording()) clip_begin(req_ms);

        if (clip_recording()) clip_write(s_chunk, n);
        if (ptt_clip && !held) { clip_end(); ptt_clip = false; }

        /* Whatever finished the clip - PTT release, the 10 s cap, or a request
         * from the page - the page hears about it here, once. */
        uint32_t id = clip_id();
        if (id != last_clip) {
            last_clip = id;
            web_notify_clip();
        }

        /* Always, transmitting or not. This keeps the pre-roll full and the
         * downstream noise estimate warm. */
        ring_write(s_chunk, n);
    }
}
