"""Accept a disputed duration when an independent tool confirms the video."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.media_duration import positive_seconds
from ..core.transaction_identity import stat_identity
from .duration_confirmation_sources import DurationConfirmationSources, DurationSample
from .verification_control import require_running

TOLERANCE_S = 1.0


@dataclass(frozen=True, slots=True)
class DurationVote:
    tool: str
    accepted: bool
    detail: str


def close_duration(left, right) -> bool:
    left, right = positive_seconds(left), positive_seconds(right)
    return bool(left is not None and right is not None and left < 1_000_000
                and right < 1_000_000 and abs(left - right) <= TOLERANCE_S + 1e-6)


def compare_durations(source: DurationSample, output: DurationSample, expected_contract) -> str:
    """Empty string means confirmation; all references remain video-specific."""
    if not close_duration(source.video_s, output.video_s):
        return f"Video weicht ab ({source.video_s:.3f}s → {output.video_s:.3f}s)"
    if source.count is not None and output.count is not None and source.frame_s and output.frame_s:
        if abs(source.frame_s - output.frame_s) < 1e-6:
            if abs(source.count - output.count) * source.frame_s > TOLERANCE_S + 1e-6:
                return "Videopaket-/Frameanzahl weicht bei gleicher Framerate um mehr als 1 s ab"
    references = []
    if expected_contract is not None:
        tracks = expected_contract.audio_tracks
        if len(tracks) != len(output.audio_s):
            return "Gewählte Audiospuren stimmen nicht überein"
        for track, actual in zip(tracks, output.audio_s):
            reference = positive_seconds(getattr(track, "duration_s", None))
            if reference is not None:
                if not close_duration(reference, actual):
                    return "Laufzeit der gewählten Audiospur weicht um mehr als 1 s ab"
                references.append(reference)
    elif len(source.audio_s) == len(output.audio_s):
        for reference, actual in zip(source.audio_s, output.audio_s):
            if reference is not None:
                if not close_duration(reference, actual):
                    return "Audiodauer weicht um mehr als 1 s ab"
                references.append(reference)
    else:
        return "Audiospurauswahl nicht unabhängig nachvollziehbar"
    # A matching video must not hide a broken/wrapped container. A legitimate
    # audio tail is allowed only using independently matching source audio.
    expected_container = max(source.video_s, *references) if references else source.video_s
    if not (close_duration(output.container_s, expected_container)
            or close_duration(output.container_s, source.container_s)):
        return "Containerdauer wird weder von Quelle noch gewählten Tracks bestätigt"
    return ""


def metadata_conflicts(source, output, measured_pairs) -> bool:
    """Derived/stale metadata cannot outvote actual packet timestamps."""
    return any(not close_duration(source.video_s, measured_source.video_s)
               or not close_duration(output.video_s, measured_output.video_s)
               for measured_source, measured_output in measured_pairs)


class DurationConfirmationService:
    def __init__(self, runtime, *, mkvextract_path="") -> None:
        self.runtime = runtime
        self.sources = DurationConfirmationSources(runtime, mkvextract_path=mkvextract_path)

    def confirm(self, *, source_path, output_path, expected_contract=None) -> tuple[DurationVote, ...]:
        require_running(worker=self.runtime.worker)
        if not source_path or not output_path:
            return ()
        source, output = Path(source_path), Path(output_path)
        if source.resolve() == output.resolve():
            return ()
        try:
            identities = stat_identity(source), stat_identity(output)
        except OSError:
            return ()
        pairs, votes = {}, {}
        readers = (("ffprobe/FFmpeg", self.sources.ffprobe),
                   ("MediaInfo", self.sources.mediainfo),
                   ("MKVToolNix", self.sources.mkvtoolnix))
        for label, read in readers:
            require_running(worker=self.runtime.worker)
            try:
                before, after = read(str(source)), read(str(output))
                pairs[label] = before, after
            except (OSError, RuntimeError, ValueError, TypeError, KeyError, OverflowError) as exc:
                votes[label] = DurationVote(label, False, f"keine Bestätigung verfügbar: {exc}")
            require_running(worker=self.runtime.worker)
        # Both input and output must remain the exact files we inspected.
        try:
            if identities != (stat_identity(source), stat_identity(output)):
                return tuple(DurationVote(label, False, "Datei während Prüfung verändert") for label, _ in readers)
        except OSError:
            return tuple(DurationVote(label, False, "Datei während Prüfung nicht mehr erreichbar") for label, _ in readers)
        measured = [(before, after) for before, after in pairs.values() if before.measured and after.measured]
        for label, (before, after) in pairs.items():
            reason = compare_durations(before, after, expected_contract)
            if not reason and not (before.measured and after.measured) and metadata_conflicts(before, after, measured):
                reason = "Metadaten widersprechen der tatsächlich vermessenen Videotimeline"
            detail = reason or f"Video bestätigt: {before.video_s:.3f}s → {after.video_s:.3f}s (±1,0 s)"
            votes[label] = DurationVote(label, not bool(reason), detail)
        return tuple(votes[label] for label, _ in readers)


def confirm_disputed_duration(ctx, result, repair_service) -> bool:
    """Only relax the duration flag; codec/stream/HDR/geometry gates stay intact."""
    if result.duration_ok or not all(getattr(result, name, False) for name in (
        "exists", "size_ok", "container_ok", "probe_ok", "video_ok", "audio_ok",
        "subtitle_ok", "contract_ok", "metadata_ok",
    )):
        return False
    confirm = getattr(repair_service, "confirm_duration", None)
    if not callable(confirm):
        return False
    votes = confirm(source_path=getattr(ctx, "input_path", None), output_path=ctx.output_path,
                    expected_contract=getattr(ctx, "expected_media_contract", None))
    accepted = [vote for vote in votes if vote.accepted]
    if not accepted:
        return False
    result.duration_ok = True
    result.messages = [message for message in (result.messages or [])
                       if message != "Ausgabedauer ist nicht plausibel."]
    result.warnings = list(result.warnings or []) + [
        f"Laufzeit-Gegenprüfung {vote.tool}: {vote.detail}" for vote in votes
    ]
    return True
