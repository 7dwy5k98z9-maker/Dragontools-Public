# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
import threading
import uuid
from pathlib import Path

from .tool_runner import run_tool
from .log_dispatch import dispatch_log
from .trickplay_commit import commit_generated_root, commit_missing_variant
from .trickplay_concurrency import trickplay_semaphore, trickplay_target_lock
from .trickplay_ffmpeg import (
    build_trickplay_ffmpeg_cmd,
    command_hwaccel_label,
    hwaccel_label,
    normalized_hwaccel,
    trickplay_ffmpeg_strategies,
)
from .trickplay_models import TrickplayFfmpegStrategy, TrickplaySettings
from .trickplay_sprite_verification import verify_command_sprites
from .trickplay_paths import (
    has_valid_trickplay_sprites,
    normalize_trickplay_conflict_mode,
    trickplay_root_for_video,
    trickplay_sprite_dir_for_video,
    unique_trickplay_backup_path,
)

TRICKPLAY_RUNTIME_TIMEOUT_S = 6 * 60 * 60

# Private compatibility aliases for existing tests/extensions.
_TrickplayFfmpegStrategy = TrickplayFfmpegStrategy
_normalized_hwaccel = normalized_hwaccel
_ffmpeg_strategies = trickplay_ffmpeg_strategies
_hwaccel_label = hwaccel_label
_command_hwaccel_label = command_hwaccel_label
_unique_backup_path = unique_trickplay_backup_path
_trickplay_semaphore = trickplay_semaphore


class TrickplayGenerator:
    def __init__(
        self,
        *,
        ffmpeg_path: str,
        log,
        worker=None,
        timeout_s: int | float = TRICKPLAY_RUNTIME_TIMEOUT_S,
    ) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.log = log
        self.worker = worker
        self.timeout_s = max(0.05, float(timeout_s))
        self._tool_state = threading.local()

    def generate(
        self,
        video_path: str | Path,
        settings: TrickplaySettings,
        *,
        target_video_path: str | Path | None = None,
    ) -> Path | None:
        if not settings.enabled or self._cancelled():
            return None
        video = Path(video_path)
        if not video.exists() or not self.ffmpeg_path:
            self._warn("Trickplay übersprungen: Video oder ffmpeg nicht gefunden.")
            return None

        target_video = Path(target_video_path) if target_video_path else video
        final_root = trickplay_root_for_video(target_video)
        final_sprite_dir = trickplay_sprite_dir_for_video(target_video, settings)
        if normalize_trickplay_conflict_mode(settings) == "skip" and has_valid_trickplay_sprites(final_sprite_dir):
            self._info(f"Trickplay vorhanden, wird übernommen: {final_root.name}")
            return final_root
        if normalize_trickplay_conflict_mode(settings) == "skip" and final_sprite_dir.exists():
            self._warn(
                "Trickplay-Variante existiert, enthält aber keine gültigen JPEGs; "
                "sie wird sicher neu aufgebaut."
            )

        max_jobs = max(1, min(int(settings.max_jobs or 1), 8))
        try:
            with trickplay_target_lock(final_root, abort_check=self._cancelled):
                with trickplay_semaphore(max_jobs, abort_check=self._cancelled):
                    return self._generate_locked(video, settings, final_root, final_sprite_dir)
        except (OSError, RuntimeError) as exc:
            self._warn(f'Trickplay konnte nicht erstellt werden: {exc}')
            return None

    def _cancelled(self):
        return bool(getattr(self.worker, 'abort_requested', False))

    def _generate_locked(
        self,
        video: Path,
        settings: TrickplaySettings,
        final_root: Path,
        final_sprite_dir: Path,
    ) -> Path | None:
        prepared = self._prepare_partial_root(final_root, final_sprite_dir)
        if prepared is None:
            return None
        partial_root, partial_sprite_dir = prepared
        self._info(
            "Trickplay: Sprite-Erstellung startet "
            f"({settings.width}px, {settings.tile_label}, alle {settings.interval_s}s, qscale {settings.qscale})."
        )
        try:
            return self._render_and_commit(video, settings, final_root, final_sprite_dir,
                                           partial_root, partial_sprite_dir)
        finally:
            shutil.rmtree(partial_root, ignore_errors=True)

    def _render_and_commit(self, video, settings, final_root, final_sprite_dir,
                           partial_root, partial_sprite_dir):
        success_message = self._render_sprites(video, settings, partial_sprite_dir)
        if not success_message or self._cancelled():
            self._warn("Trickplay konnte nicht erstellt werden.")
            return None
        self._info(success_message)

        conflict_mode = normalize_trickplay_conflict_mode(settings)
        if final_root.exists() and conflict_mode == "skip":
            return commit_missing_variant(
                partial_root=partial_root,
                partial_sprite_dir=partial_sprite_dir,
                final_root=final_root,
                final_sprite_dir=final_sprite_dir,
                info=self._info,
                warn=self._warn,
            )
        return self._commit_generated_root(
            partial_root=partial_root,
            final_root=final_root,
            final_sprite_dir=final_sprite_dir,
            conflict_mode=conflict_mode,
        )

    def _prepare_partial_root(self, final_root: Path, final_sprite_dir: Path) -> tuple[Path, Path] | None:
        partial_root = final_root.with_name(f"{final_root.name}.__partial__{uuid.uuid4().hex}")
        try:
            partial_sprite_dir = partial_root / final_sprite_dir.name
            partial_sprite_dir.mkdir(parents=True, exist_ok=False)
            return partial_root, partial_sprite_dir
        except OSError as exc:
            self._warn(f"Trickplay-Staging konnte nicht sauber vorbereitet werden: {exc}")
            return None

    def _render_sprites(
        self,
        video: Path,
        settings: TrickplaySettings,
        partial_sprite_dir: Path,
    ) -> str:
        output_pattern = partial_sprite_dir / "%d.jpg"
        for index, strategy in enumerate(trickplay_ffmpeg_strategies(settings.hwaccel)):
            if self._cancelled():
                return ''
            if index and not self._clear_partial_sprite_dir(partial_sprite_dir):
                self._warn(
                    "Trickplay-Retry abgebrochen: vorherige Teilbilder konnten nicht sicher bereinigt werden."
                )
                return ""
            if strategy.before_message:
                self._warn(strategy.before_message)
            self._info(strategy.start_message)
            cmd = self._build_ffmpeg_cmd(
                video,
                output_pattern,
                settings,
                hwaccel=strategy.hwaccel,
                force_hwdownload=strategy.force_hwdownload,
            )
            ok = self._run(cmd)
            if self._cancelled() or getattr(self._tool_state, 'stopped', False):
                return ''
            if ok and has_valid_trickplay_sprites(partial_sprite_dir):
                return strategy.success_message
            if ok:
                self._warn(f"Trickplay: {strategy.name} beendet, aber keine Kachelbilder erzeugt.")
        return ""

    def _build_ffmpeg_cmd(
        self,
        video: Path,
        output_pattern: Path,
        settings: TrickplaySettings,
        *,
        hwaccel: str,
        force_hwdownload: bool = False,
    ) -> list[str]:
        return build_trickplay_ffmpeg_cmd(
            self.ffmpeg_path,
            video,
            output_pattern,
            settings,
            hwaccel=hwaccel,
            force_hwdownload=force_hwdownload,
        )

    def _commit_generated_root(
        self,
        *,
        partial_root: Path,
        final_root: Path,
        final_sprite_dir: Path,
        conflict_mode: str,
    ) -> Path | None:
        return commit_generated_root(
            partial_root=partial_root,
            final_root=final_root,
            final_sprite_dir=final_sprite_dir,
            conflict_mode=conflict_mode,
            info=self._info,
            warn=self._warn,
        )

    def _run(self, cmd: list[str]) -> bool:
        self._tool_state.stopped = False
        try:
            result = run_tool(
                cmd,
                label=f"Trickplay ffmpeg ({command_hwaccel_label(cmd)})",
                timeout_s=self.timeout_s,
                worker=self.worker,
                log=self._runner_log,
                abort_on_request=True,
                activity_file=self._activity_file_from_command(cmd),
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._warn(f"Trickplay-Fehler: {exc}")
            return False
        self._tool_state.stopped = bool(result.aborted or result.timed_out)
        if not self._handle_run_result(result, cmd):
            return False
        if not verify_command_sprites(cmd):
            self._warn('Trickplay: JPEGs fehlen, sind beschädigt oder haben eine falsche Kachelgröße.')
            return False
        return True

    @staticmethod
    def _activity_file_from_command(cmd: list[str]) -> str | None:
        try:
            index = cmd.index("-i")
            return str(cmd[index + 1])
        except (ValueError, IndexError):
            return None

    def _handle_run_result(self, result, cmd: list[str]) -> bool:
        if result.aborted:
            self._warn("Trickplay abgebrochen.")
            return False
        if result.timed_out:
            self._warn(f"Trickplay ffmpeg wurde nach {self.timeout_s:.0f}s wegen Runtime-Timeout beendet.")
            return False
        if result.returncode == 0:
            return True
        self._warn(f"Trickplay ffmpeg ({command_hwaccel_label(cmd)}) beendet mit Code {result.returncode}.")
        stderr_lines = result.stderr.splitlines()[-10:] if result.stderr else []
        for line in stderr_lines:
            self._warn(f"Trickplay ffmpeg: {line}")
        if not stderr_lines:
            self._warn("Trickplay ffmpeg: keine Detailausgabe erhalten.")
        return False

    def _runner_log(self, message: str, level: str = "info") -> None:
        (self._warn if str(level).lower() in {"warn", "warning", "error"} else self._info)(message)

    def _clear_partial_sprite_dir(self, partial_sprite_dir: Path) -> bool:
        try:
            shutil.rmtree(partial_sprite_dir)
            partial_sprite_dir.mkdir(parents=True, exist_ok=False)
            return True
        except OSError as exc:
            self._warn(f"Trickplay-Teilbilder konnten nicht bereinigt werden: {exc}")
            return False

    def _info(self, message: str) -> None:
        dispatch_log(self.log, message, "info")

    def _warn(self, message: str) -> None:
        dispatch_log(self.log, message, "warn")


__all__ = [
    "TRICKPLAY_RUNTIME_TIMEOUT_S",
    "TrickplayGenerator",
    "TrickplaySettings",
    "normalize_trickplay_conflict_mode",
    "trickplay_root_for_video",
    "trickplay_sprite_dir_for_video",
]
