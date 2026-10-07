# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import uuid

from ..core.jellyfin_nfo import build_planned_fileinfo, write_episode_nfo, write_movie_nfo
from ..core.online_metadata import OnlineMetadataAuthError, OnlineMetadataError
from ..rules.move_rules import parse_series_match_details
from .postprocess_config import config_from_settings
from .log_dispatch import dispatch_log
from .postprocess_metadata import PostProcessMetadataSession
from .postprocess_metadata_identity import metadata_lookup_path
from .postprocess_models import NfoSettings, PostProcessItem, PostProcessRunResult, PreparedNfo
from .nfo_commit import (
    commit_nfo,
    commit_prepared_nfo as install_prepared_nfo,
    nfo_target_lock,
    plan_nfo_target,
    unique_nfo_backup_path,
)
from .trickplay_service import (
    TrickplayGenerator,
    normalize_trickplay_conflict_mode,
    trickplay_root_for_video,
    trickplay_sprite_dir_for_video,
)
from .postprocess_nfo_ownership import file_identity, validate_prepared_nfo, discard_owned_nfo
from .postprocess_source_trickplay import prepare_source_trickplay, install_source_trickplay, discard_source_trickplay
from .trickplay_paths import trickplay_result_status


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
            return config_from_settings(self.settings).after_conversion_enabled
        except Exception:
            return False

    def is_nfo_during_enabled(self) -> bool:
        try:
            cfg = config_from_settings(self.settings).nfo
            return bool(cfg.enabled and cfg.timing == "during")
        except Exception:
            return False

    def prepare_nfo_during_conversion(
        self,
        *,
        input_path: str,
        output_path: str,
        final_output_path: str,
        media_info=None,
        media_contract=None,
    ) -> PreparedNfo | None:
        """Render an NFO while the video encode is running, but do not publish it yet."""
        cfg = config_from_settings(self.settings).nfo
        if not (cfg.enabled and cfg.timing == "during"):
            return None

        target = Path(final_output_path).with_suffix(".nfo")
        try:
            media_kind, suggestion, reason = self._resolve_nfo_suggestion(input_path, cfg)
            if suggestion is None:
                message = reason or "Kein passender Metadaten-Treffer gefunden."
                self._warn(f"NFO übersprungen: {message}")
                return PreparedNfo(
                    staging_path="",
                    target_path=str(target),
                    conflict_mode=cfg.conflict_mode,
                    kind=media_kind or "unknown",
                    suggestion=None,
                    include_fileinfo=cfg.include_fileinfo,
                    status="skipped",
                    message=message,
                )

            output = Path(output_path)
            staging = output.with_name(
                f".{output.stem}.__nfo_during__{uuid.uuid4().hex}.nfo"
            )
            planned = build_planned_fileinfo(media_info, media_contract) if cfg.include_fileinfo else None
            self._render_prepared_nfo(
                path=staging,
                media_kind=media_kind,
                suggestion=suggestion,
                include_fileinfo=cfg.include_fileinfo,
                planned_fileinfo=planned,
            )
            self._info(f"NFO während Konvertierung vorbereitet: {target.name}")
            return PreparedNfo(
                staging_path=str(staging),
                target_path=str(target),
                conflict_mode=cfg.conflict_mode,
                kind=media_kind,
                suggestion=suggestion,
                include_fileinfo=cfg.include_fileinfo,
                staging_identity=file_identity(staging),
            )
        except OnlineMetadataError as exc:
            self._warn(f"NFO übersprungen: {exc}")
            return PreparedNfo(
                staging_path="",
                target_path=str(target),
                conflict_mode=cfg.conflict_mode,
                kind="unknown",
                suggestion=None,
                include_fileinfo=cfg.include_fileinfo,
                status="skipped",
                message=str(exc),
            )
        except Exception as exc:
            self._warn(f"NFO konnte während der Konvertierung nicht vorbereitet werden: {exc}")
            return PreparedNfo(
                staging_path="",
                target_path=str(target),
                conflict_mode=cfg.conflict_mode,
                kind="unknown",
                suggestion=None,
                include_fileinfo=cfg.include_fileinfo,
                status="error",
                message=str(exc),
            )

    def refresh_prepared_nfo(
        self,
        prepared: PreparedNfo | None,
        *,
        media_info=None,
        media_contract=None,
        video_path: str | None = None,
    ) -> PreparedNfo | None:
        """Refresh technical fields at the verified-output boundary.

        The pre-encode media contract is retained as a fallback, but once the
        encoded candidate exists we probe that actual file.  This prevents the
        fast "during" mode from publishing stale source/plan stream metadata.
        """
        if prepared is None or prepared.status != "prepared" or not prepared.staging_path:
            return prepared
        try:
            validate_prepared_nfo(prepared, Path(video_path)) if video_path else None
            planned = build_planned_fileinfo(media_info, media_contract) if prepared.include_fileinfo else None
            self._render_prepared_nfo(
                path=Path(prepared.staging_path),
                media_kind=prepared.kind,
                suggestion=prepared.suggestion,
                include_fileinfo=prepared.include_fileinfo,
                planned_fileinfo=planned,
                video_path=video_path,
            )
            if prepared.staging_identity is not None:
                prepared.staging_identity = file_identity(prepared.staging_path)
        except Exception as exc:
            prepared.status = "error"
            prepared.message = str(exc)
            self._warn(f"Vorbereitete NFO konnte nicht aktualisiert werden: {exc}")
        return prepared

    def commit_prepared_nfo(
        self,
        prepared: PreparedNfo | None,
        *,
        final_output_path: str,
    ) -> PostProcessRunResult:
        if prepared is None:
            return PostProcessRunResult([], [])
        target = Path(final_output_path).with_suffix(".nfo")
        if prepared.status != "prepared" or not prepared.staging_path:
            path = str(target) if prepared.status == "skipped" and target.exists() else ""
            created = [path] if path else []
            discard_owned_nfo(prepared)
            return PostProcessRunResult(created, [{
                "kind": "nfo",
                "status": prepared.status,
                "path": path,
                "message": prepared.message,
            }])

        staging = Path(prepared.staging_path)
        try:
            validate_prepared_nfo(prepared, Path(final_output_path), require_target=True)
            with nfo_target_lock(target):
                plan = plan_nfo_target(target, prepared.conflict_mode)
                if not plan.should_write:
                    self._info(f"NFO vorhanden, wird übernommen: {plan.target.name}")
                    return PostProcessRunResult([str(plan.target)], [{
                        "kind": "nfo",
                        "status": plan.status,
                        "path": str(plan.target),
                        "message": "Vorhandene NFO wurde beibehalten.",
                    }])
                installed, backup = install_prepared_nfo(plan, staging)
                if backup is not None:
                    self._info(f"Vorhandene NFO gesichert: {backup.name}")
                self._info(f"NFO installiert: {installed.name}")
                return PostProcessRunResult([str(installed)], [{
                    "kind": "nfo",
                    "status": plan.status,
                    "path": str(installed),
                    "message": "",
                }])
        except Exception as exc:
            self._warn(f"Vorbereitete NFO konnte nicht installiert werden: {exc}")
            return PostProcessRunResult([], [{
                "kind": "nfo",
                "status": "error",
                "path": "",
                "message": str(exc),
            }])
        finally:
            discard_owned_nfo(prepared)

    @staticmethod
    def discard_prepared_nfo(prepared: PreparedNfo | None) -> None:
        discard_owned_nfo(prepared)

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
        generator = TrickplayGenerator(ffmpeg_path=getattr(self.tools, 'ffmpeg', ''),
            log=self.log, worker=self.worker)
        return prepare_source_trickplay(
            generator, source=Path(input_path), output=Path(output_path),
            settings=cfg.trickplay,
        )

    def discard_prepared_source_trickplay(
        self, input_path: str, *, cleanup: bool = False
    ) -> None:
        # Compatibility no-op: prepared state is carried by the workflow/Future
        # contract, never by a shared PostProcessService instance.
        return None

    def run_result(
        self, *, input_path, output_path, prepared_source_trickplay=None,
    ) -> PostProcessRunResult:
        try:
            return self._run_result(input_path=input_path, output_path=output_path,
                prepared_source_trickplay=prepared_source_trickplay)
        finally:
            discard_source_trickplay(prepared_source_trickplay)

    def _run_result(
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
        if not cfg.after_conversion_enabled:
            return PostProcessRunResult([], [])

        created: list[str] = []
        if cfg.nfo.enabled and cfg.nfo.timing == "after":
            nfo_path = self._create_nfo(input_path=input_path, output_path=output, cfg=cfg.nfo)
            if nfo_path:
                created.append(str(nfo_path))

        prepared = prepared_source_trickplay
        if prepared is not None and prepared.prepared_trickplay is not None and cfg.trickplay.enabled:
            result = install_source_trickplay(prepared, output=output, worker=self.worker,
                info=self._info, warn=self._warn)
            created.extend(result.created_paths)
            self.last_items.extend(result.items)
        elif prepared is not None and cfg.trickplay.source_mode == "source":
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

        status = trickplay_result_status(trickplay_mode, root_exists=root_exists, variant_exists=sprite_exists)
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
            media_kind, suggestion, reason = self._resolve_nfo_suggestion(input_path, cfg)
            if suggestion is None:
                message = reason or "Kein passender Metadaten-Treffer gefunden."
                self._warn(f"NFO übersprungen: {message}")
                self._record("nfo", "skipped", "", message)
                return None

            nfo_target = output_path.with_suffix(".nfo")
            # Conflict handling is a read-then-write transaction.  Keep the
            # plan and commit under one keyed lock so two background jobs cannot
            # both observe "missing" and violate conflict_mode=skip.
            with nfo_target_lock(nfo_target):
                plan = plan_nfo_target(nfo_target, cfg.conflict_mode)
                if not plan.should_write:
                    self._info(f"NFO vorhanden, wird übernommen: {plan.target.name}")
                    self._record(
                        "nfo",
                        plan.status,
                        str(plan.target),
                        "Vorhandene NFO wurde beibehalten.",
                    )
                    return plan.target

                def writer(candidate: Path) -> None:
                    kwargs = {
                        "video_path": output_path,
                        "ffprobe_path": getattr(self.tools, "ffprobe", ""),
                        "include_fileinfo": cfg.include_fileinfo,
                    }
                    if media_kind == "episode":
                        write_episode_nfo(candidate, suggestion, **kwargs)
                    else:
                        write_movie_nfo(candidate, suggestion, **kwargs)

                target, backup = commit_nfo(plan, writer)
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

    def _resolve_nfo_suggestion(self, input_path: str, cfg: NfoSettings):
        input_path = metadata_lookup_path(self.worker, input_path)
        parsed_series = parse_series_match_details(Path(input_path).name)
        if parsed_series and parsed_series.get("series"):
            resolution = self.metadata_session.resolve_episode(
                input_path,
                require_unambiguous=cfg.only_unambiguous,
            )
            return (
                "episode",
                resolution.suggestion,
                getattr(resolution, "reason", "") or "Keine passende Serienfolge gefunden.",
            )
        resolution = self.metadata_session.resolve_movie(
            input_path,
            require_unambiguous=cfg.only_unambiguous,
        )
        return (
            "movie",
            resolution.suggestion,
            getattr(resolution, "reason", "") or "Kein passender Metadaten-Film gefunden.",
        )

    def _render_prepared_nfo(
        self,
        *,
        path: Path,
        media_kind: str,
        suggestion,
        include_fileinfo: bool,
        planned_fileinfo,
        video_path: str | None = None,
    ) -> None:
        kwargs = {
            "video_path": video_path,
            "ffprobe_path": getattr(self.tools, "ffprobe", ""),
            "include_fileinfo": include_fileinfo,
            "planned_fileinfo": planned_fileinfo,
        }
        if media_kind == "episode":
            write_episode_nfo(path, suggestion, **kwargs)
        else:
            write_movie_nfo(path, suggestion, **kwargs)

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
