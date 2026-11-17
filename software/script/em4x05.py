"""
EM4x05 / EM4x69 (EM4205, EM4305, EM4469, EM4569) response decoding.

Ported from Proxmark3 client/src/cmdlfem4x05.c: after a READ (or LOGIN) the
tag answers with the preamble 00001010 followed by 45 bits:
4 x (data byte LSB first + even row parity), 8 even column parity bits, stop 0.
The error preamble 00000001 means the tag refused (e.g. read-protected word or
login required).  The answer uses the tag's configured encoding and data rate,
so every Manchester / Biphase candidate stream is searched.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import lf_demod

PREAMBLE = (0, 0, 0, 0, 1, 0, 1, 0)
ERROR_PREAMBLE = (0, 0, 0, 0, 0, 0, 0, 1)
RESPONSE_BITS = 45

# EM4305 memory map (Proxmark3 EM4305_*_BLOCK); EM4x69 uses 3 for the password and 2 for protection.
WORD_INFO = 0
WORD_UID = 1
WORD_PASSWORD = 2
WORD_CONFIG = 4
WORD_PROTECT_1 = 14
WORD_PROTECT_2 = 15
WORD_NAMES: Dict[int, str] = {
    0: "chip info",
    1: "UID",
    2: "password (EM4305)",
    3: "user / password (EM4x69)",
    4: "config",
    14: "protection 1",
    15: "protection 2",
}

# EM4305 data rates are RF/8..RF/64; EM4x69 adds RF/40.
CLOCKS = (64, 32, 40, 16, 8)

ENCODERS: Dict[int, str] = {
    0: "NRZ",
    1: "Manchester",
    2: "Biphase",
    3: "Miller",
    4: "PSK1",
    5: "PSK2",
    6: "PSK3",
    8: "FSK1",
    12: "FSK2",
}


@dataclass(frozen=True)
class WordResult:
    word: int
    error: bool
    clock: int = 0


@dataclass(frozen=True)
class Em4x05Config:
    raw: int
    data_rate: int
    encoder: int
    psk_cf: int
    delay: int
    last_word_read: int
    read_login: bool
    write_login: bool
    disable_allowed: bool
    reader_talk_first: bool
    pigeon: bool

    @property
    def encoder_name(self) -> str:
        return ENCODERS.get(self.encoder, f"unknown ({self.encoder})")


def decode_config(word: int) -> Em4x05Config:
    """Field layout from Proxmark3 printEM4x05config()."""
    return Em4x05Config(
        raw=word,
        data_rate=(word & 0x3F) * 2 + 2,
        encoder=(word >> 6) & 0xF,
        psk_cf=(word >> 10) & 0x3,
        delay=(word >> 12) & 0x3,
        last_word_read=(word >> 14) & 0xF,
        read_login=bool((word >> 18) & 1),
        write_login=bool((word >> 20) & 1),
        disable_allowed=bool((word >> 24) & 1),
        reader_talk_first=bool((word >> 25) & 1),
        pigeon=bool((word >> 26) & 1),
    )


def _parse_payload(bits: Sequence[int]) -> Optional[int]:
    word = 0
    column = 0
    for row in range(4):
        cells = list(bits[row * 9:row * 9 + 9])
        if sum(cells) % 2:
            return None
        byte = sum(b << j for j, b in enumerate(cells[:8]))
        column ^= byte
        word |= byte << (8 * row)
    column_bits = bits[36:44]
    if any(((column >> j) & 1) != column_bits[j] for j in range(8)) or bits[44] != 0:
        return None
    return word


# The capture starts a few bits after the command, so the answer (or refusal) sits at the very
# beginning of the stream and its preamble is often truncated to the trailing "1010".
START_WINDOW_BITS = 16
# Shortest preamble tail accepted; the 13 parity/stop bits plus repeat-agreement in the CLI keep this safe.
PREAMBLE_TAILS = ((1, 0, 1, 0), (0, 1, 0), (1, 0))


def _only_leading_noise(bits: Sequence[int]) -> bool:
    return all(b in (0, lf_demod.ERR) for b in bits)


def _payload_word(bits: Sequence[int], start: int) -> Optional[int]:
    payload = bits[start:start + RESPONSE_BITS]
    if len(payload) < RESPONSE_BITS or lf_demod.ERR in payload:
        return None
    return _parse_payload(payload)


def parse_response_bits(bits: Sequence[int]) -> Optional[WordResult]:
    """Find a valid answer (or a refusal) in a decoded bit stream."""
    n = len(PREAMBLE)
    for i in range(len(bits) - n + 1):
        if tuple(bits[i:i + n]) == PREAMBLE:
            word = _payload_word(bits, i + n)
            if word is not None:
                return WordResult(word, False)

    for preamble_tail in PREAMBLE_TAILS:
        tail = len(preamble_tail)
        for i in range(tail, min(len(bits), START_WINDOW_BITS)):
            if tuple(bits[i - tail:i]) == preamble_tail and _only_leading_noise(bits[:i - tail]):
                word = _payload_word(bits, i)
                if word is not None:
                    return WordResult(word, False)

    # A refusal is only trusted at the start of the stream; later "00000001" is just data (e.g. EM410x zeros).
    for i in range(0, START_WINDOW_BITS):
        if tuple(bits[i:i + n]) == ERROR_PREAMBLE and _only_leading_noise(bits[:i]):
            return WordResult(0, True)
    return None


def decode_word_samples(samples: Sequence[int], decimation: int = 1) -> Optional[WordResult]:
    """Demodulate a raw capture taken right after a READ/LOGIN and extract the answer."""
    if not lf_demod.binarize(samples):
        return None
    error: Optional[WordResult] = None
    for clk in CLOCKS:
        candidates: List[List[int]] = lf_demod.ask_manchester(samples, clk / decimation)
        candidates += lf_demod.ask_biphase(samples, clk / decimation)
        for bits in candidates:
            for inverted in (False, True):
                stream = [b if b == lf_demod.ERR else (1 - b if inverted else b) for b in bits]
                res = parse_response_bits(stream)
                if res is None:
                    continue
                if not res.error:
                    return WordResult(res.word, False, clk)
                error = error or WordResult(0, True, clk)
    return error


# ---------------------------------------------------------------------------
# Write planning (values from Proxmark3 cmdlfem4x05.h / armsrc/lfops.c)
# ---------------------------------------------------------------------------

# EM4x05_SET_BITRATE(64) | EM4x05_MODULATION_MANCHESTER | EM4x05_SET_NUM_BLOCKS(2): EM410x/"unique", words 5-6.
CONFIG_EM_UNIQUE = 0x0001805F

# Never written: chip info and UID identify the chip; 14/15 are the protection words (irreversible lock).
WRITE_FORBIDDEN_WORDS = {
    WORD_INFO: "chip info identifies the chip",
    WORD_UID: "UID is factory programmed",
    WORD_PROTECT_1: "protection word: writing it can lock the tag permanently",
    WORD_PROTECT_2: "protection word: writing it can lock the tag permanently",
}
_CONFIG_READ_LOGIN = 1 << 18
_CONFIG_WRITE_LOGIN = 1 << 20


def write_refusal(addr: int, value: int) -> Optional[str]:
    """Return why a WRITE must not be sent, or None when it is safe."""
    if not 0 <= addr <= 15:
        return "word address must be 0-15"
    if addr in WRITE_FORBIDDEN_WORDS:
        return f"word {addr} is never written ({WRITE_FORBIDDEN_WORDS[addr]})"
    if not 0 <= value <= 0xFFFFFFFF:
        return "value must be 32 bits"
    if addr == WORD_CONFIG and value & (_CONFIG_READ_LOGIN | _CONFIG_WRITE_LOGIN):
        return "config with read/write login enabled would make the tag depend on its password; refused"
    return None


def reflect32(value: int) -> int:
    return int(f"{value & 0xFFFFFFFF:032b}"[::-1], 2)


def em410x_frame(id_hex: str) -> int:
    """64-bit EM410x frame: 9 header ones, 10 rows (nibble + even parity), 4 column parity bits, stop 0."""
    if len(id_hex) != 10:
        raise ValueError("EM410x ID must be 10 hex digits")
    try:
        nibbles = [int(c, 16) for c in id_hex]
    except ValueError as e:
        raise ValueError("EM410x ID must be hex") from e
    bits = [1] * 9
    for n in nibbles:
        row = [(n >> (3 - i)) & 1 for i in range(4)]
        bits += row + [sum(row) % 2]
    bits += [sum((n >> (3 - c)) & 1 for n in nibbles) % 2 for c in range(4)]
    bits.append(0)
    frame = 0
    for b in bits:
        frame = (frame << 1) | b
    return frame


def em410x_clone_words(id_hex: str) -> Dict[int, int]:
    """Words to program an EM410x ID onto an EM4305, in write order (Proxmark3 lf em 410x clone --em)."""
    frame = em410x_frame(id_hex)
    return {
        6: reflect32(frame & 0xFFFFFFFF),
        5: reflect32(frame >> 32),
        WORD_CONFIG: CONFIG_EM_UNIQUE,
    }


def wipe_plan() -> List[Tuple[int, int]]:
    """Zero password, user and data words, then restore the default EM/unique config last.

    Differs from Proxmark3 `lf em 4x05 wipe` on purpose: chip info (0) and UID (1) are left untouched.
    """
    plan = [(addr, 0) for addr in (WORD_PASSWORD, 3, *range(5, 14))]
    return plan + [(WORD_CONFIG, CONFIG_EM_UNIQUE)]


# ---------------------------------------------------------------------------
# Chip identification (Proxmark3 em_get_card_type / printEM4x05info)
# ---------------------------------------------------------------------------

CHIP_TYPES: Dict[int, str] = {4: "EM4469", 8: "EM4205", 9: "EM4305", 12: "EM4369"}
CAPACITORS: Dict[int, str] = {0: "none", 1: "250pF", 2: "210pF", 3: "330pF"}
DEFAULT_CUSTOMER_CODE = 0x200


@dataclass(frozen=True)
class ChipInfo:
    raw: int
    chip_type: int
    capacitor: str
    customer_code: int

    @property
    def name(self) -> str:
        return CHIP_TYPES.get(self.chip_type, f"unknown (type {self.chip_type}, EM4x05-compatible)")

    @property
    def default_customer_code(self) -> bool:
        return self.customer_code == DEFAULT_CUSTOMER_CODE


def decode_chip_info(word0: int) -> ChipInfo:
    chip_type = (word0 >> 1) & 0xF
    cap = (word0 >> 5) & 3
    capacitor = "75pF" if cap == 2 and chip_type == 4 else CAPACITORS[cap]
    return ChipInfo(word0, chip_type, capacitor, (word0 >> 9) & 0x2FF)


def em410x_id_from_words(word5: int, word6: int) -> Optional[str]:
    """Inverse of em410x_clone_words(): the EM410x ID a tag sends from words 5-6, or None."""
    frame = (reflect32(word5) << 32) | reflect32(word6)
    bits = [(frame >> (63 - i)) & 1 for i in range(64)]
    if bits[:9] != [1] * 9 or bits[63] != 0:
        return None
    rows = [bits[9 + 5 * r:14 + 5 * r] for r in range(10)]
    if any(sum(row) % 2 for row in rows):
        return None
    if any(sum(row[c] for row in rows) % 2 != bits[59 + c] for c in range(4)):
        return None
    return "".join("%X" % int("".join(map(str, row[:4])), 2) for row in rows)
