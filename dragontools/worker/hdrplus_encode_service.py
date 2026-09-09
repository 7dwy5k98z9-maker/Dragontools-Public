# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .converter_utils import _fs
from .dv_runtime_models import DVTempState
from .encoder_args import _vid_args
from .hdr10_color import hdr10_output_args
from .hdrplus_runtime_models import HDRPlusEncoderConfig


class HDRPlusEncodeService:
    """Erzeugt HEVC-Bitstream und optionalen Audio/Subtitle-Donor.

    Der Service besitzt keinen jobbezogenen Encoderzustand. Alle effektiven
    Werte werden über ``HDRPlusEncoderConfig`` pro Aufruf übergeben.
    """

    def __init__(
        self,
        *,
        ffmpeg_path: str,
        progress_runner,
        temp_state: DVTempState,
        log: Callable[[str, str], None],
    ) -> None:
        self._ffmpeg = ffmpeg_path
        self._progress = progress_runner
        self._temp_state = temp_state
        self._log = log

    @staticmethod
    def has_aux_stream_output(audio_args: list | tuple, subtitle_args: list | tuple) -> bool:
        has_audio = bool(audio_args and list(audio_args) != ["-an"])
        has_subs = bool(subtitle_args and list(subtitle_args) != ["-sn"])
        return bool(has_audio or has_subs)

    def encode(
        self,
        *,
        input_path: str,
        encoded_hevc: Path,
        stream_donor: Path,
        vf_args: list | tuple,
        audio_args: list | tuple,
        audio_input_args: list | tuple,
        subtitle_args: list | tuple,
        media_info,
        encoder: HDRPlusEncoderConfig,
    ) -> bool:
        options = encoder.mutable_encoder_options()
        color_args = hdr10_output_args(media_info, encoder.codec)
        if color_args and encoder.codec == "h265":
            options["_force_hdr10_vui"] = True

        cmd = (
            [self._ffmpeg, "-y", "-loglevel", "error"]
            + list(audio_input_args or ())
            + ["-i", input_path]
            + list(vf_args or ())
            + _vid_args(encoder.codec, encoder.crf, encoder.preset, options)
            + color_args
            + ["-an", "-sn", "-dn", "-f", "hevc", str(encoded_hevc)]
        )

        if self.has_aux_stream_output(audio_args, subtitle_args):
            cmd += (
                list(audio_args or ())
                + list(subtitle_args or ())
                + ["-vn", "-dn", "-map_metadata", "0", "-map_chapters", "0", str(stream_donor)]
            )

        dur_ms = self._progress.probe_ms(input_path)
        rc = self._progress.run_p(cmd, input_path, dur_ms)
        if rc != 0 or not encoded_hevc.exists() or encoded_hevc.stat().st_size < 1024:
            self._log(f"❌ HDR10+: direkter HEVC-Encode fehlgeschlagen (rc={rc})", "error")
            if self._temp_state.stderr:
                for line in self._temp_state.stderr.splitlines()[-5:]:
                    if line.strip():
                        self._log(f"  ffmpeg: {line}", "error")
            return False

        if self.has_aux_stream_output(audio_args, subtitle_args):
            if not stream_donor.exists() or stream_donor.stat().st_size < 128:
                self._log("❌ HDR10+: Audio/Subtitle-Donor wurde nicht erzeugt.", "error")
                return False

        self._log(
            f"HDR10+: Encode erfolgreich -> {encoded_hevc.name} ({_fs(encoded_hevc.stat().st_size)})",
            "info",
        )
        if stream_donor.exists():
            self._log(
                f"HDR10+: Stream-Donor vorbereitet -> {stream_donor.name} ({_fs(stream_donor.stat().st_size)})",
                "info",
            )
        return True
