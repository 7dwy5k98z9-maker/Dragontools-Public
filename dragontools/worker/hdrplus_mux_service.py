# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Callable

from .converter_utils import _fs


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

    def mux_mkv(self, injected_hevc: str, stream_donor: str, output_path: str) -> bool:
        try:
            video = Path(injected_hevc)
            donor = Path(stream_donor) if stream_donor else None
            out = Path(output_path)
            cmd = [getattr(self._tools, "mkvmerge", "mkvmerge"), "-o", str(out), str(video)]
            if donor is not None and donor.exists() and donor.stat().st_size > 0:
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
        if not donor.exists() or donor.stat().st_size < 128:
            return []
        result = self._capture_tool(
            [
                getattr(self._tools, "ffprobe", "ffprobe"),
                "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index,codec_name:stream_tags=language,title",
                "-of", "json", str(donor),
            ],
            label="HDR10+: MP4-Audioanalyse",
            timeout_s=30,
        )
        if not result.ok:
            self._log("❌ HDR10+ MP4: Audioanalyse des Stream-Donors fehlgeschlagen.", "error")
            return None
        try:
            return list(json.loads(result.stdout or "{}").get("streams", []) or [])
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            self._log(f"❌ HDR10+ MP4: Ungültige ffprobe-Audioanalyse: {exc}", "error")
            return None

    @staticmethod
    def audio_ext(codec: str) -> str:
        return {
            "aac": ".m4a",
            "ac3": ".ac3",
            "eac3": ".eac3",
            "mp3": ".mp3",
        }.get(str(codec or "").lower(), ".mka")

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
        cmd = [
            getattr(self._tools, "mp4box", "MP4Box"),
            "-new", str(out),
            "-inter", "500",
            "-add", str(video),
        ]

        if donor is not None and donor.exists() and donor.stat().st_size > 0:
            audio_streams = self.probe_mp4_audio(donor)
            if not audio_streams:
                self._log(
                    "❌ HDR10+ MP4: Stream-Donor vorhanden, aber keine verlässlichen Audiospuren erkannt; "
                    "Mux wird abgebrochen, damit Audio nicht still verloren geht.",
                    "error",
                )
                return False
            for ordinal, stream in enumerate(audio_streams):
                codec = str(stream.get("codec_name") or "").lower()
                audio_file = tmp_dir / f"mp4_audio_{ordinal}{self.audio_ext(codec)}"
                extract_cmd = [
                    self._tools.ffmpeg,
                    "-y", "-loglevel", "error",
                    "-i", str(donor),
                    "-map", f"0:a:{ordinal}",
                    "-c:a", "copy",
                    str(audio_file),
                ]
                if not self._run_mux_tool(
                    extract_cmd,
                    label=f"HDR10+: MP4-Audio #{ordinal} extrahieren",
                    tool_name="ffmpeg",
                ):
                    return False
                if not audio_file.exists() or audio_file.stat().st_size < 128:
                    return False
                tags = stream.get("tags") or {}
                lang = str(tags.get("language") or "und").lower()
                title = str(tags.get("title") or "").replace('"', "'").strip()
                add = f"{audio_file}:lang={lang}"
                if title:
                    add += f':name="{title}"'
                cmd += ["-add", add]

        for subtitle_track in subtitle_tracks or ():
            if not (subtitle_track.path.exists() and subtitle_track.path.stat().st_size > 0):
                continue
            lang = str(subtitle_track.language or "und").strip().lower()
            title = str(subtitle_track.title or "").replace('"', "'").strip()
            if bool(getattr(subtitle_track, "forced", False)) and "forced" not in title.lower():
                title = f"{title} [Forced]".strip() if title else "Forced"
            add = f"{subtitle_track.path}:lang={lang}"
            if title:
                add += f':name="{title}"'
            cmd += ["-add", add]

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
