# -*- coding: utf-8 -*-
"""Language-detection primitives used by the media-library Fix Queue.

The module deliberately has no hard dependency on ``faster-whisper``.  The
Whisper backend is loaded lazily only when audio language detection is actually
requested, so Dragon Tools can start and operate normally without the optional
package/model.
"""
from __future__ import annotations
import logging

from dataclasses import dataclass
import re
from typing import Iterable

from .lang_codes import canonical_lang, lang_display
from .whisper_runtime import resolve_whisper_model_reference, whisper_runtime_available


@dataclass(frozen=True)
class LanguageEvidence:
    language: str
    probability: float
    source: str = ""


@dataclass(frozen=True)
class LanguageDetectionResult:
    language: str
    probability: float
    accepted: bool
    evidence: tuple[LanguageEvidence, ...] = ()
    reason: str = ""

    @property
    def display_language(self) -> str:
        return lang_display(self.language) if self.language else "Unbekannt"


def combine_language_evidence(
    evidence: Iterable[LanguageEvidence],
    *,
    min_probability: float = 0.85,
) -> LanguageDetectionResult:
    """Combine independent samples conservatively.

    Confidence is the winning language's probability mass divided by the total
    number of requested/usable samples.  Conflicting samples therefore lower
    confidence instead of being hidden by a simple majority vote.
    """
    normalized: list[LanguageEvidence] = []
    for item in evidence:
        language = canonical_lang(item.language)
        probability = max(0.0, min(1.0, float(item.probability or 0.0)))
        if language and language not in {"und", "unk", "unknown"}:
            normalized.append(LanguageEvidence(language, probability, item.source))
    if not normalized:
        return LanguageDetectionResult("", 0.0, False, (), "Keine verwertbare Sprache erkannt.")

    score: dict[str, float] = {}
    support: dict[str, int] = {}
    for item in normalized:
        score[item.language] = score.get(item.language, 0.0) + item.probability
        support[item.language] = support.get(item.language, 0) + 1
    winner = max(score, key=lambda key: (score[key], support[key], key))
    confidence = score[winner] / len(normalized)
    required_support = (len(normalized) // 2) + 1
    accepted = support[winner] >= required_support and confidence >= float(min_probability)
    reason = (
        f"{lang_display(winner)} mit {confidence * 100:.1f}% Konsens "
        f"({support[winner]}/{len(normalized)} Samples)."
    )
    if not accepted:
        reason += f" Mindestkonfidenz: {float(min_probability) * 100:.0f}%."
    return LanguageDetectionResult(winner, confidence, accepted, tuple(normalized), reason)


class FasterWhisperLanguageDetector:
    """Lazy ``faster-whisper`` backend for short PCM/WAV samples."""

    def __init__(
        self,
        *,
        model_name: str = "small",
        model_path: str = "",
        use_local_model: bool | None = None,
    ) -> None:
        self.model_name = str(model_name or "small").strip() or "small"
        self.model_path = str(model_path or "").strip()
        self.use_local_model = bool(self.model_path) if use_local_model is None else bool(use_local_model)
        self._model = None
        self._backend = ""

    @staticmethod
    def available() -> bool:
        return whisper_runtime_available()

    @property
    def backend(self) -> str:
        return self._backend

    def detect_file(self, audio_path: str) -> LanguageEvidence:
        model = self._ensure_model()
        segments, info = model.transcribe(
            str(audio_path),
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        # faster-whisper executes lazily; consume the generator so decoding and
        # VAD errors surface inside this call rather than later in a worker.
        list(segments)
        return LanguageEvidence(
            canonical_lang(getattr(info, "language", "")),
            float(getattr(info, "language_probability", 0.0) or 0.0),
            source=str(audio_path),
        )

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        if not self.available():
            raise RuntimeError(
                "faster-whisper ist nicht installiert. Audio-Spracherkennung ist optional und bleibt deaktiviert."
            )
        from faster_whisper import WhisperModel  # type: ignore

        model_reference = resolve_whisper_model_reference(
            model_name=self.model_name,
            model_dir=self.model_path,
            use_local_model=self.use_local_model,
        )
        device, compute_type = self._preferred_backend()
        try:
            self._model = WhisperModel(model_reference, device=device, compute_type=compute_type)
            self._backend = f"{device}/{compute_type}"
        except Exception:
            if device == "cpu":
                raise
            self._model = WhisperModel(model_reference, device="cpu", compute_type="int8")
            self._backend = "cpu/int8"
        return self._model

    @staticmethod
    def _preferred_backend() -> tuple[str, str]:
        try:
            import ctranslate2  # type: ignore

            if int(ctranslate2.get_cuda_device_count()) > 0:
                return "cuda", "float16"
        except Exception:
            logging.getLogger(__name__).debug("Unterdrückte Best-Effort-Ausnahme in _preferred_backend.", exc_info=True)
        return "cpu", "int8"


_TIMESTAMP_RE = re.compile(r"^\s*\d{1,2}:\d{2}(?::\d{2})?[,.]\d{2,3}\s+-->\s+", re.MULTILINE)
_ASS_TAG_RE = re.compile(r"\{[^{}]*\}")
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# Frequent function words are intentionally favoured over topical vocabulary.
# This is not intended as a general NLP detector; it is a dependency-free
# safety gate for subtitle streams before metadata is changed.
_STOPWORDS: dict[str, set[str]] = {
    "de": {"der", "die", "das", "und", "ist", "ich", "du", "nicht", "wir", "sie", "ein", "eine", "zu", "mit", "was", "auf", "den", "von", "mir", "für"},
    "en": {"the", "and", "is", "you", "i", "not", "we", "they", "a", "to", "with", "what", "of", "in", "for", "that", "this", "it", "my", "me"},
    "fr": {"le", "la", "les", "et", "est", "je", "tu", "pas", "nous", "vous", "un", "une", "de", "des", "avec", "que", "pour", "dans", "mon", "mais"},
    "es": {"el", "la", "los", "las", "y", "es", "yo", "tu", "no", "nosotros", "un", "una", "de", "con", "que", "para", "en", "mi", "por", "pero"},
    "it": {"il", "la", "gli", "le", "e", "è", "io", "tu", "non", "noi", "un", "una", "di", "con", "che", "per", "in", "mio", "ma", "sono"},
    "pt": {"o", "a", "os", "as", "e", "é", "eu", "você", "não", "nós", "um", "uma", "de", "com", "que", "para", "em", "meu", "por", "mas"},
    "nl": {"de", "het", "een", "en", "is", "ik", "jij", "niet", "wij", "ze", "van", "met", "wat", "voor", "in", "dat", "dit", "mijn", "maar", "op"},
    "pl": {"i", "jest", "ja", "ty", "nie", "my", "oni", "to", "z", "co", "na", "do", "dla", "w", "że", "mój", "ale", "się", "jak", "tak"},
    "tr": {"ve", "bir", "bu", "ben", "sen", "değil", "biz", "onlar", "ile", "ne", "için", "var", "yok", "ama", "çok", "da", "mi", "mı", "benim", "şu"},
}


def detect_text_language(text: str, *, min_probability: float = 0.80) -> LanguageDetectionResult:
    cleaned = _clean_subtitle_text(text)
    if not cleaned:
        return LanguageDetectionResult("", 0.0, False, (), "Kein verwertbarer Untertiteltext.")

    script = _script_language(cleaned)
    if script:
        return LanguageDetectionResult(
            script,
            0.99,
            True,
            (LanguageEvidence(script, 0.99, "script"),),
            f"{lang_display(script)} anhand des Schriftsystems erkannt.",
        )

    import unicodedata
    letters = [char for char in cleaned if char.isalpha()]
    latin = sum("LATIN" in unicodedata.name(char, "") for char in letters)
    if letters and latin < len(letters) * 0.8:
        return LanguageDetectionResult("", 0.0, False, (), "Schriftsystem allein ist kein eindeutiger Sprachnachweis.")
    words = [word.casefold() for word in _WORD_RE.findall(cleaned)]
    if len(words) < 12:
        return LanguageDetectionResult("", 0.0, False, (), "Zu wenig Text für eine sichere Spracherkennung.")
    hits = {language: sum(1 for word in words if word in vocabulary) for language, vocabulary in _STOPWORDS.items()}
    winner = max(hits, key=hits.get)
    best = hits[winner]
    total_hits = sum(hits.values())
    if best < 4 or total_hits <= 0:
        return LanguageDetectionResult("", 0.0, False, (), "Zu wenig sprachspezifische Wörter gefunden.")
    confidence = best / total_hits
    accepted = confidence >= float(min_probability)
    reason = f"{lang_display(winner)} mit {confidence * 100:.1f}% Textkonfidenz ({best} Schlüsselwörter)."
    if not accepted:
        reason += f" Mindestkonfidenz: {float(min_probability) * 100:.0f}%."
    return LanguageDetectionResult(
        winner,
        confidence,
        accepted,
        (LanguageEvidence(winner, confidence, "subtitle-text"),),
        reason,
    )


def _clean_subtitle_text(text: str) -> str:
    lines: list[str] = []
    for line in str(text or "").replace("\\N", "\n").splitlines():
        stripped = line.strip()
        if not stripped or stripped.isdigit() or "-->" in stripped:
            continue
        if stripped.startswith("Dialogue:"):
            parts = stripped.split(",", 9)
            stripped = parts[-1] if parts else stripped
        stripped = _ASS_TAG_RE.sub(" ", stripped)
        stripped = re.sub(r"<[^>]+>", " ", stripped)
        lines.append(stripped)
    return " ".join(lines)


def _script_language(text: str) -> str:
    counts = {"ja": 0, "ko": 0, "zh": 0, "ru": 0, "ar": 0, "el": 0}
    for char in text:
        code = ord(char)
        if 0x3040 <= code <= 0x30FF:
            counts["ja"] += 2
        elif 0xAC00 <= code <= 0xD7AF:
            counts["ko"] += 2
        elif 0x4E00 <= code <= 0x9FFF:
            counts["zh"] += 1
        elif 0x0400 <= code <= 0x052F:
            counts["ru"] += 1
        elif 0x0600 <= code <= 0x06FF:
            counts["ar"] += 1
        elif 0x0370 <= code <= 0x03FF:
            counts["el"] += 1
    letters = sum(char.isalpha() for char in text)
    # Shared alphabets (Cyrillic, Arabic, Han) do not identify a language.
    # A short quotation must not override the surrounding subtitle language.
    if counts["ja"] >= 8 and (counts["ja"] / 2 + counts["zh"]) >= letters * 0.8:
        return "ja"
    if counts["ko"] >= 12 and counts["ko"] / 2 >= letters * 0.8:
        return "ko"
    if counts["el"] >= 12 and counts["el"] >= letters * 0.8:
        return "el"
    return ""


__all__ = [
    "FasterWhisperLanguageDetector",
    "LanguageDetectionResult",
    "LanguageEvidence",
    "combine_language_evidence",
    "detect_text_language",
]
