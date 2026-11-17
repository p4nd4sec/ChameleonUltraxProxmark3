"""
Host-side LF demodulators for raw ChameleonUltra ADC captures.

Captures are 8-bit samples at one sample per 125 kHz carrier cycle (Tc), the
same rate Proxmark3 uses by default.

The ChameleonUltra LF front-end does not deliver a clean ASK envelope: tag
load-modulation edges show up as saturated spikes, so for ASK only the
*timing* of same-polarity edges is trustworthy (exactly what the firmware
decoders in nfctag/lf/utils/manchester.c and diphase.c consume).  FSK keeps
its subcarrier and is detected by comparing tone energy, like
nfctag/lf/utils/fskdemod.c.

Every decoder returns candidate bit streams (polarity / phase is unknown),
where -1 marks positions that could not be decoded.  Callers validate
candidates (e.g. T55xx block 0 self-consistency) to pick the right one.

Algorithms follow Proxmark3 common/lfdemod.c and the firmware state machines.
"""

import math
from typing import List, Sequence, Tuple

ERR = -1
Run = Tuple[int, int]  # (level or symbol, length in samples)
Bits = List[int]

# Minimum peak-to-peak span (8-bit units) for a capture to count as modulated.
MIN_SPAN = 40

# Interval classes for edge-timing decoders.
T1, T15, T2, T_INVALID = 0, 1, 2, 3


def binarize(samples: Sequence[int]) -> List[int]:
    """Threshold samples halfway between the 5th and 95th percentile.

    Returns an empty list when the capture is flat (no tag modulation).
    """
    if not samples:
        return []
    ordered = sorted(samples)
    lo = ordered[int(0.05 * (len(ordered) - 1))]
    hi = ordered[int(0.95 * (len(ordered) - 1))]
    if hi - lo < MIN_SPAN:
        return []
    threshold = (lo + hi) / 2
    return [1 if s > threshold else 0 for s in samples]


def majority_filter(levels: Sequence[int], radius: int) -> List[int]:
    """Replace each level by the majority of its 2*radius+1 neighbourhood.

    Removes spikes shorter than radius+1 samples without shifting real edges.
    """
    if radius <= 0 or not levels:
        return list(levels)
    prefix = [0]
    for level in levels:
        prefix.append(prefix[-1] + level)
    n = len(levels)
    out: List[int] = []
    for i in range(n):
        lo, hi = max(0, i - radius), min(n, i + radius + 1)
        out.append(1 if 2 * (prefix[hi] - prefix[lo]) > hi - lo else 0)
    return out


def runs_of(levels: Sequence[int], min_run: int = 1) -> List[Run]:
    """Run-length encode levels, folding runs shorter than min_run into the previous run."""
    runs: List[Run] = []
    for level in levels:
        if runs and runs[-1][0] == level:
            runs[-1] = (level, runs[-1][1] + 1)
        else:
            runs.append((level, 1))

    merged: List[Run] = []
    for level, length in runs:
        if merged and (length < min_run or merged[-1][0] == level):
            merged[-1] = (merged[-1][0], merged[-1][1] + length)
        else:
            merged.append((level, length))
    return merged


def _clean_levels(samples: Sequence[int], radius: int) -> List[int]:
    return majority_filter(binarize(samples), radius)


def _runs_to_bits(runs: Sequence[Run], clk: float) -> Bits:
    """Expand (symbol, length) runs to bits using cumulative position, so rounding never drifts.

    ERR runs reset the position reference and emit a single ERR.
    """
    out: Bits = []
    pos = 0
    for sym, length in runs:
        if sym == ERR:
            out.append(ERR)
            pos = 0
            continue
        out += [sym] * (round((pos + length) / clk) - round(pos / clk))
        pos += length
    return out


# ---------------------------------------------------------------------------
# ASK: edge-timing decoders (Manchester, Biphase)
# ---------------------------------------------------------------------------


def edge_intervals(samples: Sequence[int], clk: float, level: int) -> List[int]:
    """Distances between consecutive edges entering `level` (1 = rising, 0 = falling)."""
    runs = runs_of(_clean_levels(samples, max(1, int(clk) // 16)), max(2, int(clk) // 8))
    intervals: List[int] = []
    pos = 0
    last = None
    for run_level, length in runs:
        if run_level == level:
            if last is not None:
                intervals.append(pos - last)
            last = pos
        pos += length
    return intervals


def classify_interval(interval: int, clk: float) -> int:
    jitter = clk / 4
    for cls, nominal in ((T1, clk), (T15, 1.5 * clk), (T2, 2 * clk)):
        if abs(interval - nominal) <= jitter:
            return cls
    return T_INVALID


def manchester_from_intervals(intervals: Sequence[int], clk: float, start_sync: bool) -> Bits:
    """Port of firmware manchester_feed(): same-polarity edge intervals -> bits."""
    out: Bits = []
    sync = start_sync
    for interval in intervals:
        t = classify_interval(interval, clk)
        if t == T_INVALID or (not sync and t == T2):
            out.append(ERR)
            sync = start_sync
        elif sync:
            out += {T1: [0], T15: [1], T2: [1, 0]}[t]
            sync = t != T15
        else:
            out += {T1: [1], T15: [1, 0]}[t]
            sync = t == T15
    return out


def biphase_from_intervals(intervals: Sequence[int], clk: float, start_boundary: bool) -> Bits:
    """Port of firmware diphase_feed(): same-polarity edge intervals -> bits."""
    out: Bits = []
    boundary = start_boundary
    for interval in intervals:
        t = classify_interval(interval, clk)
        if t == T_INVALID or (not boundary and t == T2):
            out.append(ERR)
            boundary = start_boundary
        elif boundary:
            out += {T1: [0], T15: [1, 0], T2: [1, 1]}[t]
            boundary = t != T15
        else:
            out += {T1: [0], T15: [1]}[t]
            boundary = t == T15
    return out


def ask_manchester(samples: Sequence[int], clk: float) -> List[Bits]:
    """Candidate Manchester streams for both edge polarities and both start phases."""
    return [
        manchester_from_intervals(edge_intervals(samples, clk, level), clk, sync)
        for level in (1, 0)
        for sync in (True, False)
    ]


def ask_biphase(samples: Sequence[int], clk: float) -> List[Bits]:
    """Candidate biphase streams for both edge polarities and both start phases."""
    return [
        biphase_from_intervals(edge_intervals(samples, clk, level), clk, boundary)
        for level in (1, 0)
        for boundary in (True, False)
    ]


# ---------------------------------------------------------------------------
# ASK: level decoder (Direct / NRZ)
# ---------------------------------------------------------------------------


def ask_direct(samples: Sequence[int], clk: float) -> List[Bits]:
    """Direct/NRZ: one level per bit period. Needs plateau levels, not just edge spikes."""
    runs = runs_of(_clean_levels(samples, max(1, int(clk) // 16)), max(2, int(clk) // 4))
    return [_runs_to_bits(runs, clk)]


# ---------------------------------------------------------------------------
# FSK: sliding tone-energy comparison
# ---------------------------------------------------------------------------

# 40 samples hold a whole number of fc/5, fc/8 and fc/10 cycles, so DC never leaks.
FSK_WINDOW = 40


def _tone_power(samples: Sequence[float], period: float, window: int) -> List[float]:
    """Sliding single-bin DFT power at 1/period cycles per sample (window centred)."""
    n = len(samples)
    w = 2 * math.pi / period
    pre_c = [0.0]
    pre_s = [0.0]
    for i, x in enumerate(samples):
        pre_c.append(pre_c[-1] + x * math.cos(w * i))
        pre_s.append(pre_s[-1] + x * math.sin(w * i))
    half = window // 2
    out: List[float] = []
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i - half + window)
        c, s = pre_c[hi] - pre_c[lo], pre_s[hi] - pre_s[lo]
        out.append(c * c + s * s)
    return out


def fsk(
    samples: Sequence[int], clk: float, short_period: float, long_period: float, window: int = FSK_WINDOW
) -> List[Bits]:
    """FSK: the short-period tone decodes as 0, the long-period tone as 1."""
    if not binarize(samples):
        return [[]]
    mean = sum(samples) / len(samples)
    centred = [s - mean for s in samples]
    p_short = _tone_power(centred, short_period, window)
    p_long = _tone_power(centred, long_period, window)
    floor = 0.05 * max(max(p_short), max(p_long))
    symbols: List[Run] = []
    for ps, pl in zip(p_short, p_long):
        sym = ERR if max(ps, pl) < floor else (1 if pl > ps else 0)
        if symbols and symbols[-1][0] == sym:
            symbols[-1] = (sym, symbols[-1][1] + 1)
        else:
            symbols.append((sym, 1))
    return [_runs_to_bits(symbols, clk)]


def decimate(samples: Sequence[int], factor: int) -> List[int]:
    """Average non-overlapping groups of `factor` samples (mirrors the firmware capture option)."""
    if factor <= 1:
        return list(samples)
    return [sum(samples[i:i + factor]) // factor for i in range(0, len(samples) - factor + 1, factor)]
