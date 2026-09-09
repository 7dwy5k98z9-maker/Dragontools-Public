"""Dateisystem-, Konflikt- und Speicherpruefungen fuer den Batch-Preflight."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .move_conflicts import find_target_conflicts, format_conflict_names


VERY_LOW_FREE_BYTES = 512 * 1024 * 1024
LONG_PATH_WARNING_LENGTH = 240


def _text(value: Any, fallback: str = "-") -> str:
    if value is None:
        return fallback
    result = str(value).strip()
    return result or fallback


def _codec_tag(codec: str) -> str:
    return {"h264": "H264", "h265": "H265", "av1": "AV1"}.get(
        str(codec or "").lower(),
        str(codec or "").upper() or "OUT",
    )


def _unique_output_candidate(base_dir: Path, stem: str, tag: str, container: str) -> Path:
    candidate = base_dir / f"{stem}_{tag}.{container}"
    counter = 1
    while candidate.exists():
        candidate = base_dir / f"{stem}_{tag}_{counter}.{container}"
        counter += 1
    return candidate


def _planned_output_paths(path: str, *, codec: str, container: str, overwrite_original: bool) -> dict[str, Any]:
    src = Path(path)
    base_dir = src.parent
    if overwrite_original:
        output_path = base_dir / "__temp_overwrite__" / f"{src.stem}.{container}"
        final_path = src.with_suffix(f".{container}")
    else:
        output_path = _unique_output_candidate(base_dir, src.stem, _codec_tag(codec), container)
        final_path = output_path
    return {
        "output_path": str(output_path),
        "final_output_path": str(final_path),
        "output_dir": str(output_path.parent),
    }


def _nearest_existing_dir(path: Path) -> Path | None:
    current = path
    while True:
        if current.exists():
            return current if current.is_dir() else current.parent
        if current.parent == current:
            return None
        current = current.parent


def _can_write_probe(directory: Path) -> tuple[bool, str | None]:
    base = _nearest_existing_dir(directory)
    if base is None:
        return False, "Kein existierender Elternordner gefunden."
    if not base.exists() or not base.is_dir():
        return False, f"Ziel ist kein Ordner: {base}"

    probe = base / f".dragontools_preflight_{os.getpid()}.tmp"
    try:
        with open(probe, "xb") as handle:
            handle.write(b"ok")
        probe.unlink(missing_ok=True)
        return True, None
    except Exception as exc:
        try:
            probe.unlink(missing_ok=True)
        except Exception:
            pass
        return False, str(exc)


def _disk_free(directory: Path) -> int | None:
    base = _nearest_existing_dir(directory)
    if base is None:
        return None
    try:
        return shutil.disk_usage(base).free
    except Exception:
        return None


def format_gb(value: int | None) -> str:
    if value is None:
        return "unbekannt"
    return f"{value / (1024 ** 3):.1f} GB"


def filesystem_preflight(
    path: str,
    preview: dict[str, Any],
    *,
    codec: str,
    overwrite_original: bool,
) -> tuple[dict[str, Any], list[str], bool]:
    """Prueft geplante Ausgabe und Verschiebeziel ohne die Fachanalyse zu kennen."""
    info: dict[str, Any] = {}
    warnings: list[str] = []
    error = False

    src = Path(path)
    container = _text(preview.get("target_container"), "mkv").lstrip(".").lower()
    paths = _planned_output_paths(
        path,
        codec=codec,
        container=container,
        overwrite_original=overwrite_original,
    )
    info.update(paths)

    if not src.exists():
        warnings.append("Quelldatei existiert nicht mehr.")
        return info, warnings, True
    if not src.is_file():
        warnings.append("Quelle ist keine Datei.")
        return info, warnings, True

    try:
        source_size = src.stat().st_size
    except Exception:
        source_size = 0
    info["source_size"] = source_size

    output_dir = Path(paths["output_dir"])
    if output_dir.exists() and not output_dir.is_dir():
        warnings.append(f"Ausgabeziel ist kein Ordner: {output_dir}")
        error = True

    can_write, write_error = _can_write_probe(output_dir)
    if not can_write:
        warnings.append(f"Ausgabeordner nicht beschreibbar: {write_error}")
        error = True

    output_path = Path(paths["output_path"])
    final_path = Path(paths["final_output_path"])
    if overwrite_original:
        temp_dir = output_path.parent
        if temp_dir.exists() and not temp_dir.is_dir():
            warnings.append(f"Temp-Ziel blockiert durch Datei: {temp_dir}")
            error = True
        if final_path.exists():
            try:
                final_resolved = final_path.resolve()
                input_resolved = src.resolve()
            except Exception:
                final_resolved = final_path
                input_resolved = src
            if final_resolved != input_resolved:
                warnings.append(f"Zieldatei existiert bereits: {final_path.name}")
                error = True
        if output_path.exists():
            warnings.append(f"Alte temporäre Ausgabedatei vorhanden: {output_path.name}")

    for checked_path in (output_path, final_path):
        if len(str(checked_path)) >= LONG_PATH_WARNING_LENGTH:
            warnings.append(f"Langer Pfad kann externe Tools stoeren: {checked_path.name}")
            break

    free = _disk_free(output_dir)
    info["free_bytes"] = free
    if free is not None:
        if free < VERY_LOW_FREE_BYTES:
            warnings.append(f"Sehr wenig freier Speicher am Ausgabeziel: {format_gb(free)}")
            error = True
        elif source_size and free < source_size:
            warnings.append(
                "Freier Speicher am Ausgabeziel ist kleiner als die Quelldatei "
                f"({format_gb(free)} frei, Quelle {format_gb(source_size)})."
            )

    move = dict(preview.get("move") or {})
    planned_move = _text(move.get("planned_target"), "")
    if planned_move:
        move_dir = Path(planned_move)
        info["move_target_dir"] = str(move_dir)
        can_write_move, move_error = _can_write_probe(move_dir)
        if not can_write_move:
            warnings.append(f"Verschiebe-Ziel nicht beschreibbar: {move_error}")
            error = True
        move_free = _disk_free(move_dir)
        info["move_free_bytes"] = move_free
        if move_free is not None and move_free < VERY_LOW_FREE_BYTES:
            warnings.append(f"Sehr wenig freier Speicher am Verschiebe-Ziel: {format_gb(move_free)}")
            error = True

        destination = move_dir / final_path.name
        info["move_destination"] = str(destination)
        move_conflicts = find_target_conflicts(destination)
        if move_conflicts:
            warnings.append(
                "Verschiebe-Zielkonflikt vorhanden: "
                f"{format_conflict_names(move_conflicts)}"
            )

    return info, warnings, error
