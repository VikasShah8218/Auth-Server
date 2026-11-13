"""Integer permission masks.

Each permission owns a permanent bit inside its application. A user's access is one integer with those bits
set. In a token that integer is carried as little-endian bytes in base64url, because JSON numbers above 2^53
lose accuracy in JavaScript and would silently grant the wrong access.

    bits {1, 4, 9} -> 530 -> "EgI"
"""

import base64
import binascii
from collections.abc import Iterable

MAX_BITS = 1024
WILDCARD_BIT = 0
WILDCARD_CODE = "*"

_MAX_BYTES = MAX_BITS // 8


def bits_to_mask(bits: Iterable[int]) -> int:
    mask = 0
    for bit in bits:
        if not 0 <= bit < MAX_BITS:
            raise ValueError(f"Permission bit out of range: {bit}")
        mask |= 1 << bit
    return mask


def encode_mask(mask: int) -> str:
    if mask < 0 or mask >= 1 << MAX_BITS:
        raise ValueError("Permission mask out of range")
    raw = mask.to_bytes((mask.bit_length() + 7) // 8, "little")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_mask(value: str) -> int:
    """Decode a token's mask. Anything but the exact canonical form is rejected."""
    if len(value) > (_MAX_BYTES * 4 + 2) // 3:
        raise ValueError("Permission mask too long")
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii") + b"=" * (-len(value) % 4))
    except (binascii.Error, ValueError, UnicodeEncodeError):
        raise ValueError("Permission mask is not base64url") from None
    mask = int.from_bytes(raw, "little")
    if mask >= 1 << MAX_BITS or encode_mask(mask) != value:
        raise ValueError("Permission mask is not canonical")
    return mask


def has_bit(mask: int, bit: int) -> bool:
    return bool(mask >> bit & 1)


def grants(mask: int, bit: int) -> bool:
    """True when the mask holds this bit, or the full-access bit."""
    return has_bit(mask, WILDCARD_BIT) or has_bit(mask, bit)
