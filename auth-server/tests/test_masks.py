"""Permission mask encoding, including the edges that could grant wrong access."""

import pytest

from utilities.masks import (
    MAX_BITS,
    WILDCARD_BIT,
    bits_to_mask,
    decode_mask,
    encode_mask,
    grants,
    has_bit,
)


def test_documented_example():
    mask = bits_to_mask({1, 4, 9})
    assert mask == 530
    assert encode_mask(mask) == "EgI"
    assert decode_mask("EgI") == 530


def test_empty_mask_is_an_empty_string():
    assert encode_mask(0) == ""
    assert decode_mask("") == 0


def test_bit_zero_round_trips():
    assert decode_mask(encode_mask(bits_to_mask({WILDCARD_BIT}))) == 1


@pytest.mark.parametrize("bit", [52, 53, 54, 63, 64, 255, 1023])
def test_high_bits_keep_full_accuracy(bit):
    mask = bits_to_mask({bit})
    decoded = decode_mask(encode_mask(mask))
    assert decoded == mask
    assert has_bit(decoded, bit)
    assert not has_bit(decoded, bit - 1)


def test_every_bit_set_round_trips():
    mask = bits_to_mask(range(MAX_BITS))
    assert decode_mask(encode_mask(mask)) == mask


@pytest.mark.parametrize("bit", [-1, MAX_BITS])
def test_out_of_range_bit_is_refused(bit):
    with pytest.raises(ValueError):
        bits_to_mask({bit})


def test_sixty_permissions_fit_in_eleven_characters():
    assert len(encode_mask(bits_to_mask(range(60)))) == 11


def test_wildcard_grants_everything_but_only_when_held():
    assert grants(bits_to_mask({WILDCARD_BIT}), 500)
    assert not grants(bits_to_mask({1}), 500)


@pytest.mark.parametrize(
    "value",
    [
        "EgI=",  # padding
        "EgIA",  # trailing zero byte: same number, different text
        "E+I",  # base64 alphabet, not base64url
        "!!!!",
        "é",
        "A" * 1000,
    ],
)
def test_non_canonical_mask_is_refused(value):
    with pytest.raises(ValueError):
        decode_mask(value)
