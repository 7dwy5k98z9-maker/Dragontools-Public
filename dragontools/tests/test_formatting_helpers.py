from __future__ import annotations

from dragontools.core.formatting import format_binary_size


def test_format_binary_size_preserves_iso_display_semantics():
    assert format_binary_size(0, decimals=1) == "0 B"
    assert format_binary_size(1023, decimals=1) == "1023 B"
    assert format_binary_size(1024, decimals=1) == "1.0 KB"
    assert format_binary_size(1536, decimals=1) == "1.5 KB"
    assert format_binary_size(1024**3, decimals=1) == "1.0 GB"


def test_format_binary_size_clamps_negative_values_like_previous_helpers():
    assert format_binary_size(-10, decimals=1) == "0 B"
