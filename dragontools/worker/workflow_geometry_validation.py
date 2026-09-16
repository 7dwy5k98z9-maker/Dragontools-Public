# -*- coding: utf-8 -*-
"""Tiered final geometry policy after normalized crop encoding."""
from __future__ import annotations


def apply_geometry_policy(ctx, result) -> bool:
    """Return True when the candidate must be archived instead of replaced.

    The normalized crop remains the exact target. Final RPU geometry is only
    relevant when the *video* itself deviates from that target. Exact video
    geometry is trusted and must not be turned into an archive case solely by a
    bytewise RPU/hash difference.
    """
    delta = int(getattr(result, "geometry_max_delta", 0) or 0)
    # Presence and geometry are separate contracts. A failed final extraction
    # must override earlier DV detection even when the video dimensions match.
    if bool(getattr(ctx, "pipeline_final_rpu_checked", False)) and not bool(
        getattr(ctx, "pipeline_final_rpu_present", False)
    ):
        ctx.pipeline_verified_dolby_vision = False
        ctx.pipeline_verified_dv_crop_alignment = False
        mark_geometry_archive(
            ctx,
            result,
            reason=(
                "Finale Dolby-Vision-RPU konnte nicht sicher nachgewiesen werden. "
                "Original wird nicht ersetzt; Kandidat wird mit Diagnose archiviert. "
                + str(getattr(ctx, "pipeline_final_rpu_message", "") or "")
            ).strip(),
            tier="final_rpu_unverified",
            with_postprocess=False,
        )
        return True
    if delta > 0:
        warnings = list(getattr(result, "warnings", None) or [])
        summary = geometry_summary(result)
        if summary and summary not in warnings:
            warnings.append(summary)
        result.warnings = warnings

    # Exact video geometry is the normal success path. Do not escalate a final
    # RPU hash difference here; RPU geometry is checked only if the video crop
    # actually differs from the normalized target.
    if delta <= 0:
        return False

    rpu_required = dv_rpu_check_required(ctx)
    if rpu_required:
        check_dv_rpu_alignment(ctx, result)

    if delta <= 2:
        if not result.ok:
            return False
        if rpu_required and not bool(getattr(ctx, "dv_rpu_alignment_ok", False)):
            mark_geometry_archive(
                ctx,
                result,
                reason=(
                    f"Finale Video-Geometrie weicht nur {delta} Pixel vom normalisierten Soll ab, "
                    "aber die Dolby-Vision-RPU passt weder zur Soll-Geometrie noch zur "
                    "tatsaechlichen Video-Geometrie bzw. konnte nicht sicher ausgewertet werden. "
                    "Original wird nicht ersetzt; Kandidat wird mit Diagnose archiviert."
                ),
                tier="minor_rpu_geometry_mismatch",
                with_postprocess=True,
            )
            return True
        return False

    if not is_geometry_only_failure(result):
        return False

    if delta <= 4:
        reason = (
            f"Finale Geometrie weicht um {delta} Pixel vom normalisierten Soll ab. "
            "Original wird nicht ersetzt; Kandidat wird zur manuellen Pruefung mit "
            "NFO/Trickplay archiviert."
        )
        if rpu_required:
            if bool(getattr(ctx, "dv_rpu_alignment_ok", False)):
                mode = str(getattr(ctx, "dv_rpu_alignment_match_mode", "") or "")
                if mode:
                    reason += f" Die DV-RPU-Geometrie wurde als plausibel bestaetigt ({mode})."
            else:
                reason += " Die DV-RPU-Geometrie passt nicht sicher zu Soll oder Ist des Videos."
        mark_geometry_archive(
            ctx,
            result,
            reason=reason,
            tier="review_3_4",
            with_postprocess=True,
        )
        return True

    mark_geometry_archive(
        ctx,
        result,
        reason=(
            f"Finale Geometrie weicht um {delta} Pixel vom normalisierten Soll ab (>4 Pixel). "
            "Original wird nicht ersetzt; Kandidat wird zur Diagnose archiviert."
        ),
        tier="major_gt4",
        with_postprocess=False,
    )
    return True


def dv_rpu_check_required(ctx) -> bool:
    pipeline = str(
        getattr(getattr(ctx, "pipeline", ""), "value", getattr(ctx, "pipeline", "")) or ""
    ).lower()
    requires_dv = bool(
        getattr(getattr(ctx, "expected_media_contract", None), "require_dolby_vision", False)
    )
    physical_crop = bool(str(getattr(ctx, "effective_crop_filter", "") or "").strip())
    return bool((pipeline in {"dv", "av1_dv"} or requires_dv) and physical_crop)


def _geometry_pair(width, height) -> tuple[int, int] | None:
    try:
        w = int(width)
        h = int(height)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return w, h


def _allowed_rpu_geometries(result) -> tuple[tuple[int, int], ...]:
    """Allowed Level-5 active areas for a deviating final video.

    Example: target 3840x1606, final video 3840x1608. Both active areas are
    valid: 1606 means the two retained pixels stay outside Level-5 Active Area;
    1608 means Level 5 was expanded to the actual frame.
    """
    candidates = []
    for pair in (
        _geometry_pair(getattr(result, "expected_width", None), getattr(result, "expected_height", None)),
        _geometry_pair(getattr(result, "actual_width", None), getattr(result, "actual_height", None)),
    ):
        if pair is not None and pair not in candidates:
            candidates.append(pair)
    return tuple(candidates)


def _rpu_active_areas(ctx, result) -> tuple[tuple[int, int], ...]:
    actual = _geometry_pair(getattr(result, "actual_width", None), getattr(result, "actual_height", None))
    offsets = tuple(getattr(ctx, "pipeline_final_rpu_level5_offsets", ()) or ())
    if actual is None or not offsets:
        return ()
    actual_w, actual_h = actual
    areas: list[tuple[int, int]] = []
    for values in offsets:
        try:
            left, right, top, bottom = (int(v) for v in values)
        except (TypeError, ValueError):
            return ()
        active = (actual_w - left - right, actual_h - top - bottom)
        if active[0] <= 0 or active[1] <= 0:
            return ()
        areas.append(active)
    return tuple(areas)


def check_dv_rpu_alignment(ctx, result) -> None:
    """Validate final DV Level-5 only for an actual video-geometry deviation.

    A bytewise RPU hash difference is diagnostic information, not a geometry
    failure. The relevant question is whether every final Level-5 active area
    matches either the normalized target geometry or the actual final video.
    """
    ctx.dv_rpu_alignment_checked = True
    ctx.dv_rpu_alignment_match_mode = ""

    final_checked = bool(getattr(ctx, "pipeline_final_rpu_checked", False))
    present = bool(getattr(ctx, "pipeline_final_rpu_present", False))
    matches_hash = getattr(ctx, "pipeline_final_rpu_matches_injected", None)
    allowed = _allowed_rpu_geometries(result)
    active_areas = _rpu_active_areas(ctx, result)
    expected = allowed[0] if allowed else None
    actual = _geometry_pair(getattr(result, "actual_width", None), getattr(result, "actual_height", None))

    if final_checked and present and active_areas and allowed:
        invalid = [area for area in active_areas if area not in allowed]
        ok = not invalid
        unique = tuple(dict.fromkeys(active_areas))
        if ok:
            if len(unique) == 1 and expected is not None and unique[0] == expected:
                mode = "RPU Active Area entspricht Soll-Geometrie"
            elif len(unique) == 1 and actual is not None and unique[0] == actual:
                mode = "RPU Active Area entspricht finaler Video-Geometrie"
            else:
                mode = "RPU Active Areas entsprechen zulaessigen Soll-/Ist-Geometrien"
            message = (
                f"DV-RPU-Geometrie OK: {mode}; Active-Area="
                + ", ".join(f"{w}x{h}" for w, h in unique)
                + "."
            )
            ctx.dv_rpu_alignment_match_mode = mode
        else:
            message = (
                "DV-RPU-Geometrie NICHT plausibel: zulaessig waeren "
                + " oder ".join(f"{w}x{h}" for w, h in allowed)
                + "; gefunden "
                + ", ".join(f"{w}x{h}" for w, h in unique)
                + "."
            )
    elif final_checked and present and matches_hash is True and bool(
        getattr(ctx, "pipeline_verified_dv_crop_alignment", False)
    ):
        # If Level 5 could not be exported but the final RPU is byteidentical to
        # the already verified injected crop-RPU, the RPU still represents the
        # normalized target geometry and is therefore one of the allowed states.
        ok = True
        mode = "finale RPU byteidentisch zur verifizierten Soll-RPU"
        ctx.dv_rpu_alignment_match_mode = mode
        message = f"DV-RPU-Geometrie OK: {mode}."
    elif not final_checked and bool(getattr(ctx, "pipeline_verified_dv_crop_alignment", False)):
        # Compatibility/fallback: pre-mux crop-RPU was verified against the target.
        # The current DV pipeline normally provides a final check for physical crop.
        ok = True
        mode = "verifizierte Soll-RPU (kein finaler Level-5-Export verfuegbar)"
        ctx.dv_rpu_alignment_match_mode = mode
        message = f"DV-RPU-Geometrie OK: {mode}."
    else:
        ok = False
        reason = str(getattr(ctx, "pipeline_final_rpu_message", "") or "")
        if final_checked and not present:
            base = "Finale DV-RPU ist nicht sicher vorhanden/extrahierbar."
        elif final_checked and present and not active_areas:
            base = "Finale DV-RPU ist vorhanden, aber Level-5-Geometrie konnte nicht ausgewertet werden."
        else:
            base = "DV-RPU-Geometrie konnte nicht sicher gegen Soll/Ist des Videos geprueft werden."
        message = base + (f" {reason}" if reason else "")

    ctx.dv_rpu_alignment_ok = ok
    ctx.dv_rpu_alignment_message = message
    warnings = list(getattr(result, "warnings", None) or [])
    if message not in warnings:
        warnings.append(message)
    result.warnings = warnings


def is_geometry_only_failure(result) -> bool:
    return bool(
        int(getattr(result, "geometry_max_delta", 0) or 0) > 2
        and bool(getattr(result, "exists", False))
        and bool(getattr(result, "size_ok", False))
        and bool(getattr(result, "container_ok", False))
        and bool(getattr(result, "probe_ok", False))
        and bool(getattr(result, "video_ok", False))
        and bool(getattr(result, "audio_ok", False))
        and bool(getattr(result, "subtitle_ok", False))
        and bool(getattr(result, "metadata_ok", False))
        and bool(getattr(result, "duration_ok", False))
        and bool(getattr(result, "contract_non_geometry_ok", True))
    )


def mark_geometry_archive(ctx, result, *, reason: str, tier: str, with_postprocess: bool) -> None:
    ctx.verification_archive_required = True
    ctx.verification_archive_with_postprocess = bool(with_postprocess)
    ctx.verification_archive_reason = str(reason)
    ctx.verification_archive_tier = str(tier)
    ctx.keep_failed_output = True
    result.contract_ok = False
    messages = list(getattr(result, "messages", None) or [])
    if reason not in messages:
        messages.append(reason)
    result.messages = messages


def geometry_summary(result) -> str:
    delta = int(getattr(result, "geometry_max_delta", 0) or 0)
    if delta <= 0:
        return ""
    return (
        "WARNUNG: finale Geometrie weicht vom normalisierten Soll ab: "
        f"Soll {getattr(result, 'expected_width', None) or '?'}x"
        f"{getattr(result, 'expected_height', None) or '?'}, "
        f"Ist {getattr(result, 'actual_width', None) or '?'}x"
        f"{getattr(result, 'actual_height', None) or '?'}, max. Differenz {delta} Pixel."
    )
