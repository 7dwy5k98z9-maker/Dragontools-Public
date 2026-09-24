# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from uuid import uuid4

from ..core.process_runner import tool_available
from .duration_repair_models import MediaTimingInfo, TimestampRepairResult, duration_close
from .duration_repair_stream_guard import RepairStreamGuard
from .duration_timestamp_candidate_archive import RejectedTimestampArchive
from .workflow_engine import WorkflowVerifyResult


@dataclass(frozen=True, slots=True)
class SourceVideoTimeline:
    timestamps_s: tuple[float, ...]
    duration_s: float

    @property
    def frame_count(self) -> int:
        return len(self.timestamps_s)


class OriginalTimelineRepairService:
    """Repairs MKV VFR video timestamps from the still-intact source timeline.

    The fallback is deliberately strict: it only transfers the original video
    PTS when source and output contain exactly the same number of video frames.
    No timestamps are interpolated and no CFR cadence is invented.
    """

    def __init__(self, runtime, timing_analyzer, stream_guard: RepairStreamGuard) -> None:
        self._runtime = runtime
        self._timing_analyzer = timing_analyzer
        self._stream_guard = stream_guard
        self._archive = RejectedTimestampArchive(runtime)

    def try_repair(
        self,
        *,
        source: Path,
        out: Path,
        base_dir: Path | None,
        container: str,
        expected_duration_ms: int | None,
        expected_duration_s: float | None,
        source_has_audio: bool,
        reference_result: WorkflowVerifyResult,
        before: MediaTimingInfo,
        timing_summary: list[str],
        expected_contract=None,
        verified_hdr10plus: bool = False,
        verified_dolby_vision: bool = False,
    ) -> TimestampRepairResult:
        eligibility_error = self._eligibility_error(source, out, container, before)
        if eligibility_error:
            return self._skipped(reference_result, eligibility_error, timing_summary)

        self._runtime.log(
            "ℹ️ VFR erkannt - versuche Original-Timeline-Fallback mit den PTS der Quelldatei.",
            "info",
        )
        try:
            source_info = self._timing_analyzer.get_media_timing_info(
                str(source), expected_duration_s=expected_duration_s
            )
            timeline = self._read_source_timeline(source)
        except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError) as exc:
            reason = f"Original-Timeline konnte nicht gelesen werden: {exc}"
            self._runtime.log(f"⚠️ {reason}", "warn")
            return self._skipped(reference_result, reason, timing_summary)

        validation_error = self._source_timeline_error(
            timeline, source_info=source_info, before=before, expected_duration_s=expected_duration_s
        )
        extended_summary = list(timing_summary) + [
            f"Original-Videoframes: {timeline.frame_count}",
            f"Original-VFR-Timeline: {timeline.duration_s:.3f}s",
        ]
        if validation_error:
            self._runtime.log(f"⚠️ Original-Timeline-Fallback verworfen: {validation_error}", "warn")
            return self._skipped(reference_result, validation_error, extended_summary)

        try:
            video_track_id = self._mkv_video_track_id(out)
        except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
            reason = f"MKV-Videotrack konnte nicht eindeutig bestimmt werden: {exc}"
            self._runtime.log(f"⚠️ {reason}", "warn")
            return self._skipped(reference_result, reason, extended_summary)

        timecodes = out.with_name(f"{out.stem}.source_timestamps_{uuid4().hex}.txt")
        tmp = out.with_name(f"{out.stem}.timestamp_source_{uuid4().hex}{out.suffix}")
        command: list[str] | None = None
        try:
            self._write_timecodes_v2(timecodes, timeline)
            command = [
                self._runtime.mkvmerge_path,
                "-o",
                str(tmp),
                "--timestamps",
                f"{video_track_id}:{timecodes}",
                str(out),
            ]
            before_ffprobe, before_mediainfo = self._stream_guard.inspect_pair(str(out))
            run = self._runtime.run_tool(command, label="MKVToolNix-Original-Timeline-Reparatur")
            if run.returncode > 1 or not self._candidate_plausible(out, tmp):
                detail = (run.stderr or run.stdout or f"Returncode {run.returncode}").strip().splitlines()
                reason = "Original-Timeline-Remux fehlgeschlagen"
                if detail:
                    reason += f": {detail[-1]}"
                self._archive.archive(
                    tmp, out=out, base_dir=base_dir,
                    label="Original-Timeline-Reparatur", reason=reason,
                )
                self._runtime.log(f"❌ {reason}", "error")
                return TimestampRepairResult(
                    attempted=True,
                    verify_result=reference_result,
                    reason=reason,
                    command=command,
                    timing_summary=extended_summary,
                    retry_recommended=False,
                    tool_returncode=run.returncode,
                    method="Original-VFR-Timeline",
                )

            candidate = self._validate_candidate(
                tmp,
                timeline=timeline,
                before=before,
                before_ffprobe=before_ffprobe,
                before_mediainfo=before_mediainfo,
                container=container,
                expected_duration_ms=expected_duration_ms,
                source_has_audio=source_has_audio,
                expected_contract=expected_contract,
                verified_hdr10plus=verified_hdr10plus,
                verified_dolby_vision=verified_dolby_vision,
            )
            if candidate[0] is not None:
                reason, verify_result, duration_s = candidate
                self._runtime.log(f"❌ Original-Timeline-Reparatur verworfen: {reason}", "error")
                self._archive.archive(
                    tmp, out=out, base_dir=base_dir,
                    label="Original-Timeline-Reparatur", reason=reason,
                )
                return TimestampRepairResult(
                    attempted=True,
                    verify_result=verify_result,
                    duration_s=duration_s,
                    reason=reason,
                    command=command,
                    timing_summary=extended_summary,
                    retry_recommended=False,
                    tool_returncode=run.returncode,
                    method="Original-VFR-Timeline",
                )

            _, verify_result, duration_s = candidate
            self._runtime.replace_file(tmp, out)
            self._runtime.log(
                "✅ VFR-Timestamps wurden verlustfrei aus der Originaldatei übernommen.",
                "info",
            )
            self._runtime.log(
                f"   Original-Timeline: {timeline.duration_s:.3f}s | reparierte Videodauer: "
                f"{duration_s:.3f}s" if duration_s is not None else
                f"   Original-Timeline: {timeline.duration_s:.3f}s",
                "info",
            )
            return TimestampRepairResult(
                attempted=True,
                repaired=True,
                verify_result=verify_result,
                duration_s=duration_s,
                reason="Timestamp-Reparatur erfolgreich (Original-VFR-Timeline).",
                command=command,
                timing_summary=extended_summary,
                retry_recommended=False,
                tool_returncode=run.returncode,
                method="Original-VFR-Timeline",
            )
        except Exception as exc:
            self._runtime.safe_unlink(tmp)
            reason = f"Original-Timeline-Reparatur fehlgeschlagen: {exc}"
            self._runtime.log(f"❌ {reason}", "error")
            return TimestampRepairResult(
                attempted=True,
                verify_result=reference_result,
                reason=reason,
                command=command,
                timing_summary=extended_summary,
                retry_recommended=False,
                method="Original-VFR-Timeline",
            )
        finally:
            self._runtime.safe_unlink(timecodes)

    def _eligibility_error(self, source: Path, out: Path, container: str, before: MediaTimingInfo) -> str:
        if str(container or "").strip().lower().lstrip(".") != "mkv":
            return "Original-Timeline-Fallback ist derzeit nur für MKV vorgesehen."
        if not source.exists() or not source.is_file():
            return "Originaldatei ist nicht mehr verfügbar."
        if not out.exists() or not out.is_file():
            return "Reparaturausgabe ist nicht verfügbar."
        try:
            if source.resolve() == out.resolve():
                return "Originaldatei und Reparaturausgabe sind identisch."
        except OSError:
            pass
        if not tool_available(self._runtime.ffprobe_path):
            return "ffprobe wurde nicht gefunden."
        if not tool_available(self._runtime.mkvmerge_path):
            return "MKVToolNix wurde nicht gefunden."
        if before.video_frame_count is None or before.video_frame_count <= 0:
            return "Videoframe-Anzahl der Ausgabe ist unbekannt."
        return ""

    def _read_source_timeline(self, source: Path) -> SourceVideoTimeline:
        command = [
            self._runtime.ffprobe_path,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_frames",
            "-show_entries", "frame=best_effort_timestamp_time,pts_time,pkt_duration_time",
            "-of", "json",
            str(source),
        ]
        run = self._runtime.run_tool(command, label="ffprobe-Original-Timeline")
        if run.returncode != 0:
            raise RuntimeError((run.stderr or run.stdout or "ffprobe fehlgeschlagen.").strip())
        payload = json.loads(run.stdout or "{}")
        frames = list(payload.get("frames") or [])
        points: list[float] = []
        for frame in frames:
            pts = self._finite_float(frame.get("best_effort_timestamp_time"))
            if pts is None:
                pts = self._finite_float(frame.get("pts_time"))
            if pts is None:
                raise ValueError("Mindestens ein Videoframe besitzt keinen verwertbaren PTS.")
            points.append(pts)
            # pkt_duration_time is only relevant for the final frame.  Keeping
            # durations from arbitrary earlier frames can hide a missing/invalid
            # duration on the actual last frame.
        if len(points) < 2:
            raise ValueError("Zu wenige Video-PTS in der Originaldatei.")
        first = points[0]
        normalized = [value - first for value in points]
        deltas = [b - a for a, b in zip(normalized, normalized[1:])]
        if any(delta <= 0 or not math.isfinite(delta) for delta in deltas):
            raise ValueError("Original-PTS sind nicht streng monoton steigend.")
        last_duration = self._finite_float(frames[-1].get("pkt_duration_time"))
        if last_duration is None or last_duration <= 0:
            last_duration = median(deltas[-min(len(deltas), 120):])
        if last_duration <= 0 or not math.isfinite(last_duration):
            raise ValueError("Dauer des letzten Originalframes ist nicht bestimmbar.")
        return SourceVideoTimeline(tuple(normalized), normalized[-1] + last_duration)

    def _source_timeline_error(
        self,
        timeline: SourceVideoTimeline,
        *,
        source_info: MediaTimingInfo,
        before: MediaTimingInfo,
        expected_duration_s: float | None,
    ) -> str:
        if timeline.frame_count != int(before.video_frame_count or 0):
            return (
                "Frameanzahl stimmt nicht überein: "
                f"Original={timeline.frame_count}, Ausgabe={before.video_frame_count}."
            )
        source_frames = source_info.video_frame_count
        if source_frames is not None and source_frames > 0 and source_frames != timeline.frame_count:
            return (
                "Originalanalyse und extrahierte Timeline widersprechen sich bei der Frameanzahl: "
                f"Analyse={source_frames}, Timeline={timeline.frame_count}."
            )
        if source_info.video_start_s is not None and source_info.audio_start_s is not None:
            if abs(source_info.video_start_s - source_info.audio_start_s) > 1.0:
                return (
                    "Originaldatei besitzt bereits einen unplausiblen Audio-/Video-Startversatz: "
                    f"Video={source_info.video_start_s:.3f}s, Audio={source_info.audio_start_s:.3f}s."
                )
        if source_info.audio_duration_s is not None and not duration_close(
            source_info.audio_duration_s,
            timeline.duration_s,
            min_tolerance_s=5.0,
            relative_tolerance=0.01,
        ):
            return (
                "Original-Audiodauer passt nicht sicher zur extrahierten Video-Timeline: "
                f"Audio={source_info.audio_duration_s:.3f}s, Video={timeline.duration_s:.3f}s."
            )
        if expected_duration_s is not None and not duration_close(
            timeline.duration_s,
            expected_duration_s,
            min_tolerance_s=60.0,
            relative_tolerance=0.10,
        ):
            return (
                "Original-Timeline weicht zu stark von der bekannten Quelldauer ab: "
                f"Timeline={timeline.duration_s:.3f}s, Quelle={expected_duration_s:.3f}s."
            )
        return ""

    def _mkv_video_track_id(self, out: Path) -> int:
        run = self._runtime.run_tool(
            [self._runtime.mkvmerge_path, "-J", str(out)],
            label="MKVToolNix-Trackanalyse",
        )
        if run.returncode != 0:
            raise RuntimeError((run.stderr or run.stdout or "mkvmerge -J fehlgeschlagen.").strip())
        payload = json.loads(run.stdout or "{}")
        video_tracks = [track for track in (payload.get("tracks") or []) if track.get("type") == "video"]
        if len(video_tracks) != 1:
            raise ValueError(f"erwartet genau 1 Videotrack, gefunden {len(video_tracks)}")
        try:
            return int(video_tracks[0]["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Videotrack-ID fehlt") from exc

    @staticmethod
    def _write_timecodes_v2(path: Path, timeline: SourceVideoTimeline) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("# timestamp format v2\n")
            for timestamp_s in timeline.timestamps_s:
                handle.write(f"{timestamp_s * 1000.0:.6f}\n")

    def _validate_candidate(
        self,
        path: Path,
        *,
        timeline: SourceVideoTimeline,
        before: MediaTimingInfo,
        before_ffprobe,
        before_mediainfo,
        container: str,
        expected_duration_ms: int | None,
        source_has_audio: bool,
        expected_contract,
        verified_hdr10plus: bool,
        verified_dolby_vision: bool,
    ) -> tuple[str | None, WorkflowVerifyResult, float | None]:
        info = self._timing_analyzer.get_media_timing_info(str(path), expected_duration_s=timeline.duration_s)
        verify_kwargs = {
            "expected_duration_ms": expected_duration_ms,
            "source_has_audio": source_has_audio,
        }
        if expected_contract is not None:
            verify_kwargs["expected_contract"] = expected_contract
        if verified_hdr10plus:
            verify_kwargs["verified_hdr10plus"] = True
        if verified_dolby_vision:
            verify_kwargs["verified_dolby_vision"] = True
        verify_result = self._runtime.output_verifier.verify(str(path), container, **verify_kwargs)
        guard = self._stream_guard.validate(
            before_ffprobe=before_ffprobe,
            before_mediainfo=before_mediainfo,
            candidate_path=str(path),
            expected_contract=expected_contract,
        )
        reasons = list(verify_result.messages or []) if not verify_result.ok else []
        if not guard.ok:
            reasons.extend(message for message in guard.messages if message not in reasons)
        if info.video_frame_count is not None and info.video_frame_count != timeline.frame_count:
            reasons.append(
                f"Frameanzahl nach Original-Timeline-Remux ist verändert: {info.video_frame_count} statt {timeline.frame_count}."
            )
        if not duration_close(
            info.video_duration_s,
            timeline.duration_s,
            min_tolerance_s=3.0,
            relative_tolerance=0.01,
        ):
            reasons.append(
                "Reparierte Videodauer folgt nicht der Original-Timeline: "
                f"Video={self._fmt(info.video_duration_s)}, Original={timeline.duration_s:.3f}s."
            )
        if source_has_audio and info.audio_duration_s is not None and not duration_close(
            info.audio_duration_s,
            timeline.duration_s,
            min_tolerance_s=5.0,
            relative_tolerance=0.01,
        ):
            reasons.append(
                "Audio ist nach der Reparatur nicht plausibel synchron zur Original-Timeline: "
                f"Audio={info.audio_duration_s:.3f}s, Original={timeline.duration_s:.3f}s."
            )
        if info.video_start_s is not None and info.audio_start_s is not None:
            if abs(info.video_start_s - info.audio_start_s) > 1.0:
                reasons.append("Audio und Video starten nach Original-Timeline-Reparatur nicht synchron.")
        duration_s = info.video_duration_s or verify_result.duration_s
        return ("; ".join(dict.fromkeys(reasons)) if reasons else None, verify_result, duration_s)

    @staticmethod
    def _candidate_plausible(out: Path, tmp: Path) -> bool:
        try:
            return tmp.exists() and tmp.stat().st_size >= max(1024, int(out.stat().st_size * 0.25))
        except OSError:
            return False

    @staticmethod
    def _finite_float(value) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    @staticmethod
    def _fmt(value: float | None) -> str:
        return "unbekannt" if value is None else f"{value:.3f}s"

    @staticmethod
    def _skipped(
        reference_result: WorkflowVerifyResult,
        reason: str,
        timing_summary: list[str],
    ) -> TimestampRepairResult:
        return TimestampRepairResult(
            attempted=False,
            repaired=False,
            verify_result=reference_result,
            reason=reason,
            timing_summary=list(timing_summary),
            retry_recommended=False,
            method="Original-VFR-Timeline",
        )
