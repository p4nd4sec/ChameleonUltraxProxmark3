"""
Synthetic LF tag waveforms for demodulator tests.

Produces 8-bit ADC-like sample streams at 1 sample per carrier cycle (Tc),
matching what the ChameleonUltra SAADC capture returns (saturating rails,
~0 for a loaded field and ~255 for an unloaded one).
"""

import random
from typing import List, Optional

HIGH = 255
LOW = 0


def _bits_of(word: int, nbits: int = 32) -> List[int]:
    return [(word >> (nbits - 1 - i)) & 1 for i in range(nbits)]


def repeat_word(word: int, repeats: int) -> List[int]:
    return _bits_of(word) * repeats


def ask_manchester(bits: List[int], clk: int) -> List[int]:
    """Bit 1 = high then low, bit 0 = low then high."""
    half = clk // 2
    out: List[int] = []
    for b in bits:
        first, second = (HIGH, LOW) if b else (LOW, HIGH)
        out += [first] * half + [second] * (clk - half)
    return out


def ask_biphase(bits: List[int], clk: int) -> List[int]:
    """Transition at every bit boundary; bit 0 adds a mid-bit transition."""
    half = clk // 2
    out: List[int] = []
    level = HIGH
    for b in bits:
        level = LOW if level == HIGH else HIGH
        if b:
            out += [level] * clk
        else:
            other = LOW if level == HIGH else HIGH
            out += [level] * half + [other] * (clk - half)
            level = other
    return out


def ask_direct(bits: List[int], clk: int) -> List[int]:
    out: List[int] = []
    for b in bits:
        out += [HIGH if b else LOW] * clk
    return out


def fsk(bits: List[int], clk: int, period_zero: int, period_one: int) -> List[int]:
    """Phase-continuous square-wave subcarrier, one period length per bit value."""
    out: List[int] = []
    phase = 0
    for b in bits:
        period = period_one if b else period_zero
        for _ in range(clk):
            out.append(HIGH if phase < period // 2 else LOW)
            phase = (phase + 1) % period
    return out


def edge_spikes(samples: List[int], width: int = 30, rising: bool = True) -> List[int]:
    """Model the ChameleonUltra front-end: only one edge polarity survives, as a fixed-width spike.

    Observed on real EM410x captures: a ~30-sample saturated pulse after every
    edge of one polarity, the rest of the signal pinned at the other rail.
    """
    out = [LOW] * len(samples)
    for i in range(1, len(samples)):
        edge = samples[i] > samples[i - 1] if rising else samples[i] < samples[i - 1]
        if edge:
            for j in range(i, min(i + width, len(samples))):
                out[j] = HIGH
    return out


def add_noise(samples: List[int], glitch_rate: float = 0.01, seed: Optional[int] = 1) -> List[int]:
    """Flip isolated samples to the opposite rail, like the spikes seen on real captures."""
    rng = random.Random(seed)
    return [(HIGH - s) if rng.random() < glitch_rate else s for s in samples]


def with_lead_in(samples: List[int], lead: int = 300, level: int = 170) -> List[int]:
    """Unmodulated carrier before the tag starts answering."""
    return [level] * lead + samples
