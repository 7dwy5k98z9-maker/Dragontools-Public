from __future__ import annotations

from typing import Any


def lang(value: Any) -> str:
    text = str(value).strip().lower() if value is not None else ""
    return text or "und"


def enum_value(value: Any) -> Any:
    return getattr(value, "value", value)
