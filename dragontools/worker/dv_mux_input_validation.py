"""Validate every planned mux track before invoking the final container tool."""
from pathlib import Path


def required_mux_inputs_available(paths) -> bool:
    try:
        return all(Path(path).is_file() and Path(path).stat().st_size > 0 for path in paths)
    except OSError:
        return False
