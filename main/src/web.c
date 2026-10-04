#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_mac.h"
#include "esp_log.h"
#include "esp_http_server.h"
#include "nvs_flash.h"
#include "clip.h"
#include "web.h"

static const char *TAG = "web";

/* ------------------------------------------------------------------ config */
/* 1 = the node makes its own network: join "MicRelay" and open 192.168.4.1.
 * 0 = the node joins the network below and logs the IP it was handed. */
#define WEB_SOFT_AP     1

#define WEB_AP_SSID     "MicRelay"
#define WEB_AP_PASS     "micrelay123"       /* >= 8 chars, or "" for an open AP */
#define WEB_AP_CHANNEL  1

#define WEB_STA_SSID    "your-ssid"
#define WEB_STA_PASS    "your-password"

#define WEB_DEFAULT_MS  5000                /* what the Record button asks for */

static httpd_handle_t s_httpd;
static volatile uint32_t s_req_ms;
static int s_measured_hz;

uint32_t web_take_record_request(void)
{
    uint32_t ms = s_req_ms;
    if (ms) s_req_ms = 0;
    return ms;
}

/* -------------------------------------------------------------------- page */
static const char PAGE[] =
"<!doctype html><html><head><meta charset='utf-8'>\n"
"<meta name='viewport' content='width=device-width,initial-scale=1'>\n"
"<title>MicRelay</title><style>\n"
"body{background:#14161a;color:#e6e6e6;font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px}\n"
"main{max-width:640px;margin:0 auto}\n"
"h1{font-size:20px;margin:0 0 4px}\n"
"p.sub{color:#8b93a0;margin:0 0 20px;font-size:13px}\n"
"button{background:#3d7dff;color:#fff;border:0;border-radius:8px;padding:11px 18px;font-size:15px;cursor:pointer}\n"
"button:disabled{background:#2a3140;color:#6b7280;cursor:default}\n"
"#s{margin:14px 0 22px;font-size:13px;color:#8b93a0;min-height:20px}\n"
"section{background:#1c1f26;border:1px solid #2a2f39;border-radius:10px;padding:14px 16px;margin:0 0 12px}\n"
"h2{font-size:14px;margin:0 0 2px;font-weight:600}\n"
"em{color:#8b93a0;font-style:normal;font-size:12px}\n"
"audio{width:100%;margin-top:10px}\n"
"</style></head><body><main>\n"
"<h1>MicRelay capture node</h1>\n"
"<p class='sub'>Two INMP441 on one I2S bus, 16 kHz, 16-bit.</p>\n"
"<button id='b' onclick='rec()'>Record 5 s</button>\n"
"<div id='s'>checking...</div>\n"
"<section><h2>Left channel</h2><em>mic A, primary (L/R strapped to GND)</em>\n"
"<audio id='a1' controls preload='none'></audio></section>\n"
"<section><h2>Right channel</h2><em>mic B, reference (L/R strapped to 3V3)</em>\n"
"<audio id='a2' controls preload='none'></audio></section>\n"
"<section><h2>Both combined</h2><em>stereo, mic A left / mic B right</em>\n"
"<audio id='a3' controls preload='none'></audio></section>\n"
"</main><script>\n"
"var F=[['a1','/left.wav'],['a2','/right.wav'],['a3','/both.wav']];\n"
"var last=-1,poll=null;\n"
"function $(i){return document.getElementById(i)}\n"
"function get(u){return fetch(u).then(function(r){return r.json()})}\n"
"function show(j){\n"
" if(j.recording){$('s').textContent='recording...';return}\n"
" if(!j.frames){$('s').textContent='no clip yet - press Record, or hold the PTT button';return}\n"
" $('s').textContent=j.ms+' ms captured at '+j.measured_hz+' Hz - peak L '+j.peak_l_pct+'% / R '+j.peak_r_pct+'% of full scale';\n"
"}\n"
"function load(){var t=Date.now();F.forEach(function(f){$(f[0]).src=f[1]+'?t='+t})}\n"
/* One place decides a clip is new, so the push and the fallback poll cannot
   double-load or disagree about which clip is on the page. */
"function apply(j){show(j);if(j.id!==last){last=j.id;if(j.frames)load()}}\n"
"function check(){return get('/status').then(apply)}\n"
"function startPoll(){if(!poll)poll=setInterval(check,1000)}\n"
"function connect(){\n"
" var ws;\n"
" try{ws=new WebSocket('ws://'+location.host+'/ws')}catch(e){startPoll();return}\n"
" ws.onopen=function(){if(poll){clearInterval(poll);poll=null}};\n"
" ws.onmessage=check;\n"
" ws.onerror=function(){try{ws.close()}catch(e){}};\n"
/* A phone that sleeps drops the socket, so keep polling until it is back. */
" ws.onclose=function(){startPoll();setTimeout(connect,3000)};\n"
"}\n"
"function rec(){\n"
" $('b').disabled=true;$('s').textContent='recording...';\n"
" fetch('/record').then(function(){\n"
"  var p=function(){get('/status').then(function(j){\n"
"   if(j.recording){setTimeout(p,250);return}\n"
"   apply(j);$('b').disabled=false;});};\n"
"  setTimeout(p,400);});\n"
"}\n"
"check();connect();\n"
"</script></body></html>\n";

/* ---------------------------------------------------------------- handlers */
static esp_err_t page_get(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/html");
    return httpd_resp_send(req, PAGE, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t status_get(httpd_req_t *req)
{
    int pl = 0, pr = 0;
    clip_peaks(&pl, &pr);
    size_t frames = clip_frames();

    char json[256];
    int n = snprintf(json, sizeof json,
        "{\"id\":%u,\"recording\":%d,\"frames\":%u,\"ms\":%u,\"rate\":%d,"
        "\"measured_hz\":%d,\"peak_l\":%d,\"peak_r\":%d,"
        "\"peak_l_pct\":%d,\"peak_r_pct\":%d}",
        (unsigned)clip_id(), clip_recording() ? 1 : 0, (unsigned)frames,
        (unsigned)(frames * 1000 / AUDIO_SAMPLE_RATE),
        AUDIO_SAMPLE_RATE, s_measured_hz,
        pl, pr, pl * 100 / 32767, pr * 100 / 32767);

    httpd_resp_set_type(req, "application/json");
    return httpd_resp_send(req, json, n);
}

static esp_err_t record_get(httpd_req_t *req)
{
    uint32_t ms = WEB_DEFAULT_MS;
    char q[48], v[16];
    if (httpd_req_get_url_query_str(req, q, sizeof q) == ESP_OK &&
        httpd_query_key_value(q, "ms", v, sizeof v) == ESP_OK) {
        long want = strtol(v, NULL, 10);
        if (want > 0) ms = (uint32_t)want;
    }
    if (ms > CLIP_MAX_MS) ms = CLIP_MAX_MS;

    if (clip_recording()) {
        httpd_resp_set_status(req, "409 Conflict");
        httpd_resp_set_type(req, "application/json");
        return httpd_resp_sendstr(req, "{\"error\":\"already recording\"}");
    }

    ESP_LOGI(TAG, "record requested: %u ms", (unsigned)ms);
    s_req_ms = ms;      /* the capture task picks this up on its next chunk */

    httpd_resp_set_type(req, "application/json");
    return httpd_resp_sendstr(req, "{\"ok\":1}");
}

/* Routing already matched one of the three .wav paths, but req->uri still
 * carries the "?t=..." the player appends to dodge the browser cache, so this
 * matches on the prefix rather than the whole string. */
static clip_ch_t channel_for(const char *uri)
{
    if (strncmp(uri, "/left.wav",  9) == 0) return CLIP_LEFT;
    if (strncmp(uri, "/right.wav", 10) == 0) return CLIP_RIGHT;
    return CLIP_BOTH;
}

static esp_err_t wav_get(httpd_req_t *req)
{
    clip_ch_t ch = channel_for(req->uri);

    const uint8_t *wav = NULL;
    size_t len = clip_wav_build(ch, &wav);
    if (len == 0) {
        ESP_LOGW(TAG, "%s requested but no clip is ready", req->uri);
        httpd_resp_set_status(req, "409 Conflict");
        return httpd_resp_sendstr(req, "no clip recorded yet");
    }

    ESP_LOGI(TAG, "serving %s (%u KB)", req->uri, (unsigned)(len / 1024));
    httpd_resp_set_type(req, "audio/wav");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, (const char *)wav, len);
}

/* The page keeps this open so a finished clip reaches it the moment PTT goes
 * up, instead of waiting for the next poll. Nothing is expected from the page
 * on this socket - an incoming frame is drained and dropped. */
static esp_err_t ws_handler(httpd_req_t *req)
{
    if (req->method == HTTP_GET) {          /* the handshake, not a frame */
        ESP_LOGI(TAG, "page connected (socket %d)", httpd_req_to_sockfd(req));
        return ESP_OK;
    }
    httpd_ws_frame_t f = { .type = HTTPD_WS_TYPE_TEXT };
    return httpd_ws_recv_frame(req, &f, 0);
}

/* Runs in the HTTP task, queued from the capture task: a socket write must
 * never happen inline with the I2S read loop. */
static void notify_work(void *arg)
{
    size_t fds = CONFIG_LWIP_MAX_SOCKETS;
    int    fd[CONFIG_LWIP_MAX_SOCKETS];

    if (httpd_get_client_list(s_httpd, &fds, fd) != ESP_OK) return;

    char msg[24];
    int  len = snprintf(msg, sizeof msg, "{\"id\":%u}", (unsigned)clip_id());

    for (size_t i = 0; i < fds; i++) {
        if (httpd_ws_get_fd_info(s_httpd, fd[i]) != HTTPD_WS_CLIENT_WEBSOCKET) continue;
        httpd_ws_frame_t f = {
            .type = HTTPD_WS_TYPE_TEXT, .payload = (uint8_t *)msg, .len = len,
        };
        esp_err_t err = httpd_ws_send_frame_async(s_httpd, fd[i], &f);
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "push to socket %d failed (%s), dropping it",
                     fd[i], esp_err_to_name(err));
            httpd_sess_trigger_close(s_httpd, fd[i]);
        }
    }
}

void web_notify_clip(void)
{
    if (!s_httpd) return;
    esp_err_t err = httpd_queue_work(s_httpd, notify_work, NULL);
    if (err != ESP_OK) ESP_LOGW(TAG, "could not queue the clip push: %s",
                                esp_err_to_name(err));
}

static const httpd_uri_t URIS[] = {
    { .uri = "/",          .method = HTTP_GET, .handler = page_get },
    { .uri = "/status",    .method = HTTP_GET, .handler = status_get },
    { .uri = "/record",    .method = HTTP_GET, .handler = record_get },
    { .uri = "/left.wav",  .method = HTTP_GET, .handler = wav_get },
    { .uri = "/right.wav", .method = HTTP_GET, .handler = wav_get },
    { .uri = "/both.wav",  .method = HTTP_GET, .handler = wav_get },
    { .uri = "/ws",        .method = HTTP_GET, .handler = ws_handler,
      .is_websocket = true },
};

/* ------------------------------------------------------------------ wi-fi */
static void on_wifi(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_AP_STACONNECTED) {
        wifi_event_ap_staconnected_t *e = data;
        ESP_LOGI(TAG, "client joined: " MACSTR, MAC2STR(e->mac));
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_AP_STADISCONNECTED) {
        wifi_event_ap_stadisconnected_t *e = data;
        ESP_LOGI(TAG, "client left: " MACSTR, MAC2STR(e->mac));
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_event_sta_disconnected_t *e = data;
        ESP_LOGW(TAG, "disconnected from AP (reason %d), retrying", e->reason);
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *e = data;
        ESP_LOGI(TAG, "joined " WEB_STA_SSID ", open http://" IPSTR "/",
                 IP2STR(&e->ip_info.ip));
    }
}

static esp_err_t wifi_bring_up(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "nvs partition needs erasing, doing it now");
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs init failed: %s", esp_err_to_name(err));
        return err;
    }

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    err = esp_wifi_init(&cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "wifi init failed: %s", esp_err_to_name(err));
        return err;
    }

    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                        on_wifi, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, ESP_EVENT_ANY_ID,
                                                        on_wifi, NULL, NULL));

#if WEB_SOFT_AP
    esp_netif_create_default_wifi_ap();
    wifi_config_t wc = {
        .ap = {
            .ssid = WEB_AP_SSID,
            .ssid_len = sizeof(WEB_AP_SSID) - 1,
            .password = WEB_AP_PASS,
            .channel = WEB_AP_CHANNEL,
            .max_connection = 4,
            .authmode = (sizeof(WEB_AP_PASS) - 1 >= 8) ? WIFI_AUTH_WPA2_PSK
                                                       : WIFI_AUTH_OPEN,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_LOGI(TAG, "access point up: ssid '%s' pass '%s' channel %d",
             WEB_AP_SSID, WEB_AP_PASS, WEB_AP_CHANNEL);
    ESP_LOGI(TAG, "join that network, then open http://192.168.4.1/");
#else
    esp_netif_create_default_wifi_sta();
    wifi_config_t wc = {
        .sta = { .ssid = WEB_STA_SSID, .password = WEB_STA_PASS },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_LOGI(TAG, "joining '%s' - the URL is logged once we have an IP", WEB_STA_SSID);
#endif
    return ESP_OK;
}

esp_err_t web_start(int measured_hz)
{
    s_measured_hz = measured_hz;

    esp_err_t err = wifi_bring_up();
    if (err != ESP_OK) return err;

    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.stack_size       = 6144;
    cfg.max_uri_handlers = 8;
    cfg.lru_purge_enable = true;

    err = httpd_start(&s_httpd, &cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "httpd start failed: %s", esp_err_to_name(err));
        return err;
    }

    for (size_t i = 0; i < sizeof URIS / sizeof URIS[0]; i++) {
        ESP_ERROR_CHECK(httpd_register_uri_handler(s_httpd, &URIS[i]));
    }
    ESP_LOGI(TAG, "http server on port %d: / /status /record /left.wav /right.wav /both.wav",
             cfg.server_port);
    return ESP_OK;
}
