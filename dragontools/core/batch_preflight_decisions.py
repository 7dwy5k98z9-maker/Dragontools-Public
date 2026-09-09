from __future__ import annotations

from pathlib import Path
from typing import Any

from .batch_preflight_formatting import _bitrate_label, _channel_label, _stream_list_label, _text, _value

OLD_CONTAINER_EXTENSIONS = {
    ".avi", ".divx", ".flv", ".m2ts", ".mpeg", ".mpg", ".mts", ".ogm", ".ts", ".vob", ".wmv",
}

def _decision_reasons(preview: dict[str, Any], fs_info: dict[str, Any] | None = None) -> list[str]:
    reasons: list[str] = []
    pipeline = str(_value(preview.get("pipeline") or "standard")).lower()
    container = _text(preview.get("target_container"), "?")
    source_codec = _text(preview.get("source_codec"), "?").upper()

    if pipeline == "dv":
        reasons.append(
            f"Pipeline: Dolby Vision wird erhalten; deshalb Sonderpfad DV -> .{container}."
        )
    elif pipeline == "av1_dv":
        reasons.append(
            f"Pipeline: AV1 Dolby Vision Profile 10 (Beta) -> .{container}."
        )
    elif pipeline == "hdrplus":
        reasons.append(
            f"Pipeline: HDR10+ wird erhalten; deshalb Sonderpfad HDR10+ -> .{container}."
        )
    elif pipeline == "av1_hdrplus":
        reasons.append(
            f"Pipeline: AV1 HDR10+ (Beta) -> .{container}."
        )
    else:
        reasons.append(
            f"Pipeline: Standardpfad -> .{container} (Quellcodec {source_codec})."
        )

    overrides = dict(preview.get("overrides") or {})
    manual_encoder = overrides.get("encoder_override")
    if isinstance(manual_encoder, dict):
        encoder = _text(manual_encoder.get("encoder"), "?").upper()
        quality = manual_encoder.get("quality", manual_encoder.get("crf"))
        scale = _text(manual_encoder.get("scale_mode") or manual_encoder.get("scale"), "original")
        q_label = {"NVENC": "CQ", "QSV": "Q", "AMF": "QP"}.get(encoder, "CRF")
        quality_text = f", {q_label} {quality}" if quality is not None else ""
        reasons.append(f"Override: Encoder/Skalierung = {encoder}{quality_text}, {scale}.")

    ignored_hdr = set(str(v).lower() for v in preview.get("ignored_hdr") or [])
    if "dv" in ignored_hdr:
        reasons.append("HDR/DV: Dolby Vision wurde erkannt, kann in diesem Pfad aber nicht erhalten werden.")
    if "hdr10plus" in ignored_hdr:
        reasons.append("HDR/DV: HDR10+ wurde erkannt, kann in diesem Pfad aber nicht erhalten werden.")

    audio = dict(preview.get("audio") or {})
    selected_audio = [dict(entry) for entry in audio.get("selected_streams") or []]
    if not selected_audio:
        if int(audio.get("source_count") or 0) > 0:
            reasons.append("Audio: Keine Spur ausgewählt, weil die Audioregeln keinen Treffer liefern.")
        else:
            reasons.append("Audio: Keine Audiospur in der Quelle erkannt.")
    else:
        mode = _text(audio.get("override_mode"), "auto")
        prefix = "Datei-Override" if mode == "custom" else "Audioregel"
        for entry in selected_audio[:4]:
            lang = _text(entry.get("language"), "und")
            source = (
                f"Audio #{_text(entry.get('index'), '?')}: {lang}, "
                f"{_text(entry.get('source_codec'), '?')} {_channel_label(entry.get('source_channels'))}"
            )
            if entry.get("decision") == "copy":
                bitrate = _bitrate_label(entry.get("source_bitrate"))
                suffix = f", {bitrate}" if bitrate else ""
                reasons.append(f"{prefix}: {source}{suffix} wird kopiert.")
            else:
                bitrate = _bitrate_label(entry.get("target_bitrate"))
                suffix = f" {bitrate}" if bitrate else ""
                target = (
                    f"{_text(entry.get('target_codec'), '?').upper()} "
                    f"{_channel_label(entry.get('target_channels'))}{suffix}"
                )
                extra = " als zusätzlicher Stereo-Downmix" if entry.get("is_extra_stereo") else ""
                reasons.append(f"{prefix}: {source} wird zu {target} konvertiert{extra}.")
        remaining_audio = len(selected_audio) - 4
        if remaining_audio > 0:
            reasons.append(f"Audio: +{remaining_audio} weitere ausgewählte Spur(en).")

    subs = dict(preview.get("subtitles") or {})
    subtitle_source_count = int(subs.get("source_count") or 0)
    if subtitle_source_count <= 0:
        reasons.append("Untertitel: Keine Untertitelquelle erkannt.")
    else:
        sub_prefix = "Datei-Override" if subs.get("override_mode") == "custom" else "Untertitelregel"
        burn = dict(subs.get("burn_candidate") or {}) if subs.get("burn_in") else {}
        if burn:
            reasons.append(
                f"{sub_prefix}: Burn-in gewinnt mit #{_text(burn.get('index'), '?')} "
                f"{_text(burn.get('language'), 'und')}/{_text(burn.get('codec'), '?')}"
                f"{' forced' if burn.get('forced') else ''}."
            )
        else:
            blocked = str(subs.get("burn_blocked_reason") or "")
            if blocked == "ambiguous":
                reasons.append("Untertitelregel: Forced-Burn-In bleibt offen, weil mehrere gleich gute Kandidaten existieren.")
            elif blocked == "auto_burn_disabled":
                reasons.append("Untertitelregel: automatischer Forced-Burn-In ist deaktiviert.")
            elif blocked == "no_audio_for_burn_language":
                reasons.append("Untertitelregel: kein Burn-in, weil keine passende Audio-Sprache vorhanden ist.")
            else:
                reasons.append("Untertitelregel: kein Burn-in-Kandidat gewählt.")

        if not subs.get("container_copy_supported", True):
            candidates = [dict(entry) for entry in subs.get("external_export_candidates") or []]
            if subs.get("external_export_enabled", True):
                reasons.append(
                    "Untertitel: Zielcontainer übernimmt Untertitel nicht intern; "
                    f"externe Sidecars: {_stream_list_label(candidates)}."
                )
            else:
                reasons.append("Untertitel: externe Sidecars sind für diesen Pfad deaktiviert.")
        else:
            candidates = [dict(entry) for entry in subs.get("stream_copy_candidates") or []]
            if candidates:
                reasons.append(
                    "Untertitelregel: Stream-Copy nach Sprache/Format/Limit: "
                    f"{_stream_list_label(candidates)}."
                )
            else:
                reasons.append("Untertitelregel: keine kompatiblen Untertitel zum Kopieren ausgewählt.")

    overrides = dict(preview.get("overrides") or {})
    if overrides.get("processing_mode") == "strip_only":
        reasons.append(
            "Override: Diese Datei nutzt Strip-Only; Video wird per Stream-Copy "
            "übernommen, Audio und Untertitel folgen den Strip-Only-Regeln."
        )
    profile = overrides.get("encoder_profile")
    if isinstance(profile, dict):
        label = _text(profile.get("label") or profile.get("key"), "")
        if label:
            reasons.append(f"Profil: Datei nutzt Encoder-Profil '{label}'.")
    if overrides.get("audio_mode") == "custom":
        reasons.append("Override: Audioentscheidung kommt aus der Datei-Einstellung.")
    if overrides.get("subtitle_mode") == "custom":
        reasons.append("Override: Untertitelentscheidung kommt aus der Datei-Einstellung.")

    move = dict(preview.get("move") or {})
    planned = _text(move.get("planned_target"), "")
    if planned:
        reasons.append(f"Verschieben: Zielordner ist geplant: {planned}")
    fs_info = fs_info or {}
    final_path = _text(fs_info.get("final_output_path") or fs_info.get("output_path"), "")
    if final_path:
        reasons.append(f"Ausgabe: geplante Datei {Path(final_path).name}.")

    return reasons


def _warnings_for(path: str, preview: dict[str, Any]) -> tuple[list[str], bool]:
    warnings: list[str] = []
    error = False

    warnings.extend(str(w) for w in preview.get("analysis_warnings") or [] if w)
    overrides = dict(preview.get("overrides") or {})
    warnings.extend(str(w) for w in overrides.get("_warnings") or [] if w)

    video = dict(preview.get("video") or {})
    if not video.get("available", True):
        warnings.append("Kein Videostream erkannt.")
        error = True

    audio = dict(preview.get("audio") or {})
    audio_source_count = int(audio.get("source_count") or 0)
    audio_selection_count = int(audio.get("selection_count") or 0)
    if audio_source_count <= 0:
        warnings.append("Keine Audioquelle erkannt.")
    elif audio_selection_count <= 0:
        warnings.append("Audioregeln wählen keine Spur aus.")

    archive_reason = preview.get("archive_reason")
    if archive_reason:
        warnings.append(str(archive_reason))

    ignored_hdr = set(str(v).lower() for v in preview.get("ignored_hdr") or [])
    source_codec = _text(preview.get("source_codec"), "unbekannt").upper()
    if "dv" in ignored_hdr:
        warnings.append(f"Dolby Vision wird mit Quellcodec {source_codec} nicht erhalten.")
    if "hdr10plus" in ignored_hdr:
        warnings.append(f"HDR10+ wird mit Quellcodec {source_codec} nicht erhalten.")

    subs = dict(preview.get("subtitles") or {})
    if subs.get("burn_blocked_reason") == "ambiguous":
        warnings.append("Forced-Burn-In ist mehrdeutig und wird nicht automatisch gewählt.")
    if subs.get("burn_blocked_reason") == "forced_full_sub_suspected":
        warnings.append(
            "Forced-Burn-In wurde wegen Full-Sub-Verdacht blockiert; "
            "die Spur wird zusätzlich behalten/exportiert."
        )
    for warning in list(subs.get("burn_warnings") or []):
        warnings.append(str(warning))

    warnings.extend(_strip_only_warnings(preview))

    suffix = Path(path).suffix.lower()
    if suffix in OLD_CONTAINER_EXTENSIONS:
        warnings.append(f"Altes/empfindliches Quellformat erkannt ({suffix}).")

    return warnings, error


def _strip_only_warnings(preview: dict[str, Any]) -> list[str]:
    overrides = dict(preview.get("overrides") or {})
    if overrides.get("processing_mode") != "strip_only":
        return []

    warnings: list[str] = []
    video = dict(preview.get("video") or {})
    container = _text(preview.get("target_container"), "mkv").lower()
    subs = dict(preview.get("subtitles") or {})

    if video.get("has_dv"):
        warnings.append(
            "Strip-Only: Dolby Vision wird nur als vorhandener Videostream übernommen; "
            "keine DV-Profilkonvertierung, kein RPU-Editor und keine neue DV-Injection."
        )
    if video.get("has_hdr10plus"):
        warnings.append(
            "Strip-Only: HDR10+ wird nur als vorhandener Videostream übernommen; "
            "keine HDR10+-Extraktion oder neue Metadaten-Injection."
        )
    if container == "mp4" and int(subs.get("source_count") or 0) > 0:
        warnings.append(
            "Strip-Only + MP4: interne Untertitel sind je nach Format nicht MP4-kompatibel "
            "(z. B. PGS/ASS/VobSub). Bei Fehlern MKV oder externe Untertitel nutzen."
        )
    if subs.get("burn_in"):
        warnings.append(
            "Strip-Only: Burn-In ist nicht möglich; ein gewählter Forced-Untertitel "
            "wird als Untertitelspur übernommen."
        )

    return warnings
