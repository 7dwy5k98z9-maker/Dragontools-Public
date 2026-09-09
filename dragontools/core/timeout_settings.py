# -*- coding: utf-8 -*-
"""
dragontools/core/timeout_settings.py

Zentrale Timeout-Definitionen für DragonTools.
Alle user-konfigurierbaren Timeouts an einem Ort.

Zeiteinheit intern: Sekunden  |  Anzeige im Dialog: Minuten
Deaktivierte Timeouts liefern None und werden von subprocess als unbegrenzt
behandelt. Die gespeicherten Minutenwerte bleiben dabei erhalten.
"""
from __future__ import annotations
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Timeout-Definitionen
# ---------------------------------------------------------------------------

class TimeoutDef(NamedTuple):
    key: str            # QSettings-Schlüssel (ohne Präfix)
    label: str          # Anzeigename im Dialog
    default_s: int      # Standard in Sekunden
    category: str       # Gruppierung im Dialog
    description: str    # Infotext (ℹ️)


#: Alle konfigurierbaren Timeouts in der Reihenfolge wie sie im Dialog erscheinen.
TIMEOUT_DEFS: list[TimeoutDef] = [
    # ── DV-Pipeline ──────────────────────────────────────────────────────────
    TimeoutDef(
        key="dv_hevc_extract",
        label="HEVC-Extraktion",
        default_s=14_400,
        category="DV-Pipeline",
        description=(
            "Maximale Zeit für die Extraktion des HEVC-Videostreams aus einer "
            "großen Dolby-Vision-Quelldatei (via ffmpeg).\n\n"
            "Greift bei sehr großen Dateien (4K-Blu-ray, mehrere Stunden Laufzeit).\n"
            "Standard: 240 Minuten (4 Stunden)"
        ),
    ),
    TimeoutDef(
        key="dv_dovi_convert",
        label="Dolby-Vision-Profilkonvertierung",
        default_s=14_400,
        category="DV-Pipeline",
        description=(
            "Maximale Zeit für dovi_tool bei der Konvertierung des DV-Profils "
            "(z. B. Profil 7 → Profil 8.1).\n\n"
            "Läuft auf dem gesamten HEVC-Stream und kann bei langen Inhalten "
            "sehr lange dauern.\n"
            "Standard: 240 Minuten (4 Stunden)"
        ),
    ),
    TimeoutDef(
        key="dv_rpu_extract",
        label="RPU-Extraktion",
        default_s=600,
        category="DV-Pipeline",
        description=(
            "Maximale Zeit für die Extraktion der Dolby-Vision-Metadaten (RPU) "
            "aus dem HEVC-Stream via dovi_tool.\n\n"
            "Deutlich schneller als die Profilkonvertierung, da nur Metadaten "
            "gelesen werden.\n"
            "Standard: 10 Minuten"
        ),
    ),
    TimeoutDef(
        key="dv_dovi_editor",
        label="Dolby-Vision-Editor (Level 5)",
        default_s=120,
        category="DV-Pipeline",
        description=(
            "Maximale Zeit für dovi_tool im Editor-Modus, z. B. beim Anpassen "
            "der Level-5-Metadaten (Bildgrenzen-Trimming für bestimmte DV-Profile).\n\n"
            "Sehr schneller Schritt, da nur Metadaten modifiziert werden.\n"
            "Standard: 2 Minuten"
        ),
    ),
    TimeoutDef(
        key="dv_rpu_inject",
        label="RPU-Injektion",
        default_s=1_800,
        category="DV-Pipeline",
        description=(
            "Maximale Zeit für das Einbetten der RPU-Metadaten in den "
            "encodierten HEVC-Stream via dovi_tool inject-rpu.\n\n"
            "Dauert proportional zur Dateilänge.\n"
            "Standard: 30 Minuten"
        ),
    ),
    TimeoutDef(
        key="dv_audio",
        label="Audio-Extraktion (DV)",
        default_s=3_600,
        category="DV-Pipeline",
        description=(
            "Maximale Zeit für die Extraktion aller Audiospuren aus der "
            "Quelldatei während der DV-Pipeline (via ffmpeg).\n\n"
            "Abhängig von Anzahl und Größe der Audiospuren.\n"
            "Standard: 60 Minuten"
        ),
    ),
    TimeoutDef(
        key="dv_mp4box",
        label="MP4Box-Muxing",
        default_s=3_600,
        category="DV-Pipeline",
        description=(
            "Maximale Zeit für das Zusammenfügen aller Streams "
            "(HEVC+RPU + Audio) zur finalen MP4-Ausgabedatei via MP4Box.\n\n"
            "Der letzte Schritt der DV-Pipeline – bei sehr großen Dateien "
            "kann er länger dauern.\n"
            "Standard: 60 Minuten"
        ),
    ),
    TimeoutDef(
        key="dv_mkvmerge",
        label="mkvmerge-Muxing (DV)",
        default_s=3_600,
        category="DV-Pipeline",
        description=(
            "Maximale Zeit für den finalen Dolby-Vision-MKV-Mux über mkvmerge.\n\n"
            "Dieser Timeout wird nur verwendet, wenn für Dolby Vision bzw. "
            "DV+HDR10+ als Zielcontainer MKV gewählt ist. Der injizierte "
            "HEVC-Bitstream wird dabei ohne Re-Encoding übernommen.\n"
            "Standard: 60 Minuten"
        ),
    ),
    TimeoutDef(
        key="dv_encode",
        label="ffmpeg-Encode (DV-Pipeline)",
        default_s=300,
        category="DV-Pipeline",
        description=(
            "Inaktivitäts-Timeout für den produktiven ffmpeg-Videoencoding-"
            "Schritt innerhalb der Dolby-Vision-Pipeline.\n\n"
            "Der Encode darf beliebig lange laufen, solange ffmpeg regelmäßig "
            "Fortschritt oder stderr-Ausgaben liefert. Abgebrochen wird nur, "
            "wenn ffmpeg für diese Zeit gar keine Rückmeldung mehr sendet.\n"
            "Standard: 5 Minuten"
        ),
    ),

    # ── Allgemeiner Encoder ───────────────────────────────────────────────────
    TimeoutDef(
        key="encoder_general",
        label="Allgemeiner Encoder-Timeout",
        default_s=300,
        category="Encoder",
        description=(
            "Inaktivitäts-Timeout für Standard-Konvertierungen "
            "(H.264 / H.265 / AV1 via ffmpeg).\n\n"
            "Der Encode darf beliebig lange laufen, solange ffmpeg regelmäßig "
            "Fortschritt oder stderr-Ausgaben liefert. Abgebrochen wird nur, "
            "wenn ffmpeg für diese Zeit gar keine Rückmeldung mehr sendet.\n"
            "Standard: 5 Minuten"
        ),
    ),

    # ── Spezialtools ─────────────────────────────────────────────────────────
    TimeoutDef(
        key="hdrplus_tool",
        label="HDR10+-Toolschritte",
        default_s=3_600,
        category="HDR10+",
        description=(
            "Maximale Zeit für HDR10+-Spezialschritte wie Bitstream-Extraktion, "
            "hdr10plus_tool-Extraktion, Injection und finales Muxing.\n\n"
            "Der eigentliche Video-Encode nutzt weiterhin den Encoder-Inaktivitäts-"
            "Timeout; dieser Wert schützt nur die zusätzlichen Container- und "
            "Metadaten-Werkzeuge.\n"
            "Standard: 60 Minuten"
        ),
    ),
    TimeoutDef(
        key="duration_repair",
        label="Container-Dauerreparatur",
        default_s=3_600,
        category="Reparatur",
        description=(
            "Maximale Zeit für automatische Laufzeit-Reparaturen nach einem "
            "erfolgreichen Encode. MKV wird über MKVToolNix repariert, MP4 "
            "über MP4Box; eine sichere Timestamp-Rekonstruktion folgt nur bei "
            "eindeutig erkanntem Timingfehler.\n\n"
            "Diese Reparatur wird nur gestartet, wenn die Ausgabedauer unplausibel "
            "ist. Es wird dabei nicht erneut encodiert.\n"
            "Standard: 60 Minuten"
        ),
    ),
    TimeoutDef(
        key="quality_test_process",
        label="Qualitätstester-Toolprozess",
        default_s=3_600,
        category="Analyse",
        description=(
            "Maximale Laufzeit eines einzelnen externen Toolschritts im "
            "Qualitätstester (Encode, ffprobe oder Metrikberechnung).\n\n"
            "Verhindert, dass ein hängender ffmpeg-/Analyseprozess den "
            "kompletten Qualitätstest unbegrenzt blockiert.\n"
            "Standard: 60 Minuten"
        ),
    ),
    TimeoutDef(
        key="worker_media_process",
        label="Remux-/Mux-/Disc-Tool (Inaktivität)",
        default_s=300,
        category="Spezialtools",
        description=(
            "Inaktivitäts-Timeout für lange externe Medienwerkzeuge außerhalb "
            "des Hauptencoders, z. B. Audio-Mux, MP4-Remux, mkvmerge, MakeMKV "
            "und FFmpeg-ISO-Fallback.\n\n"
            "Der Prozess darf beliebig lange laufen, solange er regelmäßig "
            "Fortschritt bzw. Konsolenausgabe liefert. Abgebrochen wird nur, "
            "wenn für diese Zeit keinerlei Aktivität mehr erkannt wird.\n"
            "Standard: 5 Minuten"
        ),
    ),
    TimeoutDef(
        key="avmatch_process",
        label="Audio-/Video-Matcher Toolprozess",
        default_s=14_400,
        category="Analyse",
        description=(
            "Maximale Gesamtlaufzeit einzelner FFmpeg-Schritte beim Erzeugen "
            "einer synchronisierten Audiospur bzw. beim finalen Mux des "
            "Audio-/Video-Matchers.\n\n"
            "Diese Prozesse laufen teilweise mit reduzierter Konsolenausgabe; "
            "deshalb wird hier bewusst ein Gesamtlaufzeit-Timeout statt eines "
            "Inaktivitäts-Timeouts verwendet.\n"
            "Standard: 240 Minuten (4 Stunden)"
        ),
    ),

    # ── Untertitel ────────────────────────────────────────────────────────────
    TimeoutDef(
        key="subtitle_extract",
        label="Untertitel extrahieren",
        default_s=300,
        category="Untertitel",
        description=(
            "Maximale Zeit für die Extraktion von Untertitelspuren aus "
            "Video-Dateien (via ffmpeg/mkvextract).\n\n"
            "Untertitel-Extraktion ist in der Regel schnell; dieser Wert "
            "greift nur bei sehr großen Dateien oder langsamen Datenträgern.\n"
            "Standard: 5 Minuten"
        ),
    ),
    TimeoutDef(
        key="subtitle_inject",
        label="Untertitel einbetten",
        default_s=600,
        category="Untertitel",
        description=(
            "Maximale Zeit für das Einbetten von Untertitelspuren in "
            "Video-Dateien (via ffmpeg/mkvmerge).\n\n"
            "Kann länger dauern als die Extraktion, da die gesamte Datei "
            "neu verpackt wird.\n"
            "Standard: 10 Minuten"
        ),
    ),
    TimeoutDef(
        key="subtitle_tag",
        label="Untertitel-Flags setzen",
        default_s=60,
        category="Untertitel",
        description=(
            "Maximale Zeit für das Setzen von Forced- und Language-Flags "
            "auf MKV-Dateien via mkvpropedit.\n\n"
            "Sehr schneller Schritt – mkvpropedit schreibt nur die Header-Metadaten "
            "der Datei, ohne den Stream neu zu codieren.\n"
            "Standard: 1 Minute"
        ),
    ),

    # ── Medienanalyse ─────────────────────────────────────────────────────────
    TimeoutDef(
        key="media_analysis",
        label="Medienanalyse (ffprobe/mediainfo)",
        default_s=60,
        category="Analyse",
        description=(
            "Maximale Zeit für die Analyse einer Mediendatei mit ffprobe oder "
            "mediainfo beim Start der Verarbeitung.\n\n"
            "Bei sehr großen oder beschädigten Dateien kann die Analyse "
            "ungewöhnlich lange dauern.\n"
            "Standard: 1 Minute"
        ),
    ),
    TimeoutDef(
        key="format_detection",
        label="Format- und Codec-Erkennung",
        default_s=90,
        category="Analyse",
        description=(
            "Maximale Zeit für die automatische Erkennung von Dateiformat und "
            "Codec vor dem Start der Konvertierung.\n\n"
            "Wird für die Pipeline-Entscheidung (DV / HDR10+ / Standard) verwendet. "
            "Normalerweise sehr schnell.\n"
            "Standard: 1,5 Minuten"
        ),
    ),
]

# Schneller Lookup nach Key
_BY_KEY: dict[str, TimeoutDef] = {td.key: td for td in TIMEOUT_DEFS}

# QSettings-Präfix für alle Timeout-Keys
_SETTINGS_PREFIX = "timeouts/"
_ENABLED_PREFIX = "timeouts_enabled/"
_V91_MIGRATION_KEY = "timeouts/v91_inactivity_migrated"
_INACTIVITY_TIMEOUT_KEYS = {"encoder_general", "dv_encode"}


# ---------------------------------------------------------------------------
# Lese- / Schreib-API
# ---------------------------------------------------------------------------

def _read_qsettings_or_none():
    """Erzeugt QSettings, ohne reine Core-/Headless-Imports an PyQt6 zu koppeln."""
    try:
        from PyQt6.QtCore import QSettings
    except ModuleNotFoundError:
        return None
    from .settings import APP_ORG, APP_NAME
    return QSettings(APP_ORG, APP_NAME)


def _read_timeout_value(qs, td: TimeoutDef) -> int:
    val = qs.value(_SETTINGS_PREFIX + td.key, defaultValue=None)
    if val is None:
        return td.default_s
    try:
        return max(1, int(val))
    except (TypeError, ValueError):
        return td.default_s


def get_timeout_value(key: str) -> int:
    """
    Gibt den konfigurierten Timeout-Wert in **Sekunden** zurück.
    Liest aus QSettings; fällt auf den Standardwert zurück wenn nicht gesetzt.

    Kann aus Worker-Threads aufgerufen werden (QSettings ist thread-safe
    wenn jeder Thread eine eigene Instanz erzeugt).
    """
    td = _BY_KEY.get(key)
    if td is None:
        raise KeyError(f"Unbekannter Timeout-Key: '{key}'")

    qs = _read_qsettings_or_none()
    if qs is None:
        return td.default_s
    return _read_timeout_value(qs, td)


def is_timeout_enabled(key: str) -> bool:
    """Gibt zurück, ob ein Timeout aktiv angewendet werden soll."""
    if key not in _BY_KEY:
        raise KeyError(f"Unbekannter Timeout-Key: '{key}'")

    qs = _read_qsettings_or_none()
    if qs is None:
        return True
    return bool(qs.value(_ENABLED_PREFIX + key, True, type=bool))


def get_timeout(key: str) -> int | None:
    """
    Gibt den aktiven Timeout in **Sekunden** zurück.

    Ist der Timeout deaktiviert, wird None geliefert. subprocess.run/wait
    behandeln None als unbegrenzt.
    """
    if not is_timeout_enabled(key):
        return None
    return get_timeout_value(key)


def get_all_timeouts() -> dict[str, int]:
    """Gibt alle Timeout-Werte (Sekunden) als Dict zurück."""
    return {td.key: get_timeout_value(td.key) for td in TIMEOUT_DEFS}


def get_all_timeout_enabled() -> dict[str, bool]:
    """Gibt alle Timeout-Aktivstatuswerte als Dict zurück."""
    return {td.key: is_timeout_enabled(td.key) for td in TIMEOUT_DEFS}


def save_timeout(key: str, seconds: int) -> None:
    """Speichert einen einzelnen Timeout-Wert (Sekunden) in QSettings."""
    from PyQt6.QtCore import QSettings
    from .settings import APP_ORG, APP_NAME

    if key not in _BY_KEY:
        raise KeyError(f"Unbekannter Timeout-Key: '{key}'")
    qs = QSettings(APP_ORG, APP_NAME)
    qs.setValue(_SETTINGS_PREFIX + key, seconds)


def save_timeout_enabled(key: str, enabled: bool) -> None:
    """Speichert den Aktivstatus eines Timeouts in QSettings."""
    from PyQt6.QtCore import QSettings
    from .settings import APP_ORG, APP_NAME

    if key not in _BY_KEY:
        raise KeyError(f"Unbekannter Timeout-Key: '{key}'")
    qs = QSettings(APP_ORG, APP_NAME)
    qs.setValue(_ENABLED_PREFIX + key, bool(enabled))


def save_all_timeouts(
    values: dict[str, int],
    enabled: dict[str, bool] | None = None,
) -> None:
    """Speichert mehrere Timeout-Werte auf einmal."""
    from PyQt6.QtCore import QSettings
    from .settings import APP_ORG, APP_NAME

    qs = QSettings(APP_ORG, APP_NAME)
    for key, seconds in values.items():
        if key in _BY_KEY:
            qs.setValue(_SETTINGS_PREFIX + key, seconds)
    for key, is_enabled in (enabled or {}).items():
        if key in _BY_KEY:
            qs.setValue(_ENABLED_PREFIX + key, bool(is_enabled))


def reset_all_timeouts() -> None:
    """Setzt alle Timeouts auf ihre Standardwerte zurück."""
    from PyQt6.QtCore import QSettings
    from .settings import APP_ORG, APP_NAME

    qs = QSettings(APP_ORG, APP_NAME)
    for td in TIMEOUT_DEFS:
        qs.remove(_SETTINGS_PREFIX + td.key)
        qs.remove(_ENABLED_PREFIX + td.key)


def get_default(key: str) -> int:
    """Gibt den Standardwert in Sekunden zurück."""
    td = _BY_KEY.get(key)
    if td is None:
        raise KeyError(f"Unbekannter Timeout-Key: '{key}'")
    return td.default_s


def migrate_v91_timeout_defaults() -> None:
    """Migriert alte Gesamt-Timeout-Werte auf die Inaktivitätssemantik.

    V9.0 speicherte für Encoder-Timeouts lange Maximal-Laufzeiten. In neueren
    Versionen sind dieselben Einstellungen Inaktivitätslimits. Deshalb werden einmalig
    alte große Werte auf den neuen 5-Minuten-Standard gesetzt.
    """
    from PyQt6.QtCore import QSettings
    from .settings import APP_ORG, APP_NAME

    qs = QSettings(APP_ORG, APP_NAME)
    if qs.value(_V91_MIGRATION_KEY, False, type=bool):
        return

    for key in _INACTIVITY_TIMEOUT_KEYS:
        td = _BY_KEY[key]
        raw = qs.value(_SETTINGS_PREFIX + key, defaultValue=None)
        try:
            current = int(raw) if raw is not None else td.default_s
        except (TypeError, ValueError):
            current = td.default_s
        if raw is None or current >= 3_600:
            qs.setValue(_SETTINGS_PREFIX + key, td.default_s)
        if qs.value(_ENABLED_PREFIX + key, defaultValue=None) is None:
            qs.setValue(_ENABLED_PREFIX + key, True)

    qs.setValue(_V91_MIGRATION_KEY, True)
