#!/usr/bin/env python3

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import em4x05  # noqa: E402
from tests import lf_signal_synth as synth  # noqa: E402

PREAMBLE = [0, 0, 0, 0, 1, 0, 1, 0]
ERR_PREAMBLE = [0, 0, 0, 0, 0, 0, 0, 1]


def response_bits(word: int):
    """Reference encoder: preamble + 4 x (byte LSB first + even parity) + 8 column parity + stop."""
    bits = list(PREAMBLE)
    col = 0
    for i in range(4):
        byte = (word >> (8 * i)) & 0xFF
        row = [(byte >> j) & 1 for j in range(8)]
        bits += row + [sum(row) % 2]
        col ^= byte
    bits += [(col >> j) & 1 for j in range(8)] + [0]
    return bits


def tag_answer(bits, clk=64, modulate=synth.ask_manchester, spikes=True):
    # Tag idles in its default (EM4100-like) stream before and after the answer; model as alternating bits.
    idle = [1, 0] * 8
    samples = modulate(idle + bits + idle, clk)
    if spikes:
        samples = synth.edge_spikes(samples, width=clk // 2 - 2)
    return synth.with_lead_in(synth.add_noise(samples))


class TestResponseDecode(unittest.TestCase):
    def test_parse_bits(self):
        word = 0x0002C05F
        res = em4x05.parse_response_bits(response_bits(word))
        assert res is not None
        self.assertEqual(res.word, word)
        self.assertFalse(res.error)

    def test_parse_rejects_bad_parity(self):
        bits = response_bits(0x12345678)
        bits[10] ^= 1
        self.assertIsNone(em4x05.parse_response_bits(bits))

    def test_error_preamble(self):
        res = em4x05.parse_response_bits([0, -1] + ERR_PREAMBLE + [1, 0, 1])
        assert res is not None
        self.assertTrue(res.error)

    def test_decode_samples_manchester(self):
        for word in (0x0002C05F, 0x5A3C9E17, 0xFFFFFFFF, 0x00000001):
            res = em4x05.decode_word_samples(tag_answer(response_bits(word)))
            assert res is not None, hex(word)
            self.assertEqual(res.word, word)

    def test_decode_samples_biphase_rf32(self):
        res = em4x05.decode_word_samples(tag_answer(response_bits(0xDEADBEEF), 32, synth.ask_biphase))
        assert res is not None
        self.assertEqual(res.word, 0xDEADBEEF)

    def test_truncated_preamble(self):
        # Real captures start a few bits late: only the "1010" tail of the preamble survives.
        bits = response_bits(0x0001805F)[4:]
        res = em4x05.parse_response_bits(bits)
        assert res is not None
        self.assertEqual(res.word, 0x0001805F)

    def test_truncated_preamble_in_samples(self):
        samples = synth.ask_manchester(response_bits(0x2C6A1D93)[5:] + [1, 0] * 8, 64)
        res = em4x05.decode_word_samples(synth.edge_spikes(samples, width=30))
        assert res is not None
        self.assertEqual(res.word, 0x2C6A1D93)

    def test_em410x_stream_is_not_an_error(self):
        # An EM410x ID with zero nibbles contains 00000001; it must not be reported as a refusal.
        bits = [1] * 9 + [0, 0, 0, 0, 0] * 3 + [0, 1, 0, 0, 1] + [0, 0, 1, 1, 0] * 6 + [0, 1, 1, 0, 0]
        self.assertIsNone(em4x05.parse_response_bits(bits * 2))

    def test_no_answer(self):
        self.assertIsNone(em4x05.decode_word_samples([170] * 4000))


class TestConfig(unittest.TestCase):
    def test_decode_config(self):
        # RF/64 (0x1F), Manchester (1), LWR 0, no login, RTF clear
        cfg = em4x05.decode_config(0x0000005F)
        self.assertEqual(cfg.data_rate, 64)
        self.assertEqual(cfg.encoder_name, "Manchester")
        self.assertFalse(cfg.read_login)
        self.assertFalse(cfg.write_login)

    def test_login_bits(self):
        cfg = em4x05.decode_config((1 << 18) | (1 << 20) | (5 << 14) | 0x9F)
        self.assertTrue(cfg.read_login)
        self.assertTrue(cfg.write_login)
        self.assertEqual(cfg.last_word_read, 5)
        self.assertEqual(cfg.encoder_name, "Biphase")


class TestWritePlanning(unittest.TestCase):
    def test_em410x_frame_layout(self):
        frame = em4x05.em410x_frame("0F0368568B")
        bits = [(frame >> (63 - i)) & 1 for i in range(64)]
        self.assertEqual(bits[:9], [1] * 9)
        self.assertEqual(bits[63], 0)
        rows = [bits[9 + 5 * r:14 + 5 * r] for r in range(10)]
        self.assertTrue(all(sum(r) % 2 == 0 for r in rows))
        self.assertEqual("".join("%X" % int("".join(map(str, r[:4])), 2) for r in rows), "0F0368568B")

    def test_clone_words_round_trip(self):
        words = em4x05.em410x_clone_words("0F0368568B")
        self.assertEqual(list(words), [6, 5, 4])  # data first, config last (Proxmark3 order)
        self.assertEqual(words[4], em4x05.CONFIG_EM_UNIQUE)
        # The tag sends word 5 then word 6, each LSB first: that must be the EM410x frame.
        sent = [(words[5] >> i) & 1 for i in range(32)] + [(words[6] >> i) & 1 for i in range(32)]
        frame = em4x05.em410x_frame("0F0368568B")
        self.assertEqual(sent, [(frame >> (63 - i)) & 1 for i in range(64)])

    def test_clone_rejects_bad_id(self):
        for bad in ("123", "0F0368568G", "0F0368568B00"):
            with self.assertRaises(ValueError):
                em4x05.em410x_clone_words(bad)

    def test_write_guard(self):
        for addr in (0, 1, 14, 15, 16, -1):
            self.assertIsNotNone(em4x05.write_refusal(addr, 0))
        self.assertIsNone(em4x05.write_refusal(5, 0x12345678))
        self.assertIsNone(em4x05.write_refusal(4, em4x05.CONFIG_EM_UNIQUE))
        self.assertIsNotNone(em4x05.write_refusal(4, em4x05.CONFIG_EM_UNIQUE | (1 << 18)))  # read login
        self.assertIsNotNone(em4x05.write_refusal(4, em4x05.CONFIG_EM_UNIQUE | (1 << 20)))  # write login

    def test_wipe_plan(self):
        plan = em4x05.wipe_plan()
        self.assertEqual(plan[-1], (4, em4x05.CONFIG_EM_UNIQUE))  # config last
        addrs = [a for a, _ in plan]
        self.assertEqual(sorted(addrs), [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13])
        self.assertTrue(all(em4x05.write_refusal(a, v) is None for a, v in plan))


class TestChipInfo(unittest.TestCase):
    def test_known_types(self):
        # chip type is bits 1-4 of word 0 (Proxmark3 em_get_card_type)
        self.assertEqual(em4x05.decode_chip_info(0x00040072).name, "EM4305")
        self.assertEqual(em4x05.decode_chip_info(8 << 1).name, "EM4205")
        self.assertEqual(em4x05.decode_chip_info(4 << 1).name, "EM4469")
        self.assertEqual(em4x05.decode_chip_info(12 << 1).name, "EM4369")

    def test_unknown_type_and_fields(self):
        info = em4x05.decode_chip_info(0x00040074)
        self.assertEqual(info.chip_type, 10)
        self.assertIn("unknown", info.name)
        self.assertEqual(info.capacitor, "330pF")
        self.assertTrue(info.default_customer_code)


class TestEm410xFromWords(unittest.TestCase):
    def test_round_trip(self):
        for id_hex in ("0F0368568B", "1A2B3C4D5E", "0000000000", "FFFFFFFFFF"):
            words = em4x05.em410x_clone_words(id_hex)
            self.assertEqual(em4x05.em410x_id_from_words(words[5], words[6]), id_hex)

    def test_not_em410x(self):
        self.assertIsNone(em4x05.em410x_id_from_words(0, 0))
        self.assertIsNone(em4x05.em410x_id_from_words(0x12345678, 0x9ABCDEF0))


if __name__ == "__main__":
    unittest.main()
