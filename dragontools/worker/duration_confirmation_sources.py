"""Independent video timelines for disputed output durations; media stay read-only."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory, TemporaryFile

from ..core.media_duration import positive_seconds, stream_duration
from ..core.process_runner import tool_available
from .duration_timing_parsing import parse_mediainfo_duration
from .packet_json_stream import JsonRecordReader
from .verification_control import require_running


@dataclass(frozen=True, slots=True)
class DurationSample:
    video_s: float
    container_s: float | None
    audio_s: tuple[float | None, ...] = ()
    measured: bool = False
    count: int | None = None
    frame_s: float | None = None


class DurationConfirmationSources:
    def __init__(self, runtime, *, mkvextract_path: str = "") -> None:
        self.runtime = runtime
        suffix = Path(runtime.mkvmerge_path).suffix
        self.mkvextract_path = mkvextract_path or (
            str(Path(runtime.mkvmerge_path).with_name("mkvextract" + suffix))
            if runtime.mkvmerge_path else ""
        )

    def _run(self, command, label, *, stdout_file=None, allow_warning=False):
        if not tool_available(command[0]):
            raise RuntimeError("Tool nicht verfügbar")
        run = self.runtime.run_tool(command, label=label, stdout_file=stdout_file)
        require_running(run, self.runtime.worker)
        if run.returncode not in ({0, 1} if allow_warning else {0}):
            raise RuntimeError((run.stderr or "Tool konnte die Laufzeit nicht lesen")[-1000:])
        return run

    def ffprobe(self, path: str) -> DurationSample:
        tool = self.runtime.ffprobe_path
        metadata = json.loads(self._run([
            tool, "-v", "error", "-show_format", "-show_streams", "-of", "json", path,
        ], "ffprobe Laufzeitmetadaten").stdout)
        fmt = metadata.get("format") or {}
        writer = str((fmt.get("tags") or {}).get("encoder") or "")
        audios = tuple(stream_duration(s, writing_application=writer)
                       for s in metadata.get("streams", ()) if s.get("codec_type") == "audio")
        # Write the full packet probe to a temporary file instead of keeping a
        # feature-length JSON array in the worker/tool runner's output buffer.
        with TemporaryFile(mode="w+", encoding="utf-8") as output:
            run = self._run([
                tool, "-v", "error", "-select_streams", "V:0", "-show_streams", "-show_packets",
                "-show_entries", "stream=index,codec_type,avg_frame_rate:packet=pts_time,duration_time",
                "-of", "json", path,
            ], "ffprobe tatsächliche Videolaufzeit", stdout_file=output)
            if run.stdout:  # injectable legacy tool adapters
                output.write(run.stdout)
            output.seek(0)
            first, end, count, frame_s = math.inf, -math.inf, 0, None
            for section, record in JsonRecordReader(output).records():
                if section == "streams":
                    try:
                        rate = Fraction(record.get("avg_frame_rate") or "0")
                        frame_s = float(1 / rate) if rate > 0 else None
                    except (ValueError, ZeroDivisionError):
                        frame_s = None
                    continue
                pts = float(record["pts_time"])
                length = positive_seconds(record.get("duration_time"))
                if not math.isfinite(pts) or length is None or pts >= 1_000_000:
                    raise ValueError("Videopaket ohne verlässliche Zeitstempel/Dauer")
                first, end = min(first, pts), max(end, pts + length)
                count += 1
        duration = positive_seconds(end - first)
        if not count or duration is None or duration >= 1_000_000:
            raise ValueError("Keine vollständige Videotimeline")
        return DurationSample(duration, positive_seconds(fmt.get("duration")), audios,
                              measured=True, count=count, frame_s=frame_s)

    def mediainfo(self, path: str) -> DurationSample:
        payload = json.loads(self._run([
            self.runtime.mediainfo_path, "--Output=JSON", path,
        ], "MediaInfo unabhängige Videolaufzeit").stdout)
        tracks = (payload.get("media") or {}).get("track") or []
        videos = [t for t in tracks if t.get("@type") == "Video"]
        if len(videos) != 1:
            raise ValueError("Videospur nicht eindeutig")
        duration = parse_mediainfo_duration(videos[0].get("Duration"))
        if duration is None or duration >= 1_000_000:
            raise ValueError("Keine verlässliche Videodauer")
        general = next((t for t in tracks if t.get("@type") == "General"), {})
        audios = tuple(parse_mediainfo_duration(t.get("Duration"))
                       for t in tracks if t.get("@type") == "Audio")
        return DurationSample(duration, parse_mediainfo_duration(general.get("Duration")), audios)

    def mkvtoolnix(self, path: str) -> DurationSample:
        if Path(path).suffix.lower() != ".mkv":
            raise RuntimeError("MKVToolNix-Timestampprüfung nur für MKV verfügbar")
        payload = json.loads(self._run([
            self.runtime.mkvmerge_path, "-J", path,
        ], "MKVToolNix Spuridentifikation", allow_warning=True).stdout)
        tracks = payload.get("tracks") or []
        videos = [t for t in tracks if t.get("type") == "video"]
        if len(videos) != 1:
            raise ValueError("Videospur nicht eindeutig")
        audios = [t for t in tracks if t.get("type") == "audio"]
        selected = [videos[0], *audios]
        with TemporaryDirectory(prefix="dragontools_duration_") as folder:
            outputs = [Path(folder) / f"track_{index}.txt" for index in range(len(selected))]
            command = [self.mkvextract_path, path, "timestamps_v2"]
            for track, output in zip(selected, outputs):
                identifier = track.get("id")
                if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier < 0:
                    raise ValueError("Ungültige MKV-Track-ID")
                command.append(f"{identifier}:{output}")
            self._run(command, "MKVToolNix tatsächliche Tracklaufzeiten", allow_warning=True)
            values = [read_mkv_timestamps(output, track.get("properties") or {})
                      for output, track in zip(outputs, selected)]
        properties = (payload.get("container") or {}).get("properties") or {}
        container_ns = positive_seconds(properties.get("duration"))
        video_s, count, frame_s = values[0]
        return DurationSample(video_s, container_ns / 1e9 if container_ns else None,
                              tuple(value[0] for value in values[1:]), True, count, frame_s)


def read_mkv_timestamps(path: Path, properties: dict) -> tuple[float, int, float]:
    first, last, count, recent = None, None, 0, []
    with path.open(encoding="utf-8-sig") as source:
        for line in source:
            if not line.strip() or line.startswith("#"):
                continue
            value = float(line.strip()) / 1000
            if not math.isfinite(value) or value >= 1_000_000:
                raise ValueError("Ungültiger MKV-Zeitstempel")
            # MKV extraction can preserve decode order for B-frames. Their
            # presentation timestamps legitimately arrive out of order.
            first = min(first, value) if first is not None else value
            last = max(last, value) if last is not None else value
            recent.append(value)
            recent = recent[-128:]
            count += 1
    default_ns = positive_seconds(properties.get("default_duration"))
    ordered = sorted(set(recent))
    steps = [right - left for left, right in zip(ordered, ordered[1:])]
    frame_s = default_ns / 1e9 if default_ns else (median(steps) if steps else None)
    if first is None or last is None or frame_s is None or frame_s <= 0:
        raise ValueError("MKV-Timeline nicht vollständig vermessbar")
    return last - first + frame_s, count, frame_s
