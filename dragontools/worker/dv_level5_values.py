"""One strict parser for all exported Dolby Vision active-area consumers."""
from __future__ import annotations

from ..core.strict_numbers import nonnegative_integer

_ALIASES = (
    ('left', 'right', 'top', 'bottom'),
    ('active_area_left_offset', 'active_area_right_offset',
     'active_area_top_offset', 'active_area_bottom_offset'),
)


def collect_level5_offsets(node, result: list[tuple[int, int, int, int]]) -> None:
    if isinstance(node, dict):
        for names in _ALIASES:
            if any(name in node for name in names):
                if not all(name in node for name in names):
                    raise ValueError('Incomplete Level-5 active-area offsets')
                result.append(tuple(nonnegative_integer(node[name]) for name in names))
        for child in node.values():
            collect_level5_offsets(child, result)
    elif isinstance(node, list):
        for child in node:
            collect_level5_offsets(child, result)
