#!/usr/bin/env python3

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import lf_demod  # noqa: E402
from tests import lf_signal_synth as synth  # noqa: E402

WORD = 0x00148040  # EM410x-on-T5577 block 0
WORD_BITS = synth.repeat_word(WORD, 1)
WORD_BITS_INV = [1 - b for b in WORD_BITS]


def contains(haystack, needle):
    n = len(needle)
    return any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


def any_contains(candidates, needle):
    return any(contains(c, needle) for c in candidates)


class TestBinarize(unittest.TestCase):
    def test_threshold_between_rails(self):
        levels = lf_demod.binarize([0, 255, 0, 255, 10, 240])
        self.assertEqual(levels, [0, 1, 0, 1, 0, 1])

    def test_flat_signal_returns_empty(self):
        self.assertEqual(lf_demod.binarize([170] * 500), [])

    def test_runs_merge_glitches(self):
        levels = [1] * 30 + [0] + [1] * 30 + [0] * 32
        runs = lf_demod.runs_of(levels, min_run=4)
        self.assertEqual(runs, [(1, 61), (0, 32)])

    def test_majority_filter_removes_spike_keeps_edge(self):
        levels = [1] * 10 + [0] + [1] * 10 + [0] * 10
        self.assertEqual(lf_demod.majority_filter(levels, 2), [1] * 21 + [0] * 10)

    def test_decimate(self):
        self.assertEqual(lf_demod.decimate([0, 2, 4, 6, 8], 2), [1, 5])


class TestIntervals(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(lf_demod.classify_interval(64, 64), lf_demod.T1)
        self.assertEqual(lf_demod.classify_interval(98, 64), lf_demod.T15)
        self.assertEqual(lf_demod.classify_interval(126, 64), lf_demod.T2)
        self.assertEqual(lf_demod.classify_interval(40, 64), lf_demod.T_INVALID)


class TestAskDemod(unittest.TestCase):
    def check(self, decode, modulate, clk, spikes=False):
        samples = modulate(synth.repeat_word(WORD, 3), clk)
        if spikes:
            samples = synth.edge_spikes(samples, width=clk // 2 - 2)
        samples = synth.with_lead_in(synth.add_noise(samples))
        candidates = decode(samples, clk)
        self.assertTrue(
            any_contains(candidates, WORD_BITS) or any_contains(candidates, WORD_BITS_INV),
            f"word not found at clk {clk} (spikes={spikes})",
        )

    def test_manchester_levels(self):
        for clk in (16, 32, 40, 50, 64, 100, 128):
            self.check(lf_demod.ask_manchester, synth.ask_manchester, clk)

    def test_manchester_edge_spikes(self):
        for clk in (32, 64):
            self.check(lf_demod.ask_manchester, synth.ask_manchester, clk, spikes=True)

    def test_biphase_levels_and_spikes(self):
        for clk in (32, 64):
            self.check(lf_demod.ask_biphase, synth.ask_biphase, clk)
            self.check(lf_demod.ask_biphase, synth.ask_biphase, clk, spikes=True)

    def test_direct(self):
        for clk in (32, 64):
            self.check(lf_demod.ask_direct, synth.ask_direct, clk)

    def test_manchester_rejects_wrong_clock(self):
        candidates = lf_demod.ask_manchester(synth.ask_manchester(synth.repeat_word(WORD, 3), 64), 32)
        self.assertFalse(any_contains(candidates, WORD_BITS) or any_contains(candidates, WORD_BITS_INV))


class TestFskDemod(unittest.TestCase):
    def test_fsk2_rf50(self):
        samples = synth.fsk(synth.repeat_word(WORD, 3), 50, period_zero=8, period_one=10)
        # short period (fc/8) decodes as 0
        self.assertTrue(any_contains(lf_demod.fsk(samples, 50, 8, 10), WORD_BITS))

    def test_fsk1_rf64(self):
        samples = synth.fsk(synth.repeat_word(WORD, 3), 64, period_zero=8, period_one=5)
        # FSK1: short period (fc/5) is the '1', so the decoded stream is inverted
        self.assertTrue(any_contains(lf_demod.fsk(samples, 64, 5, 8), WORD_BITS_INV))

    def test_fsk2_decimated(self):
        samples = lf_demod.decimate(synth.fsk(synth.repeat_word(WORD, 3), 64, period_zero=8, period_one=10), 2)
        self.assertTrue(any_contains(lf_demod.fsk(samples, 32, 4, 5, lf_demod.FSK_WINDOW // 2), WORD_BITS))


if __name__ == "__main__":
    unittest.main()
