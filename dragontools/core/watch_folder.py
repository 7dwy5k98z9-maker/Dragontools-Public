# -*- coding: utf-8 -*-
"""Qt-free Watch-Folder discovery and stability tracking."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from .path_syntax import is_video_file, normalize_user_path, path_compare_key, strip_long_path_prefix, to_long_path

_ALLOWED_CODECS = {"h265", "h264", "av1"}


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


@dataclass
class _Observation:
    signature: str
    stable_since: float


def _signature(size: int, mtime_ns: int) -> str:
    return f"{int(size)}:{int(mtime_ns)}"


def _iter_rule_files(rule: WatchFolderRule):
    root = to_long_path(rule.path)
    if not root or not os.path.isdir(root):
        return
    if rule.recursive:
        for dirpath, _dirnames, filenames in os.walk(root):
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
        self._processed: dict[str, str] = dict(processed_state or {})
        self._observations: dict[str, _Observation] = {}

    def set_stable_seconds(self, seconds: int) -> None:
        self.stable_seconds = max(0, int(seconds))

    def scan(
        self,
        rules: list[WatchFolderRule],
        *,
        now: float | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[WatchFolderCandidate]:
        stamp = time.monotonic() if now is None else float(now)
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
                signature = _signature(stat.st_size, stat.st_mtime_ns)
                if self._processed.get(key) == signature:
                    self._observations.pop(key, None)
                    continue

                observation = self._observations.get(key)
                if observation is None or observation.signature != signature:
                    self._observations[key] = _Observation(signature, stamp)
                    if self.stable_seconds > 0:
                        continue
                    observation = self._observations[key]

                if stamp - observation.stable_since < self.stable_seconds:
                    continue
                ready.append(WatchFolderCandidate(
                    rule_id=rule.rule_id,
                    path=path,
                    signature=signature,
                    codec=rule.codec,
                    profile_key=rule.profile_key,
                    auto_start=rule.auto_start,
                ))

        for key in list(self._observations):
            if key not in seen:
                self._observations.pop(key, None)
        return ready

    def acknowledge(self, candidate: WatchFolderCandidate) -> None:
        key = path_compare_key(candidate.path)
        if not key:
            return
        self._processed[key] = str(candidate.signature)
        self._observations.pop(key, None)

    def acknowledge_current(self, candidate: WatchFolderCandidate) -> str:
        """Acknowledge the post-processing on-disk signature when available.

        Overwrite-in-place workflows (notably Strip-Only) replace the watched
        source with a new file.  Acknowledging only the *pre*-conversion
        signature would make the next scan treat DragonTools' own output as a
        fresh input and enqueue it again.  Use the current size/mtime after a
        successful job so the produced file is considered handled.  If the
        source was moved away, fall back to the original candidate signature.
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
            signature = _signature(stat.st_size, stat.st_mtime_ns)
        self._processed[key] = signature
        self._observations.pop(key, None)
        return signature

    def processed_state(self) -> dict[str, str]:
        return dict(self._processed)


__all__ = ["WatchFolderRule", "WatchFolderCandidate", "WatchFolderScanner"]
