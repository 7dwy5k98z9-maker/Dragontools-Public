# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
import traceback
from datetime import datetime
from pathlib import Path

from ..core.path_safety import is_safe_subpath, safe_unlink


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
