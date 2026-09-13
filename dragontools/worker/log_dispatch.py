# -*- coding: utf-8 -*-
from __future__ import annotations

import inspect
from typing import Any


_LEVEL_METHODS: dict[str, tuple[str, ...]] = {
    "debug": ("debug", "info"),
    "info": ("info",),
    "warn": ("warn", "warning"),
    "warning": ("warn", "warning"),
    "error": ("error", "warn", "warning"),
    "success": ("success", "info"),
}


def normalize_log_level(level: str | None) -> str:
    value = str(level or "info").strip().lower()
    if value == "warning":
        return "warn"
    return value if value in {"debug", "info", "warn", "error", "success"} else "info"


def _accepts_level_argument(callback: Any) -> bool:
    """Return whether callback can be invoked as callback(message, level).

    Qt/PyQt callables and some C implemented callables do not expose a usable
    Python signature. For those we deliberately fall back to the one-argument
    form instead of speculatively calling twice and potentially duplicating a
    side effect after an unrelated TypeError inside the callback.
    """
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return False
    try:
        signature.bind("message", "info")
    except TypeError:
        return False
    return True


def dispatch_log(log: Any, message: object, level: str = "info") -> bool:
    """Best-effort logging adapter for DragonLogger, worker.log, callables and Qt signals.

    Logging is infrastructure and must never abort media processing. The helper
    therefore intentionally swallows ordinary callback/logger exceptions and
    reports success via its return value.

    Supported shapes:
    - logger object with ``info()/warn()/error()/success()`` methods
    - worker style callable ``log(message, level)``
    - single argument callable such as ``list.append``
    - native Qt bound signal / signal-like object exposing ``emit(message)``
    - bound ``signal.emit`` callback
    """
    if log is None:
        return False

    text = str(message)
    normalized = normalize_log_level(level)

    # Logger-like objects get the level-specific method first. A pyqtBoundSignal
    # does not expose these methods, so it safely falls through to ``emit``.
    for method_name in _LEVEL_METHODS.get(normalized, (normalized, "info")):
        method = getattr(log, method_name, None)
        if not callable(method):
            continue
        try:
            method(text)
            return True
        except Exception:
            return False

    # Native Qt signals are not normal Python callables. Calling them directly
    # raises ``TypeError: native Qt signal is not callable``; ``emit`` is the
    # supported boundary.
    emit = getattr(log, "emit", None)
    if callable(emit):
        try:
            emit(text)
            return True
        except Exception:
            return False

    if callable(log):
        try:
            if _accepts_level_argument(log):
                log(text, normalized)
            else:
                log(text)
            return True
        except Exception:
            return False

    # Some adapters wrap the actual callable in a ``log`` attribute.
    nested = getattr(log, "log", None)
    if nested is not None and nested is not log:
        return dispatch_log(nested, text, normalized)
    return False


__all__ = ["dispatch_log", "normalize_log_level"]
