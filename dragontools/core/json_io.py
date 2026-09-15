# -*- coding: utf-8 -*-
"""Robuste atomare JSON-Schreiboperationen für persistente Zustandsdateien."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


_TRANSIENT_WINDOWS_REPLACE_ERRORS = {5, 32, 33}
_REPLACE_RETRY_DELAYS = (0.01, 0.025, 0.05, 0.10)


def _replace_with_retry(source: Path, target: Path) -> None:
    """Replace a file atomically, retrying transient Windows file locks.

    Antivirus/indexer activity can briefly hold ``target`` open and make
    ``os.replace`` fail with access denied/sharing/lock violations. Persistent
    permission errors are still raised after the short bounded retry sequence.
    """
    for attempt in range(len(_REPLACE_RETRY_DELAYS) + 1):
        try:
            os.replace(str(source), str(target))
            return
        except OSError as exc:
            winerror = getattr(exc, "winerror", None)
            if winerror not in _TRANSIENT_WINDOWS_REPLACE_ERRORS or attempt >= len(_REPLACE_RETRY_DELAYS):
                raise
            time.sleep(_REPLACE_RETRY_DELAYS[attempt])


def quarantine_corrupt_file(path: Path, *, tag: str = "corrupt") -> Path | None:
    """Verschiebt eine defekte persistente Datei verlustfrei neben das Original.

    Die Datei bleibt damit fuer Diagnose bzw. manuelle Wiederherstellung erhalten,
    waehrend der regulaere Pfad anschliessend wieder mit einer gueltigen Datei
    belegt werden kann. Die Operation bleibt im selben Verzeichnis und nutzt
    ``os.replace`` fuer einen atomaren Rename auf demselben Dateisystem.
    """
    path = Path(path)
    if not path.exists():
        return None

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = path.suffix
    stem = path.stem
    candidate = path.with_name(f"{stem}.{tag}_{stamp}{suffix}")
    counter = 2
    while candidate.exists():
        candidate = path.with_name(f"{stem}.{tag}_{stamp}_{counter}{suffix}")
        counter += 1

    _replace_with_retry(path, candidate)
    return candidate


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Schreibt JSON über Tempdatei + fsync + atomaren ``os.replace``.

    Die bekannte Tempdatei wird auch nach Fehlern best-effort entfernt.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    token = f"{os.getpid()}_{threading.get_ident()}_{uuid.uuid4().hex[:8]}"
    tmp = path.with_name(f"{path.name}.{token}.tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = ["atomic_write_json", "quarantine_corrupt_file"]
