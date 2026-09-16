# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .crop_geometry import CropRect, normalize_crop_rect, parse_crop_filter


@dataclass(frozen=True)
class DVCropComparison:
    autocrop: CropRect | None
    rpu_crop: CropRect | None
    max_difference_px: int
    dynamic_rpu_area: bool = False

    @property
    def needs_user_decision(self) -> bool:
        return bool((self.autocrop is not None or self.rpu_crop is not None)
                    and self.max_difference_px > 20)


def crop_from_level5_offsets(
    *,
    source_width: int,
    source_height: int,
    left: int,
    right: int,
    top: int,
    bottom: int,
) -> CropRect | None:
    width = int(source_width) - int(left) - int(right)
    height = int(source_height) - int(top) - int(bottom)
    rect = CropRect(width, height, int(left), int(top))
    if width <= 0 or height <= 0 or min(left, right, top, bottom) < 0:
        return None
    return rect


def _collect_offset_dicts(node: Any, result: list[tuple[int, int, int, int]]) -> None:
    if isinstance(node, dict):
        aliases = (
            ("left", "right", "top", "bottom"),
            (
                "active_area_left_offset",
                "active_area_right_offset",
                "active_area_top_offset",
                "active_area_bottom_offset",
            ),
        )
        for names in aliases:
            if all(name in node for name in names):
                try:
                    result.append(tuple(int(node[name]) for name in names))
                except (TypeError, ValueError):
                    pass
                break
        for value in node.values():
            _collect_offset_dicts(value, result)
    elif isinstance(node, list):
        for value in node:
            _collect_offset_dicts(value, result)


def read_level5_offsets(path: str | Path) -> tuple[tuple[int, int, int, int], ...]:
    """Return all unique Level-5 active-area offset tuples from a dovi_tool export."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    offsets: list[tuple[int, int, int, int]] = []
    _collect_offset_dicts(payload, offsets)
    return tuple(dict.fromkeys(offsets))


def parse_level5_export(
    path: str | Path,
    *,
    source_width: int,
    source_height: int,
) -> tuple[CropRect | None, bool]:
    """Liest einen dovi_tool-Level-5-Export.

    Returns ``(crop, dynamic)``. Bei mehreren unterschiedlichen Active Areas
    wird kein globaler physischer Crop erzwungen, weil das typischerweise auf
    wechselnde Aspect-Ratios/IMAX hindeutet.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    offsets: list[tuple[int, int, int, int]] = []
    _collect_offset_dicts(payload, offsets)
    unique = list(dict.fromkeys(offsets))
    if not unique:
        return None, False
    if len(unique) > 1:
        return None, True
    left, right, top, bottom = unique[0]
    return (
        crop_from_level5_offsets(
            source_width=source_width,
            source_height=source_height,
            left=left,
            right=right,
            top=top,
            bottom=bottom,
        ),
        False,
    )


def compare_crops(
    autocrop: CropRect | None,
    rpu_crop: CropRect | None,
    *,
    source_width: int,
    source_height: int,
    dynamic_rpu_area: bool = False,
) -> DVCropComparison:
    full_frame = CropRect(int(source_width), int(source_height), 0, 0)
    auto_cmp = autocrop or full_frame
    rpu_cmp = rpu_crop or full_frame
    # Kein Crop entspricht dem vollen Frame. So wird auch "kein Crop" gegen
    # einen deutlich gecroppten Gegenwert korrekt als Konflikt erkannt.
    diff = max(
        abs(auto_cmp.width - rpu_cmp.width), abs(auto_cmp.height - rpu_cmp.height),
        abs(auto_cmp.x - rpu_cmp.x), abs(auto_cmp.y - rpu_cmp.y),
        *(abs(a - b) for a, b in zip(auto_cmp.edges(source_width, source_height),
                                     rpu_cmp.edges(source_width, source_height))),
    )
    return DVCropComparison(autocrop, rpu_crop, diff, dynamic_rpu_area)


def automatic_choice(comparison: DVCropComparison) -> str:
    """Return the physical-crop policy for compatibility callers.

    AutoCrop is authoritative. RPU Level-5 is diagnostic source metadata and
    must never become the physical video crop. If AutoCrop selected no crop,
    the physical result remains the full frame (``none``).
    """
    return "autocrop" if comparison.autocrop is not None else "none"



@dataclass(frozen=True)
class DVCropOutcome:
    success: bool
    crop: CropRect | None
    source: str = "autocrop"
    disable_dv: bool = False
    failure_reason: str = ""


def _normalize_candidate(
    rect: CropRect | None,
    *,
    source_width: int,
    source_height: int,
    label: str,
    log,
) -> CropRect | None:
    if rect is None:
        return None
    try:
        normalized = normalize_crop_rect(
            rect,
            source_width=source_width,
            source_height=source_height,
        )
    except ValueError as exc:
        log(f"⚠️ [DV][CROP] {label} ist ungueltig und wird nicht erzwungen: {exc}", "warn")
        return None
    if normalized != rect:
        log(
            f"ℹ️ [DV][CROP] {label} auf 4:2:0-Geometrie normalisiert: "
            f"{rect.as_filter()} → {normalized.as_filter()}. "
            "Ungerade Kanten werden bevorzugt um 1 Pixel nach außen erweitert.",
            "info",
        )
    return normalized


def reconcile_dv_crop(
    *, runner, dovi_tool: str, rpu_path: Path, export_path: Path,
    source_width: int, source_height: int, autocrop_text: str | None,
    input_path: str, crop_decision=None, timeout: int | float = 3600, log=lambda *_: None,
) -> DVCropOutcome:
    """Use FFmpeg AutoCrop as the authoritative physical video crop.

    Dolby-Vision Level-5 data is source metadata and is useful for diagnostics,
    but it must never enlarge, shrink or shift the physical crop selected by the
    image analysis.  After the physical crop, ``DVLevel5Editor`` rewrites the
    RPU for the cropped output (L5=0/0/0/0).

    ``crop_decision`` remains in the signature for API compatibility only.
    """
    del input_path, crop_decision

    auto = _normalize_candidate(
        parse_crop_filter(autocrop_text),
        source_width=source_width,
        source_height=source_height,
        label="AutoCrop",
        log=log,
    )
    auto_label = auto.as_filter() if auto else "kein Crop"

    export_path.unlink(missing_ok=True)
    attempts = (
        [dovi_tool, "export", "-i", str(rpu_path), "-d", f"level5={export_path}"],
        [dovi_tool, "export", "-i", str(rpu_path), "--data", f"level5={export_path}"],
    )
    for idx, cmd in enumerate(attempts):
        export_path.unlink(missing_ok=True)
        rc = runner.run(
            cmd,
            timeout=timeout,
            label=f"DV Level-5 Export ({idx + 1}/{len(attempts)})",
            allow_error=True,
        )
        if rc == 0 and export_path.exists() and export_path.stat().st_size > 0:
            break
    else:
        log(
            "⚠️ [DV][CROP] Level-5 konnte nicht aus der RPU exportiert werden – "
            f"AutoCrop bleibt allein maßgeblich: {auto_label}.",
            "warn",
        )
        return DVCropOutcome(True, auto, "autocrop")

    try:
        # Deliberately keep the source RPU geometry *raw* here.  It is only a
        # diagnostic reference; normalising it must not create a competing
        # physical crop candidate.
        rpu, dynamic = parse_level5_export(
            export_path,
            source_width=source_width,
            source_height=source_height,
        )
    except (OSError, ValueError, TypeError) as exc:
        log(f"⚠️ [DV][CROP] Level-5-Export konnte nicht ausgewertet werden: {exc}", "warn")
        return DVCropOutcome(True, auto, "autocrop")

    if dynamic:
        log(
            "ℹ️ [DV][CROP] RPU enthält mehrere Active-Area-Werte (z. B. wechselndes IMAX). "
            f"Sie werden nur diagnostisch betrachtet; physischer Crop bleibt AutoCrop={auto_label}.",
            "info",
        )
        return DVCropOutcome(True, auto, "autocrop")

    comparison = compare_crops(auto, rpu, source_width=source_width, source_height=source_height)
    rpu_label = rpu.as_filter() if rpu else "kein Crop"
    log(
        f"ℹ️ [DV][CROP] AutoCrop={auto_label} | RPU-Level5={rpu_label} | "
        f"Abweichung={comparison.max_difference_px}px | AutoCrop ist maßgeblich; "
        "RPU wird nach dem physischen Crop an den Zielstream angepasst.",
        "info",
    )
    return DVCropOutcome(True, auto, "autocrop")



def _split_filter_chain(chain: str) -> list[str]:
    """Teilt eine FFmpeg-Filterkette nur an *nicht escapten* Kommata.

    Ausdrücke wie ``min(1080\\,ih)`` enthalten absichtlich ein escaptes
    Komma und dürfen beim DV-Crop-Abgleich nicht in zwei Filter zerfallen.
    """
    parts: list[str] = []
    current: list[str] = []
    backslashes = 0
    for char in str(chain):
        if char == "," and backslashes % 2 == 0:
            parts.append("".join(current))
            current = []
            backslashes = 0
            continue
        current.append(char)
        if char == "\\":
            backslashes += 1
        else:
            backslashes = 0
    parts.append("".join(current))
    return [part for part in parts if part]

def replace_crop_in_vf_args(vf_args: list, old_crop: str | None, new_crop: str | None) -> list:
    """Replace the physical crop without losing subtitle/filter graphs.

    Image based subtitle burn-in uses ``-filter_complex``.  If AutoCrop is
    normalised (for example 1607 -> 1608), the crop inside that graph must be
    updated in-place; adding a second ``-vf`` would leave the burn-in path on
    the stale geometry.
    """
    args = list(vf_args)
    old_text = str(old_crop or "").strip()
    new_text = str(new_crop or "").strip()

    if "-filter_complex" in args:
        idx = args.index("-filter_complex")
        if idx + 1 >= len(args):
            return args
        graph = str(args[idx + 1])
        if old_text and old_text in graph:
            graph = graph.replace(old_text, new_text, 1) if new_text else graph.replace(old_text, "", 1)
        elif new_text:
            # Insert directly after the video input label.  DV P7/P8 remapping
            # later turns [0:v:0] into [1:v:0], so support both forms here.
            for label in ("[0:v:0]", "[1:v:0]"):
                if label in graph:
                    graph = graph.replace(label, f"{label}{new_text},", 1)
                    break
            else:
                # A graph without a recognisable video input cannot be safely
                # rewritten.  Keep it unchanged rather than creating a second
                # independent -vf chain.
                return args
        args[idx + 1] = graph
        return args

    try:
        idx = args.index("-vf")
    except ValueError:
        if not new_text:
            return args
        return args + ["-vf", new_text]
    if idx + 1 >= len(args):
        return args
    chain = str(args[idx + 1])
    filters = _split_filter_chain(chain)
    if old_text:
        filters = [new_text if item == old_text and new_text else item for item in filters if item != old_text or new_text]
    elif new_text:
        insert_at = 1 if filters and filters[0].startswith("libplacebo=") else 0
        filters.insert(insert_at, new_text)
    args[idx + 1] = ",".join(filters)
    if not filters:
        del args[idx:idx + 2]
    return args
