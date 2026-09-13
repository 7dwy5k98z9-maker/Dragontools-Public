from __future__ import annotations

from typing import Any

from ..rules.audio_rules import normalize_audio_codec
from ..rules.audio_plan import compute_audio_track_plan
from .rules_preview_common import lang


def build_audio_preview(mi, ov: dict[str, Any], container: str) -> dict[str, Any]:
    """Preview der Audioentscheidung über denselben Kern wie die Worker."""
    audio_mode = ov.get("audio_mode", "auto")
    fa = ((ov.get("_legacy") or {}).get("audio_action") or "auto")
    plan = compute_audio_track_plan(
        audio_streams=mi.audio_streams,
        file_override=ov,
        container=container,
    )

    result: list[dict[str, Any]] = []
    for decision in plan:
        chosen = decision.stream
        result.append({
            "index": chosen.index,
            "language": lang(chosen.language),
            "title": chosen.title,
            "source_codec": normalize_audio_codec(chosen.codec),
            "source_channels": chosen.channels,
            "source_bitrate": chosen.bitrate,
            "decision": "transcode" if decision.needs_transcode else "copy",
            "target_codec": decision.target_codec,
            "target_channels": decision.target_channels,
            "target_bitrate": decision.target_bitrate,
            "is_extra_stereo": decision.is_extra_stereo,
        })

    return {
        "override_mode": audio_mode,
        "override_action": fa if audio_mode == "custom" and not ov.get("audio_tracks") else "auto",
        "source_count": len(mi.audio_streams),
        "selected_streams": result,
        "selection_count": len(result),
        "disabled": not bool(result),
    }
