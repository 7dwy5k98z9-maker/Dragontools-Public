from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .paths import app_documents_dir

SCHEMA_VERSION = 5
DEFAULT_DB_FILENAME = "dragontools_mediathek.sqlite3"

LogFn = Callable[[str], None] | None
ProgressFn = Callable[[int, int, str], None] | None
AbortFn = Callable[[], bool] | None

@dataclass(frozen=True)
class PathMapping:
    label: str
    external_prefix: str
    local_prefix: str


def describe_series_path_resolution(mapping_note: str = "", base_type: str = "") -> str:
    """Benutzerverständlicher Hinweis für einen aufgelösten DB-Serienpfad.

    ``mapping_note`` bleibt der stabile technische Grund für Tests/Logik. Die
    GUI muss diese internen Kennungen nicht selbst interpretieren und zeigt
    dadurch nicht mehr für jeden Mapping-Fall pauschal "normalisiert" an.
    """
    note = str(mapping_note or "").strip()
    area = str(base_type or "").strip()
    area_prefix = f"{area}-" if area else ""

    if not note:
        return (
            "DB-Pfad entspricht dem aktuell konfigurierten Speicherpfad "
            "und wurde vor dem Verschieben geprüft."
        )
    if note == "external_to_current":
        return (
            f"Jellyfin-/DB-Pfad wurde über das aktuelle {area_prefix}Pfad-Mapping "
            "auf den konfigurierten Speicherpfad umgesetzt und geprüft."
        )
    if note == "stored_mapping":
        return (
            f"DB-Pfad wurde über das in der Mediathek gespeicherte {area_prefix}Pfad-Mapping "
            "aufgelöst und geprüft."
        )
    if note == "rebased_from_persisted_mapping":
        return (
            f"Alter DB-Speicherpfad wurde über das gespeicherte {area_prefix}Pfad-Mapping "
            "auf den aktuell konfigurierten Speicherpfad umgesetzt und geprüft."
        )
    if note == "rebased_from_series_folder_name":
        return (
            f"Alter DB-Pfad wurde nicht direkt übernommen; der Serienordner wurde unter dem "
            f"aktuell konfigurierten {area_prefix}Speicherpfad anhand des Ordnernamens gefunden "
            "und geprüft."
        )
    return (
        "DB-Pfad wurde über die Pfad-Mapping-Logik auf den aktuellen Speicherpfad "
        "umgesetzt und geprüft."
    )


@dataclass(frozen=True)
class LibraryStats:
    db_path: Path
    schema_version: int
    media_count: int
    active_count: int
    inactive_count: int
    movie_count: int
    series_count: int
    episode_count: int
    stream_count: int
    updated_at: str


@dataclass(frozen=True)
class LibraryImportResult:
    db_path: Path
    imported_items: int
    imported_streams: int
    skipped_items: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class LibraryScanResult:
    db_path: Path
    scanned_files: int
    imported_items: int
    imported_streams: int
    failed_files: int
    skipped_roots: int
    aborted: bool
    warnings: tuple[str, ...]


def default_media_library_dir(root: str | Path | None = None) -> Path:
    return Path(app_documents_dir(root)) / "Mediathek"


def default_media_library_db_path(root: str | Path | None = None) -> Path:
    return default_media_library_dir(root) / DEFAULT_DB_FILENAME


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
