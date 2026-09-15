"""Monotonic result transitions within one conversion run."""
TERMINAL_RANK = {"✅": 1, "⏭️": 2, "⚠️": 3, "❌": 4}


def accepts_result(previous: str | None, incoming: str) -> bool:
    """Terminal outcomes may deteriorate, never revert to pending or success."""
    old = TERMINAL_RANK.get(previous, 0)
    return not old or TERMINAL_RANK.get(incoming, 0) > old
