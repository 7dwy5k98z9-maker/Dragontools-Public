# -*- coding: utf-8 -*-
"""Runtime helpers for the optional faster-whisper integration.

The official EXE bundles the Python runtime packages.  Whisper *models* are a
separate concern: when no explicit local CTranslate2 model directory is chosen,
faster-whisper downloads the selected model on first use and reuses the normal
Hugging Face model cache afterwards.
"""
from __future__ import annotations

import importlib
from importlib import metadata
import os
from pathlib import Path
import sys
from typing import Any


_REQUIRED_LOCAL_MODEL_FILES = ("model.bin", "config.json")
_MODEL_REPOSITORIES = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
}


def _module_available(name: str) -> bool:
    """Return whether a runtime module is actually importable.

    Importing is intentional here.  ``find_spec`` can be misleading in frozen
    PyInstaller builds or when a package is present but one of its binary
    dependencies cannot be loaded.  The tool diagnostic should report the
    runtime that Dragon Tools can really use.
    """
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def whisper_runtime_available() -> bool:
    return _module_available("faster_whisper") and _module_available("ctranslate2")


def package_version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return ""
    except Exception:
        return ""


def validate_local_whisper_model_dir(path: str | Path | None) -> tuple[bool, str]:
    """Validate a local faster-whisper/CTranslate2 model directory.

    An empty path is valid and means that ``WhisperModel`` may use its normal
    model-name/cache/download mechanism.
    """
    value = str(path or "").strip()
    if not value:
        return True, "Kein lokales Modell konfiguriert; Modellname/Cache wird verwendet."
    model_dir = Path(value)
    if not model_dir.is_dir():
        return False, f"Lokaler Whisper-Modellordner existiert nicht: {model_dir}"
    missing = [name for name in _REQUIRED_LOCAL_MODEL_FILES if not (model_dir / name).is_file()]
    if missing:
        return False, "Lokaler Whisper-Modellordner ist unvollständig; fehlt: " + ", ".join(missing)
    return True, f"Lokales CTranslate2-Modell: {model_dir}"


def resolve_whisper_model_reference(
    *,
    model_name: str,
    model_dir: str | Path | None = None,
    use_local_model: bool | None = None,
) -> str:
    """Return the model reference passed to :class:`faster_whisper.WhisperModel`.

    A configured local directory is authoritative.  Invalid configured paths
    are rejected instead of silently downloading a different model.
    """
    value = str(model_dir or "").strip()
    use_local = bool(value) if use_local_model is None else bool(use_local_model)
    if use_local:
        if not value:
            raise RuntimeError("Lokales Whisper-Modell ist aktiviert, aber kein Modellordner ausgewählt.")
        ok, detail = validate_local_whisper_model_dir(value)
        if not ok:
            raise RuntimeError(detail)
        return str(Path(value))
    return str(model_name or "small").strip() or "small"


def _cache_roots() -> tuple[Path, ...]:
    """Return likely Hugging Face hub cache roots without requiring the package."""
    candidates: list[Path] = []
    for env_name in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        value = str(os.environ.get(env_name, "") or "").strip()
        if value:
            candidates.append(Path(value).expanduser())
    hf_home = str(os.environ.get("HF_HOME", "") or "").strip()
    if hf_home:
        candidates.append(Path(hf_home).expanduser() / "hub")
    candidates.append(Path.home() / ".cache" / "huggingface" / "hub")

    result: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path).casefold()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return tuple(result)


def find_cached_whisper_model(model_name: str = "small") -> Path | None:
    """Find a complete cached faster-whisper model snapshot, if one exists."""
    name = str(model_name or "small").strip() or "small"
    repo = _MODEL_REPOSITORIES.get(name, f"Systran/faster-whisper-{name}")
    repo_folder = "models--" + repo.replace("/", "--")

    for cache_root in _cache_roots():
        repo_root = cache_root / repo_folder
        snapshots = repo_root / "snapshots"
        if not snapshots.is_dir():
            continue

        preferred: list[Path] = []
        ref_main = repo_root / "refs" / "main"
        try:
            if ref_main.is_file():
                revision = ref_main.read_text(encoding="utf-8", errors="replace").strip()
                if revision:
                    preferred.append(snapshots / revision)
        except OSError:
            pass

        try:
            preferred.extend(
                child for child in snapshots.iterdir()
                if child.is_dir() and child not in preferred
            )
        except OSError:
            continue

        for snapshot in preferred:
            ok, _detail = validate_local_whisper_model_dir(snapshot)
            if ok:
                return snapshot
    return None


def _runtime_missing_hint(*, faster_available: bool, ctranslate_available: bool) -> str:
    missing: list[str] = []
    if not faster_available:
        missing.append("faster-whisper")
    if not ctranslate_available:
        missing.append("CTranslate2")
    joined = " und ".join(missing) if missing else "Whisper-Laufzeit"
    verb = "sind" if len(missing) > 1 else "ist"
    if getattr(sys, "frozen", False):
        return (
            f"{joined} {verb} im aktuell gestarteten EXE-Build nicht nutzbar. "
            "Der Modellcache enthält nur Modelldaten und ersetzt die Python/CTranslate2-Laufzeit nicht. "
            "Der offizielle Build muss faster-whisper und CTranslate2 mit PyInstaller einbinden."
        )
    return (
        f"{joined} {verb} im aktuell verwendeten Python-Interpreter nicht installiert/nutzbar. "
        "Der Modellcache enthält nur Modelldaten und ersetzt die Python/CTranslate2-Laufzeit nicht. "
        "Im offiziellen EXE-Build werden beide Komponenten mitgeliefert."
    )


def build_whisper_diagnostic(
    model_dir: str | Path | None = None,
    *,
    use_local_model: bool | None = None,
    model_name: str = "small",
) -> dict[str, Any]:
    """Return one row compatible with ``format_tool_diagnostics``.

    Runtime packages and model cache are reported separately.  A missing model
    cache is *not* an error because faster-whisper creates it on first use.
    """
    faster_available = _module_available("faster_whisper")
    ctranslate_available = _module_available("ctranslate2")
    configured_model = str(model_dir or "").strip()
    selected_model = str(model_name or "small").strip() or "small"
    use_local = bool(configured_model) if use_local_model is None else bool(use_local_model)

    cached_model: Path | None = None
    if use_local and not configured_model:
        model_ok = False
        model_detail = "Lokales Whisper-Modell ist aktiviert, aber kein Modellordner ausgewählt."
    elif use_local:
        model_ok, model_detail = validate_local_whisper_model_dir(configured_model)
    else:
        model_ok = True
        cached_model = find_cached_whisper_model(selected_model)
        if cached_model:
            model_detail = f"Modell '{selected_model}' im Cache: {cached_model}"
        else:
            model_detail = (
                f"Modell '{selected_model}' ist noch nicht im lokalen Modellcache. "
                "Es wird beim ersten tatsächlichen Einsatz automatisch geladen und danach wiederverwendet."
            )

    versions: list[str] = []
    faster_version = package_version("faster-whisper")
    ctranslate_version = package_version("ctranslate2")
    if faster_version:
        versions.append(f"faster-whisper {faster_version}")
    if ctranslate_version:
        versions.append(f"CTranslate2 {ctranslate_version}")

    errors: list[str] = []
    if not (faster_available and ctranslate_available):
        errors.append(
            _runtime_missing_hint(
                faster_available=faster_available,
                ctranslate_available=ctranslate_available,
            )
        )
    if not model_ok:
        errors.append(model_detail)
    elif not use_local and cached_model is None and faster_available and ctranslate_available:
        # Informative only: the row remains green because first-use download is valid.
        errors.append(model_detail)

    features = ["Audio-Spracherkennung"]
    if use_local and configured_model and model_ok:
        features.append("lokales Offline-Modell")
    elif cached_model:
        features.append(f"Modellcache '{selected_model}' vorhanden")
    else:
        features.append(f"Modell '{selected_model}' / Download bei erster Nutzung")

    if use_local:
        display_path = configured_model or "lokaler Modellordner nicht gewählt"
    elif cached_model:
        display_path = str(cached_model)
    else:
        display_path = "intern / Hugging-Face-Modellcache"

    if configured_model and not use_local:
        display_path += " (lokaler Pfad deaktiviert)"

    return {
        "name": "faster-whisper",
        "path": display_path,
        "found": faster_available and ctranslate_available and model_ok,
        "version": " / ".join(versions),
        "features": features,
        "error": "; ".join(errors),
    }


__all__ = [
    "build_whisper_diagnostic",
    "find_cached_whisper_model",
    "package_version",
    "resolve_whisper_model_reference",
    "validate_local_whisper_model_dir",
    "whisper_runtime_available",
]
