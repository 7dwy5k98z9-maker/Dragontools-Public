# -*- coding: utf-8 -*-
"""
ConverterConfig – Datenhaltungsobjekt für ConverterThread.

Problem vorher:
    ConverterThread.__init__ hatte 15+ Parameter und konstruierte intern ~15
    Service-Objekte. Das machte den Konstruktor untestbar und machte es
    schwer zu erkennen, was ein ConverterThread überhaupt braucht.

Loesung:
    Alle fachlichen Konfigurationsparameter leben jetzt in einem einzigen, klar
    typisierten Dataclass-Objekt. ConverterThread akzeptiert dieses Objekt als
    einzigen fachlichen Konfigurationsparameter; ``files``, ``parent`` und ein
    optionaler geteilter Logger bleiben reine Laufzeit-/Infrastrukturparameter.

Vorteile:
    - Tests können ConverterConfig ohne QThread/Qt instanziieren und prüfen.
    - Die Callsite in conversion_controller.py ist kompakter und expliziter.
    - Neue Parameter ergaenzen das Dataclass, nicht die Konstruktorsignatur.
    - Fehlende Defaults werden sofort sichtbar.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConverterConfig:
    """Alle Konfigurationsparameter für einen Konvertierungslauf.

    Instanzen sind bewusst mutable (kein frozen=True), damit die GUI
    optionale Felder nachtraeglich setzen kann bevor der Thread gestartet
    wird.
    """

    # ------------------------------------------------------------------ #
    # Pflichtfelder                                                        #
    # ------------------------------------------------------------------ #
    codec: str
    """Ziel-Videocodec: "h265" | "h264" | "av1"."""

    crf: int
    """Constant Rate Factor – codec-spezifische Qualitätszahl."""

    preset: str
    """Encoder-Geschwindigkeitsstufe (z.B. "medium", "slow", "6")."""

    scale_mode: str
    """Skalierungsstufe: "original" | "4k" | "1080p" | "720p" | "480p"."""

    overwrite_original: bool
    """True = Quelldatei nach erfolgreicher Konvertierung ersetzen."""

    # ------------------------------------------------------------------ #
    # Optionale Felder mit sinnvollen Defaults                            #
    # ------------------------------------------------------------------ #
    strip_only: bool = False
    """Kein Re-Encode – nur Streams entfernen (z.B. Untertitel stripping)."""

    encoder_options: dict = field(default_factory=dict)
    """Erweiterte Encoder-Optionen (GPU, autocrop, IMAX, etc.)."""

    file_overrides: dict = field(default_factory=dict)
    """Per-Datei-Overrides für Audio, Untertitel, DV-Flags etc."""

    subtitle_rules: dict = field(default_factory=dict)
    """Regelwerk für Untertitel-Selektion und Burn-In."""

    tv_path: str | None = None
    """Zielpfad für TV-Serien (für automatisches Verschieben)."""

    anime_path: str | None = None
    """Zielpfad für Anime (für automatisches Verschieben)."""

    filme_path: str | None = None
    """Zielpfad für Filme (für automatisches Verschieben)."""

    log_file_path: str | None = None
    """Expliziter Log-Dateipfad; None = automatisch aus Datum ableiten."""
