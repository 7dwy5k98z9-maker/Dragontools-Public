# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

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
    before_mkvmerge: StreamInventory | None = None
    after_ffprobe: StreamInventory | None = None
    after_mediainfo: StreamInventory | None = None
    after_mkvmerge: StreamInventory | None = None
    confirmed_kinds: set[str] = field(default_factory=set)


class RepairStreamGuard:
    """Mehrfach abgesicherte Stream-Gegenprüfung für Reparaturkandidaten.

    ffprobe, MediaInfo und MKVToolNix werden bewusst als drei unabhängige
    Beobachter behandelt. Ein erwarteter Video-/Audio-/Untertiteltyp gilt als
    vorhanden, sobald *eines* der verfügbaren Werkzeuge die erwartete Anzahl
    bestätigt. Als wirklich fehlend wird er nur bewertet, wenn alle drei Tools
    erfolgreich analysieren konnten und alle drei den Stream als fehlend
    melden. Dadurch kann ein einzelner Parserfehler (z. B. MediaInfo V=0/A=0/S=0
    bei einem ansonsten lesbaren MKV) keinen intakten Reparaturkandidaten mehr
    verwerfen.
    """

    def __init__(
        self,
        *,
        timing_analyzer,
        ffprobe_path: str,
        mediainfo_path: str,
        log,
        mkvmerge_path: str = "",
        run_tool_fn: Callable | None = None,
    ) -> None:
        self._timing_analyzer = timing_analyzer
        self._ffprobe_path = str(ffprobe_path or "")
        self._mediainfo_path = str(mediainfo_path or "")
        self._mkvmerge_path = str(mkvmerge_path or "")
        self._log = log
        self._run_tool_fn = run_tool_fn

    def inspect_pair(self, path: str) -> tuple[StreamInventory, StreamInventory]:
        """Legacy-API: ffprobe + MediaInfo."""
        return self._inspect_ffprobe(path), self._inspect_mediainfo(path)

    def inspect_all(self, path: str) -> tuple[StreamInventory, StreamInventory, StreamInventory]:
        return self._inspect_ffprobe(path), self._inspect_mediainfo(path), self._inspect_mkvmerge(path)

    def validate(
        self,
        *,
        before_ffprobe: StreamInventory,
        before_mediainfo: StreamInventory,
        candidate_path: str,
        expected_contract=None,
        before_mkvmerge: StreamInventory | None = None,
    ) -> StreamGuardResult:
        after_ffprobe, after_mediainfo, after_mkvmerge = self.inspect_all(candidate_path)
        if before_mkvmerge is None:
            before_mkvmerge = StreamInventory(
                "MKVToolNix", False, error="Referenzinventar nicht vorab ermittelt"
            )
        result = StreamGuardResult(
            before_ffprobe=before_ffprobe,
            before_mediainfo=before_mediainfo,
            before_mkvmerge=before_mkvmerge,
            after_ffprobe=after_ffprobe,
            after_mediainfo=after_mediainfo,
            after_mkvmerge=after_mkvmerge,
        )
        expected = self._expected_counts(before_ffprobe, before_mediainfo, before_mkvmerge, expected_contract)
        after = (after_ffprobe, after_mediainfo, after_mkvmerge)

        for kind in ("video", "audio", "subtitle"):
            needed = expected[kind]
            if needed <= 0:
                continue
            confirming = [inv for inv in after if inv.available and getattr(inv, kind) >= needed]
            if confirming:
                result.confirmed_kinds.add(kind)
                disagreeing = [inv for inv in after if inv.available and getattr(inv, kind) < needed]
                if disagreeing:
                    result.messages.append(
                        f"Parser-Widerspruch bei {self._label(kind)}: "
                        + ", ".join(f"{inv.source}={getattr(inv, kind)}" for inv in after if inv.available)
                        + f"; erwartet {needed}. Vorhanden gilt, weil mindestens ein Werkzeug bestätigt."
                    )
                continue

            all_three_available = all(inv.available for inv in after)
            if all_three_available:
                result.ok = False
                result.retry_recommended = True
                result.messages.append(
                    f"Alle drei Prüfwerkzeuge melden fehlende {self._label(kind)}: erwartet {needed}; "
                    + ", ".join(f"{inv.source}={getattr(inv, kind)}" for inv in after)
                    + "."
                )
            else:
                # Kein positives Signal, aber auch kein belastbarer 3-von-3-Nachweis.
                # Fail-safe: nicht als 'wirklich weg' klassifizieren; die nachgelagerte
                # Paket-/Vertragsprüfung entscheidet weiter.
                result.messages.append(
                    f"{self._label(kind)} konnten nicht von allen drei Werkzeugen gegengeprüft werden; "
                    f"erwartet {needed}. Kein 3-von-3-Verlustnachweis."
                )

        # Attachments sind zwischen den Tools nicht 1:1 vergleichbar. Hier bleibt
        # ffprobe die Referenz, sofern es vorher und nachher auswertbar ist.
        if before_ffprobe.available and after_ffprobe.available:
            if after_ffprobe.attachment < before_ffprobe.attachment:
                result.ok = False
                result.retry_recommended = True
                result.messages.append("ffprobe meldet nach der Reparatur weniger Attachments/Attachment-Streams.")

        if not any(inv.available for inv in after):
            result.ok = False
            result.retry_recommended = True
            result.messages.append("Keines der drei Prüfwerkzeuge konnte den Reparaturkandidaten analysieren.")
        return result

    def _inspect_ffprobe(self, path: str) -> StreamInventory:
        if not path or not tool_available(self._ffprobe_path):
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
        if not path or not tool_available(self._mediainfo_path):
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

    def _inspect_mkvmerge(self, path: str) -> StreamInventory:
        if not path or not tool_available(self._mkvmerge_path):
            return StreamInventory("MKVToolNix", False, error="mkvmerge nicht verfügbar")
        if self._run_tool_fn is None:
            return StreamInventory("MKVToolNix", False, error="mkvmerge Runner nicht verfügbar")
        try:
            run = self._run_tool_fn([self._mkvmerge_path, "-J", str(path)], label="MKVToolNix-Streamanalyse")
            if getattr(run, "returncode", 1) != 0:
                detail = str(getattr(run, "stderr", "") or getattr(run, "stdout", "") or "mkvmerge -J fehlgeschlagen")
                return StreamInventory("MKVToolNix", False, error=detail.strip())
            data = json.loads(str(getattr(run, "stdout", "") or "{}"))
            tracks = list(data.get("tracks") or [])
            types = [str(track.get("type") or "").strip().casefold() for track in tracks]
            return StreamInventory(
                "MKVToolNix",
                True,
                video=sum(1 for kind in types if kind == "video"),
                audio=sum(1 for kind in types if kind == "audio"),
                subtitle=sum(1 for kind in types if kind in {"subtitles", "subtitle"}),
                attachment=0,
            )
        except Exception as exc:
            return StreamInventory("MKVToolNix", False, error=str(exc))

    @staticmethod
    def _expected_counts(
        before_ffprobe: StreamInventory,
        before_mediainfo: StreamInventory,
        before_mkvmerge: StreamInventory | None,
        contract,
    ) -> dict[str, int]:
        before_all = [before_ffprobe, before_mediainfo]
        if before_mkvmerge is not None:
            before_all.append(before_mkvmerge)
        counts = {
            kind: max((getattr(inv, kind) for inv in before_all if inv.available), default=0)
            for kind in ("video", "audio", "subtitle")
        }
        if contract is not None:
            counts["video"] = max(counts["video"], int(getattr(contract, "video_stream_count", 0) or 0))
            counts["audio"] = max(counts["audio"], len(getattr(contract, "audio_tracks", []) or []))
            counts["subtitle"] = max(counts["subtitle"], len(getattr(contract, "subtitle_tracks", []) or []))
        return counts

    @staticmethod
    def _label(kind: str) -> str:
        return {"video": "Videostreams", "audio": "Audiospuren", "subtitle": "Untertitelspuren"}[kind]
