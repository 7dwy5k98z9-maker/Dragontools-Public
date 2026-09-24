# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil

from ..core.jellyfin_nfo import write_episode_nfo, write_movie_nfo
from ..core.online_metadata import OnlineMetadataAuthError, OnlineMetadataError
from ..rules.move_rules import parse_series_match_details
from .postprocess_config import config_from_settings
from .log_dispatch import dispatch_log
from .postprocess_metadata import PostProcessMetadataSession
from .postprocess_models import NfoSettings, PostProcessItem, PostProcessRunResult
from .nfo_commit import commit_nfo, plan_nfo_target, unique_nfo_backup_path
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

    def create_nfo_only(self, *, media_path: str) -> PostProcessRunResult:
        """Create a missing NFO for an existing library item without other post-processing.

        Fix-Queue repairs are intentionally create-only: even if the normal NFO
        policy is configured to overwrite or back up, this helper uses ``skip``
        so a file that appeared after issue discovery is never replaced.
        """
        self.last_items = []
        output = Path(media_path)
        if not output.exists():
            return PostProcessRunResult([], [{
                "kind": "nfo", "status": "error", "path": "",
                "message": "Mediendatei wurde nicht gefunden.",
            }])
        cfg = replace(config_from_settings(self.settings).nfo, enabled=True, conflict_mode="skip")
        nfo_path = self._create_nfo(input_path=str(output), output_path=output, cfg=cfg)
        created = [str(nfo_path)] if nfo_path else []
        return PostProcessRunResult(created, [dict(item) for item in self.last_items])

    def create_trickplay_only(self, *, media_path: str) -> PostProcessRunResult:
        """Create missing trickplay for an existing media file without replacing existing data."""
        self.last_items = []
        video = Path(media_path)
        if not video.exists():
            return PostProcessRunResult([], [{
                "kind": "trickplay", "status": "error", "path": "",
                "message": "Mediendatei wurde nicht gefunden.",
            }])
        cfg = replace(
            config_from_settings(self.settings).trickplay,
            enabled=True,
            only_missing=True,
            conflict_mode="skip",
            source_mode="output",
        )
        result = self._run_trickplay(video_input=video, target_output=video, settings=cfg)
        return PostProcessRunResult(list(result.created_paths), [dict(item) for item in result.items])

    def prepare_source_trickplay(
        self,
        *,
        input_path: str,
        output_path: str,
    ) -> PostProcessRunResult:
        """Stage source-based trickplay before a destructive overwrite.

        ``output_path`` is the anticipated final video path.  The video itself
        does not need to exist yet: Trickplay reads ``input_path`` but derives
        its companion stem from this final target.
        """
        cfg = config_from_settings(self.settings)
        if not (cfg.trickplay.enabled and cfg.trickplay.source_mode == "source"):
            return PostProcessRunResult([], [])
        return self._run_trickplay(
            video_input=Path(input_path),
            target_output=Path(output_path),
            settings=cfg.trickplay,
        )

    def discard_prepared_source_trickplay(
        self, input_path: str, *, cleanup: bool = False
    ) -> None:
        # Compatibility no-op: prepared state is carried by the workflow/Future
        # contract, never by a shared PostProcessService instance.
        return None

    def run_result(
        self,
        *,
        input_path: str,
        output_path: str,
        prepared_source_trickplay: PostProcessRunResult | None = None,
    ) -> PostProcessRunResult:
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

        prepared = prepared_source_trickplay
        if prepared is not None and cfg.trickplay.source_mode == "source":
            final_root = trickplay_root_for_video(output)
            for item in prepared.items:
                row = dict(item)
                if row.get("path"):
                    row["path"] = str(final_root)
                self.last_items.append(row)
            if prepared.created_paths and final_root.exists():
                created.append(str(final_root))
        else:
            trickplay_input = Path(input_path) if cfg.trickplay.source_mode == "source" else output
            trickplay_result = self._run_trickplay(
                video_input=trickplay_input,
                target_output=output,
                settings=cfg.trickplay,
            )
            created.extend(trickplay_result.created_paths)
            self.last_items.extend(dict(item) for item in trickplay_result.items)

        return PostProcessRunResult(created, [dict(item) for item in self.last_items])

    def _run_trickplay(self, *, video_input: Path, target_output: Path, settings) -> PostProcessRunResult:
        if not settings.enabled:
            return PostProcessRunResult([], [])
        trickplay_mode = normalize_trickplay_conflict_mode(settings)
        final_root = trickplay_root_for_video(target_output)
        final_sprite = trickplay_sprite_dir_for_video(target_output, settings)
        root_exists = final_root.exists()
        sprite_exists = final_sprite.exists()
        root = TrickplayGenerator(
            ffmpeg_path=getattr(self.tools, "ffmpeg", ""),
            log=self.log,
            worker=self.worker,
        ).generate(video_input, settings, target_video_path=target_output)
        if not root:
            return PostProcessRunResult([], [{
                "kind": "trickplay",
                "status": "error",
                "path": "",
                "message": "Trickplay konnte nicht erstellt werden.",
            }])

        status = "created"
        if trickplay_mode == "skip" and sprite_exists:
            status = "skipped"
        elif trickplay_mode == "skip" and root_exists:
            status = "created_variant"
        elif trickplay_mode == "backup" and root_exists:
            status = "backed_up"
        elif trickplay_mode == "overwrite" and root_exists:
            status = "replaced"
        return PostProcessRunResult([str(root)], [{
            "kind": "trickplay",
            "status": status,
            "path": str(root),
            "message": "",
        }])

    def _create_nfo(self, *, input_path: str, output_path: Path, cfg: NfoSettings) -> Path | None:
        if not cfg.enabled:
            return None
        try:
            parsed_series = parse_series_match_details(Path(input_path).name)
            if parsed_series and parsed_series.get("series"):
                try:
                    resolution = self.metadata_session.resolve_episode(input_path, require_unambiguous=cfg.only_unambiguous)
                    suggestion = resolution.suggestion
                except OnlineMetadataAuthError as exc:
                    self._warn(f"NFO übersprungen: {exc}")
                    self._record("nfo", "skipped", "", str(exc))
                    return None
                if suggestion is None:
                    reason = getattr(resolution, "reason", "") or "Keine passende Serienfolge gefunden."
                    self._warn(f"NFO übersprungen: {reason}")
                    self._record("nfo", "skipped", "", reason)
                    return None
                plan = plan_nfo_target(output_path.with_suffix(".nfo"), cfg.conflict_mode)
                if not plan.should_write:
                    self._info(f"NFO vorhanden, wird übernommen: {plan.target.name}")
                    self._record("nfo", plan.status, str(plan.target), "Vorhandene NFO wurde beibehalten.")
                    return plan.target
                target, backup = commit_nfo(
                    plan,
                    lambda candidate: write_episode_nfo(
                        candidate, suggestion, video_path=output_path,
                        ffprobe_path=getattr(self.tools, "ffprobe", ""),
                        include_fileinfo=cfg.include_fileinfo,
                    ),
                )
                if backup is not None:
                    self._info(f"Vorhandene NFO gesichert: {backup.name}")
                self._info(f"NFO erstellt: {target.name}")
                self._record("nfo", plan.status, str(target))
                return target

            try:
                resolution = self.metadata_session.resolve_movie(input_path, require_unambiguous=cfg.only_unambiguous)
                suggestion = resolution.suggestion
            except OnlineMetadataAuthError as exc:
                self._warn(f"NFO übersprungen: {exc}")
                self._record("nfo", "skipped", "", str(exc))
                return None
            if suggestion is None:
                reason = getattr(resolution, "reason", "") or "Kein passender Metadaten-Film gefunden."
                self._warn(f"NFO übersprungen: {reason}")
                self._record("nfo", "skipped", "", reason)
                return None
            plan = plan_nfo_target(output_path.with_suffix(".nfo"), cfg.conflict_mode)
            if not plan.should_write:
                self._info(f"NFO vorhanden, wird übernommen: {plan.target.name}")
                self._record("nfo", plan.status, str(plan.target), "Vorhandene NFO wurde beibehalten.")
                return plan.target
            target, backup = commit_nfo(
                plan,
                lambda candidate: write_movie_nfo(
                    candidate, suggestion, video_path=output_path,
                    ffprobe_path=getattr(self.tools, "ffprobe", ""),
                    include_fileinfo=cfg.include_fileinfo,
                ),
            )
            if backup is not None:
                self._info(f"Vorhandene NFO gesichert: {backup.name}")
            self._info(f"NFO erstellt: {target.name}")
            self._record("nfo", plan.status, str(target))
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
        # Legacy helper for tests/extensions. Backup mode now copies instead of
        # moving the live NFO, so the compatibility side effect is non-destructive.
        plan = plan_nfo_target(target, cfg.conflict_mode)
        if plan.conflict_mode == "backup" and target.exists():
            backup = unique_nfo_backup_path(target)
            shutil.copy2(target, backup)
        return plan.target, plan.status, plan.should_write

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

