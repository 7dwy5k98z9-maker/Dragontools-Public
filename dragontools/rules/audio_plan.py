# -*- coding: utf-8 -*-
"""
dragontools/rules/audio_plan.py

Zentrale, reine Entscheidungsfunktion für die Audio-Spurwahl.

Zweck
=====
Die gleiche fachliche Audio-Entscheidung wurde bisher dreimal parallel
implementiert:

  - core/rules_preview.py : _build_audio_preview()       (Preview-Dict)
  - worker/converter_stream_args.py : audio_args()       (ffmpeg-Args)
  - worker/dv_audio_mux_service.py : build_audio_meta()   (DV-Mux-Meta)

Diese Parallelimplementierungen sind driftanfaellig. Konkrete Drift:
Der DV-Pfad kannte bisher keinen ``fa == "aac"``-Branch, wodurch die DV-
Mux-Meta bei ``audio_mode=custom + audio_action=aac`` falsche Zielcodec-
Labels produzierte, obwohl die ffmpeg-Args über ``audio_args`` AAC
erzeugten.

Diese Funktion ist die *kleinste* gemeinsame Entscheidungsebene. Sie
formt keine ffmpeg-Args und keine MP4Box-Args und keine Preview-Dicts -
sie liefert nur pro ausgewähltem Audiostream den Entscheidungsvektor
(needs_transcode, target_codec, target_channels, target_bitrate).

Jeder der drei Konsumenten baut daraus seine jeweilige Ausgabeform.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.models import AudioStream, normalize_override_dict
from .audio_rules import (
    _load_rules as _load_audio_rules,
    clamp_audio_target_to_codec_cap,
    migrate_audio_rules,
    normalize_audio_codec,
    normalize_audio_processing_config,
    safe_float,
    safe_int,
)
from .audio_plan_policy import (
    MP4_COMPATIBLE_AUDIO_CODECS,
    build_custom_track_map,
    default_target_for_stream,
    resolve_track_transcode,
    select_streams_for_plan,
)


@dataclass(slots=True)
class AudioTrackDecision:
    """
    Eine Entscheidung pro ausgewähltem Audiostream.

    Felder:
      out_idx         : 0-basierter Mux-Index in der Zielreihenfolge
      stream          : der Quell-AudioStream
      needs_transcode : True wenn transkodiert wird, False bei Stream-Copy
      target_codec    : Zielcodec in Lowercase (bei copy: normalisierter
                        Quellcodec)
      target_channels : Kanalzahl nach ggf. Downmix (bei copy: unverändert)
      target_bitrate  : Zielbitrate in bps (bei copy: unverändert)
      is_extra_stereo : True wenn diese Spur ein Zusatz-Stereo-Downmix ist
      audio_filters   : Filter, die auf diese Audiospur angewendet werden
                        (z.B. loudnorm). Stereo-Downmix wird separat aus
                        target_channels abgeleitet.
      drc_scale       : AC3/EAC3-DRC-Wert. Wird als ffmpeg-Eingabeoption
                        vor -i gesetzt und erzwingt Re-Encode.
    """
    out_idx: int
    stream: AudioStream
    needs_transcode: bool
    target_codec: str
    target_channels: int
    target_bitrate: int
    is_extra_stereo: bool = False
    audio_filters: tuple[str, ...] = ()
    drc_scale: float | None = None
    processing_notes: tuple[str, ...] = ()


def needs_stereo_downmix_filter(decision: AudioTrackDecision) -> bool:
    """True wenn eine Mehrkanalspur beim Transkodieren auf Stereo reduziert wird."""
    return (
        decision.needs_transcode
        and safe_int(getattr(decision.stream, "channels", 0), 0) > 2
        and safe_int(decision.target_channels, 0) == 2
    )


def _fmt_filter_float(value: float) -> str:
    text = f"{float(value):.1f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _mode_enabled_from_override(raw: Any, default_enabled: bool) -> bool:
    if not isinstance(raw, dict):
        return default_enabled
    mode = str(raw.get("mode", "inherit") or "inherit").lower()
    if mode == "on":
        return True
    if mode == "off":
        return False
    return default_enabled


def _scale_from_override(raw: Any, default_value: float) -> float:
    if not isinstance(raw, dict):
        return default_value
    return round(max(0.0, min(4.0, safe_float(raw.get("scale"), default_value))), 1)


def _loudnorm_i_from_override(raw: Any, default_value: float) -> float:
    if not isinstance(raw, dict):
        return default_value
    return round(max(-40.0, min(-5.0, safe_float(raw.get("i"), default_value))), 1)


def effective_audio_processing(
    rules: dict[str, Any] | None,
    file_override: dict[str, Any] | None,
) -> dict[str, Any]:
    """Ermittelt DRC/Loudness inklusive per-Datei-Override."""
    base = normalize_audio_processing_config(rules)
    ov = normalize_override_dict(file_override)

    drc_raw = ov.get("audio_drc")
    loud_raw = ov.get("audio_loudnorm")
    return {
        "drc_enabled": _mode_enabled_from_override(drc_raw, bool(base["drc_enabled"])),
        "drc_scale": _scale_from_override(drc_raw, float(base["drc_scale"])),
        "loudnorm_enabled": _mode_enabled_from_override(loud_raw, bool(base["loudnorm_enabled"])),
        "loudnorm_i": _loudnorm_i_from_override(loud_raw, float(base["loudnorm_i"])),
        "loudnorm_lra": float(base["loudnorm_lra"]),
        "loudnorm_tp": float(base["loudnorm_tp"]),
    }


def _loudnorm_filter(processing: dict[str, Any]) -> str:
    return (
        "loudnorm="
        f"I={_fmt_filter_float(float(processing['loudnorm_i']))}:"
        f"LRA={_fmt_filter_float(float(processing['loudnorm_lra']))}:"
        f"TP={_fmt_filter_float(float(processing['loudnorm_tp']))}"
    )


def _processing_for_decision(
    chosen: AudioStream,
    processing: dict[str, Any],
) -> tuple[list[str], float | None, list[str]]:
    codec_norm = normalize_audio_codec(getattr(chosen, "codec", ""))
    filters: list[str] = []
    notes: list[str] = []
    drc_scale: float | None = None

    if bool(processing.get("drc_enabled")):
        if codec_norm in {"ac3", "eac3"}:
            drc_scale = float(processing.get("drc_scale", 1.0))
            notes.append(f"AC3/EAC3-DRC {drc_scale:.1f}")
        else:
            notes.append("DRC übersprungen: Quelle ist nicht AC3/EAC3")

    if bool(processing.get("loudnorm_enabled")):
        filters.append(_loudnorm_filter(processing))
        notes.append(f"Lautheitsnormalisierung {processing.get('loudnorm_i', -18.0):.1f} LUFS")

    return filters, drc_scale, notes


def audio_filter_chain(decision: AudioTrackDecision) -> str:
    """Gibt die kombinierte Filterchain für einen Audio-Output zurück."""
    filters: list[str] = []
    if needs_stereo_downmix_filter(decision):
        filters.append("aresample=matrix_encoding=dplii")
    filters.extend(decision.audio_filters)
    return ",".join(filters)


def audio_input_args_for_plan(plan: list[AudioTrackDecision]) -> list[str]:
    """Input-Argumente für ffmpeg, aktuell AC3/EAC3-DRC vor -i."""
    scales: list[float] = []
    for decision in plan:
        if decision.drc_scale is None:
            continue
        if decision.drc_scale not in scales:
            scales.append(float(decision.drc_scale))
    if not scales:
        return []
    return ["-drc_scale", f"{scales[0]:.1f}"]


def _build_track_decision(
    *,
    out_idx: int,
    stream: AudioStream,
    rules: dict[str, Any],
    processing: dict[str, Any],
    container: str,
    audio_mode: str,
    legacy_action: str,
    custom_entry: dict[str, Any] | None,
) -> AudioTrackDecision:
    needs, target = resolve_track_transcode(
        stream,
        rules,
        container=container,
        audio_mode=audio_mode,
        legacy_action=legacy_action,
        custom_entry=custom_entry,
    )
    filters, drc_scale, processing_notes = _processing_for_decision(stream, processing)
    if (filters or drc_scale is not None) and not needs:
        needs = True
        target = default_target_for_stream(stream, rules)

    if needs:
        target = clamp_audio_target_to_codec_cap(target, safe_int(stream.channels, 2))
        target_codec = str(target.get("codec") or "").lower()
        target_channels = safe_int(target.get("channels"), safe_int(stream.channels, 2))
        target_bitrate = safe_int(target.get("bitrate"), 0)
    else:
        target_codec = normalize_audio_codec(stream.codec)
        target_channels = safe_int(stream.channels, 2)
        target_bitrate = safe_int(stream.bitrate, 0)

    return AudioTrackDecision(
        out_idx=out_idx,
        stream=stream,
        needs_transcode=needs,
        target_codec=target_codec,
        target_channels=target_channels,
        target_bitrate=target_bitrate,
        audio_filters=tuple(filters),
        drc_scale=drc_scale,
        processing_notes=tuple(processing_notes),
    )


def _extra_stereo_decisions(
    plan: list[AudioTrackDecision],
    *,
    rules: dict[str, Any],
    processing: dict[str, Any],
) -> list[AudioTrackDecision]:
    if not rules.get("extra_stereo", False):
        return []

    stereo_codec = normalize_audio_codec(str(rules.get("extra_stereo_codec", "aac") or "aac"))
    if stereo_codec not in {"aac", "eac3", "ac3"}:
        stereo_codec = "aac"
    stereo_bitrate = safe_int(rules.get("extra_stereo_bitrate_k", 256), 256) * 1000

    decisions: list[AudioTrackDecision] = []
    for decision in plan:
        if decision.target_channels <= 2:
            continue
        filters, drc_scale, processing_notes = _processing_for_decision(decision.stream, processing)
        decisions.append(
            AudioTrackDecision(
                out_idx=len(plan) + len(decisions),
                stream=decision.stream,
                needs_transcode=True,
                target_codec=stereo_codec,
                target_channels=2,
                target_bitrate=stereo_bitrate,
                is_extra_stereo=True,
                audio_filters=tuple(filters),
                drc_scale=drc_scale,
                processing_notes=tuple(processing_notes),
            )
        )
    return decisions


def compute_audio_track_plan(
    audio_streams: list[AudioStream],
    file_override: dict[str, Any] | None,
    container: str,
    rules: dict[str, Any] | None = None,
    *,
    apply_language_rules: bool = True,
) -> list[AudioTrackDecision]:
    """Build audio decisions in mux order from rules and per-file overrides."""
    override = normalize_override_dict(file_override)
    audio_rules = migrate_audio_rules(rules) if rules is not None else _load_audio_rules()
    processing = effective_audio_processing(audio_rules, override)
    legacy_action = ((override.get("_legacy") or {}).get("audio_action") or "auto")
    audio_mode = override.get("audio_mode", "auto")

    custom_track_map = build_custom_track_map(override, audio_mode=audio_mode)
    chosen_streams = select_streams_for_plan(
        audio_streams,
        audio_rules,
        audio_mode=audio_mode,
        custom_track_map=custom_track_map,
        apply_language_rules=apply_language_rules,
    )
    plan = [
        _build_track_decision(
            out_idx=out_idx,
            stream=stream,
            rules=audio_rules,
            processing=processing,
            container=container,
            audio_mode=audio_mode,
            legacy_action=legacy_action,
            custom_entry=custom_track_map.get(int(stream.index)),
        )
        for out_idx, stream in enumerate(chosen_streams)
    ]
    plan.extend(_extra_stereo_decisions(plan, rules=audio_rules, processing=processing))
    return plan
