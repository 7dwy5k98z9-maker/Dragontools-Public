# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.process_runner import tool_available


@dataclass(frozen=True, slots=True)
class StreamInventory:
    source: str
    available: bool
    video: int = 0
    audio: int = 0
    subtitle: int = 0
    attachment: int = 0
    error: str = ""


@dataclass(slots=True)
class StreamGuardResult:
    ok: bool = True
    retry_recommended: bool = False
    messages: list[str] = field(default_factory=list)
    before_ffprobe: StreamInventory | None = None
    before_mediainfo: StreamInventory | None = None
    after_ffprobe: StreamInventory | None = None
    after_mediainfo: StreamInventory | None = None


class RepairStreamGuard:
    """Vergleicht Stream-Anzahlen unabhängig mit ffprobe und MediaInfo.

    ffprobe bleibt die normale Pipeline-Prüfung. MediaInfo dient als zweite,
    unabhängige Absicherung. Sobald ein Werkzeug einen möglichen Streamverlust
    meldet oder beide Inventare einander widersprechen, wird der Kandidat
    fail-closed verworfen und ein weiterer Reparaturversuch empfohlen.
    """

    def __init__(self, *, timing_analyzer, ffprobe_path: str, mediainfo_path: str, log) -> None:
        self._timing_analyzer = timing_analyzer
        self._ffprobe_path = str(ffprobe_path or "")
        self._mediainfo_path = str(mediainfo_path or "")
        self._log = log

    def inspect_pair(self, path: str) -> tuple[StreamInventory, StreamInventory]:
        return self._inspect_ffprobe(path), self._inspect_mediainfo(path)

    def validate(
        self,
        *,
        before_ffprobe: StreamInventory,
        before_mediainfo: StreamInventory,
        candidate_path: str,
        expected_contract=None,
    ) -> StreamGuardResult:
        after_ffprobe, after_mediainfo = self.inspect_pair(candidate_path)
        result = StreamGuardResult(
            before_ffprobe=before_ffprobe,
            before_mediainfo=before_mediainfo,
            after_ffprobe=after_ffprobe,
            after_mediainfo=after_mediainfo,
        )
        expected = self._expected_counts(before_ffprobe, before_mediainfo, expected_contract)

        for kind in ("video", "audio", "subtitle"):
            needed = expected[kind]
            if needed <= 0:
                continue
            ff_missing = after_ffprobe.available and getattr(after_ffprobe, kind) < needed
            mi_missing = after_mediainfo.available and getattr(after_mediainfo, kind) < needed

            if mi_missing:
                result.ok = False
                result.retry_recommended = True
                result.messages.append(
                    f"MediaInfo bestätigt fehlende {self._label(kind)}: "
                    f"erwartet {needed}, gefunden {getattr(after_mediainfo, kind)}."
                )
                continue
            if ff_missing and after_mediainfo.available:
                result.ok = False
                result.retry_recommended = True
                result.messages.append(
                    f"ffprobe und MediaInfo widersprechen sich bei {self._label(kind)}: "
                    f"erwartet {needed}, ffprobe={getattr(after_ffprobe, kind)}, "
                    f"MediaInfo={getattr(after_mediainfo, kind)}. Der Kandidat wird sicherheitshalber verworfen."
                )
                continue
            if ff_missing:
                result.ok = False
                result.retry_recommended = True
                result.messages.append(
                    f"ffprobe meldet fehlende {self._label(kind)} und MediaInfo ist nicht verfügbar: "
                    f"erwartet {needed}, gefunden {getattr(after_ffprobe, kind)}."
                )

        # Attachments sind bei MediaInfo nicht 1:1 zu ffprobe abbildbar (Menu != Attachment).
        # Deshalb ausschließlich ffprobe-zu-ffprobe vergleichen.
        if before_ffprobe.available and after_ffprobe.available:
            if after_ffprobe.attachment < before_ffprobe.attachment:
                result.ok = False
                result.retry_recommended = True
                result.messages.append(
                    "ffprobe meldet nach der Reparatur weniger Attachments/Attachment-Streams."
                )

        if not after_ffprobe.available:
            result.ok = False
            result.retry_recommended = True
            result.messages.append(
                "ffprobe konnte den Reparaturkandidaten nicht zuverlässig analysieren."
            )
        if not after_mediainfo.available and tool_available(self._mediainfo_path):
            result.messages.append(
                "MediaInfo war konfiguriert, konnte den Reparaturkandidaten aber nicht analysieren."
            )
        return result

    def _inspect_ffprobe(self, path: str) -> StreamInventory:
        if not tool_available(self._ffprobe_path):
            return StreamInventory("ffprobe", False, error="ffprobe nicht verfügbar")
        try:
            data = self._timing_analyzer.run_ffprobe_json(path, count_frames=False)
            streams = list(data.get("streams") or [])
            return StreamInventory(
                "ffprobe",
                True,
                video=sum(1 for s in streams if s.get("codec_type") == "video"),
                audio=sum(1 for s in streams if s.get("codec_type") == "audio"),
                subtitle=sum(1 for s in streams if s.get("codec_type") == "subtitle"),
                attachment=sum(1 for s in streams if s.get("codec_type") == "attachment"),
            )
        except Exception as exc:
            return StreamInventory("ffprobe", False, error=str(exc))

    def _inspect_mediainfo(self, path: str) -> StreamInventory:
        if not tool_available(self._mediainfo_path):
            return StreamInventory("MediaInfo", False, error="MediaInfo nicht verfügbar")
        try:
            data = self._timing_analyzer.run_mediainfo_json(path)
            tracks = list(((data.get("media") or {}).get("track")) or [])
            kinds = [str(t.get("@type") or t.get("track_type") or "").strip().casefold() for t in tracks]
            return StreamInventory(
                "MediaInfo",
                True,
                video=sum(1 for kind in kinds if kind == "video"),
                audio=sum(1 for kind in kinds if kind == "audio"),
                subtitle=sum(1 for kind in kinds if kind in {"text", "subtitle"}),
                attachment=sum(1 for kind in kinds if kind == "attachment"),
            )
        except Exception as exc:
            return StreamInventory("MediaInfo", False, error=str(exc))

    @staticmethod
    def _expected_counts(before_ffprobe: StreamInventory, before_mediainfo: StreamInventory, contract) -> dict[str, int]:
        counts = {
            "video": max(before_ffprobe.video if before_ffprobe.available else 0, before_mediainfo.video if before_mediainfo.available else 0),
            "audio": max(before_ffprobe.audio if before_ffprobe.available else 0, before_mediainfo.audio if before_mediainfo.available else 0),
            "subtitle": max(before_ffprobe.subtitle if before_ffprobe.available else 0, before_mediainfo.subtitle if before_mediainfo.available else 0),
        }
        if contract is not None:
            counts["video"] = max(counts["video"], int(getattr(contract, "video_stream_count", 0) or 0))
            counts["audio"] = max(counts["audio"], len(getattr(contract, "audio_tracks", []) or []))
            counts["subtitle"] = max(counts["subtitle"], len(getattr(contract, "subtitle_tracks", []) or []))
        return counts

    @staticmethod
    def _label(kind: str) -> str:
        return {"video": "Videostreams", "audio": "Audiospuren", "subtitle": "Untertitelspuren"}[kind]
