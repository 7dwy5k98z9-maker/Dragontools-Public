# -*- coding: utf-8 -*-
"""Signal-safe callback dispatch for Python callables and native Qt signals.

A ``pyqtBoundSignal`` exposes ``emit(...)`` but is intentionally not directly
callable. Generic worker boundaries therefore must not assume ``callback(...)``
is always valid. This helper keeps that distinction in one Qt-independent place.
"""
from __future__ import annotations

from typing import Any


def is_callback_like(callback: Any) -> bool:
    """Return True for normal Python callables and Qt signal-like objects."""
    if callback is None:
        return False
    emit = getattr(callback, "emit", None)
    return callable(emit) or callable(callback)


def invoke_callback(callback: Any, *args, **kwargs):
    """Invoke a Python callable or a Qt-signal-like object.

    ``signal.emit`` callbacks continue to work as normal callables. If the
    signal object itself was injected, ``emit`` is preferred so PyQt never sees
    an illegal direct signal call.
    """
    if callback is None:
        return None

    emit = getattr(callback, "emit", None)
    if callable(emit):
        return emit(*args, **kwargs)

    if callable(callback):
        return callback(*args, **kwargs)

    raise TypeError(f"Callback is neither callable nor signal-like: {type(callback).__name__}")


__all__ = ["invoke_callback", "is_callback_like"]
