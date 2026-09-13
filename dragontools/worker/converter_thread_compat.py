# -*- coding: utf-8 -*-
"""Deprecated compatibility import kept for old third-party imports.

``ConverterThread`` no longer inherits this mixin. Runtime state is owned by the
explicit job/control/session/service contexts instead of descriptor aliases.
"""
from __future__ import annotations


class ConverterThreadCompatibilityMixin:
    """Deprecated empty marker; legacy state aliases were removed."""

    __slots__ = ()
