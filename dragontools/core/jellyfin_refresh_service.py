# -*- coding: utf-8 -*-
"""Pure orchestration for best-effort Jellyfin library refreshes."""
from __future__ import annotations

import posixpath
from dataclasses import dataclass
from typing import Iterable

from .jellyfin_api import JellyfinApiError, JellyfinClient
from .jellyfin_full_scan_guard import start_full_scan_if_needed
from .media_library_path_mappings import map_local_to_external_path
from .media_library_types import PathMapping


@dataclass(frozen=True)
class JellyfinRefreshConfig:
    server_url: str
    api_key: str
    refresh_mode: str = "targeted"
    fallback_full_scan: bool = False


@dataclass(frozen=True)
class JellyfinRefreshResult:
    ok: bool
    mode: str
    update_count: int
    fallback_used: bool = False
    full_scan_reused: bool = False
    message: str = ""


def _normalize_jellyfin_path(path: str) -> str:
    text = str(path or "").strip().replace("\\", "/")
    if not text:
        return ""
    while "//" in text[1:]:
        text = text.replace("//", "/")
    if text != "/":
        text = text.rstrip("/")
    return text


def _path_within_root(path: str, root: str) -> bool:
    path_norm = _normalize_jellyfin_path(path).casefold()
    root_norm = _normalize_jellyfin_path(root).casefold()
    if not path_norm or not root_norm:
        return False
    if root_norm == "/":
        return path_norm.startswith("/")
    return path_norm == root_norm or path_norm.startswith(root_norm + "/")


def _matching_root(path: str, roots: Iterable[str]) -> str | None:
    matches = [root for root in roots if _path_within_root(path, root)]
    if not matches:
        return None
    return max(matches, key=lambda value: len(_normalize_jellyfin_path(value)))


def _canonicalize_under_root(path: str, root: str) -> str:
    path_norm = _normalize_jellyfin_path(path)
    root_norm = _normalize_jellyfin_path(root)
    if not _path_within_root(path_norm, root_norm):
        return path_norm
    if path_norm.casefold() == root_norm.casefold():
        return root_norm
    return root_norm + path_norm[len(root_norm) :]


def merge_refresh_mappings(
    configured: Iterable[PathMapping],
    stored: Iterable[PathMapping],
) -> list[PathMapping]:
    """Merge runtime mappings with the media-library DB mappings.

    The media-library DB is authoritative for Jellyfin's external path while
    the live settings mapping is authoritative for the current local move root.
    This keeps an existing DB import useful even after a local destination was
    changed in Dragon Tools.
    """
    current = list(configured)
    database = list(stored)
    result: list[PathMapping] = []
    used_current: set[int] = set()

    def label_key(value: str) -> str:
        return " ".join(str(value or "").casefold().split())

    for db_mapping in database:
        db_label = label_key(db_mapping.label)
        db_external = _normalize_jellyfin_path(db_mapping.external_prefix).casefold()
        match_index: int | None = None
        for index, mapping in enumerate(current):
            if index in used_current:
                continue
            same_label = bool(db_label and db_label == label_key(mapping.label))
            same_external = bool(
                db_external
                and db_external == _normalize_jellyfin_path(mapping.external_prefix).casefold()
            )
            if same_label or same_external:
                match_index = index
                break

        if match_index is None:
            result.append(db_mapping)
            continue

        used_current.add(match_index)
        settings_mapping = current[match_index]
        result.append(PathMapping(
            db_mapping.label or settings_mapping.label,
            db_mapping.external_prefix or settings_mapping.external_prefix,
            settings_mapping.local_prefix or db_mapping.local_prefix,
        ))

    result.extend(mapping for index, mapping in enumerate(current) if index not in used_current)

    unique: list[PathMapping] = []
    seen: set[tuple[str, str]] = set()
    for mapping in result:
        external = _normalize_jellyfin_path(mapping.external_prefix)
        local = str(mapping.local_prefix or "").strip()
        if not external or not local:
            continue
        key = (external.casefold(), local.replace("\\", "/").rstrip("/").casefold())
        if key in seen:
            continue
        seen.add(key)
        unique.append(PathMapping(mapping.label, external, local))
    return unique


def prepare_targeted_updates(
    updates: Iterable[dict[str, str]],
    physical_roots: Iterable[str],
) -> tuple[list[dict[str, str]], int]:
    """Validate Jellyfin paths and add one parent-directory refresh hint.

    Jellyfin accepts ``/Library/Media/Updated`` even when a path cannot be
    resolved. Validating against ``/Library/PhysicalPaths`` prevents that
    misleading 204-success. For new files the containing folder is reported as
    modified as well, so Jellyfin refreshes the known parent (season/movie
    folder) and runs its normal discovery/media-metadata pipeline.
    """
    roots = [_normalize_jellyfin_path(root) for root in physical_roots if str(root or "").strip()]
    if not roots:
        raise JellyfinApiError("Jellyfin meldet keine physischen Mediathekspfade.")

    originals: list[dict[str, str]] = []
    parent_hints: list[dict[str, str]] = []
    invalid: list[str] = []
    seen_originals: set[tuple[str, str]] = set()
    seen_parents: set[str] = set()

    for raw in updates:
        path = _normalize_jellyfin_path(raw.get("Path", ""))
        update_type = str(raw.get("UpdateType") or "").strip().title()
        if not path or update_type not in {"Created", "Modified", "Deleted"}:
            continue
        root = _matching_root(path, roots)
        if root is None:
            invalid.append(path)
            continue
        path = _canonicalize_under_root(path, root)

        key = (path.casefold(), update_type)
        if key not in seen_originals:
            seen_originals.add(key)
            originals.append({"Path": path, "UpdateType": update_type})

        parent = _normalize_jellyfin_path(posixpath.dirname(path))
        if parent and parent.casefold() != _normalize_jellyfin_path(root).casefold():
            parent_key = parent.casefold()
            if parent_key not in seen_parents and _path_within_root(parent, root):
                seen_parents.add(parent_key)
                parent_hints.append({"Path": parent, "UpdateType": "Modified"})

    if invalid:
        sample = ", ".join(invalid[:3])
        if len(invalid) > 3:
            sample += f" (+{len(invalid) - 3} weitere)"
        roots_text = ", ".join(roots)
        raise JellyfinApiError(
            "Jellyfin-Pfadvalidierung fehlgeschlagen. "
            f"Nicht in einer Server-Mediathek: {sample}. Jellyfin kennt: {roots_text}"
        )

    return parent_hints + originals, len(parent_hints)


def build_move_updates(move_log: Iterable[dict], mappings: Iterable[PathMapping]) -> list[dict[str, str]]:
    mapping_list = list(mappings)
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entry in move_log or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("kind", "video") != "video" or not entry.get("ok"):
            continue
        destination = str(entry.get("dest_path") or "").strip()
        if not destination:
            continue
        replacement = bool(
            entry.get("deleted_existing")
            or entry.get("replaced_existing")
            or entry.get("episode_identity_replacement")
        )
        if replacement:
            for old_path in entry.get("conflict_paths") or []:
                old_text = str(old_path or "").strip()
                if not old_text:
                    continue
                old_mapped = map_local_to_external_path(old_text, mapping_list)
                old_key = (old_mapped.casefold(), "Deleted")
                if old_key in seen:
                    continue
                seen.add(old_key)
                result.append({"Path": old_mapped, "UpdateType": "Deleted"})

        mapped = map_local_to_external_path(destination, mapping_list)
        key = (mapped.casefold(), "Created")
        if key in seen:
            continue
        seen.add(key)
        result.append({"Path": mapped, "UpdateType": "Created"})
    return result


def build_rename_updates(
    renamed_paths: Iterable[tuple[str, str]],
    mappings: Iterable[PathMapping],
) -> list[dict[str, str]]:
    mapping_list = list(mappings)
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for old_path, new_path in renamed_paths:
        for path, update_type in ((old_path, "Deleted"), (new_path, "Created")):
            text = str(path or "").strip()
            if not text:
                continue
            mapped = map_local_to_external_path(text, mapping_list)
            key = (mapped.casefold(), update_type)
            if key in seen:
                continue
            seen.add(key)
            result.append({"Path": mapped, "UpdateType": update_type})
    return result


def execute_refresh(
    config: JellyfinRefreshConfig,
    updates: Iterable[dict[str, str]],
    *,
    client_factory=JellyfinClient,
) -> JellyfinRefreshResult:
    update_list = list(updates)
    client = client_factory(config.server_url, config.api_key)
    if config.refresh_mode == "full":
        full_scan = start_full_scan_if_needed(client, config.server_url)
        message = (
            "Vollständiger Jellyfin-Bibliotheksscan gestartet."
            if full_scan.started
            else "Jellyfin-Bibliotheksscan läuft bereits; vorhandener Scan wird weiterverwendet."
        )
        return JellyfinRefreshResult(
            ok=True,
            mode="full",
            update_count=len(update_list),
            full_scan_reused=full_scan.reused,
            message=message,
        )

    if not update_list:
        return JellyfinRefreshResult(
            ok=True,
            mode="targeted",
            update_count=0,
            message="Keine Jellyfin-Pfadänderung zu melden.",
        )

    try:
        physical_roots = client.get_physical_paths()
        targeted_updates, parent_hint_count = prepare_targeted_updates(update_list, physical_roots)
        client.notify_media_updates(targeted_updates)
    except JellyfinApiError as exc:
        if not config.fallback_full_scan:
            raise
        full_scan = start_full_scan_if_needed(client, config.server_url)
        action = (
            "vollständiger Scan gestartet"
            if full_scan.started
            else "bereits laufender vollständiger Scan wird weiterverwendet"
        )
        return JellyfinRefreshResult(
            ok=True,
            mode="full",
            update_count=len(update_list),
            fallback_used=True,
            full_scan_reused=full_scan.reused,
            message=f"Gezielte Jellyfin-Aktualisierung fehlgeschlagen; {action}: {exc}",
        )

    suffix = (
        f" Zusätzlich {parent_hint_count} Zielordner für Erkennung/Metadatenanalyse gemeldet."
        if parent_hint_count
        else ""
    )
    return JellyfinRefreshResult(
        ok=True,
        mode="targeted",
        update_count=len(update_list),
        message=f"Jellyfin über {len(update_list)} Pfadänderung(en) informiert.{suffix}",
    )
