#include "lf_reader_generic.h"
#include "lf_reader_data.h"

#include "bsp_delay.h"
#include "bsp_wdt.h"
#include "bsp_time.h"
#include "lf_125khz_radio.h"
#include "lf_reader_data.h"
#include "protocols/protocols.h"

#define NRF_LOG_MODULE_NAME lfgeneric
#include "nrf_log.h"
#include "nrf_log_ctrl.h"
#include "nrf_log_default_backends.h"
NRF_LOG_MODULE_REGISTER();

/*
 * Samples are copied straight from the SAADC callback into the caller's buffer.
 * The SAADC delivers 2048-sample DMA blocks; routing them through a small
 * circular buffer dropped everything past its capacity (~75% of each block),
 * which made captures discontinuous in time.
 */
static uint8_t *m_cap_buf;
static size_t m_cap_max;
static volatile size_t m_cap_len;
static uint8_t m_cap_decimation;
static uint32_t m_cap_acc;
static uint8_t m_cap_acc_count;

/* 14-bit ADC value -> 8-bit, clamped (kept identical to the historical conversion). */
static inline uint8_t sample_to_u8(nrf_saadc_value_t v) {
    uint16_t u = ((uint16_t)v) >> 5;
    return u > 0xff ? 0xff : (uint8_t)u;
}

static void capture_cb(nrf_saadc_value_t *vals, size_t size) {
    for (size_t i = 0; i < size && m_cap_len < m_cap_max; i++) {
        m_cap_acc += sample_to_u8(vals[i]);
        if (++m_cap_acc_count == m_cap_decimation) {
            m_cap_buf[m_cap_len++] = (uint8_t)(m_cap_acc / m_cap_decimation);
            m_cap_acc = 0;
            m_cap_acc_count = 0;
        }
    }
}

size_t raw_capture_field_on(uint8_t *data, size_t maxlen, uint8_t decimation, uint32_t timeout_ms) {
    m_cap_buf = data;
    m_cap_max = maxlen;
    m_cap_len = 0;
    m_cap_decimation = decimation == 0 ? 1 : decimation;
    m_cap_acc = 0;
    m_cap_acc_count = 0;

    lf_125khz_radio_saadc_enable(capture_cb);

    autotimer *p_at = bsp_obtain_timer(0);
    while (NO_TIMEOUT_1MS(p_at, timeout_ms) && m_cap_len < m_cap_max) {
        bsp_wdt_feed();  /* prevent watchdog reset during long captures */
    }
    bsp_return_timer(p_at);

    lf_125khz_radio_saadc_disable();
    return m_cap_len;
}

bool raw_read_to_buffer(uint8_t *data, size_t maxlen, uint32_t timeout_ms, size_t *outlen) {
    start_lf_125khz_radio();

    /* Wait for antenna to settle before capturing.
     * The LC circuit rings for ~400µs on field startup, then takes
     * another ~800µs to reach steady state. Skip 2ms to be safe. */
    bsp_delay_ms(2);

    *outlen = raw_capture_field_on(data, maxlen, 1, timeout_ms);

    stop_lf_125khz_radio();
    return true;
}
