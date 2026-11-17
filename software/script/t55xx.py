"""
T55x7/T5577 configuration (block 0) decoding and modulation detection.

Port of the idea behind Proxmark3 `lf t55xx detect` (client/src/cmdlft55xx.c):
read block 0 with a direct-access command, then try every demodulation and
bit rate until a 32-bit word appears that is a self-consistent config block,
i.e. its own bit-rate and modulation fields match the demodulation that
produced it, and it repeats in the capture.
"""

from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import lf_demod

MOD_DIRECT = 0
MOD_PSK1 = 1
MOD_PSK2 = 2
MOD_PSK3 = 3
MOD_FSK1 = 4
MOD_FSK2 = 5
MOD_FSK1A = 6
MOD_FSK2A = 7
MOD_MANCHESTER = 8
MOD_BIPHASE = 16
MOD_DIPHASE = 24

MOD_NAMES: Dict[int, str] = {
    MOD_DIRECT: "Direct (NRZ)",
    MOD_PSK1: "PSK1",
    MOD_PSK2: "PSK2",
    MOD_PSK3: "PSK3",
    MOD_FSK1: "FSK1 (RF/8, RF/5)",
    MOD_FSK2: "FSK2 (RF/8, RF/10)",
    MOD_FSK1A: "FSK1a (RF/8, RF/5)",
    MOD_FSK2A: "FSK2a (RF/8, RF/10)",
    MOD_MANCHESTER: "ASK / Manchester",
    MOD_BIPHASE: "Biphase",
    MOD_DIPHASE: "Diphase (Biphase-a)",
}

BIT_RATES = (8, 16, 32, 40, 50, 64, 100, 128)

# Block 0 bit masks (same layout as firmware protocols/t55xx.h)
_MASTER_KEY_SHIFT = 28
_RESERVED_BASIC = 0x0FE00000  # must be zero in basic (T55x7-compatible) mode
_RESERVED_BIT8 = 0x00000100
_X_MODE = 0x00020000
_BITRATE_SHIFT = 18
_MOD_SHIFT = 12
_PSKCF_SHIFT = 10
_AOR = 0x00000200
_MAXBLOCK_SHIFT = 5
_PWD = 0x00000010
_ST = 0x00000008
_POR_DELAY = 0x00000001


@dataclass(frozen=True)
class T55xxConfig:
    raw: int
    master_key: int
    extended_mode: bool
    bit_rate: int
    modulation: int
    psk_cf: int
    aor: bool
    max_block: int
    password_enabled: bool
    seq_terminator: bool
    por_delay: bool

    @property
    def modulation_name(self) -> str:
        return MOD_NAMES.get(self.modulation, f"unknown ({self.modulation})")


@dataclass(frozen=True)
class DetectResult:
    block0: int
    config: T55xxConfig
    demod: str
    inverted: bool
    offset: int
    repeats: int


def decode_config(word: int) -> T55xxConfig:
    key = (word >> _MASTER_KEY_SHIFT) & 0xF
    extended = key in (6, 9) and bool(word & _X_MODE)
    if extended:
        bit_rate = 2 * ((word >> _BITRATE_SHIFT) & 0x3F) + 2
    else:
        bit_rate = BIT_RATES[(word >> _BITRATE_SHIFT) & 0x7]
    return T55xxConfig(
        raw=word,
        master_key=key,
        extended_mode=extended,
        bit_rate=bit_rate,
        modulation=(word >> _MOD_SHIFT) & 0x1F,
        psk_cf=2 << ((word >> _PSKCF_SHIFT) & 0x3),
        aor=bool(word & _AOR),
        max_block=(word >> _MAXBLOCK_SHIFT) & 0x7,
        password_enabled=bool(word & _PWD),
        seq_terminator=bool(word & _ST),
        por_delay=bool(word & _POR_DELAY),
    )


def is_plausible_config(word: int) -> bool:
    if word in (0x00000000, 0xFFFFFFFF):
        return False
    cfg = decode_config(word)
    if cfg.modulation not in MOD_NAMES or word & _RESERVED_BIT8:
        return False
    if cfg.extended_mode:
        return 8 <= cfg.bit_rate <= 128
    return not (word & _RESERVED_BASIC) and not (word & _X_MODE and cfg.master_key not in (6, 9))


Decoder = Callable[[Sequence[int], float], List[List[int]]]


def _fsk_decoder(short_period: int, long_period: int) -> Callable[[Sequence[int], float, int], List[List[int]]]:
    def decode(samples: Sequence[int], clk: float, decimation: int) -> List[List[int]]:
        return lf_demod.fsk(
            samples, clk, short_period / decimation, long_period / decimation, lf_demod.FSK_WINDOW // decimation
        )

    return decode


def _ask_decoder(decode: Decoder) -> Callable[[Sequence[int], float, int], List[List[int]]]:
    return lambda samples, clk, decimation: decode(samples, clk)


# (name, decoder, modulation values this decoder can legitimately produce)
DEMODULATORS: Tuple[Tuple[str, Callable[[Sequence[int], float, int], List[List[int]]], Tuple[int, ...]], ...] = (
    ("ASK/Manchester", _ask_decoder(lf_demod.ask_manchester), (MOD_MANCHESTER,)),
    ("Biphase", _ask_decoder(lf_demod.ask_biphase), (MOD_BIPHASE, MOD_DIPHASE)),
    ("Direct", _ask_decoder(lf_demod.ask_direct), (MOD_DIRECT,)),
    ("FSK RF/8-RF/10", _fsk_decoder(8, 10), (MOD_FSK2, MOD_FSK2A)),
    ("FSK RF/5-RF/8", _fsk_decoder(5, 8), (MOD_FSK1, MOD_FSK1A)),
)

# Direct-access reads repeat the block back-to-back; some tags insert a 0 bit between repeats.
_REPEAT_PERIODS = (32, 33)
# Any stream this long contains a full block followed by its repeat, so a repeat is mandatory.
_BITS_FOR_MANDATORY_REPEAT = 96
# Device sample decimation factors the detector can use (see firmware LF_T55XX_READ_RAW).
DECIMATIONS = (1, 2, 4)


def _pack(bits: Sequence[int]) -> int:
    word = 0
    for b in bits:
        word = (word << 1) | b
    return word


def _count_repeats(bits: Sequence[int], start: int) -> int:
    window = list(bits[start:start + 32])
    best = 0
    for period in _REPEAT_PERIODS:
        repeats = 0
        pos = start + period
        while pos + 32 <= len(bits) and list(bits[pos:pos + 32]) == window:
            repeats += 1
            pos += period
        best = max(best, repeats)
    return best


def find_config(bits: Sequence[int], clk: int, modulations: Tuple[int, ...]) -> Optional[Tuple[int, int, int]]:
    """Return (block0, offset, repeats) of the best self-consistent config word in bits."""
    need_repeat = len(bits) >= _BITS_FOR_MANDATORY_REPEAT
    best: Optional[Tuple[int, int, int]] = None
    for i in range(len(bits) - 31):
        window = bits[i:i + 32]
        if lf_demod.ERR in window:
            continue
        word = _pack(window)
        if not is_plausible_config(word):
            continue
        cfg = decode_config(word)
        if cfg.bit_rate != clk or cfg.modulation not in modulations:
            continue
        repeats = _count_repeats(bits, i)
        if repeats == 0 and need_repeat:
            continue
        if best is None or repeats > best[2]:
            best = (word, i, repeats)
    return best


def _pick_capture(captures: Mapping[int, Sequence[int]], clk: int) -> Optional[Tuple[int, Sequence[int]]]:
    """Least-decimated capture that still holds enough bits at this clock (else the longest one)."""
    usable = sorted(captures.items())
    for decimation, samples in usable:
        if len(samples) * decimation / clk >= _BITS_FOR_MANDATORY_REPEAT + 8:
            return decimation, samples
    return max(usable, key=lambda c: len(c[1]) * c[0]) if usable else None


def detect_from_captures(captures: Mapping[int, Sequence[int]]) -> Optional[DetectResult]:
    """Try every demodulator and bit rate on raw block-0 captures keyed by decimation factor."""
    captures = {d: s for d, s in captures.items() if lf_demod.binarize(s)}
    best: Optional[DetectResult] = None
    for name, decode, modulations in DEMODULATORS:
        for clk in BIT_RATES:
            picked = _pick_capture(captures, clk)
            if picked is None:
                return None
            decimation, samples = picked
            for bits in decode(samples, clk / decimation, decimation):
                for inverted in (False, True):
                    stream = [b if b == lf_demod.ERR else (1 - b if inverted else b) for b in bits]
                    found = find_config(stream, clk, modulations)
                    if found is None:
                        continue
                    word, offset, repeats = found
                    if best is None or repeats > best.repeats:
                        best = DetectResult(word, decode_config(word), name, inverted, offset, repeats)
    return best


def detect_from_samples(samples: Sequence[int]) -> Optional[DetectResult]:
    """Detect from a single full-rate capture."""
    return detect_from_captures({1: samples})


def describe(result: DetectResult, password: Optional[int] = None) -> List[str]:
    cfg = result.config
    rate = f"RF/{cfg.bit_rate}" + (" (extended mode)" if cfg.extended_mode else "")
    lines = [
        f"Chip type......... T55x7 / T5577{' (X-mode)' if cfg.extended_mode else ''}",
        f"Modulation........ {cfg.modulation_name}",
        f"Bit rate.......... {rate}",
        f"Block0............ {result.block0:08X}",
        f"Max block......... {cfg.max_block}",
        f"Password set...... {'Yes' if cfg.password_enabled else 'No'}",
        f"Seq. terminator... {'Yes' if cfg.seq_terminator else 'No'}",
        f"AOR............... {'Yes' if cfg.aor else 'No'}",
        f"Master key........ {cfg.master_key:X}",
        f"Demodulator....... {result.demod} (offset {result.offset}, repeats {result.repeats})",
    ]
    if cfg.modulation in (MOD_PSK1, MOD_PSK2, MOD_PSK3):
        lines.insert(2, f"PSK carrier....... RF/{cfg.psk_cf}")
    if password is not None:
        lines.append(f"Password used..... {password:08X}")
    return lines
