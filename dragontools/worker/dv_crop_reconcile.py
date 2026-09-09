# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CropRect:
    width: int
    height: int
    x: int
    y: int

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def as_filter(self) -> str:
        return f"crop={self.width}:{self.height}:{self.x}:{self.y}"

    def edges(self, source_width: int, source_height: int) -> tuple[int, int, int, int]:
        return (
            self.x,
            max(0, source_width - self.x - self.width),
            self.y,
            max(0, source_height - self.y - self.height),
        )


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


def parse_crop_filter(value: str | None) -> CropRect | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("crop="):
        text = text[5:]
    parts = text.split(":")
    if len(parts) < 4:
        return None
    try:
        width, height, x, y = (int(float(part.strip().replace(",", "."))) for part in parts[:4])
    except (TypeError, ValueError):
        return None
    if min(width, height) <= 0 or min(x, y) < 0:
        return None
    return CropRect(width, height, x, y)


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
    """Liefert ``autocrop``/``rpu``/``none`` für sichere automatische Fälle.

    Bei kleinen Abweichungen gewinnt bewusst der weniger aggressive Crop, also
    der größere aktive Bildbereich. So werden Bildinhalte nicht wegen einer
    leicht zu engen Erkennung abgeschnitten.
    """
    auto, rpu = comparison.autocrop, comparison.rpu_crop
    if comparison.dynamic_rpu_area:
        return "autocrop" if auto is not None else "none"
    if auto is None and rpu is None:
        return "none"
    if comparison.needs_user_decision:
        return "ask"
    # Bei <=20 px gewinnt weiterhin der größere aktive Bildbereich. "Kein
    # Crop" entspricht dabei dem kompletten Frame und ist am wenigsten aggressiv.
    if auto is None:
        return "autocrop"
    if rpu is None:
        return "rpu"
    if auto.area > rpu.area:
        return "autocrop"
    if rpu.area > auto.area:
        return "rpu"
    # Gleich große Fläche: RPU-Masteringdaten sind der stabilere Tie-Breaker.
    return "rpu"



@dataclass(frozen=True)
class DVCropOutcome:
    success: bool
    crop: CropRect | None
    source: str = "autocrop"
    disable_dv: bool = False
    failure_reason: str = ""


def reconcile_dv_crop(
    *, runner, dovi_tool: str, rpu_path: Path, export_path: Path,
    source_width: int, source_height: int, autocrop_text: str | None,
    input_path: str, crop_decision=None, timeout: int | float = 3600, log=lambda *_: None,
) -> DVCropOutcome:
    """Exportiert Level 5, vergleicht RPU/AutoCrop und liefert den sicheren Ziel-Crop."""
    auto = parse_crop_filter(autocrop_text)
    export_path.unlink(missing_ok=True)
    attempts = (
        [dovi_tool, "export", "-i", str(rpu_path), "-d", f"level5={export_path}"],
        [dovi_tool, "export", "-i", str(rpu_path), "--data", f"level5={export_path}"],
    )
    for idx, cmd in enumerate(attempts):
        export_path.unlink(missing_ok=True)
        rc = runner.run(cmd, timeout=timeout, label=f"DV Level-5 Export ({idx + 1}/{len(attempts)})", allow_error=True)
        if rc == 0 and export_path.exists() and export_path.stat().st_size > 0:
            break
    else:
        log("⚠️ [DV][CROP] Level-5 konnte nicht aus der RPU exportiert werden – FFmpeg-AutoCrop bleibt maßgeblich.", "warn")
        return DVCropOutcome(True, auto, "autocrop")

    try:
        rpu, dynamic = parse_level5_export(export_path, source_width=source_width, source_height=source_height)
    except (OSError, ValueError, TypeError) as exc:
        log(f"⚠️ [DV][CROP] Level-5-Export konnte nicht ausgewertet werden: {exc}", "warn")
        return DVCropOutcome(True, auto, "autocrop")
    if dynamic:
        log("ℹ️ [DV][CROP] RPU enthält mehrere Active-Area-Werte (z. B. wechselndes IMAX). Kein globaler RPU-Crop wird erzwungen; AutoCrop bleibt unverändert.", "info")
        return DVCropOutcome(True, auto, "autocrop")

    comparison = compare_crops(auto, rpu, source_width=source_width, source_height=source_height)
    auto_label = auto.as_filter() if auto else "kein Crop"
    rpu_label = rpu.as_filter() if rpu else "kein Crop"
    log(f"ℹ️ [DV][CROP] AutoCrop={auto_label} | RPU-Level5={rpu_label} | Abweichung={comparison.max_difference_px}px", "info")
    choice = automatic_choice(comparison)
    if choice == "ask":
        if crop_decision is None:
            return DVCropOutcome(False, auto, failure_reason="DV-Crop-Abweichung >20px; Benutzerentscheidung erforderlich.")
        choice = str(crop_decision({
            "input_path": input_path, "autocrop": auto_label, "rpu_crop": rpu_label,
            "difference_px": comparison.max_difference_px,
        }) or "").strip().lower()
        if choice == "disable_dv":
            return DVCropOutcome(False, auto, disable_dv=True, failure_reason="DV_DISABLED_BY_USER_CROP")
        if choice not in {"autocrop", "rpu"}:
            return DVCropOutcome(False, auto, failure_reason="DV-Crop-Konflikt wurde ohne gültige Auswahl beendet.")
    crop = auto if choice == "autocrop" else rpu if choice == "rpu" else None
    return DVCropOutcome(True, crop, choice)



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
    """Ersetzt/ergänzt den Crop in einer FFmpeg ``-vf``-Kette ohne andere Filter zu verlieren."""
    args = list(vf_args)
    old_text = str(old_crop or "").strip()
    new_text = str(new_crop or "").strip()
    try:
        idx = args.index("-vf")
    except ValueError:
        if not new_text:
            return args
        # Video-Map bleibt vorne, Filter wird direkt danach ergänzt.
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
