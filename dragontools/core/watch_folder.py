# -*- coding: utf-8 -*-
"""Qt-free Watch-Folder discovery and stability tracking."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from .watch_folder_observations import WatchObservationState, file_signature

from .path_syntax import is_video_file, normalize_user_path, path_compare_key, strip_long_path_prefix, to_long_path

_ALLOWED_CODECS = {"h265", "h264", "av1"}
_MANAGED_DIRECTORY_NAMES = {
    "archiv",
    "fehler",
    "__temp_overwrite__",
    "__temp_dv_remux__",
}
_MANAGED_DIRECTORY_PREFIXES = (
    "dragontools_",
)


def _is_managed_directory_name(name: str) -> bool:
    folded = str(name or "").casefold()
    return (
        folded in _MANAGED_DIRECTORY_NAMES
        or folded.startswith(_MANAGED_DIRECTORY_PREFIXES)
        or (folded.startswith(".") and folded.endswith(".partial"))
    )


@dataclass(frozen=True)
class WatchFolderRule:
    rule_id: str
    name: str
    path: str
    recursive: bool = True
    codec: str = "h265"
    profile_key: str = ""
    auto_start: bool = True
    enabled: bool = True

    @classmethod
    def from_mapping(cls, raw) -> "WatchFolderRule | None":
        if not isinstance(raw, Mapping):
            return None
        rule_id = str(raw.get("rule_id") or "").strip()
        path = normalize_user_path(str(raw.get("path") or "").strip())
        if not rule_id or not path:
            return None
        codec = str(raw.get("codec") or "h265").strip().lower()
        if codec not in _ALLOWED_CODECS:
            codec = "h265"
        name = str(raw.get("name") or "").strip() or Path(strip_long_path_prefix(path)).name or path
        return cls(
            rule_id=rule_id,
            name=name,
            path=path,
            recursive=bool(raw.get("recursive", True)),
            codec=codec,
            profile_key=str(raw.get("profile_key") or "").strip(),
            auto_start=bool(raw.get("auto_start", True)),
            enabled=bool(raw.get("enabled", True)),
        )


@dataclass(frozen=True)
class WatchFolderCandidate:
    rule_id: str
    path: str
    signature: str
    codec: str
    profile_key: str
    auto_start: bool


def _iter_rule_files(rule: WatchFolderRule):
    root = to_long_path(rule.path)
    if not root or not os.path.isdir(root):
        return
    if rule.recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            # Only prune descendants.  The configured watch root itself is
            # intentionally still valid even when its basename is e.g. Archiv.
            dirnames[:] = [name for name in dirnames if not _is_managed_directory_name(name)]
            for filename in filenames:
                path = strip_long_path_prefix(os.path.join(dirpath, filename))
                if is_video_file(path):
                    yield normalize_user_path(path)
        return
    try:
        entries = os.scandir(root)
    except OSError:
        return
    with entries:
        for entry in entries:
            try:
                if entry.is_file() and is_video_file(entry.name):
                    yield normalize_user_path(strip_long_path_prefix(entry.path))
            except OSError:
                continue


class WatchFolderScanner:
    """Detects stable video files and remembers acknowledged source signatures."""

    def __init__(self, *, stable_seconds: int = 60, processed_state: Mapping[str, str] | None = None) -> None:
        self.stable_seconds = max(0, int(stable_seconds))
        self._state = WatchObservationState(processed_state)

    def set_stable_seconds(self, seconds: int) -> None:
        self.stable_seconds = max(0, int(seconds))

    def scan(
        self,
        rules: list[WatchFolderRule],
        *,
        now: float | None = None,
        should_stop: Callable[[], bool] | None = None,
        stable_seconds_override: int | None = None,
    ) -> list[WatchFolderCandidate]:
        stamp = time.monotonic() if now is None else float(now)
        stable_seconds = (
            self.stable_seconds
            if stable_seconds_override is None
            else max(0, int(stable_seconds_override))
        )
        ready: list[WatchFolderCandidate] = []
        seen: set[str] = set()

        for rule in rules:
            if should_stop is not None and should_stop():
                break
            if not rule.enabled:
                continue
            for path in _iter_rule_files(rule) or ():
                if should_stop is not None and should_stop():
                    break
                key = path_compare_key(path)
                if not key or key in seen:
                    continue
                seen.add(key)
                try:
                    stat = os.stat(to_long_path(path))
                except OSError:
                    continue
                signature = file_signature(stat)
                if not self._state.ready(key, signature, stamp, stable_seconds):
                    continue
                ready.append(WatchFolderCandidate(
                    rule_id=rule.rule_id,
                    path=path,
                    signature=signature,
                    codec=rule.codec,
                    profile_key=rule.profile_key,
                    auto_start=rule.auto_start,
                ))

        self._state.prune(seen)
        return ready

    def acknowledge(self, candidate: WatchFolderCandidate) -> None:
        key = path_compare_key(candidate.path)
        if not key:
            return
        self._state.acknowledge(key, str(candidate.signature))

    def acknowledge_current(self, candidate: WatchFolderCandidate) -> str:
        """Acknowledge the post-processing on-disk signature when available.

        This is safe only when DragonTools deliberately replaced the watched
        pathname in-place.  For conversions that write elsewhere, a newer
        on-disk signature may belong to an external writer and must remain
        eligible for the next scan.
        """
        key = path_compare_key(candidate.path)
        if not key:
            return str(candidate.signature)
        signature = str(candidate.signature)
        try:
            stat = os.stat(to_long_path(candidate.path))
        except OSError:
            pass
        else:
            signature = file_signature(stat)
        self._state.acknowledge(key, signature)
        return signature

    def acknowledge_success(
        self, candidate: WatchFolderCandidate, *, output_path: str = ""
    ) -> str:
        """Persist exactly the signature that a successful job actually owns.

        When the committed output has the same pathname as the watched source,
        DragonTools itself changed that signature and the final on-disk state
        must be acknowledged to prevent Strip-Only/overwrite feedback loops.
        If output lives elsewhere, only the originally queued signature was
        processed; a newer source signature must remain visible for requeue.
        """
        if output_path and path_compare_key(output_path) == path_compare_key(candidate.path):
            return self.acknowledge_current(candidate)
        self.acknowledge(candidate)
        return str(candidate.signature)

    def processed_state(self) -> dict[str, str]:
        return self._state.processed()


__all__ = ["WatchFolderRule", "WatchFolderCandidate", "WatchFolderScanner"]
