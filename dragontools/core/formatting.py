# -*- coding: utf-8 -*-
from __future__ import annotations


def format_binary_size(value: int, *, decimals: int = 1) -> str:
    """Formatiert nicht-negative Bytewerte binär (1024er-Schritte).

    Die Funktion ist absichtlich klein und streng: Aufrufer liefern Bytewerte;
    ungültige Fremddaten sollen am jeweiligen Parser-Rand behandelt werden.
    """
    size = float(max(0, int(value or 0)))
    digits = max(0, int(decimals))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.{digits}f} {unit}"
        size /= 1024.0
    return "0 B"


__all__ = ["format_binary_size"]
