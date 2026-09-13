# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path

from ..core.jellyfin_nfo import write_episode_nfo, write_movie_nfo
from ..core.online_metadata import OnlineMetadataAuthError, OnlineMetadataError
from ..rules.move_rules import parse_series_match_details
from .postprocess_config import config_from_settings
from .log_dispatch import dispatch_log
from .postprocess_metadata import PostProcessMetadataSession
from .postprocess_models import NfoSettings, PostProcessItem, PostProcessRunResult
from .trickplay_service import (
    TrickplayGenerator,
    normalize_trickplay_conflict_mode,
    trickplay_root_for_video,
    trickplay_sprite_dir_for_video,
)


class PostProcessService:
    def __init__(self, *, settings, tools, log, worker=None, metadata_session=None) -> None:
        self.settings = settings
        self.tools = tools
        self.log = log
        self.worker = worker
        self.metadata_session = metadata_session or PostProcessMetadataSession(settings)
        self.last_items: list[dict[str, str]] = []

    def is_enabled(self) -> bool:
        try:
            return config_from_settings(self.settings).enabled
        except Exception:
            return False

    def run(self, *, input_path: str, output_path: str) -> list[str]:
        return self.run_result(input_path=input_path, output_path=output_path).created_paths

    def run_result(self, *, input_path: str, output_path: str) -> PostProcessRunResult:
        self.last_items = []
        output = Path(output_path)
        if not output.exists():
            return PostProcessRunResult([], [])
        cfg = config_from_settings(self.settings)
        if not cfg.enabled:
            return PostProcessRunResult([], [])

        created: list[str] = []
        nfo_path = self._create_nfo(input_path=input_path, output_path=output, cfg=cfg.nfo)
        if nfo_path:
            created.append(str(nfo_path))

        trickplay_input = input_path if cfg.trickplay.source_mode == "source" else output
        trickplay_mode = normalize_trickplay_conflict_mode(cfg.trickplay)
        trickplay_final_root = trickplay_root_for_video(output)
        trickplay_final_sprite = trickplay_sprite_dir_for_video(output, cfg.trickplay)
        trickplay_root_exists = trickplay_final_root.exists()
        trickplay_sprite_exists = trickplay_final_sprite.exists()
        trickplay_root = TrickplayGenerator(
            ffmpeg_path=getattr(self.tools, "ffmpeg", ""),
            log=self.log,
            worker=self.worker,
        ).generate(trickplay_input, cfg.trickplay, target_video_path=output)
        if trickplay_root:
            created.append(str(trickplay_root))
            status = "created"
            if trickplay_mode == "skip" and trickplay_sprite_exists:
                status = "skipped"
            elif trickplay_mode == "skip" and trickplay_root_exists:
                status = "created_variant"
            elif trickplay_mode == "backup" and trickplay_root_exists:
                status = "backed_up"
            elif trickplay_mode == "overwrite" and trickplay_root_exists:
                status = "replaced"
            self._record("trickplay", status, str(trickplay_root))
        elif cfg.trickplay.enabled:
            self._record("trickplay", "error", "", "Trickplay konnte nicht erstellt werden.")

        return PostProcessRunResult(created, [dict(item) for item in self.last_items])

    def _create_nfo(self, *, input_path: str, output_path: Path, cfg: NfoSettings) -> Path | None:
        if not cfg.enabled:
            return None
        try:
            parsed_series = parse_series_match_details(Path(input_path).name)
            if parsed_series and parsed_series.get("series"):
                try:
                    suggestion = self.metadata_session.resolve_episode_file(input_path)
                except OnlineMetadataAuthError as exc:
                    self._warn(f"NFO übersprungen: {exc}")
                    self._record("nfo", "skipped", "", str(exc))
                    return None
                if suggestion is None:
                    self._warn("NFO übersprungen: keine passende Serienfolge gefunden.")
                    self._record("nfo", "skipped", "", "Keine passende Serienfolge gefunden.")
                    return None
                target, status, should_write = self._prepare_nfo_path(output_path.with_suffix(".nfo"), cfg)
                if target is None:
                    self._record("nfo", status, "", "NFO konnte nicht vorbereitet werden.")
                    return None
                if not should_write:
                    self._record("nfo", status, str(target), "Vorhandene NFO wurde beibehalten.")
                    return target
                write_episode_nfo(
                    target,
                    suggestion,
                    video_path=output_path,
                    ffprobe_path=getattr(self.tools, "ffprobe", ""),
                    include_fileinfo=cfg.include_fileinfo,
                )
                self._info(f"NFO erstellt: {target.name}")
                self._record("nfo", status, str(target))
                return target

            try:
                suggestion = self.metadata_session.resolve_movie_file(input_path)
            except OnlineMetadataAuthError as exc:
                self._warn(f"NFO übersprungen: {exc}")
                self._record("nfo", "skipped", "", str(exc))
                return None
            if suggestion is None:
                self._warn("NFO übersprungen: kein passender Metadaten-Film gefunden.")
                self._record("nfo", "skipped", "", "Kein passender Metadaten-Film gefunden.")
                return None
            target, status, should_write = self._prepare_nfo_path(output_path.with_suffix(".nfo"), cfg)
            if target is None:
                self._record("nfo", status, "", "NFO konnte nicht vorbereitet werden.")
                return None
            if not should_write:
                self._record("nfo", status, str(target), "Vorhandene NFO wurde beibehalten.")
                return target
            write_movie_nfo(
                target,
                suggestion,
                video_path=output_path,
                ffprobe_path=getattr(self.tools, "ffprobe", ""),
                include_fileinfo=cfg.include_fileinfo,
            )
            self._info(f"NFO erstellt: {target.name}")
            self._record("nfo", status, str(target))
            return target
        except OnlineMetadataError as exc:
            self._warn(f"NFO übersprungen: {exc}")
            self._record("nfo", "skipped", "", str(exc))
            return None
        except Exception as exc:
            self._warn(f"NFO konnte nicht erstellt werden: {exc}")
            self._record("nfo", "error", "", str(exc))
            return None

    def _prepare_nfo_path(self, target: Path, cfg: NfoSettings) -> tuple[Path | None, str, bool]:
        if not target.exists():
            return target, "created", True
        if cfg.conflict_mode == "skip":
            self._info(f"NFO vorhanden, wird übernommen: {target.name}")
            return target, "skipped", False
        if cfg.conflict_mode == "backup":
            backup = _unique_path(target.with_suffix(target.suffix + ".bak"))
            os.replace(str(target), str(backup))
            self._info(f"Vorhandene NFO gesichert: {backup.name}")
            return target, "backed_up", True
        try:
            target.unlink()
        except OSError as exc:
            self._warn(f"Vorhandene NFO konnte nicht ersetzt werden: {exc}")
            return None, "error", False
        return target, "replaced", True

    def _info(self, message: str) -> None:
        dispatch_log(self.log, message, "info")

    def _warn(self, message: str) -> None:
        dispatch_log(self.log, message, "warn")

    def _record(self, kind: str, status: str, path: str = "", message: str = "") -> None:
        item = PostProcessItem(
            kind=str(kind or "postprocess"),
            status=str(status or "unknown"),
            path=str(path or ""),
            message=str(message or ""),
        )
        self.last_items.append(dict(item.__dict__))


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for idx in range(1, 1000):
        candidate = parent / f"{stem}_{idx:02d}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Kein freier Dateiname gefunden: {path.name}")
