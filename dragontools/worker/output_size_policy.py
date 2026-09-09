# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from ..core.settings import (
    SET_KEY_SAVE_ALLOW_LARGER_OUTPUT,
    SET_KEY_SAVE_ALLOW_LARGER_OUTPUT_PERCENT,
    SET_KEY_SAVE_MIN_OUTPUT_SIZE_ENABLED,
    SET_KEY_SAVE_MIN_OUTPUT_SIZE_PERCENT,
    app_qsettings,
    settings_bool,
    settings_int,
)


def _log_warn(logger: Callable[[str], None] | Callable[[str, str], None] | None, message: str) -> None:
    if logger is None:
        return
    try:
        logger(message, "warn")
    except TypeError:
        logger(message)


def _unique_path_in_dir(directory: Path, filename: str) -> Path:
    """Gibt einen freien Pfad in directory zurück – kein Überschreiben bestehender Dateien."""
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    idx = 1
    while True:
        candidate = directory / f"{stem}_{idx}{suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


def _preserve_in_archiv(
    *,
    input_path: Path,
    output_path: Path,
) -> Path:
    """Verschiebt output_path in den Archiv-Ordner neben input_path.

    Der Ordner ``Archiv/`` wird direkt neben der Quelldatei angelegt,
    sofern er noch nicht existiert. Bei Namenskonflikt wird _1, _2, ...
    an den Dateinamen angehängt. Wirft OSError/IOError bei Fehlern.
    """
    archiv_dir = input_path.parent / "Archiv"
    archiv_dir.mkdir(parents=True, exist_ok=True)
    target_path = _unique_path_in_dir(archiv_dir, output_path.name)
    os.replace(str(output_path), str(target_path))
    return target_path


def validate_output_size_policy(
    input_path: str | Path,
    output_path: str | Path,
    logger: Callable[[str], None] | Callable[[str, str], None] | None = None,
    settings=None,
) -> tuple[bool, Path | None]:
    """Prüft Größenregeln und archiviert die Ausgabe bei Regelverstoß.

    Returns:
        (True, None)            – Regelkonform, normal fortfahren.
        (False, Path)           – Regelverstoß; Ausgabe in Archiv/ abgelegt.
        (False, None)           – Regelverstoß; Archivierung selbst fehlgeschlagen.
    """
    input_path_obj = Path(input_path)
    output_path_obj = Path(output_path)
    if not input_path_obj.exists() or not output_path_obj.exists():
        return True, None

    input_size = input_path_obj.stat().st_size
    output_size = output_path_obj.stat().st_size
    settings = settings or app_qsettings()

    allow_larger = settings_bool(settings, SET_KEY_SAVE_ALLOW_LARGER_OUTPUT, False)
    allow_larger_percent = settings_int(
        settings,
        SET_KEY_SAVE_ALLOW_LARGER_OUTPUT_PERCENT,
        10,
        minimum=0,
        maximum=1000,
    )
    min_output_enabled = settings_bool(settings, SET_KEY_SAVE_MIN_OUTPUT_SIZE_ENABLED, False)
    min_output_percent = settings_int(
        settings,
        SET_KEY_SAVE_MIN_OUTPUT_SIZE_PERCENT,
        50,
        minimum=1,
        maximum=100,
    )

    if allow_larger:
        max_size = int(input_size * (1 + allow_larger_percent / 100.0))
        if output_size > max_size:
            _log_warn(
                logger,
                "[WARN] Output-Datei ist größer als erlaubt. Automatisches Ersetzen deaktiviert.",
            )
            preserved_path = _try_archive(input_path_obj, output_path_obj, logger)
            return False, preserved_path

    if min_output_enabled:
        min_size = int(input_size * (min_output_percent / 100.0))
        if output_size < min_size:
            _log_warn(
                logger,
                "[WARN] Datei ist zu klein geworden. Automatisches Ersetzen deaktiviert.",
            )
            preserved_path = _try_archive(input_path_obj, output_path_obj, logger)
            return False, preserved_path

    return True, None


def _try_archive(
    input_path_obj: Path,
    output_path_obj: Path,
    logger,
) -> Path | None:
    """Archiviert output_path_obj in Archiv/ neben input_path_obj.

    Gibt den Archivpfad zurück oder None wenn die Archivierung fehlschlägt.
    """
    try:
        preserved_path = _preserve_in_archiv(
            input_path=input_path_obj,
            output_path=output_path_obj,
        )
        _log_warn(
            logger,
            f"[WARN] Konvertierte Datei wurde im Archiv-Ordner abgelegt: {preserved_path}",
        )
        return preserved_path
    except Exception as exc:
        _log_warn(
            logger,
            f"[WARN] Archivierung fehlgeschlagen – konvertierte Datei möglicherweise verloren: {exc}",
        )
        return None
