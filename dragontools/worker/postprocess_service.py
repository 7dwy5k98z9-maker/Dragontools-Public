# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from ..core.jellyfin_nfo import write_episode_nfo, write_movie_nfo
from ..core.online_metadata import OnlineMetadataAuthError, OnlineMetadataError, client_from_settings_for
from ..core.settings import (
    DEFAULT_NFO_CONFLICT_MODE,
    DEFAULT_NFO_ENABLED,
    DEFAULT_NFO_FILEINFO_ENABLED,
    DEFAULT_NFO_MOVIE_TARGET_NAME,
    DEFAULT_NFO_ONLY_UNAMBIGUOUS,
    DEFAULT_TRICKPLAY_ENABLED,
    DEFAULT_TRICKPLAY_CONFLICT_MODE,
    DEFAULT_TRICKPLAY_HWACCEL,
    DEFAULT_TRICKPLAY_INTERVAL_S,
    DEFAULT_TRICKPLAY_JPEG_QUALITY,
    DEFAULT_TRICKPLAY_MAX_JOBS,
    DEFAULT_TRICKPLAY_ONLY_MISSING,
    DEFAULT_TRICKPLAY_QSCALE,
    DEFAULT_TRICKPLAY_SOURCE_MODE,
    DEFAULT_TRICKPLAY_TILE_COLUMNS,
    DEFAULT_TRICKPLAY_TILE_ROWS,
    DEFAULT_TRICKPLAY_WIDTH,
    SET_KEY_NFO_CONFLICT_MODE,
    SET_KEY_NFO_ENABLED,
    SET_KEY_NFO_FILEINFO_ENABLED,
    SET_KEY_NFO_MOVIE_TARGET_NAME,
    SET_KEY_NFO_ONLY_UNAMBIGUOUS,
    SET_KEY_TRICKPLAY_ENABLED,
    SET_KEY_TRICKPLAY_CONFLICT_MODE,
    SET_KEY_TRICKPLAY_HWACCEL,
    SET_KEY_TRICKPLAY_INTERVAL_S,
    SET_KEY_TRICKPLAY_JPEG_QUALITY,
    SET_KEY_TRICKPLAY_MAX_JOBS,
    SET_KEY_TRICKPLAY_ONLY_MISSING,
    SET_KEY_TRICKPLAY_QSCALE,
    SET_KEY_TRICKPLAY_SOURCE_MODE,
    SET_KEY_TRICKPLAY_TILE_COLUMNS,
    SET_KEY_TRICKPLAY_TILE_ROWS,
    SET_KEY_TRICKPLAY_WIDTH,
    settings_bool,
    settings_int,
    settings_text,
)
from ..rules.move_rules import parse_series_match_details
from .trickplay_service import (
    TrickplayGenerator,
    TrickplaySettings,
    trickplay_root_for_video,
    trickplay_sprite_dir_for_video,
    normalize_trickplay_conflict_mode,
)


@dataclass(frozen=True)
class NfoSettings:
    enabled: bool = False
    only_unambiguous: bool = True
    include_fileinfo: bool = True
    movie_target_name: str = "movie.nfo"
    conflict_mode: str = "skip"


@dataclass(frozen=True)
class PostProcessConfig:
    nfo: NfoSettings
    trickplay: TrickplaySettings

    @property
    def enabled(self) -> bool:
        return self.nfo.enabled or self.trickplay.enabled


@dataclass(frozen=True)
class PostProcessItem:
    kind: str
    status: str
    path: str = ""
    message: str = ""


@dataclass(frozen=True)
class PostProcessRunResult:
    created_paths: list[str]
    items: list[dict[str, str]]


def config_from_settings(settings) -> PostProcessConfig:
    conflict_modes = {"skip", "overwrite", "backup"}
    nfo_conflict = settings_text(
        settings,
        SET_KEY_NFO_CONFLICT_MODE,
        DEFAULT_NFO_CONFLICT_MODE,
        allowed=conflict_modes,
    )
    movie_target_name = settings_text(
        settings,
        SET_KEY_NFO_MOVIE_TARGET_NAME,
        DEFAULT_NFO_MOVIE_TARGET_NAME,
    )
    trickplay_source_mode = settings_text(
        settings,
        SET_KEY_TRICKPLAY_SOURCE_MODE,
        DEFAULT_TRICKPLAY_SOURCE_MODE,
        allowed={"output", "source"},
    )
    trickplay_conflict_mode = settings_text(
        settings,
        SET_KEY_TRICKPLAY_CONFLICT_MODE,
        "",
        allowed=conflict_modes,
    )
    if not trickplay_conflict_mode:
        only_missing = settings_bool(
            settings,
            SET_KEY_TRICKPLAY_ONLY_MISSING,
            DEFAULT_TRICKPLAY_ONLY_MISSING,
        )
        trickplay_conflict_mode = "skip" if only_missing else "overwrite"
    if trickplay_conflict_mode not in conflict_modes:
        trickplay_conflict_mode = DEFAULT_TRICKPLAY_CONFLICT_MODE

    return PostProcessConfig(
        nfo=NfoSettings(
            enabled=settings_bool(settings, SET_KEY_NFO_ENABLED, DEFAULT_NFO_ENABLED),
            only_unambiguous=settings_bool(
                settings,
                SET_KEY_NFO_ONLY_UNAMBIGUOUS,
                DEFAULT_NFO_ONLY_UNAMBIGUOUS,
            ),
            include_fileinfo=settings_bool(
                settings,
                SET_KEY_NFO_FILEINFO_ENABLED,
                DEFAULT_NFO_FILEINFO_ENABLED,
            ),
            movie_target_name=movie_target_name,
            conflict_mode=nfo_conflict,
        ),
        trickplay=TrickplaySettings(
            enabled=settings_bool(settings, SET_KEY_TRICKPLAY_ENABLED, DEFAULT_TRICKPLAY_ENABLED),
            only_missing=settings_bool(
                settings,
                SET_KEY_TRICKPLAY_ONLY_MISSING,
                DEFAULT_TRICKPLAY_ONLY_MISSING,
            ),
            conflict_mode=trickplay_conflict_mode,
            width=settings_int(
                settings,
                SET_KEY_TRICKPLAY_WIDTH,
                DEFAULT_TRICKPLAY_WIDTH,
                minimum=16,
            ),
            tile_columns=settings_int(
                settings,
                SET_KEY_TRICKPLAY_TILE_COLUMNS,
                DEFAULT_TRICKPLAY_TILE_COLUMNS,
                minimum=1,
            ),
            tile_rows=settings_int(
                settings,
                SET_KEY_TRICKPLAY_TILE_ROWS,
                DEFAULT_TRICKPLAY_TILE_ROWS,
                minimum=1,
            ),
            interval_s=settings_int(
                settings,
                SET_KEY_TRICKPLAY_INTERVAL_S,
                DEFAULT_TRICKPLAY_INTERVAL_S,
                minimum=1,
            ),
            jpeg_quality=settings_int(
                settings,
                SET_KEY_TRICKPLAY_JPEG_QUALITY,
                DEFAULT_TRICKPLAY_JPEG_QUALITY,
                minimum=1,
                maximum=100,
            ),
            qscale=settings_int(
                settings,
                SET_KEY_TRICKPLAY_QSCALE,
                DEFAULT_TRICKPLAY_QSCALE,
                minimum=2,
                maximum=31,
            ),
            hwaccel=settings_text(
                settings,
                SET_KEY_TRICKPLAY_HWACCEL,
                DEFAULT_TRICKPLAY_HWACCEL,
                allowed={"cuda", "none", "qsv", "dxva2", "d3d11va"},
            ),
            max_jobs=settings_int(
                settings,
                SET_KEY_TRICKPLAY_MAX_JOBS,
                DEFAULT_TRICKPLAY_MAX_JOBS,
                minimum=1,
                maximum=8,
            ),
            source_mode=trickplay_source_mode,
        ),
    )


class PostProcessService:
    def __init__(self, *, settings, tools, log, worker=None) -> None:
        self.settings = settings
        self.tools = tools
        self.log = log
        self.worker = worker
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
                    client = client_from_settings_for(self.settings, "series", require_enabled=True)
                except OnlineMetadataAuthError as exc:
                    self._warn(f"NFO übersprungen: {exc}")
                    self._record("nfo", "skipped", "", str(exc))
                    return None
                suggestion = client.resolve_episode_file(input_path)
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
                client = client_from_settings_for(self.settings, "movie", require_enabled=True)
            except OnlineMetadataAuthError as exc:
                self._warn(f"NFO übersprungen: {exc}")
                self._record("nfo", "skipped", "", str(exc))
                return None
            suggestion = client.resolve_movie_file(input_path)
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
        getattr(self.log, "info", self.log)(message)

    def _warn(self, message: str) -> None:
        getattr(self.log, "warn", getattr(self.log, "warning", self.log))(message)

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


def postprocess_max_workers(settings) -> int:
    try:
        return config_from_settings(settings).trickplay.max_jobs
    except Exception:
        return DEFAULT_TRICKPLAY_MAX_JOBS


class AsyncPostProcessCoordinator:
    """Fuehrt NFO-/Trickplay-Nacharbeit im Hintergrund aus."""

    def __init__(self, *, settings, tools, log, worker=None, service_factory=None) -> None:
        self.settings = settings
        self.tools = tools
        self.log = log
        self.worker = worker
        self._service_factory = service_factory or (
            lambda: PostProcessService(
                settings=self.settings,
                tools=self.tools,
                log=self.log,
                worker=self.worker,
            )
        )
        self._executor = ThreadPoolExecutor(
            max_workers=postprocess_max_workers(settings),
            thread_name_prefix="DragonPostprocess",
        )
        self._futures: list[Future] = []
        self._lock = threading.Lock()

    def submit(
        self,
        *,
        input_path: str,
        output_path: str,
        existing_sidecars: list[str] | None,
        sidecar_outputs: dict[str, list[str]] | None,
        postprocess_outputs: dict[str, list[dict]] | None,
        result_service,
    ) -> bool:
        try:
            service = self._service_factory()
            future = self._executor.submit(
                service.run_result,
                input_path=input_path,
                output_path=output_path,
            )
        except Exception as exc:
            self._warn(f"Post-Processing konnte nicht gestartet werden: {exc}")
            return False

        with self._lock:
            self._futures.append(future)
        self._info(f"🧩 Post-Processing im Hintergrund gestartet: {Path(output_path).name}")
        future.add_done_callback(
            lambda done: self._complete(
                done,
                input_path=input_path,
                output_path=output_path,
                existing_sidecars=existing_sidecars,
                sidecar_outputs=sidecar_outputs,
                postprocess_outputs=postprocess_outputs,
                result_service=result_service,
            )
        )
        return True

    def wait_for_all(self) -> None:
        with self._lock:
            futures = list(self._futures)
        if futures:
            self._info(f"🧩 Warte auf {len(futures)} Post-Processing-Auftrag/Aufträge ...")
            wait(futures)
        self._executor.shutdown(wait=True)

    def _complete(
        self,
        future: Future,
        *,
        input_path: str,
        output_path: str,
        existing_sidecars: list[str] | None,
        sidecar_outputs: dict[str, list[str]] | None,
        postprocess_outputs: dict[str, list[dict]] | None,
        result_service,
    ) -> None:
        try:
            result = future.result()
        except Exception as exc:
            self._warn(f"Post-Processing fehlgeschlagen: {exc}")
            result = PostProcessRunResult(
                [],
                [
                    {
                        "kind": "postprocess",
                        "status": "error",
                        "path": "",
                        "message": str(exc),
                    }
                ],
            )

        details = [dict(item) for item in (getattr(result, "items", []) or [])]
        if postprocess_outputs is not None:
            postprocess_outputs[input_path] = details

        sidecars = list(existing_sidecars or [])
        for path in list(getattr(result, "created_paths", []) or []):
            if path and path not in sidecars:
                sidecars.append(path)
        if sidecar_outputs is not None:
            sidecar_outputs[input_path] = sidecars

        errors = [
            item for item in details
            if str(item.get("status", "")).lower() == "error"
        ]
        if errors:
            self._warn(f"🧩 Post-Processing mit Hinweis beendet: {Path(output_path).name}")
        else:
            self._info(f"🧩 Post-Processing abgeschlossen: {Path(output_path).name}")

        try:
            result_service.emit_file_progress(input_path, 100)
            result_service.emit_file_result(input_path, output_path, "✅")
        except Exception as exc:
            self._warn(f"Post-Processing-Abschluss konnte nicht gemeldet werden: {exc}")

    def _info(self, message: str) -> None:
        getattr(self.log, "info", self.log)(message)

    def _warn(self, message: str) -> None:
        getattr(self.log, "warn", getattr(self.log, "warning", self.log))(message)
