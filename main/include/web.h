/*
 * Wi-Fi + HTTP player. Started only after the I2S probe passes, so if the page
 * is reachable at all, the microphones were confirmed running at boot.
 */
#pragma once

#include <stdint.h>
#include "esp_err.h"

/* measured_hz is what the I2S probe timed on the bus - it lands on the status
 * line of the page so the bring-up result is visible without a serial cable. */
esp_err_t web_start(int measured_hz);

/* Tells every open page that a new clip is ready. Safe to call from the
 * capture task: the socket writes are queued onto the HTTP task. */
void web_notify_clip(void);

/* Non-zero once, when a browser has asked for a recording. Polled by the
 * capture task, which owns every write to the clip buffer. */
uint32_t web_take_record_request(void);
