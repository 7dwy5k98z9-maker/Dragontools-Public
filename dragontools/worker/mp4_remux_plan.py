# -*- coding: utf-8 -*-
"""Qt-unabhängige Planung für den normalen MP4-Remux."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..core.audio_titles import build_audio_title
from ..rules.audio_plan import (
    audio_filter_chain,
    audio_input_args_for_plan,
    compute_audio_track_plan,
)
from ..rules.subtitle_rules import build_mp4_subtitle_storage_plan, compute_subtitle_plan


@dataclass(frozen=True)
class MP4RemuxPlan:
    source: Path
    destination: Path
    staging: Path
    command: tuple[str, ...]
    duration_s: float
    audio_plan: tuple[Any, ...]


class MP4RemuxPlanner:
    """Baut Stream-/Codec-Entscheidungen und den ffmpeg-Befehl."""

    def __init__(
        self,
        *,
        ffmpeg_path: str,
        apply_audio_rules: bool,
        export_subtitles: bool,
        ignore_subtitles: bool,
        subtitle_rules: dict,
        faststart: bool,
        log: Callable[[str, str], None],
        log_audio: Callable[..., None],
    ) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.apply_audio_rules = bool(apply_audio_rules)
        self.export_subtitles = bool(export_subtitles)
        self.ignore_subtitles = bool(ignore_subtitles)
        self.subtitle_rules = dict(subtitle_rules or {})
        self.faststart = bool(faststart)
        self._log = log
        self._log_audio = log_audio

    @staticmethod
    def video_compatibility(media_info) -> tuple[bool, str]:
        primary = media_info.primary_video
        if primary is None:
            return False, "Kein Primärvideo gefunden."
        if (
            bool(getattr(media_info, "dolby_vision", False))
            or bool(getattr(media_info, "dolby_vision_profile", None))
            or bool(getattr(media_info, "has_dv", False))
        ):
            return False, (
                "Dolby Vision erkannt. Der normale MP4-Remux erhält DV/RPU nicht sicher. "
                "Bitte den DV-Remux oder den Standard-Converter verwenden."
            )
        if bool(getattr(media_info, "has_hdr10plus", False)) or bool(
            getattr(media_info, "has_hdrplus", False)
        ):
            return False, (
                "HDR10+ erkannt. Der normale MP4-Remux erhält dynamische HDR10+-Metadaten nicht sicher. "
                "Bitte den Standard-Converter mit HDR10+-Erhalt verwenden."
            )
        codec = (primary.codec or "").lower()
        if codec in {"h264", "hevc", "h265"}:
            return True, codec
        return False, (
            f"Videocodec '{codec or 'unbekannt'}' ist nicht für MP4-Copy freigegeben. "
            "Bitte den Standard-Converter verwenden."
        )

    def build_audio_plan(self, media_info):
        return compute_audio_track_plan(
            audio_streams=media_info.audio_streams,
            file_override=None,
            container="mp4",
            apply_language_rules=self.apply_audio_rules,
        )

    def build_audio_args(self, plan) -> list[str]:
        if not plan:
            return ["-an"]
        args: list[str] = []
        for decision in plan:
            chosen = decision.stream
            out_idx = decision.out_idx
            args += ["-map", f"0:{chosen.index}"]
            if decision.needs_transcode:
                bitrate_k = max(
                    1,
                    int(decision.target_bitrate / 1000)
                    if decision.target_bitrate
                    else 256,
                )
                args += [
                    f"-c:a:{out_idx}",
                    decision.target_codec,
                    f"-ac:a:{out_idx}",
                    str(decision.target_channels),
                    f"-b:a:{out_idx}",
                    f"{bitrate_k}k",
                ]
                filter_chain = audio_filter_chain(decision)
                if filter_chain:
                    args += [f"-filter:a:{out_idx}", filter_chain]
                self._log_audio(
                    chosen.index,
                    chosen.codec,
                    "transcode",
                    decision.target_codec,
                    decision.target_channels,
                    bitrate_k,
                    getattr(chosen, "language", None),
                )
            else:
                args += [f"-c:a:{out_idx}", "copy"]
                self._log_audio(
                    chosen.index,
                    chosen.codec,
                    "copy",
                    language=getattr(chosen, "language", None),
                )
            for note in getattr(decision, "processing_notes", ()) or ():
                self._log(f"Audio Spur {out_idx + 1}: {note}", "info")
            if chosen.language:
                args += [f"-metadata:s:a:{out_idx}", f"language={chosen.language.lower()}"]
            title = build_audio_title(
                language=getattr(chosen, "language", None),
                codec=(decision.target_codec if decision.needs_transcode else chosen.codec),
                channels=(
                    decision.target_channels
                    if decision.needs_transcode
                    else getattr(chosen, "channels", None)
                ),
                bitrate_bps=(
                    decision.target_bitrate
                    if decision.needs_transcode
                    else getattr(chosen, "bitrate", None)
                ),
            )
            args += [f"-metadata:s:a:{out_idx}", f"title={title}"]
        return args

    def build_subtitle_args(self, media_info) -> list[str]:
        if not self.export_subtitles or self.ignore_subtitles:
            return ["-sn"]
        subtitle_plan = compute_subtitle_plan(
            list(getattr(media_info, "subtitle_streams", []) or []),
            audio_streams=list(getattr(media_info, "audio_streams", []) or []),
            file_override=None,
            subtitle_rules=self.subtitle_rules,
            container_copy_supported=True,
            media_duration_s=getattr(media_info, "duration_s", None),
        )
        storage = build_mp4_subtitle_storage_plan(
            subtitle_plan,
            subtitle_rules=self.subtitle_rules,
            preserve_burn_candidate=True,
        )
        if not storage.internal_streams:
            return ["-sn"]
        args: list[str] = []
        for out_idx, stream in enumerate(storage.internal_streams):
            args += ["-map", f"0:{stream.index}", f"-c:s:{out_idx}", "mov_text"]
            if getattr(stream, "language", None):
                args += [
                    f"-metadata:s:s:{out_idx}",
                    f"language={str(stream.language).lower()}",
                ]
            title = str(getattr(stream, "title", "") or "").replace("\n", " ").strip()
            if title:
                args += [f"-metadata:s:s:{out_idx}", f"title={title}"]
            args += [
                f"-disposition:s:{out_idx}",
                "forced" if bool(getattr(stream, "forced", False)) else "0",
            ]
        return args

    def build(self, input_path: str, output_path: str, media_info) -> MP4RemuxPlan:
        source = Path(input_path)
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination
        if destination.resolve() == source.resolve():
            staging = destination.with_name(f"{destination.stem}.__mp4_remux_tmp__.mp4")

        audio_plan = self.build_audio_plan(media_info)
        command: list[str] = [
            self.ffmpeg_path,
            "-y",
            "-loglevel",
            "error",
            *audio_input_args_for_plan(audio_plan),
            "-i",
            input_path,
            "-map_metadata",
            "0",
            "-map_chapters",
            "0",
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            *self.build_audio_args(audio_plan),
            *self.build_subtitle_args(media_info),
        ]
        if self.faststart:
            command += ["-movflags", "+faststart"]
        command += [str(staging)]
        return MP4RemuxPlan(
            source=source,
            destination=destination,
            staging=staging,
            command=tuple(command),
            duration_s=float(getattr(media_info, "duration_s", 0.0) or 0.0),
            audio_plan=tuple(audio_plan or ()),
        )


def resolve_mp4_output_path(
    input_path: str,
    *,
    output_dir: str | None,
    overwrite_original: bool,
) -> tuple[Path, str | None]:
    """Bestimmt einen kollisionsfreien MP4-Zielpfad und optional eine Warnung."""
    source = Path(input_path)
    base_dir = Path(output_dir).resolve() if output_dir else source.parent
    if overwrite_original and source.suffix.lower() == ".mp4" and base_dir == source.parent:
        return source, None

    target = (base_dir / f"{source.stem}.mp4").resolve()
    if target != source.resolve() and not target.exists():
        return target, None

    candidate = (base_dir / f"{source.stem}_remux.mp4").resolve()
    index = 1
    while candidate.exists() or candidate == source.resolve():
        candidate = (base_dir / f"{source.stem}_remux_{index}.mp4").resolve()
        index += 1
    warning = None
    if target.exists() and target != source.resolve():
        warning = f"Konflikt: '{target.name}' existiert bereits, weiche aus auf '{candidate.name}'."
    elif candidate.name != f"{source.stem}_remux.mp4":
        warning = (
            f"Konflikt: '{source.stem}_remux.mp4' existiert bereits, "
            f"weiche aus auf '{candidate.name}'."
        )
    return candidate, warning
