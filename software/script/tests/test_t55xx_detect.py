#!/usr/bin/env python3

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import lf_demod  # noqa: E402
from tests import lf_signal_synth as synth  # noqa: E402
import t55xx  # noqa: E402

# Block 0 values from firmware/application/src/rfid/nfctag/lf/protocols/t55xx.h
EM410X_CFG = 0x00148050      # RF/64 Manchester, PWD, maxblock 2
VIKING_CFG = 0x00088050      # RF/32 Manchester, PWD, maxblock 2
HIDPROX_CFG = 0x00107070     # RF/50 FSK2a, PWD, maxblock 3
IOPROX_CFG = 0x00147050      # RF/64 FSK2a, PWD, maxblock 2
PAC_CFG = 0x00080090         # RF/32 direct, PWD, maxblock 4
JABLOTRON_CFG = 0x00158050   # RF/64 diphase, PWD, maxblock 2
DEFAULT_CFG = 0x000880E8     # T5577 factory default: RF/32 Manchester, maxblock 7, ST


class TestConfigDecode(unittest.TestCase):
    def test_decode_em410x(self):
        cfg = t55xx.decode_config(EM410X_CFG)
        self.assertEqual(cfg.bit_rate, 64)
        self.assertEqual(cfg.modulation, t55xx.MOD_MANCHESTER)
        self.assertTrue(cfg.password_enabled)
        self.assertEqual(cfg.max_block, 2)
        self.assertFalse(cfg.seq_terminator)

    def test_decode_default(self):
        cfg = t55xx.decode_config(DEFAULT_CFG)
        self.assertEqual(cfg.bit_rate, 32)
        self.assertEqual(cfg.max_block, 7)
        self.assertTrue(cfg.seq_terminator)
        self.assertFalse(cfg.password_enabled)

    def test_plausible(self):
        for word in (EM410X_CFG, VIKING_CFG, HIDPROX_CFG, IOPROX_CFG, PAC_CFG, JABLOTRON_CFG, DEFAULT_CFG):
            self.assertTrue(t55xx.is_plausible_config(word), hex(word))
        for word in (0x00000000, 0xFFFFFFFF, 0x5A3C9E17, 0x0FE00000 | EM410X_CFG):
            self.assertFalse(t55xx.is_plausible_config(word), hex(word))


class TestDetect(unittest.TestCase):
    def test_hardware_spikes_decimated_capture(self):
        # Mimic the real front-end (edge spikes) and the device's 4000-sample, decimated capture.
        full = synth.edge_spikes(synth.ask_manchester(synth.repeat_word(EM410X_CFG, 5), 64), width=30)
        captures = {d: lf_demod.decimate(full, d)[:4000] for d in t55xx.DECIMATIONS}
        res = t55xx.detect_from_captures(captures)
        assert res is not None
        self.assertEqual(res.block0, EM410X_CFG)
        self.assertGreaterEqual(res.repeats, 1)

    def detect(self, samples):
        return t55xx.detect_from_samples(synth.with_lead_in(synth.add_noise(samples)))

    def test_manchester_em410x(self):
        res = self.detect(synth.ask_manchester(synth.repeat_word(EM410X_CFG, 3), 64))
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res.block0, EM410X_CFG)
        self.assertEqual(res.config.modulation, t55xx.MOD_MANCHESTER)

    def test_manchester_inverted_polarity(self):
        bits = [1 - b for b in synth.repeat_word(VIKING_CFG, 4)]
        res = self.detect(synth.ask_manchester(bits, 32))
        assert res is not None
        self.assertEqual(res.block0, VIKING_CFG)

    def test_factory_default(self):
        res = self.detect(synth.ask_manchester(synth.repeat_word(DEFAULT_CFG, 4), 32))
        assert res is not None
        self.assertEqual(res.block0, DEFAULT_CFG)

    def test_fsk2a_hid(self):
        # FSK2a: '1' = fc/8, '0' = fc/10
        res = self.detect(synth.fsk(synth.repeat_word(HIDPROX_CFG, 3), 50, period_zero=10, period_one=8))
        assert res is not None
        self.assertEqual(res.block0, HIDPROX_CFG)
        self.assertEqual(res.config.modulation, t55xx.MOD_FSK2A)

    def test_fsk2a_ioprox(self):
        res = self.detect(synth.fsk(synth.repeat_word(IOPROX_CFG, 3), 64, period_zero=10, period_one=8))
        assert res is not None
        self.assertEqual(res.block0, IOPROX_CFG)

    def test_direct_pac(self):
        res = self.detect(synth.ask_direct(synth.repeat_word(PAC_CFG, 4), 32))
        assert res is not None
        self.assertEqual(res.block0, PAC_CFG)

    def test_diphase_jablotron(self):
        res = self.detect(synth.ask_biphase(synth.repeat_word(JABLOTRON_CFG, 3), 64))
        assert res is not None
        self.assertEqual(res.block0, JABLOTRON_CFG)

    def test_em410x_frame_is_not_a_config(self):
        # A read-only EM4100 ignores the read command and keeps sending its 64-bit frame.
        frame = 0xFF8C0000_00000000 | 0x1F3A5C7E9B
        bits = [(frame >> (63 - i)) & 1 for i in range(64)] * 2
        self.assertIsNone(self.detect(synth.ask_manchester(bits, 64)))

    def test_no_tag(self):
        self.assertIsNone(t55xx.detect_from_samples([170] * 4000))


if __name__ == "__main__":
    unittest.main()
