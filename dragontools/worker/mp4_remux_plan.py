# -*- coding: utf-8 -*-
"""Qt-unabhängige Planung für den normalen MP4-Remux."""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from .audio_metadata_args import audio_metadata_args, audio_output_title, audio_output_forced
from .utility_output_workspace import VerifiedOutputWorkspace
from ..core.lang_codes import mkv_language_tags
from ..core.media_metadata import normalize_video_codec
from ..core.output_timestamps import build_output_timestamp_args
from ..rules.audio_plan import (
    audio_filter_chain,
    audio_input_args_for_plan,
    compute_audio_track_plan,
    output_default_for_decision,
)
from ..rules.subtitle_rules import build_mp4_subtitle_storage_plan, compute_subtitle_plan
from .media_contract import _audio_codec_family, _subtitle_codec_family
from .media_contract_types import ExpectedAudioTrack, ExpectedMediaContract, ExpectedSubtitleTrack


@dataclass(frozen=True)
class MP4RemuxPlan:
    source: Path
    destination: Path
    staging: Path
    command: tuple[str, ...]
    duration_s: float
    audio_plan: tuple[Any, ...]
    expected_audio_tracks: int
    expected_subtitle_tracks: int
    expected_contract: ExpectedMediaContract | None = None
    workspace: Any = None


def _subtitle_disposition(stream) -> str:
    flags: list[str] = []
    if bool(getattr(stream, "default", False)):
        flags.append("default")
    if bool(getattr(stream, "forced", False)):
        flags.append("forced")
    return "+".join(flags) if flags else "0"


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
        self.subtitle_rules = deepcopy(subtitle_rules or {})
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
        codec = normalize_video_codec(primary.codec or "")
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
            args += audio_metadata_args(decision)
        return args

    def build_subtitle_args_with_count(self, media_info) -> tuple[list[str], int]:
        if not self.export_subtitles or self.ignore_subtitles:
            return ["-sn"], 0
        internal = self._internal_subtitles(media_info)
        return self._subtitle_args(internal), len(internal)

    def _internal_subtitles(self, media_info):
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
        internal = list(storage.internal_streams or [])
        return internal

    @staticmethod
    def _subtitle_args(internal) -> list[str]:
        args: list[str] = []
        for out_idx, stream in enumerate(internal):
            args += ["-map", f"0:{stream.index}", f"-c:s:{out_idx}", "mov_text"]
            if getattr(stream, "language", None):
                args += [
                    f"-metadata:s:s:{out_idx}",
                    f"language={mkv_language_tags(stream.language)[0]}",
                ]
            title = str(getattr(stream, "title", "") or "").replace("\n", " ").strip()
            if title:
                args += [f"-metadata:s:s:{out_idx}", f"title={title}",
                         f"-metadata:s:s:{out_idx}", f"handler_name={title}"]
            args += [
                f"-disposition:s:{out_idx}",
                _subtitle_disposition(stream),
            ]
        return args if internal else ["-sn"]

    def build_subtitle_args(self, media_info) -> list[str]:
        # Kompatibilitätsfassade für bestehende Tests/Plugins.
        return self.build_subtitle_args_with_count(media_info)[0]

    def build(self, input_path: str, output_path: str, media_info) -> MP4RemuxPlan:
        source = Path(input_path)
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        audio_plan = self.build_audio_plan(media_info)
        internal_subtitles = self._internal_subtitles(media_info) if self.export_subtitles and not self.ignore_subtitles else []
        subtitle_args = self._subtitle_args(internal_subtitles)
        primary_index = getattr(media_info.primary_video, "index", None)
        if isinstance(primary_index, bool) or not isinstance(primary_index, int) or primary_index < 0:
            raise ValueError("Primärvideo besitzt keinen bestätigten FFmpeg-Streamindex.")
        if getattr(media_info, 'ffmpeg_stream_indices_trusted', True) is False:
            raise ValueError("FFmpeg-Streamindizes der Quelle sind nicht bestätigt.")
        command: list[str] = [
            self.ffmpeg_path,
            "-n",
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
            f"0:{primary_index}",
            "-c:v",
            "copy",
            *self.build_audio_args(audio_plan),
            *subtitle_args,
        ]
        if self.faststart:
            command += ["-movflags", "+faststart"]
        expected_contract = self._expected_contract(media_info, audio_plan, internal_subtitles)
        workspace = VerifiedOutputWorkspace(destination.parent, self._log, prefix='.__dragontools_mp4_remux_')
        staging = workspace.root / 'remux.mp4'
        command += [*build_output_timestamp_args("mp4"), str(staging)]
        return MP4RemuxPlan(
            source=source,
            destination=destination,
            staging=staging,
            command=tuple(command),
            duration_s=float(getattr(media_info, "duration_s", 0.0) or 0.0),
            audio_plan=tuple(audio_plan or ()),
            expected_audio_tracks=len(tuple(audio_plan or ())),
            expected_subtitle_tracks=len(internal_subtitles),
            expected_contract=expected_contract,
            workspace=workspace,
        )


    @staticmethod
    def _expected_contract(media_info, audio_plan, internal_subtitles):
        primary = media_info.primary_video
        return ExpectedMediaContract(
            container="mp4",
            video_codec=normalize_video_codec(getattr(primary, "codec", "") or ""),
            video_stream_count=1,
            audio_tracks=tuple(
                ExpectedAudioTrack(
                    codec=_audio_codec_family(
                        decision.target_codec if decision.needs_transcode else getattr(decision.stream, "codec", "")
                    ),
                    channels=int(
                        decision.target_channels if decision.needs_transcode else getattr(decision.stream, "channels", 0) or 0
                    ),
                    language=str(getattr(decision.stream, "language", "") or ""),
                    default=bool(output_default_for_decision(decision)),
                    title=audio_output_title(decision),
                    forced=audio_output_forced(decision),
                )
                for decision in (audio_plan or ())
            ),
            subtitle_tracks=tuple(
                ExpectedSubtitleTrack(
                    codec=_subtitle_codec_family("mov_text"),
                    language=str(getattr(stream, "language", "") or ""),
                    forced=bool(getattr(stream, "forced", False)),
                    default=bool(getattr(stream, "default", False)),
                    title=str(getattr(stream, "title", "") or "").replace("\n", " ").strip(),
                )
                for stream in internal_subtitles
            ),
            min_video_bit_depth=(int(getattr(primary, "bit_depth", 0) or 0) or None),
            require_hdr=bool(getattr(media_info, "is_hdr", False)),
            expected_width=(int(getattr(primary, "width", 0) or 0) or None),
            expected_height=(int(getattr(primary, "height", 0) or 0) or None),
            attachment_stream_count=0,
            data_stream_count=0,
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
