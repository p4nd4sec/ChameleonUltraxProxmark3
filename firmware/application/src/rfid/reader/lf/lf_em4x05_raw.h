#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * EM4x05/EM4x69 (EM4305, EM4205, EM4469, EM4569) read with host-side demodulation.
 *
 * Downlink framing and timing follow Proxmark3 armsrc/lfops.c
 * (Prepare_Cmd / Prepare_Addr / Prepare_Data / SendForward).  READ, LOGIN and
 * WRITE are implemented; PROTECT and DISABLE (irreversible) are not, and WRITE
 * refuses the protection words 14/15.
 *
 * Timings are in carrier cycles (Tc = 8us); 0 selects the Proxmark3 default.
 */
typedef struct {
    uint8_t start_gap_tc;  /* first pulse: field off           (default 55) */
    uint8_t zero_gap_tc;   /* '0' bit: field off               (default 23) */
    uint8_t field_on_tc;   /* field on after every gap         (default 18) */
    uint8_t one_tc;        /* '1' bit: field stays on          (default 32) */
} em4x05_timing_t;

/* Highest word WRITE accepts; 14 and 15 are the protection words. */
#define EM4X05_MAX_WRITABLE_ADDR 13

/**
 * Optionally LOGIN, then send READ for one word and capture the tag's answer as raw ADC samples.
 *
 * @return STATUS_LF_TAG_OK when samples were captured, STATUS_LF_TAG_NO_FOUND otherwise
 */
uint8_t em4x05_read_word_raw(uint8_t addr, bool use_pwd, uint32_t pwd, const em4x05_timing_t *timing,
                             uint8_t decimation, uint8_t *out, size_t maxlen, size_t *outlen);

/**
 * Optionally LOGIN, then WRITE one word and capture the tag's answer (ACK / error) as raw ADC samples.
 * The caller must verify the result by reading the word back.
 *
 * @return STATUS_PAR_ERR for addr > EM4X05_MAX_WRITABLE_ADDR, else as em4x05_read_word_raw()
 */
uint8_t em4x05_write_word_raw(uint8_t addr, uint32_t data, bool use_pwd, uint32_t pwd, const em4x05_timing_t *timing,
                              uint8_t decimation, uint8_t *out, size_t maxlen, size_t *outlen);

#ifdef __cplusplus
}
#endif
