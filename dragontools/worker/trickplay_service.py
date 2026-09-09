# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from ..core.move_transaction import PathSwapTransaction, PathTransactionRollbackError
from .tool_runner import run_tool


@dataclass(frozen=True)
class TrickplaySettings:
    enabled: bool = False
    only_missing: bool = True
    conflict_mode: str = "skip"
    width: int = 320
    tile_columns: int = 10
    tile_rows: int = 10
    interval_s: int = 10
    jpeg_quality: int = 90
    qscale: int = 4
    hwaccel: str = "cuda"
    max_jobs: int = 1
    source_mode: str = "output"

    @property
    def tile_label(self) -> str:
        return f"{max(1, self.tile_columns)}x{max(1, self.tile_rows)}"


@dataclass(frozen=True)
class _TrickplayFfmpegStrategy:
    name: str
    hwaccel: str
    start_message: str
    success_message: str
    before_message: str | None = None
    force_hwdownload: bool = False


_SEMAPHORE_LOCK = threading.Lock()
_SEMAPHORE_SIZE = 0
_SEMAPHORE: threading.Semaphore | None = None

TRICKPLAY_RUNTIME_TIMEOUT_S = 6 * 60 * 60


def trickplay_root_for_video(video_path: str | Path) -> Path:
    video = Path(video_path)
    return video.with_name(f"{video.stem}.trickplay")


def trickplay_sprite_dir_for_video(video_path: str | Path, settings: TrickplaySettings) -> Path:
    return trickplay_root_for_video(video_path) / f"{int(settings.width)} - {settings.tile_label}"


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

    def generate(
        self,
        video_path: str | Path,
        settings: TrickplaySettings,
        *,
        target_video_path: str | Path | None = None,
    ) -> Path | None:
        if not settings.enabled:
            return None
        video = Path(video_path)
        if not video.exists() or not self.ffmpeg_path:
            self._warn("Trickplay übersprungen: Video oder ffmpeg nicht gefunden.")
            return None

        target_video = Path(target_video_path) if target_video_path else video
        final_root = trickplay_root_for_video(target_video)
        final_sprite_dir = trickplay_sprite_dir_for_video(target_video, settings)
        conflict_mode = normalize_trickplay_conflict_mode(settings)
        if conflict_mode == "skip" and final_sprite_dir.exists():
            self._info(f"Trickplay vorhanden, wird übernommen: {final_root.name}")
            return final_root

        max_jobs = max(1, min(int(settings.max_jobs or 1), 8))
        with _trickplay_semaphore(max_jobs):
            return self._generate_locked(video, settings, final_root, final_sprite_dir)

    def _generate_locked(
        self,
        video: Path,
        settings: TrickplaySettings,
        final_root: Path,
        final_sprite_dir: Path,
    ) -> Path | None:
        conflict_mode = normalize_trickplay_conflict_mode(settings)
        partial_root = final_root.with_name(f"{final_root.name}.__partial__")
        if partial_root.exists():
            shutil.rmtree(partial_root, ignore_errors=True)
        partial_sprite_dir = partial_root / final_sprite_dir.name
        partial_sprite_dir.mkdir(parents=True, exist_ok=True)
        output_pattern = partial_sprite_dir / "%d.jpg"

        self._info(
            "Trickplay: Sprite-Erstellung startet "
            f"({settings.width}px, {settings.tile_label}, alle {settings.interval_s}s, qscale {settings.qscale})."
        )
        hwaccel = _normalized_hwaccel(settings.hwaccel)
        success_message = ""
        for idx, strategy in enumerate(_ffmpeg_strategies(hwaccel)):
            if idx > 0:
                self._clear_partial_sprite_dir(partial_sprite_dir)
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
            if ok and any(partial_sprite_dir.glob("*.jpg")):
                success_message = strategy.success_message
                break
            if ok:
                self._warn(f"Trickplay: {strategy.name} beendet, aber keine Kachelbilder erzeugt.")

        if not success_message:
            shutil.rmtree(partial_root, ignore_errors=True)
            self._warn("Trickplay konnte nicht erstellt werden.")
            return None
        self._info(success_message)

        if final_root.exists() and conflict_mode == "skip":
            if final_sprite_dir.exists():
                shutil.rmtree(partial_root, ignore_errors=True)
                self._info(f"Trickplay vorhanden, wird übernommen: {final_root.name}")
                return final_root
            try:
                final_sprite_dir.parent.mkdir(parents=True, exist_ok=True)
                partial_sprite_dir.rename(final_sprite_dir)
            except OSError as exc:
                self._warn(f"Trickplay-Variante konnte nicht committed werden: {exc}")
                return None
            shutil.rmtree(partial_root, ignore_errors=True)
            count = len(list(final_sprite_dir.glob("*.jpg")))
            self._info(f"Trickplay ergänzt: {final_sprite_dir.parent.name} ({count} Kachelbild(er)).")
            return final_root

        return self._commit_generated_root(
            partial_root=partial_root,
            final_root=final_root,
            final_sprite_dir=final_sprite_dir,
            conflict_mode=conflict_mode,
        )

    def _build_ffmpeg_cmd(
        self,
        video: Path,
        output_pattern: Path,
        settings: TrickplaySettings,
        *,
        hwaccel: str,
        force_hwdownload: bool = False,
    ) -> list[str]:
        cmd = [self.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y"]
        if hwaccel and hwaccel.lower() != "none":
            cmd.extend(["-hwaccel", hwaccel])
            if force_hwdownload and hwaccel.lower() == "cuda":
                cmd.extend(["-hwaccel_output_format", "cuda"])
        cols = max(1, int(settings.tile_columns))
        rows = max(1, int(settings.tile_rows))
        interval = max(1, int(settings.interval_s))
        width = max(16, int(settings.width))
        qscale = max(2, min(31, int(settings.qscale)))
        vf = f"fps=1/{interval},scale={width}:-2,tile={cols}x{rows}"
        if force_hwdownload and hwaccel.lower() == "cuda":
            vf = f"hwdownload,format=nv12,{vf}"
        cmd.extend(
            [
                "-noautorotate",
                "-i",
                str(video),
                "-an",
                "-sn",
                "-vf",
                vf,
                "-q:v",
                str(qscale),
                "-start_number",
                "0",
                "-f",
                "image2",
                str(output_pattern),
            ]
        )
        return cmd

    def _commit_generated_root(
        self,
        *,
        partial_root: Path,
        final_root: Path,
        final_sprite_dir: Path,
        conflict_mode: str,
    ) -> Path | None:
        final_root.parent.mkdir(parents=True, exist_ok=True)
        backup = _unique_backup_path(final_root)
        transaction = PathSwapTransaction(
            source=partial_root,
            destination=final_root,
            backup_path=backup,
            # Die von ffmpeg vollständig erzeugte Partial-Struktur IST bereits
            # das Staging. Dadurch wird kein zweites Mal kopiert.
            staging_path=partial_root,
        )
        try:
            transaction.commit()
        except PathTransactionRollbackError as exc:
            self._warn(
                "Trickplay-Commit fehlgeschlagen und automatisches Rollback war unvollständig. "
                f"Altbestand-Backup bleibt erhalten: {exc.backup_path}"
            )
            return None
        except (OSError, shutil.Error, RuntimeError) as exc:
            self._warn(
                "Trickplay-Commit fehlgeschlagen; vorhandener Altbestand wurde wiederhergestellt: "
                f"{exc}"
            )
            return None

        if transaction.backup_created:
            if conflict_mode == "backup":
                self._info(f"Vorhandene Trickplaybilder gesichert: {backup.name}")
            else:
                try:
                    transaction.discard_backup()
                except (OSError, shutil.Error) as exc:
                    # Der neue Commit ist gültig. Den nicht löschbaren Altbestand
                    # absichtlich erhalten und sichtbar melden statt ihn zu verlieren.
                    self._warn(
                        f"Trickplay ersetzt; Altbestand-Backup konnte nicht entfernt werden "
                        f"und bleibt unter {backup}: {exc}"
                    )

        count = len(list(final_sprite_dir.glob("*.jpg")))
        self._info(f"Trickplay erstellt: {final_root.name} ({count} Kachelbild(er)).")
        return final_root

    def _run(self, cmd: list[str]) -> bool:
        try:
            result = run_tool(
                cmd,
                label=f"Trickplay ffmpeg ({_command_hwaccel_label(cmd)})",
                timeout_s=self.timeout_s,
                worker=self.worker,
                log=self._runner_log,
                abort_on_request=True,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._warn(f"Trickplay-Fehler: {exc}")
            return False

        if result.aborted:
            self._warn("Trickplay abgebrochen.")
            return False
        if result.timed_out:
            self._warn(
                f"Trickplay ffmpeg wurde nach {self.timeout_s:.0f}s wegen Runtime-Timeout beendet."
            )
            return False
        if result.returncode != 0:
            self._warn(
                "Trickplay ffmpeg "
                f"({_command_hwaccel_label(cmd)}) beendet mit Code {result.returncode}."
            )
            stderr_lines = result.stderr.splitlines()[-10:] if result.stderr else []
            for line in stderr_lines:
                self._warn(f"Trickplay ffmpeg: {line}")
            if not stderr_lines:
                self._warn("Trickplay ffmpeg: keine Detailausgabe erhalten.")
            return False
        return True

    def _runner_log(self, message: str, level: str = "info") -> None:
        if str(level).lower() in {"warn", "warning", "error"}:
            self._warn(message)
        else:
            self._info(message)

    def _clear_partial_sprite_dir(self, partial_sprite_dir: Path) -> None:
        try:
            shutil.rmtree(partial_sprite_dir, ignore_errors=True)
            partial_sprite_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def _info(self, message: str) -> None:
        getattr(self.log, "info", self.log)(message)

    def _warn(self, message: str) -> None:
        getattr(self.log, "warn", getattr(self.log, "warning", self.log))(message)


def normalize_trickplay_conflict_mode(settings: TrickplaySettings) -> str:
    mode = str(getattr(settings, "conflict_mode", "") or "").strip().lower()
    if mode in {"skip", "overwrite", "backup"}:
        return mode
    return "skip" if bool(getattr(settings, "only_missing", True)) else "overwrite"


def _normalized_hwaccel(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    return mode or "none"


def _ffmpeg_strategies(hwaccel: str) -> list[_TrickplayFfmpegStrategy]:
    mode = _normalized_hwaccel(hwaccel)
    if mode == "none":
        return [
            _TrickplayFfmpegStrategy(
                name="CPU-Pfad",
                hwaccel="none",
                start_message="Trickplay: CPU-Pfad startet.",
                success_message="Trickplay: CPU-Pfad erfolgreich.",
            )
        ]

    if mode == "cuda":
        return [
            _TrickplayFfmpegStrategy(
                name="CUDA/NVDEC-Pfad",
                hwaccel="cuda",
                start_message=(
                    "Trickplay: CUDA/NVDEC-Pfad startet "
                    "(GPU-Decoding, kompatible CPU-Filter/Tiling)."
                ),
                success_message=(
                    "Trickplay: CUDA/NVDEC-Pfad erfolgreich "
                    "(GPU-Decoding; Filter/Tiling kompatibel ausgeführt)."
                ),
            ),
            _TrickplayFfmpegStrategy(
                name="CUDA/NVDEC-Kompatibilitätsretry",
                hwaccel="cuda",
                force_hwdownload=True,
                before_message=(
                    "Trickplay: CUDA/NVDEC-Pfad fehlgeschlagen; "
                    "Kompatibilitätsretry mit explizitem Frame-Download startet."
                ),
                start_message=(
                    "Trickplay: CUDA/NVDEC-Kompatibilitätsretry startet "
                    "(Frame-Download vor CPU-Filtern)."
                ),
                success_message="Trickplay: CUDA/NVDEC-Kompatibilitätsretry erfolgreich.",
            ),
            _TrickplayFfmpegStrategy(
                name="CPU-Fallback",
                hwaccel="none",
                before_message=(
                    "Trickplay: CUDA/NVDEC-Kompatibilitätsretry fehlgeschlagen; "
                    "CPU-Fallback startet."
                ),
                start_message="Trickplay: CPU-Fallback startet.",
                success_message="Trickplay: CPU-Fallback erfolgreich.",
            ),
        ]

    label = _hwaccel_label(mode)
    return [
        _TrickplayFfmpegStrategy(
            name=f"{label}-Pfad",
            hwaccel=mode,
            start_message=(
                f"Trickplay: Hardwarepfad {label} startet "
                "(GPU-Decoding, kompatible CPU-Filter/Tiling)."
            ),
            success_message=f"Trickplay: Hardwarepfad {label} erfolgreich.",
        ),
        _TrickplayFfmpegStrategy(
            name="CPU-Fallback",
            hwaccel="none",
            before_message=f"Trickplay: Hardwarepfad {label} fehlgeschlagen; CPU-Fallback startet.",
            start_message="Trickplay: CPU-Fallback startet.",
            success_message="Trickplay: CPU-Fallback erfolgreich.",
        ),
    ]


def _hwaccel_label(value: str) -> str:
    labels = {
        "cuda": "CUDA/NVDEC",
        "qsv": "Intel QSV",
        "dxva2": "DXVA2",
        "d3d11va": "D3D11VA",
        "none": "CPU",
    }
    return labels.get(value.lower(), value.upper())


def _command_hwaccel_label(cmd: list[str]) -> str:
    try:
        idx = cmd.index("-hwaccel")
        label = _hwaccel_label(str(cmd[idx + 1]))
        if "-hwaccel_output_format" in cmd:
            return f"{label} + hwdownload"
        return label
    except Exception:
        return "CPU"


def _unique_backup_path(path: Path) -> Path:
    candidate = path.with_name(f"{path.name}.bak")
    if not candidate.exists():
        return candidate
    for idx in range(1, 1000):
        numbered = path.with_name(f"{path.name}.bak_{idx:02d}")
        if not numbered.exists():
            return numbered
    raise RuntimeError(f"Kein freier Backup-Ordner gefunden: {path.name}")


class _trickplay_semaphore:
    def __init__(self, max_jobs: int) -> None:
        self.max_jobs = max(1, int(max_jobs or 1))
        self._sem: threading.Semaphore | None = None

    def __enter__(self):
        global _SEMAPHORE, _SEMAPHORE_SIZE
        with _SEMAPHORE_LOCK:
            if _SEMAPHORE is None or _SEMAPHORE_SIZE != self.max_jobs:
                _SEMAPHORE = threading.Semaphore(self.max_jobs)
                _SEMAPHORE_SIZE = self.max_jobs
            self._sem = _SEMAPHORE
        self._sem.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._sem is not None:
            self._sem.release()
