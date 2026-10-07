"""Geometry detection and normalization, separate from track/color planning."""
from .crop_geometry import normalize_crop_filter
from ..core.type_utils import _safe_bool, _safe_int


def detect_encode_imax(input_path, media_info, override, options, *, detect_imax_auto, probe_duration_ms, log):
    active_options = options
    file_override = override
    duration_s = None
    imax = _safe_bool(file_override.get("imax"), False)
    video = media_info.primary_video
    src_width = video.width if video else 0
    src_height = video.height if video else 0

    if not imax and _safe_bool(active_options.get("imax_auto_detect"), False):
        duration_s = (probe_duration_ms(input_path) or 0) / 1000
        interval_s = _safe_int(active_options.get("imax_probe_interval_s"), 90) or 90
        if detect_imax_auto(
            input_path,
            duration_s,
            src_width,
            src_height,
            interval_s,
            _safe_int(active_options.get("imax_probe_duration_s"), 3) or 3,
            _safe_int(active_options.get("imax_min_variance_percent"), 15) or 15,
            _safe_int(active_options.get("imax_min_hits"), 2) or 2,
        ):
            imax = True
            log("🎬 IMAX-Auto aktiviert.", "info")

    return imax, src_width, src_height, duration_s


def detect_encode_crop(input_path, pipeline, options, *, imax, src_width, src_height,
                       detected_duration_s, detect_crop, probe_duration_ms, log, logger):
    active_options = options
    duration_s = detected_duration_s
    global_autocrop = _safe_bool(active_options.get("autocrop_enabled"), True)
    crop = None
    if imax:
        logger.info("🎬 IMAX: Auto-Crop deaktiviert.")
    elif not global_autocrop:
        logger.info("Auto-Crop global deaktiviert.")
    else:
        autocrop_mode = active_options.get("autocrop_mode", "single")
        if autocrop_mode == "multi" and duration_s is None:
            duration_s = (probe_duration_ms(input_path) or 0) / 1000
        crop = detect_crop(
            input_path,
            src_width,
            src_height,
            autocrop_mode,
            _safe_int(active_options.get("autocrop_probe_start_s"), 30),
            _safe_int(active_options.get("autocrop_probe_duration_s"), 45) or 45,
            _safe_int(active_options.get("autocrop_probe_interval_s"), 600) or 600,
            duration_s,
        )
        if crop and src_width > 0 and src_height > 0:
            raw_crop = crop
            try:
                crop = normalize_crop_filter(
                    crop,
                    source_width=src_width,
                    source_height=src_height,
                )
            except ValueError as exc:
                log(f"⚠️ Auto-Crop konnte nicht normalisiert werden: {exc}", "warn")
                crop = None
            else:
                if crop != raw_crop:
                    logger.info(
                        f"Auto-Crop vor Encode normalisiert: {raw_crop} → {crop}."
                    )
        if not crop:
            logger.info("Auto-Crop: Keine schwarzen Balken erkannt.")
        elif pipeline == "dv" or str(pipeline).lower() == "pipeline.dv" or getattr(pipeline, "value", None) == "dv" or getattr(pipeline, "name", "").lower() == "dv":
            logger.info(f"DV+Crop: {crop} → RPU wird nach physischem Crop auf L5=0/0/0/0 normalisiert.")

    return crop
