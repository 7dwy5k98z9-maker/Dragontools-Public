# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class EncoderOverrideApplyResult:
    applied: int = 0
    rejected: list[str] = field(default_factory=list)


def apply_encoder_override(owner, paths: list[str], encoder_value: dict | None) -> EncoderOverrideApplyResult:
    result = EncoderOverrideApplyResult()
    for path in paths:
        override = dict(owner._state.file_overrides.get(path) or {})
        if encoder_value is None:
            override.pop("encoder_override", None)
        else:
            override["encoder_override"] = dict(encoder_value)

        thread = owner._state.thread
        if thread and hasattr(thread, "update_override") and not thread.update_override(path, override):
            result.rejected.append(path)
            continue

        owner._state.file_overrides[path] = override
        getattr(owner._state, "preflight_rows_by_path", {}).pop(path, None)
        owner.update_queue_label(path)
        result.applied += 1
    return result
