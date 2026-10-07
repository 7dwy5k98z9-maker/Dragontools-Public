# -*- coding: utf-8 -*-
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Callable

from .converter_utils import _fs
from .hdrplus_mp4_audio_service import HDRPlusMP4AudioService
from .dv_mux_input_validation import required_mux_inputs_available
from .mp4box_track_args import append_mp4box_subtitle


class HDRPlusMuxService:
    """Container-spezifischer finaler Mux fuer HDR10+-Bitstreams.

    MKV wird mit mkvmerge erzeugt, damit rohes HEVC ohne Container-Zeitstempel
    korrekt eingelesen wird. MP4 wird mit MP4Box und ``-inter 500``
    streamingoptimiert aufgebaut. Die Prozessausfuehrung bleibt beim zentralen
    ``HDRPlusToolRunner`` und wird ueber Callbacks injiziert.
    """

    def __init__(
        self,
        *,
        tools,
        log: Callable[[str, str], None],
        run_mux_tool: Callable[..., bool],
        capture_tool: Callable[..., object],
    ) -> None:
        self._tools = tools
        self._log = log
        self._run_mux_tool = run_mux_tool
        self._capture_tool = capture_tool
        self._audio = HDRPlusMP4AudioService(tools, log, run_mux_tool, capture_tool)

    def mux_mkv(self, injected_hevc: str, stream_donor: str, output_path: str) -> bool:
        try:
            video = Path(injected_hevc)
            donor = Path(stream_donor) if stream_donor else None
            out = Path(output_path)
            if not required_mux_inputs_available([video] + ([donor] if donor is not None else [])):
                return False
            cmd = [getattr(self._tools, "mkvmerge", "mkvmerge"), "-o", str(out), str(video)]
            if donor is not None:
                cmd += ["--no-video", str(donor)]

            self._log(f"HDR10+: Muxe finales MKV mit mkvmerge -> {out.name} …", "info")
            if not self._run_mux_tool(
                cmd,
                label="HDR10+: MKV-Mux",
                tool_name="mkvmerge",
                accepted_returncodes=(0, 1),
            ):
                return False
            if not out.exists() or out.stat().st_size < 1024:
                self._log(
                    f"❌ HDR10+: Finale MKV-Datei fehlt oder ist unplausibel klein: {out.name}",
                    "error",
                )
                return False
            self._log(
                f"HDR10+: Finales MKV erfolgreich erstellt -> {out.name} ({_fs(out.stat().st_size)})",
                "info",
            )
            return True
        except Exception:
            self._log(
                f"❌ Unbehandelte Ausnahme in HDRPlusMuxService.mux_mkv() bei {Path(output_path).name}",
                "error",
            )
            self._log(traceback.format_exc(), "error")
            return False

    def probe_mp4_audio(self, donor: Path) -> list[dict] | None:
        return self._audio.probe(donor)

    @staticmethod
    def audio_ext(codec: str) -> str:
        return HDRPlusMP4AudioService.audio_ext(codec)

    def mux_mp4(
        self,
        injected_hevc: str,
        stream_donor: str,
        output_path: str,
        *,
        tmp_dir: Path,
        subtitle_tracks=(),
    ) -> bool:
        video = Path(injected_hevc)
        donor = Path(stream_donor) if stream_donor else None
        out = Path(output_path)
        subtitle_tracks = tuple(subtitle_tracks or ())
        required = [video] + ([donor] if donor is not None else []) + [track.path for track in subtitle_tracks]
        if not required_mux_inputs_available(required):
            return False
        cmd = [
            getattr(self._tools, "mp4box", "MP4Box"),
            "-new", str(out),
            "-inter", "500",
            "-add", str(video),
        ]

        if donor is not None:
            additions = self._audio.prepare_additions(donor, tmp_dir)
            if additions is None:
                return False
            cmd += additions

        for subtitle_track in subtitle_tracks or ():
            append_mp4box_subtitle(cmd, subtitle_track)

        self._log(
            f"HDR10+: Muxe finales MP4 mit MP4Box (streamingoptimiert) -> {out.name} …",
            "info",
        )
        if not self._run_mux_tool(
            cmd,
            label="HDR10+: MP4Box-Mux",
            tool_name="MP4Box",
        ):
            return False
        if not out.exists() or out.stat().st_size < 1024:
            self._log(
                f"❌ HDR10+: Finale MP4-Datei fehlt oder ist unplausibel klein: {out.name}",
                "error",
            )
            return False
        self._log(
            f"HDR10+: Finales MP4 erfolgreich erstellt -> {out.name} ({_fs(out.stat().st_size)})",
            "info",
        )
        return True
