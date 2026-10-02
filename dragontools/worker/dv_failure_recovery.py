# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import shutil
import traceback
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from ..core.path_safety import is_safe_subpath, safe_unlink


def preserve_completed_dv_work(state, result, *, log):
    """Retain late failures without copying huge files or requiring HDR10+."""
    if result.success or not state.video_encode_completed or result.failure_archive_path:
        return result
    root = state.files.root
    # Set the cleanup veto before any fallible I/O. Even a full/unavailable
    # archive volume must not destroy hours of completed encoding.
    result = replace(result, preserve_failed_output=True,
                     failure_artifact_paths=tuple(dict.fromkeys((*result.failure_artifact_paths, str(root)))))
    try:
        status = {
            "format": "DragonTools-DV-recovery-v1",
            "source": state.request.input_path,
            "planned_output": state.request.output_path,
            "failure_stage": result.failure_stage,
            "failure_reason": result.failure_reason,
            "video_encode_completed": True,
            "container": state.request.container,
            "effective_crop": state.effective_crop,
            "override": state.request.override,
            "encoded_frame_evidence": str(state.encoded_frame_evidence),
            "frame_recovery_applied": bool(getattr(state, "frame_recovery_applied", False)),
            "frame_recovery_original_count": getattr(state, "frame_recovery_original_count", None),
            "frame_recovery_final_count": getattr(state, "frame_recovery_final_count", None),
            "frame_recovery_message": str(getattr(state, "frame_recovery_message", "") or ""),
            "files": [p.name for p in root.iterdir()],
            "notice": "Original nicht ersetzt. Kein validierter Finalfilm. Manuelle Wiederaufnahme; kein automatischer Resume.",
        }
        (root / "recovery.json").write_text(json.dumps(status, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        archive = Path(state.request.input_path).parent / "Archiv"
        archive.mkdir(parents=True, exist_ok=True)
        bundle = archive / (Path(state.request.output_path).stem + "__DV_FAILED__"
                            + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8])
        # Atomic rename only: cross-volume/unavailable archives leave root intact.
        os.rename(root, bundle)
        result = replace(result, failure_archive_path=str(bundle),
                         failure_artifact_paths=tuple(
                             str(bundle / Path(p).relative_to(root)) if Path(p).is_relative_to(root) else p
                             for p in result.failure_artifact_paths))
        log(f"📦 [DV] Fertiger Encode und Arbeitsdateien für manuelle Wiederaufnahme gesichert: {bundle}", "warn")
    except (OSError, ValueError) as exc:
        log(f"⚠️ [DV] Archivierung nicht abgeschlossen: {exc}. Arbeitsdateien bleiben erhalten: {root}", "warn")
    return result



def _nonempty_file(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _reserve_dynamic_archive(archive_root: Path, output_stem: str, timestamp: str, log):
    try:
        archive_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log(f"❌ [DV+HDR10+] Diagnose-Archiv konnte nicht angelegt werden: {exc}", "error")
        return None

    for index in range(1000):
        suffix = "" if index == 0 else f"_{index:03d}"
        bundle = archive_root / f"{output_stem}__DV_HDR10PLUS_FAILED__{timestamp}{suffix}"
        staging = archive_root / f".{bundle.name}.partial"
        if bundle.exists() or staging.exists():
            continue
        try:
            staging.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            continue
        except OSError as exc:
            log(f"❌ [DV+HDR10+] Diagnose-Staging konnte nicht angelegt werden: {exc}", "error")
            return None
        return bundle, staging

    log("❌ [DV+HDR10+] Kein freier Diagnose-Archivordner gefunden.", "error")
    return None


def _copy_diagnostic_artifact(
    src: Path | None,
    target: Path,
    *,
    staged: list[Path],
    source_artifacts: list[Path],
    log,
) -> Path | None:
    if not _nonempty_file(src):
        return None
    source = Path(src)
    source_artifacts.append(source)
    try:
        shutil.copy2(str(source), str(target))
        if not _nonempty_file(target):
            raise OSError("Archivdatei fehlt oder ist leer")
    except (OSError, shutil.Error) as exc:
        log(
            f"⚠️ [DV+HDR10+] Diagnoseartefakt konnte nicht ins Staging kopiert werden: "
            f"{source.name} – {exc}",
            "warn",
        )
        return None
    staged.append(target)
    return target


def _select_dynamic_video_candidate(files, output: Path) -> tuple[Path | None, str]:
    if _nonempty_file(output):
        return output, output.name
    for candidate, name in (
        (getattr(files, "injected", None), f"{output.stem}.injected.hevc"),
        (getattr(files, "hdr10plus_hevc", None), f"{output.stem}.hdr10plus.hevc"),
        (getattr(files, "enc_hevc", None), f"{output.stem}.encoded.hevc"),
    ):
        if _nonempty_file(candidate):
            return candidate, name
    return None, output.name


def _valid_json_object(path: Path | None, log) -> bool:
    if path is None:
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return True
        raise ValueError("HDR10+-JSON ist kein JSON-Objekt")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        log(f"⚠️ [DV+HDR10+] Archivierte HDR10+-JSON ist ungültig: {exc}", "warn")
        return False


def _copy_rpu_diagnostics(state, files, output: Path, staging: Path, *, staged, source_artifacts, log) -> None:
    seen: set[str] = set()
    candidates = (
        (getattr(state, "rpu_to_use", None), f"{output.stem}.rpu"),
        (getattr(files, "rpu_orig", None), f"{output.stem}.rpu_original.bin"),
        (getattr(files, "rpu_final", None), f"{output.stem}.rpu_final.bin"),
        (getattr(files, "rpu_verify", None), f"{output.stem}.rpu_verify.bin"),
        (getattr(files, "root", Path(".")) / "final_mux_verify.rpu", f"{output.stem}.rpu_final_mux.bin"),
    )
    for candidate, name in candidates:
        if candidate is None:
            continue
        try:
            key = str(candidate.resolve())
        except (OSError, RuntimeError):
            key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        _copy_diagnostic_artifact(
            candidate, staging / name, staged=staged, source_artifacts=source_artifacts, log=log
        )


def _write_dynamic_archive_status(
    staging: Path,
    *,
    source: Path,
    output: Path,
    stage: str,
    reason: str,
    video_ok: bool,
    json_ok: bool,
    staged: list[Path],
    log,
) -> None:
    status = staging / "status.txt"
    lines = [
        "DragonTools DV/HDR10+ Diagnosearchiv",
        f"Quelle: {source}",
        f"Geplantes Ziel: {output}",
        f"Fehlerstufe: {stage or '<unbekannt>'}",
        f"Grund: {reason or '<nicht angegeben>'}",
        "Original ersetzt: NEIN",
        f"Video-Kandidat archiviert: {'JA' if video_ok else 'NEIN'}",
        f"HDR10+-JSON archiviert: {'JA' if json_ok else 'NEIN'}",
        "RPU-Artefakte: siehe Ordnerinhalt (sofern im Lauf vorhanden)",
        "",
        "Hinweis: Das Paket wurde transaktional in einem .partial-Staging aufgebaut.",
    ]
    try:
        status.write_text("\n".join(lines), encoding="utf-8")
        staged.append(status)
    except OSError as exc:
        log(f"⚠️ [DV+HDR10+] status.txt konnte nicht geschrieben werden: {exc}", "warn")


def _persistent_diagnostic_paths(staged: list[Path], source_artifacts: list[Path]) -> tuple[str, ...]:
    paths = [str(path) for path in staged if path.exists()]
    paths.extend(str(path) for path in source_artifacts if path.exists())
    return tuple(dict.fromkeys(paths))

class DVFailureRecovery:
    def __init__(self, *, log) -> None:
        self._log = log

    def cleanup_tmp_sub(self, *, base_dir: Path, tmp_sub: str | None, clear_tmp_sub) -> None:
        if not tmp_sub:
            return
        try:
            path = Path(tmp_sub)
            if not is_safe_subpath(base_dir, path):
                self._log(f"⚠️ Unsicherer Löschpfad übersprungen: {path}", "warn")
            elif not safe_unlink(base_dir, path):
                self._log(
                    f"⚠️ Temporäre Datei konnte nicht gelöscht werden: {path.name}",
                    "warn",
                )
        except Exception as e:
            self._log(
                f"⚠️ Temporäre Datei konnte nicht gelöscht werden: {Path(tmp_sub).name} – {e}",
                "warn",
            )
            self._log(traceback.format_exc(), "error")
        finally:
            clear_tmp_sub()


    def preserve_dynamic_metadata_failure(
        self,
        *,
        state,
        reason: str,
        stage: str,
    ) -> tuple[Path | None, tuple[str, ...]]:
        """Persist failed DV/HDR10+ diagnostics transactionally.

        The final archive is committed only after a non-empty video candidate
        and a valid HDR10+ JSON have both reached ``.partial`` staging.
        """
        request = state.request
        files = state.files
        source = Path(str(request.input_path))
        output = Path(str(request.output_path))
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        reserved = _reserve_dynamic_archive(source.parent / "Archiv", output.stem, timestamp, self._log)
        if reserved is None:
            return None, ()
        bundle, staging = reserved
        staged: list[Path] = []
        source_artifacts: list[Path] = []

        video_source, video_name = _select_dynamic_video_candidate(files, output)
        video_target = _copy_diagnostic_artifact(
            video_source, staging / video_name, staged=staged, source_artifacts=source_artifacts, log=self._log
        )
        json_target = _copy_diagnostic_artifact(
            getattr(files, "hdr10plus_json", None),
            staging / f"{output.stem}.hdr10plus.json",
            staged=staged,
            source_artifacts=source_artifacts,
            log=self._log,
        )
        json_valid = _valid_json_object(json_target, self._log)
        _copy_diagnostic_artifact(
            getattr(files, "hdr10plus_verify_json", None),
            staging / f"{output.stem}.hdr10plus.verify.json",
            staged=staged,
            source_artifacts=source_artifacts,
            log=self._log,
        )
        _copy_rpu_diagnostics(
            state, files, output, staging, staged=staged, source_artifacts=source_artifacts, log=self._log
        )
        _write_dynamic_archive_status(
            staging,
            source=source,
            output=output,
            stage=stage,
            reason=reason,
            video_ok=video_target is not None,
            json_ok=json_target is not None and json_valid,
            staged=staged,
            log=self._log,
        )

        if video_target is None or json_target is None or not json_valid:
            persistent = _persistent_diagnostic_paths(staged, source_artifacts)
            self._log(
                f"⚠️ [DV+HDR10+] Diagnosearchiv unvollständig; Staging bleibt unter {staging} "
                "und der DV-Arbeitsordner wird vor Temp-Cleanup geschützt.",
                "warn",
            )
            return None, persistent

        try:
            os.replace(str(staging), str(bundle))
        except OSError as exc:
            self._log(
                f"⚠️ [DV+HDR10+] Diagnosearchiv konnte nicht atomar committed werden: {exc}. "
                "Staging und DV-Arbeitsordner bleiben erhalten.",
                "warn",
            )
            return None, _persistent_diagnostic_paths(staged, source_artifacts)

        archived = tuple(str(bundle / path.name) for path in staged)
        if video_source == output:
            try:
                output.unlink(missing_ok=True)
            except OSError as exc:
                self._log(
                    f"⚠️ [DV+HDR10+] Arbeitsausgabe konnte nach Archiv-Commit nicht gelöscht werden: {exc}",
                    "warn",
                )
        self._log(
            f"📦 [DV+HDR10+] Fehlgeschlagener Metadaten-Nachweis archiviert: {bundle}",
            "warn",
        )
        return bundle, archived

    def save_dv_crop_failure(
        self,
        *,
        input_path: str,
        output_path: str,
        crop: str | None,
        plain_mp4: Path,
        src_hevc: Path,
        enc_hevc: Path,
        rpu_orig: Path,
        rpu_final: Path,
        edit_json: Path,
        audio_tracks,
        mux_plain_mp4_without_dv,
        level5_proc=None,
    ) -> Path:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        fail_dir = Path(output_path).parent / "Fehler" / f"{Path(output_path).stem}__DV_CROP_FAILED__{ts}"
        fail_dir.mkdir(parents=True, exist_ok=True)

        mux_plain_mp4_without_dv()

        def copy_if_exists(src: Path | None, dst_name: str):
            if src and src.exists():
                shutil.copy2(src, fail_dir / dst_name)

        copy_if_exists(plain_mp4, "video_no_dv.mp4")
        copy_if_exists(src_hevc, "source_video.hevc")
        copy_if_exists(enc_hevc, "cropped_video.hevc")
        copy_if_exists(rpu_orig, "rpu_extracted.bin")
        copy_if_exists(rpu_final, "rpu_level5.bin")
        copy_if_exists(edit_json, "level5.json")
        for i, track in enumerate(audio_tracks):
            af = track.path
            if af.exists() and af.stat().st_size > 0:
                shutil.copy2(af, fail_dir / f"audio_{i}{af.suffix}")

        lines = [
            f"Quelldatei: {input_path}",
            f"Zieldatei: {output_path}",
            f"Crop: {crop or 'kein Crop'}",
            "DV erkannt: ja",
            "RPU-Extraktion: erfolgreich",
            "Level-5-RPU-Crop: fehlgeschlagen",
            "Unsicherer AutoCrop-Fallback: bewusst deaktiviert",
            "DV-Injektion: abgebrochen",
            "Hinweis: MP4 ohne DV wurde gesichert.",
            "",
        ]

        if level5_proc is not None:
            lines.append(f"Level5 returncode: {level5_proc.returncode}")
            txt = ((level5_proc.stdout or "") + "\n" + (level5_proc.stderr or "")).strip()
            if txt:
                lines.append("--- Level5-Ausgabe ---")
                lines.extend(txt.splitlines()[-20:])
                lines.append("")

        (fail_dir / "status.txt").write_text("\n".join(lines), encoding="utf-8")
        return fail_dir
