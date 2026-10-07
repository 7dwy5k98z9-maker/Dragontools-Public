"""Validate discrete media counts and tool identifiers without rounding."""
from __future__ import annotations

import re


def nonnegative_integer(value: object) -> int:
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]+', str(value).strip()):
        raise ValueError(f'Expected a nonnegative integer, got {value!r}')
    return int(str(value).strip())


def positive_integer(value: object) -> int:
    result = nonnegative_integer(value)
    if result == 0:
        raise ValueError('Expected a positive integer')
    return result
