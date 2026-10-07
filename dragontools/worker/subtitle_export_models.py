"""Public sidecar names and structured export outcomes, without tool I/O."""

from dataclasses import dataclass
from pathlib import Path
import re


def safe_lang_tag(language: str | None) -> str:
    """Normalisiert einen Sprach-Tag für Dateinamen.

    Wandelt den Tag in Kleinbuchstaben um und entfernt alle Zeichen
    außer [a-z0-9].  Ergibt einen leeren String wird "und" verwendet.

    Beispiele:
        "deu"       → "deu"
        "de"        → "de"
        "zh-Hant"   → "zhhant"
        None        → "und"
        ""          → "und"
    """
    tag = (language or "und").lower()
    cleaned = re.sub(r"[^a-z0-9]", "", tag)
    return cleaned or "und"


def sidecar_filename(
    base: Path,
    lang: str,
    forced: bool,
    ext: str,
    number: int | None = None,
) -> str:
    """Erzeugt den vollständigen Sidecar-Pfad nach Jellyfin/VLC-Schema.

    Parameters
    ----------
    base : Path
        Output-Stem (Videodatei ohne Suffix), z.B. Path("/films/Film")
    lang : str
        Bereits normalisierter Sprach-Tag (ISO-639-1, lowercase, [a-z0-9])
    forced : bool
        True wenn Sub-Stream als Forced markiert ist
    ext : str
        Dateierweiterung inkl. Punkt, z.B. ".srt"
    number : int | None
        Laufende Nummer für doppelte (lang, forced)-Kombinationen.
        None   → keine Nummerierung (einzige Spur dieser Art)
        1, 2 … → Nummer wird angehängt

    Returns
    -------
    str
        Vollständiger Dateipfad, z.B.:
            "/films/Film.de.srt"
            "/films/Film.de.forced.srt"
            "/films/Film.de.1.srt"
            "/films/Film.de.forced.2.srt"
    """
    forced_part = ".forced" if forced else ""
    num_part = f".{number}" if number is not None else ""
    base_text = str(base)
    if not base.drive:
        base_text = base.as_posix()
    return base_text + f".{lang}{forced_part}{num_part}{ext}"


@dataclass(frozen=True)
class SubtitleExportFailure:
    stream_index: int
    language: str
    codec: str
    reason: str
    output_path: str = ""


@dataclass(frozen=True)
class SubtitleExportResult:
    """Vollstaendiger fachlicher Status eines Sidecar-Exports."""

    planned_stream_indices: tuple[int, ...] = ()
    exported_paths: tuple[str, ...] = ()
    failures: tuple[SubtitleExportFailure, ...] = ()
    aborted: bool = False
    disabled: bool = False

    @property
    def expected_count(self) -> int:
        return len(self.planned_stream_indices)

    @property
    def exported_count(self) -> int:
        return len(self.exported_paths)

    @property
    def complete(self) -> bool:
        return (
            not self.aborted
            and not self.failures
            and self.exported_count >= self.expected_count
        )

    @property
    def ok(self) -> bool:
        return self.complete

    def failure_summary(self) -> str:
        if self.aborted:
            return "Sidecar-Export wurde abgebrochen."
        if self.failures:
            details = "; ".join(
                f"Sub #{item.stream_index}: {item.reason}" for item in self.failures
            )
            return (
                f"Sidecar-Export unvollstaendig "
                f"({self.exported_count}/{self.expected_count}): {details}"
            )
        if self.exported_count != self.expected_count:
            return (
                f"Sidecar-Export unvollstaendig "
                f"({self.exported_count}/{self.expected_count})."
            )
        return ""
