# -*- coding: utf-8 -*-
"""Pure data/model helpers for bitmap subtitle OCR drafts.

Patch J intentionally separates OCR generation from acceptance.  A worker may
create ``*.srt.pending`` + JSON metadata, but only the review step promotes the
edited draft to a normal SRT sidecar.  The source bitmap stream is never
modified or removed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import ExitStack
import csv
import io
import json
import os
from pathlib import Path
import re
from typing import Iterable

from .lang_codes import canonical_lang, lang_iso_tag
from .language_detection import detect_text_language


BITMAP_SUBTITLE_CODECS = frozenset({
    "hdmv_pgs_subtitle",
    "pgs",
    "dvd_subtitle",
    "vobsub",
})


@dataclass(frozen=True)
class BitmapSubtitlePacket:
    start_s: float
    end_s: float

    @property
    def midpoint_s(self) -> float:
        duration = max(0.0, self.end_s - self.start_s)
        return self.start_s + (duration * 0.5)


@dataclass(frozen=True)
class BitmapOcrCue:
    index: int
    start_s: float
    end_s: float
    text: str
    confidence: float
    uncertain: bool = False


@dataclass(frozen=True)
class BitmapOcrDraft:
    draft_path: str
    report_path: str
    cue_count: int
    uncertain_count: int
    average_confidence: float
    language: str
    language_probability: float
    message: str


def is_bitmap_subtitle_codec(codec: str | None) -> bool:
    return str(codec or "").strip().casefold() in BITMAP_SUBTITLE_CODECS


def parse_tesseract_tsv(tsv_text: str) -> tuple[str, float]:
    """Return OCR text and weighted word confidence from Tesseract TSV."""
    rows = csv.DictReader(io.StringIO(str(tsv_text or "")), delimiter="\t")
    lines: dict[tuple[str, str, str, str], list[str]] = {}
    confidence_sum = 0.0
    confidence_weight = 0
    for row in rows:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        try:
            confidence = float(row.get("conf") or -1)
        except (TypeError, ValueError):
            confidence = -1.0
        if confidence < 0:
            continue
        key = (
            str(row.get("page_num") or "0"),
            str(row.get("block_num") or "0"),
            str(row.get("par_num") or "0"),
            str(row.get("line_num") or "0"),
        )
        lines.setdefault(key, []).append(text)
        weight = max(1, len(re.sub(r"\s+", "", text)))
        confidence_sum += confidence * weight
        confidence_weight += weight
    rendered = "\n".join(" ".join(words).strip() for words in lines.values() if words).strip()
    probability = (confidence_sum / confidence_weight / 100.0) if confidence_weight else 0.0
    return rendered, max(0.0, min(1.0, probability))


def normalize_packets(packets: Iterable[BitmapSubtitlePacket]) -> list[BitmapSubtitlePacket]:
    result: list[BitmapSubtitlePacket] = []
    for packet in sorted(packets, key=lambda item: (item.start_s, item.end_s)):
        start = max(0.0, float(packet.start_s))
        end = max(start + 0.05, float(packet.end_s))
        if result and abs(result[-1].start_s - start) < 0.01 and abs(result[-1].end_s - end) < 0.01:
            continue
        result.append(BitmapSubtitlePacket(start, end))
    return result


def merge_adjacent_duplicate_cues(cues: Iterable[BitmapOcrCue], *, max_gap_s: float = 0.6) -> list[BitmapOcrCue]:
    merged: list[BitmapOcrCue] = []
    for cue in cues:
        text = _normalized_text(cue.text)
        if not text:
            continue
        if merged:
            previous = merged[-1]
            if (
                _normalized_text(previous.text).casefold() == text.casefold()
                and cue.start_s - previous.end_s <= max_gap_s
            ):
                merged[-1] = BitmapOcrCue(
                    index=previous.index,
                    start_s=previous.start_s,
                    end_s=max(previous.end_s, cue.end_s),
                    text=previous.text,
                    confidence=min(previous.confidence, cue.confidence),
                    uncertain=previous.uncertain or cue.uncertain,
                )
                continue
        merged.append(BitmapOcrCue(
            index=len(merged) + 1,
            start_s=cue.start_s,
            end_s=cue.end_s,
            text=text,
            confidence=cue.confidence,
            uncertain=cue.uncertain,
        ))
    return merged


def serialize_srt(cues: Iterable[BitmapOcrCue]) -> str:
    blocks: list[str] = []
    for number, cue in enumerate(cues, start=1):
        text = _normalized_text(cue.text)
        if not text:
            continue
        blocks.append(
            f"{number}\n{_srt_time(cue.start_s)} --> {_srt_time(cue.end_s)}\n{text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def write_pending_draft(
    *,
    media_path: str | Path,
    stream_ordinal: int,
    stream_index: int | None,
    codec: str,
    source_language: str,
    forced: bool,
    cues: Iterable[BitmapOcrCue],
    min_confidence: float,
) -> BitmapOcrDraft:
    media = Path(media_path)
    normalized = merge_adjacent_duplicate_cues(cues)
    if not normalized:
        raise RuntimeError("OCR hat keinen verwertbaren Untertiteltext erzeugt.")

    base = media.with_name(f"{media.stem}.track{max(1, int(stream_ordinal))}.ocr")
    draft_path = Path(str(base) + ".srt.pending")
    report_path = Path(str(base) + ".json.pending")
    if draft_path.exists() or report_path.exists():
        raise FileExistsError(
            f"OCR-Entwurf existiert bereits: {draft_path.name}. Bitte zuerst prüfen oder entfernen."
        )

    full_text = "\n".join(item.text for item in normalized)
    detected = detect_text_language(full_text, min_probability=0.70)
    language = canonical_lang(source_language)
    language_probability = 1.0 if language and language not in {"und", "unk"} else 0.0
    if not language or language in {"und", "unk"}:
        language = detected.language if detected.accepted else "und"
        language_probability = detected.probability if detected.language else 0.0

    average = sum(item.confidence for item in normalized) / len(normalized)
    uncertain_count = sum(1 for item in normalized if item.uncertain)
    payload = {
        "schema": 1,
        "media_path": str(media),
        "stream_ordinal": max(1, int(stream_ordinal)),
        "stream_index": stream_index,
        "codec": str(codec or ""),
        "source_language": str(source_language or ""),
        "detected_language": language,
        "language_probability": language_probability,
        "forced": bool(forced),
        "min_confidence": float(min_confidence),
        "average_confidence": average,
        "draft_path": str(draft_path),
        "cues": [asdict(item) for item in normalized],
    }
    # Reserve both names exclusively. Never overwrite another producer's draft.
    created = []
    try:
        with ExitStack() as stack:
            for target, content in (
                (draft_path, serialize_srt(normalized)),
                (report_path, json.dumps(payload, ensure_ascii=False, indent=2)),
            ):
                handle = stack.enter_context(target.open("x", encoding="utf-8", newline="\n"))
                created.append((target, os.fstat(handle.fileno())))
                handle.write(content)
    except Exception:
        for target, identity in created:
            try:
                current = target.lstat()
                if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                    target.unlink()
            except OSError:
                pass
        raise
    return BitmapOcrDraft(
        draft_path=str(draft_path),
        report_path=str(report_path),
        cue_count=len(normalized),
        uncertain_count=uncertain_count,
        average_confidence=average,
        language=language,
        language_probability=language_probability,
        message=(
            f"OCR-Entwurf: {len(normalized)} Cues, {uncertain_count} unsicher, "
            f"Ø {average * 100:.1f}% Konfidenz. Prüfung erforderlich."
        ),
    )


def load_ocr_report(report_path: str | Path) -> dict:
    path = Path(report_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if int(data.get("schema") or 0) != 1 or not isinstance(data.get("cues"), list):
        raise ValueError("Ungültiger OCR-Bericht.")
    return data


def finalize_ocr_report(
    report_path: str | Path,
    edited_texts: Iterable[str],
    *,
    expected_media: str | Path | None = None,
    expected_report: dict | None = None,
) -> Path:
    """Promote a reviewed pending draft to a collision-safe SRT sidecar."""
    report = load_ocr_report(report_path)
    if expected_report is not None and report != expected_report:
        raise ValueError("OCR-Bericht wurde während der Prüfung verändert. Bitte neu öffnen.")
    report_file = Path(report_path).absolute()
    media = Path(str(report.get("media_path") or "")).absolute()
    ordinal = int(report.get("stream_ordinal") or 0)
    base = media.with_name(f"{media.stem}.track{ordinal}.ocr")
    draft = Path(str(base) + ".srt.pending")
    expected_path = Path(str(base) + ".json.pending")
    if (ordinal < 1 or report_file != expected_path
            or Path(str(report.get("draft_path") or "")).absolute() != draft
            or (expected_media is not None and media != Path(expected_media).absolute())
            or not media.is_file()):
        raise ValueError("OCR-Bericht gehört nicht zu diesem Medienauftrag.")
    for candidate in (media, report_file, draft):
        if any(p.is_symlink() or p.is_junction() for p in (candidate, *candidate.parents)):
            raise ValueError("Verknüpfungen sind für OCR-Dateizugriffe nicht erlaubt.")
    cues_raw = list(report.get("cues") or [])
    texts = list(edited_texts)
    if len(texts) != len(cues_raw):
        raise ValueError("Die Anzahl bearbeiteter OCR-Zeilen passt nicht zum Bericht.")
    cues: list[BitmapOcrCue] = []
    for number, (raw, text) in enumerate(zip(cues_raw, texts), start=1):
        cues.append(BitmapOcrCue(
            index=number,
            start_s=float(raw.get("start_s") or 0.0),
            end_s=float(raw.get("end_s") or 0.0),
            text=_normalized_text(text),
            confidence=float(raw.get("confidence") or 0.0),
            uncertain=bool(raw.get("uncertain")),
        ))
    cues = [item for item in cues if item.text]
    if not cues:
        raise ValueError("Der geprüfte OCR-Entwurf enthält keinen Untertiteltext.")

    language = canonical_lang(str(report.get("detected_language") or "")) or "und"
    language = lang_iso_tag(language)
    if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", language):
        raise ValueError("Ungültige Sprache im OCR-Bericht.")
    forced = bool(report.get("forced"))
    for _attempt in range(1000):
        final_path = _next_sidecar_path(media, language=language, forced=forced)
        try:
            with final_path.open("x", encoding="utf-8", newline="\n") as output:
                output.write(serialize_srt(cues))
            break
        except FileExistsError:
            continue
    else:
        raise FileExistsError("Kein freier SRT-Sidecar-Dateiname gefunden.")

    try:
        if draft.is_file():
            draft.unlink()
    except OSError:
        pass
    try:
        Path(report_path).unlink()
    except OSError:
        pass
    return final_path


def _next_sidecar_path(media: Path, *, language: str, forced: bool) -> Path:
    suffix = f".{language}" + (".forced" if forced else "")
    first = media.with_name(media.stem + suffix + ".srt")
    if not first.exists():
        return first
    for number in range(1, 1000):
        candidate = media.with_name(media.stem + suffix + f".{number}.srt")
        if not candidate.exists():
            return candidate
    raise RuntimeError("Kein freier SRT-Sidecar-Dateiname gefunden.")


def _normalized_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in str(text or "").replace("\\N", "\n").splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _srt_time(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds or 0.0) * 1000.0)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


__all__ = [
    "BITMAP_SUBTITLE_CODECS",
    "BitmapOcrCue",
    "BitmapOcrDraft",
    "BitmapSubtitlePacket",
    "finalize_ocr_report",
    "is_bitmap_subtitle_codec",
    "load_ocr_report",
    "merge_adjacent_duplicate_cues",
    "normalize_packets",
    "parse_tesseract_tsv",
    "serialize_srt",
    "write_pending_draft",
]
