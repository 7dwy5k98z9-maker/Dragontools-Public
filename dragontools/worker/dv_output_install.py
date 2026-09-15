# -*- coding: utf-8 -*-
"""Typed install state for direct Dolby Vision remux outputs."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DVOutputInstallResult:
    """Durable state after the DV video install step.

    ``committed`` protects an installed destination from incomplete-output
    cleanup. ``preserved`` marks an intentional Archiv/ result. Iteration keeps
    the historical ``ok, path = result`` adapter contract alive.
    """

    ok: bool
    output_path: str
    committed: bool = False
    preserved: bool = False
    cleanup_pending: bool = False
    cleanup_message: str = ""
    backup_path: str | None = None

    def __iter__(self):
        yield self.ok
        yield self.output_path

    @classmethod
    def from_value(cls, value) -> "DVOutputInstallResult":
        if isinstance(value, cls):
            return value
        if isinstance(value, tuple) and len(value) >= 2:
            ok, output_path = value[:2]
            return cls(bool(ok), str(output_path), committed=bool(ok))
        raise TypeError(f"Ungültiges DV-Output-Commit-Ergebnis: {type(value).__name__}")


__all__ = ["DVOutputInstallResult"]
