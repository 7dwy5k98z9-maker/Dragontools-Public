# -*- coding: utf-8 -*-
"""Preserve completed outputs that fail final verification."""
from __future__ import annotations

import csv
import errno
import os
import shutil
from pathlib import Path


def _unique_archive_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    index = 1
    while True:
        candidate = directory / f"{stem}_{index:03d}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _cross_volume_preserve(output: Path, target: Path) -> None:
    """Copy safely when an atomic move cannot cross filesystem boundaries."""
    staging = target.with_name(f".{target.name}.archiving-{os.getpid()}.part")
    counter = 1
    while staging.exists():
        staging = target.with_name(
            f".{target.name}.archiving-{os.getpid()}-{counter:03d}.part"
        )
        counter += 1
    try:
        shutil.copy2(str(output), str(staging))
        if staging.stat().st_size != output.stat().st_size:
            raise OSError(
                "Archivkopie hat eine abweichende Dateigroesse "
                f"({staging.stat().st_size} != {output.stat().st_size})"
            )
        os.replace(str(staging), str(target))
        try:
            output.unlink()
        except OSError:
            # The archive is already durable. Keeping the original duplicate is safer
            # than treating the preservation itself as failed.
            pass
    finally:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass


def preserve_failed_verification_output(ctx, result, *, logger) -> str | None:
    """Archive an invalid completed output and never let generic cleanup delete it.

    Verification failures are evidence that an output needs inspection, not proof
    that the produced bytes are disposable. The candidate is moved to ``Archiv``
    next to the source when possible. If that move cannot be completed, the
    candidate remains at its working path and ``keep_failed_output`` protects it.
    """
    output_raw = str(getattr(ctx, "output_path", "") or "")
    if not output_raw:
        return None
    output = Path(output_raw)
    if not output.exists() or output.is_dir():
        return None

    # Set this before any filesystem operation: even an archive failure must not let
    # CleanupService delete the diagnostic candidate afterwards.
    ctx.keep_failed_output = True
    source_raw = str(getattr(ctx, "input_path", "") or "")
    if not source_raw:
        return None

    source = Path(source_raw)
    archive_dir = source.parent / "Archiv"
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = _unique_archive_path(archive_dir, output.name)
        try:
            os.replace(str(output), str(target))
        except OSError as exc:
            if exc.errno not in {errno.EXDEV, errno.EACCES, errno.EPERM}:
                raise
            _cross_volume_preserve(output, target)

        ctx.verification_archive_path = str(target)
        message = f"Fehlerhafte Ausgabedatei wurde archiviert: {target}"
        messages = list(getattr(result, "messages", []) or [])
        if message not in messages:
            messages.append(message)
            result.messages = messages
        logger.warn(message)
        return str(target)
    except Exception as exc:
        message = (
            "Archivierung der fehlerhaften Ausgabedatei fehlgeschlagen; "
            f"die Datei bleibt erhalten: {output} ({exc})"
        )
        messages = list(getattr(result, "messages", []) or [])
        if message not in messages:
            messages.append(message)
            result.messages = messages
        logger.warn(message)
        return None


def _rpu_geometry_diagnostics(ctx, result) -> dict[str, object]:
    """Build final RPU/video geometry facts for archive reports.

    When the final video differs from the normalized target, Level-5 Active Area
    is considered geometrically plausible if it matches either the normalized
    target geometry or the actual final video geometry. A bytewise RPU hash
    mismatch is diagnostic only.
    """
    expected_w = getattr(result, "expected_width", None)
    expected_h = getattr(result, "expected_height", None)
    actual_w = getattr(result, "actual_width", None)
    actual_h = getattr(result, "actual_height", None)
    offsets = tuple(getattr(ctx, "pipeline_final_rpu_level5_offsets", ()) or ())

    allowed: list[tuple[int, int]] = []
    for width, height in ((expected_w, expected_h), (actual_w, actual_h)):
        try:
            pair = (int(width), int(height))
        except (TypeError, ValueError):
            continue
        if pair[0] > 0 and pair[1] > 0 and pair not in allowed:
            allowed.append(pair)

    expected_pair = None
    actual_pair = None
    try:
        if expected_w and expected_h:
            expected_pair = (int(expected_w), int(expected_h))
    except (TypeError, ValueError):
        expected_pair = None
    try:
        if actual_w and actual_h:
            actual_pair = (int(actual_w), int(actual_h))
    except (TypeError, ValueError):
        actual_pair = None

    rows: list[dict[str, object]] = []
    max_delta = None
    accepted = None
    if actual_w and actual_h and offsets:
        deltas: list[int] = []
        area_acceptance: list[bool] = []
        for index, values in enumerate(offsets, start=1):
            left, right, top, bottom = (int(v) for v in values)
            active_w = int(actual_w) - left - right
            active_h = int(actual_h) - top - bottom
            delta_w = left + right
            delta_h = top + bottom
            delta = max(delta_w, delta_h)
            active = (active_w, active_h)
            is_allowed = active in allowed
            if is_allowed and expected_pair is not None and active == expected_pair:
                match = "Soll-Geometrie"
            elif is_allowed and actual_pair is not None and active == actual_pair:
                match = "Ist-Geometrie"
            elif is_allowed:
                match = "zulaessige Geometrie"
            else:
                match = "keine zulaessige Soll-/Ist-Geometrie"
            deltas.append(delta)
            area_acceptance.append(is_allowed)
            rows.append({
                "index": index,
                "left": left,
                "right": right,
                "top": top,
                "bottom": bottom,
                "active_width": active_w,
                "active_height": active_h,
                "delta_width": delta_w,
                "delta_height": delta_h,
                "max_delta": delta,
                "accepted": is_allowed,
                "match": match,
            })
        max_delta = max(deltas, default=0)
        accepted = bool(area_acceptance) and all(area_acceptance)

    dynamic = bool(getattr(ctx, "pipeline_final_rpu_level5_dynamic", False) or len(offsets) > 1)
    allowed_text = " oder ".join(f"{w}x{h}" for w, h in allowed) or "unbekannt"
    if not offsets:
        status = "unbekannt"
        recommendation = (
            "RPU-Level-5 konnte nicht automatisch ausgewertet werden. RPU manuell exportieren "
            f"und Active-Area gegen die zulaessigen Geometrien {allowed_text} vergleichen."
        )
    elif accepted is True:
        status = "rpu_geometrie_passt_zu_soll_oder_ist"
        recommendation = (
            f"RPU-Level-5 ist geometrisch plausibel. Zulaessig sind {allowed_text}; "
            "ein abweichender RPU-Hash allein ist kein Fehler."
        )
    else:
        status = "rpu_geometrie_passt_nicht_zu_soll_oder_ist"
        recommendation = (
            f"RPU-Active-Area passt nicht zu {allowed_text}. Kandidat behalten und vor manueller "
            "Uebernahme Level 5 nachcroppen/erweitern oder die Video-Geometrie korrigieren."
        )
    return {
        "offsets": offsets,
        "rows": rows,
        "dynamic": dynamic,
        "max_delta": max_delta,
        "accepted": accepted,
        "allowed": tuple(allowed),
        "allowed_text": allowed_text,
        "status": status,
        "recommendation": recommendation,
    }


def write_verification_archive_csv(
    ctx,
    result,
    *,
    archived_path: str | Path,
    postprocess_paths: list[str] | None = None,
) -> str | None:
    """Write machine-readable geometry/RPU diagnostics next to an archived video."""
    video = Path(archived_path)
    if not video.exists():
        return None

    report = video.with_name(f"{video.stem} - VALIDIERUNG.csv")
    source = Path(str(getattr(ctx, "input_path", "") or ""))
    expected_w = getattr(result, "expected_width", None)
    expected_h = getattr(result, "expected_height", None)
    actual_w = getattr(result, "actual_width", None)
    actual_h = getattr(result, "actual_height", None)
    delta_w = abs(int(actual_w) - int(expected_w)) if actual_w and expected_w else None
    delta_h = abs(int(actual_h) - int(expected_h)) if actual_h and expected_h else None
    max_delta = int(getattr(result, "geometry_max_delta", 0) or 0)
    rpu = _rpu_geometry_diagnostics(ctx, result)
    matches = getattr(ctx, "pipeline_final_rpu_matches_injected", None)
    rpu_present = bool(getattr(ctx, "pipeline_final_rpu_present", False))
    rpu_checked = bool(getattr(ctx, "pipeline_final_rpu_checked", False))

    rows: list[tuple[str, str, object, str]] = [
        ("Datei", "Quelle", source, ""),
        ("Datei", "Archivierte_Datei", video, ""),
        ("Workflow", "Pipeline", str(getattr(getattr(ctx, "pipeline", ""), "value", getattr(ctx, "pipeline", "")) or ""), ""),
        ("Workflow", "Validierungsstufe", str(getattr(ctx, "verification_archive_tier", "") or ""), ""),
        ("Workflow", "Grund", str(getattr(ctx, "verification_archive_reason", "") or ""), ""),
        ("Workflow", "Original_ersetzt", "NEIN", "Archivfall: Original bleibt unangetastet"),
        ("Video", "Normalisierter_Crop", str(getattr(ctx, "effective_crop_filter", "") or ""), "FFmpeg crop-Filter"),
        ("Video", "Soll_Breite", expected_w or "", "Pixel"),
        ("Video", "Soll_Hoehe", expected_h or "", "Pixel"),
        ("Video", "Ist_Breite", actual_w or "", "Pixel"),
        ("Video", "Ist_Hoehe", actual_h or "", "Pixel"),
        ("Video", "Delta_Breite", delta_w if delta_w is not None else "", "Pixel"),
        ("Video", "Delta_Hoehe", delta_h if delta_h is not None else "", "Pixel"),
        ("Video", "Delta_Max", max_delta, "Pixel"),
        ("RPU", "Final_geprueft", "JA" if rpu_checked else "NEIN", ""),
        ("RPU", "Final_vorhanden", "JA" if rpu_present else "NEIN", ""),
        ("RPU", "Hash_identisch_zur_injizierten_RPU", "JA" if matches is True else "NEIN" if matches is False else "n/a", ""),
        ("RPU", "SHA256_geplant_injiziert", str(getattr(ctx, "pipeline_final_rpu_expected_sha256", "") or ""), ""),
        ("RPU", "SHA256_final_extrahiert", str(getattr(ctx, "pipeline_final_rpu_actual_sha256", "") or ""), ""),
        ("RPU", "Level5_dynamisch", "JA" if rpu["dynamic"] else "NEIN", ""),
        ("RPU", "Zulaessige_Active_Area_Geometrien", rpu["allowed_text"], "Soll oder finales Video"),
        ("RPU", "Geometrie_akzeptiert", "JA" if rpu["accepted"] is True else "NEIN" if rpu["accepted"] is False else "n/a", ""),
        ("RPU", "Match_Modus", str(getattr(ctx, "dv_rpu_alignment_match_mode", "") or ""), ""),
        ("RPU", "RPU_Video_Max_Delta", rpu["max_delta"] if rpu["max_delta"] is not None else "", "Pixel"),
        ("RPU", "Geometrie_Status", rpu["status"], ""),
        ("RPU", "Automatische_Diagnose", str(getattr(ctx, "dv_rpu_alignment_message", "") or getattr(ctx, "pipeline_final_rpu_message", "") or ""), ""),
        ("RPU", "Empfehlung", rpu["recommendation"], ""),
    ]
    for item in rpu["rows"]:
        idx = item["index"]
        rows.extend([
            ("RPU_Level5", f"Area_{idx}_Offsets", f"L={item['left']},R={item['right']},T={item['top']},B={item['bottom']}", "Pixel"),
            ("RPU_Level5", f"Area_{idx}_Aktive_Breite", item["active_width"], "Pixel"),
            ("RPU_Level5", f"Area_{idx}_Aktive_Hoehe", item["active_height"], "Pixel"),
            ("RPU_Level5", f"Area_{idx}_Match", item["match"], ""),
            ("RPU_Level5", f"Area_{idx}_Akzeptiert", "JA" if item["accepted"] else "NEIN", ""),
            ("RPU_Level5", f"Area_{idx}_Delta_Breite_zum_Video", item["delta_width"], "Pixel"),
            ("RPU_Level5", f"Area_{idx}_Delta_Hoehe_zum_Video", item["delta_height"], "Pixel"),
        ])

    hevc = video.with_name(f"{video.stem} - RPU_CHECK.hevc")
    rpu_file = video.with_name(f"{video.stem} - RPU_CHECK.rpu")
    level5 = video.with_name(f"{video.stem} - RPU_CHECK_level5.json")
    bitstream_filter = " -bsf:v hevc_mp4toannexb" if video.suffix.lower() in {".mp4", ".mov", ".m4v"} else ""
    rows.extend([
        ("Anweisung", "1_ffprobe", f'ffprobe -v error -select_streams v:0 -show_entries stream=width,height,pix_fmt -of default=nw=1 "{video}"', "Videogeometrie prüfen"),
        ("Anweisung", "2_HEVC_extrahieren", f'ffmpeg -y -v error -i "{video}" -map 0:v:0 -c:v copy{bitstream_filter} -an -sn -dn -f hevc "{hevc}"', ""),
        ("Anweisung", "3_RPU_extrahieren", f'dovi_tool extract-rpu -i "{hevc}" -o "{rpu_file}"', ""),
        ("Anweisung", "4_Level5_exportieren", f'dovi_tool export -i "{rpu_file}" -d "level5={level5}"', "Fallback: --data statt -d"),
        ("Anweisung", "5_RPU_gegen_Soll_und_Ist", "aktive Breite = Video-Breite - left - right; aktive Hoehe = Video-Hoehe - top - bottom", f"Akzeptiert: {rpu['allowed_text']}"),
        ("Anweisung", "6_Entscheidung", "Wenn die RPU-Active-Area weder der normalisierten Soll-Geometrie noch der finalen Video-Geometrie entspricht, Kandidat im Archiv behalten und Level 5 nachcroppen/erweitern bzw. Video/Crop korrigieren.", "Ein anderer RPU-Hash allein ist kein Fehler"),
    ])
    for path in [str(path) for path in (postprocess_paths or []) if path]:
        rows.append(("Begleitdaten", "Erzeugt", path, "NFO/Trickplay/Sidecar"))
    for message in list(getattr(result, "warnings", None) or []) + list(getattr(result, "messages", None) or []):
        if message:
            rows.append(("Meldung", "Validierung", str(message), ""))

    with report.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["Kategorie", "Feld", "Wert", "Einheit_Hinweis"])
        writer.writerows(rows)
    ctx.verification_csv_path = str(report)
    return str(report)


def write_verification_archive_report(
    ctx,
    result,
    *,
    archived_path: str | Path,
    postprocess_paths: list[str] | None = None,
) -> str | None:
    """Write a human-readable diagnostic/readme next to an archived candidate."""
    video = Path(archived_path)
    if not video.exists():
        return None

    report = video.with_name(f"{video.stem} - VALIDIERUNG.txt")
    source = Path(str(getattr(ctx, "input_path", "") or ""))
    expected_w = getattr(result, "expected_width", None)
    expected_h = getattr(result, "expected_height", None)
    actual_w = getattr(result, "actual_width", None)
    actual_h = getattr(result, "actual_height", None)
    delta = int(getattr(result, "geometry_max_delta", 0) or 0)
    tier = str(getattr(ctx, "verification_archive_tier", "") or "")
    reason = str(getattr(ctx, "verification_archive_reason", "") or "")
    rpu_checked = bool(getattr(ctx, "dv_rpu_alignment_checked", False))
    rpu_ok = getattr(ctx, "dv_rpu_alignment_ok", None)
    rpu_message = str(getattr(ctx, "dv_rpu_alignment_message", "") or "")
    crop_filter = str(getattr(ctx, "effective_crop_filter", "") or "")
    pipeline = str(getattr(getattr(ctx, "pipeline", ""), "value", getattr(ctx, "pipeline", "")) or "")

    if delta <= 2:
        recommendation = (
            "Die Videoabweichung liegt innerhalb der tolerierten 1-2 Pixel. Bei Dolby Vision "
            "wird nur in diesem Abweichungsfall Level 5 bewertet: die RPU-Active-Area darf "
            "entweder der normalisierten Soll-Geometrie oder der tatsaechlichen finalen "
            "Video-Geometrie entsprechen."
        )
    elif delta <= 4:
        recommendation = (
            "Die Abweichung liegt im manuellen Pruefbereich von 3-4 Pixeln. DragonTools "
            "ersetzt das Original bewusst nicht. Wiedergabe, Crop und bei DV die RPU sollten "
            "vor einer manuellen Uebernahme kontrolliert werden."
        )
    else:
        recommendation = (
            "Die Abweichung ist groesser als 4 Pixel. Der Kandidat sollte nicht automatisch "
            "uebernommen werden. Crop-/Scale-Kette und Quelle zuerst pruefen."
        )

    lines = [
        "DragonTools - Archivierte Ausgabe nach Geometrievalidierung",
        "=" * 68,
        "",
        f"Quelle: {source}",
        f"Archivierte Datei: {video}",
        f"CSV-Diagnose: {video.with_name(f'{video.stem} - VALIDIERUNG.csv')}",
        f"Pipeline: {pipeline or '<unbekannt>'}",
        f"Normalisierter Crop: {crop_filter or '<kein physischer Crop>'}",
        f"Erwartete Geometrie: {expected_w or '?'}x{expected_h or '?'}",
        f"Gefundene Geometrie: {actual_w or '?'}x{actual_h or '?'}",
        f"Maximale Abweichung: {delta} Pixel",
        f"Validierungsstufe: {tier or '<unbekannt>'}",
        f"Grund: {reason or '<nicht angegeben>'}",
        "",
        "Dolby-Vision-RPU-Pruefung",
        "-" * 28,
        f"Automatisch geprueft: {'JA' if rpu_checked else 'NEIN / nicht erforderlich'}",
        f"Automatisches Ergebnis: {('OK' if rpu_ok is True else 'NICHT OK' if rpu_ok is False else 'n/a')}",
        f"Details: {rpu_message or 'Keine zusaetzliche RPU-Pruefung protokolliert.'}",
        "",
        "Bewertung",
        "-" * 10,
        recommendation,
        "",
        "Manuelle Geometriepruefung",
        "-" * 28,
        "1. Finale Videogeometrie mit ffprobe kontrollieren:",
        f'   ffprobe -v error -select_streams v:0 -show_entries stream=width,height,pix_fmt -of default=nw=1 "{video}"',
        "2. Die angezeigte Breite/Hoehe mit 'Erwartete Geometrie' oben vergleichen.",
        "3. Bei 3-4 Pixel Abweichung das Bild an mehreren Stellen visuell auf abgeschnittene",
        "   Kanten oder sichtbare Balken pruefen. Bei >4 Pixeln zuerst die Crop-/Scale-Kette",
        "   im DragonTools-Log kontrollieren.",
        "",
        "Manuelle Dolby-Vision-RPU-Pruefung bei Video-Geometrieabweichung",
        "-" * 62,
        "Wenn die finale Video-Geometrie vom normalisierten Soll abweicht, sind zwei",
        "Level-5-Zustaende zulaessig: Die RPU-Active-Area entspricht entweder dem",
        "urspruenglichen Soll-Crop oder der tatsaechlichen finalen Video-Geometrie.",
        "Ein abweichender RPU-Hash allein ist dabei kein Fehler.",
    ]

    hevc = video.with_name(f"{video.stem} - RPU_CHECK.hevc")
    rpu = video.with_name(f"{video.stem} - RPU_CHECK.rpu")
    level5 = video.with_name(f"{video.stem} - RPU_CHECK_level5.json")
    ffmpeg_cmd = [
        "ffmpeg -y -v error",
        f'-i "{video}"',
        "-map 0:v:0 -c:v copy",
    ]
    if video.suffix.lower() in {".mp4", ".mov", ".m4v"}:
        ffmpeg_cmd.append("-bsf:v hevc_mp4toannexb")
    ffmpeg_cmd.append(f'-an -sn -dn -f hevc "{hevc}"')
    lines.extend([
        "1. HEVC-Bitstream extrahieren:",
        "   " + " ".join(ffmpeg_cmd),
        "2. RPU extrahieren:",
        f'   dovi_tool extract-rpu -i "{hevc}" -o "{rpu}"',
        "3. Level-5 exportieren:",
        f'   dovi_tool export -i "{rpu}" -d "level5={level5}"',
        "   Falls die dovi_tool-Version -d nicht akzeptiert:",
        f'   dovi_tool export -i "{rpu}" --data "level5={level5}"',
        "4. In der JSON alle Level-5-Offsets kontrollieren.",
        "5. Aus den Offsets die RPU-Active-Area berechnen:",
        "      aktive Breite = Video-Breite - left - right",
        "      aktive Hoehe  = Video-Hoehe  - top  - bottom",
        f"   Zulaessig sind hier: {expected_w or '?'}x{expected_h or '?'} (Soll) oder "
        f"{actual_w or '?'}x{actual_h or '?'} (finales Video).",
        "   Beispiel: Soll 3840x1606, Video 3840x1608 -> sowohl Active-Area 3840x1606",
        "   als auch 3840x1608 sind korrekt; andere Geometrien bleiben ein Archivfall.",
        "6. Die temporaeren RPU_CHECK-Dateien koennen nach der Pruefung geloescht werden.",
        "",
        "Weitere Validierungsmeldungen",
        "-" * 30,
    ])
    for message in list(getattr(result, "warnings", None) or []) + list(getattr(result, "messages", None) or []):
        if message:
            lines.append(f"- {message}")

    paths = [str(path) for path in (postprocess_paths or []) if path]
    if paths:
        lines.extend(["", "Erzeugte Begleitdaten", "-" * 20])
        lines.extend(f"- {path}" for path in paths)

    lines.extend([
        "",
        "Wichtig: DragonTools hat das Original in diesem Fall NICHT automatisch ersetzt.",
        "Eine manuelle Uebernahme sollte erst nach der oben beschriebenen Pruefung erfolgen.",
        "",
    ])
    report.write_text("\n".join(lines), encoding="utf-8")
    ctx.verification_report_path = str(report)
    return str(report)
