"""Monotonic result transitions within one conversion run."""

# ``🧩`` remains the internal protocol marker for a video that is already
# committed while optional NFO/Trickplay post-processing is still running.
# The GUI intentionally renders that state as the historical green star-like
# symbol ``✳️`` so the user can distinguish encode-finished from fully-finished.
POSTPROCESS_PENDING_STATUS = "🧩"
POSTPROCESS_PENDING_ICON = "✳️"

TERMINAL_RANK = {"✅": 1, "⏭️": 2, "⚠️": 3, "❌": 4}


def accepts_result(previous: str | None, incoming: str) -> bool:
    """Terminal outcomes may deteriorate, never revert to pending or success."""
    old = TERMINAL_RANK.get(previous, 0)
    return not old or TERMINAL_RANK.get(incoming, 0) > old
