"""Validation and application of a manually selected release/start year."""
from dataclasses import replace


def normalize_year_override(value) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    text = str(value).strip()
    if not text.isascii() or not text.isdecimal() or len(text) != 4:
        raise ValueError("Bitte ein vierstelliges Jahr zwischen 1800 und 2199 eingeben.")
    year = int(text)
    if not 1800 <= year <= 2199:
        raise ValueError("Bitte ein Jahr zwischen 1800 und 2199 eingeben.")
    return year


def apply_year_override(parsed, value):
    year = normalize_year_override(value)
    if year is None:
        return parsed
    return replace(parsed, year=year, warnings=(*parsed.warnings, f"Jahr {year} manuell gesetzt."))
