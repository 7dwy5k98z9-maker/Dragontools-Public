# -*- coding: utf-8 -*-
"""Windows-sichere Move-Namen und relative Unterpfade."""
from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath
from ..core.paths import user_path_stem

_WIN_FORBIDDEN_SEGMENT_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WIN_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}


def sanitize_win_segment(value: str, fallback: str = "Unbekannt") -> str:
    """Bereinigt einen Pfadsegment-Namen für Windows-Kompatibilität.

    Ersetzt verbotene Zeichen durch '_', entfernt fuehrende/trailing Punkte
    und Leerzeichen, und hängt '_' an reservierte Namen an.
    """
    text = str(value or "").strip()
    text = _WIN_FORBIDDEN_SEGMENT_CHARS.sub("_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        return fallback
    if text.lower() in _WIN_RESERVED_NAMES:
        return f"{text}_"
    return text


def move_safe_stem(path: str) -> str:
    """Bereinigt Dateinamen für die Move-Zielfindung um Codec-Suffixe."""
    stem = user_path_stem(path)
    return re.sub(r"[_\s]?(H264|H265|AV1|HEVC|x265|x264)$", "", stem, flags=re.IGNORECASE).strip()


def default_film_series_name(stem: str) -> str:
    """Leitet aus einem Film-Stem einen Vorschlagsnamen für Filmreihen ab."""
    return re.sub(
        r"[\s_]*(Teil|Part|Vol|Volume|\d+)[\s_]*\d*$",
        "",
        stem,
        flags=re.IGNORECASE,
    ).strip() or stem


def film_bucket_from_title(title: str) -> str:
    """Erster Buchstabe des Titels als Sortier-Bucket für Einzelfilme.

    Gibt '#' für Titel zurück, die nicht mit A-Z beginnen.
    """
    t = (title or "").strip()
    if not t:
        return "#"
    first = t[0].upper()
    if "A" <= first <= "Z":
        return first
    return "#"


def normalize_relative_move_subpath(value: str | None) -> str:
    """Validiert und normalisiert einen optionalen relativen Unterpfad.

    Erlaubt leere Eingaben. Verhindert absolute Pfade, Laufwerksangaben,
    '..'-Segmente und Windows-ungültige Zeichen.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith(("/", "\\")):
        raise ValueError("Unterpfad muss relativ sein.")

    normalized = text.replace("\\", "/").strip("/")
    if not normalized:
        return ""

    pure = PureWindowsPath(normalized)
    if pure.is_absolute() or pure.drive or pure.root:
        raise ValueError("Unterpfad darf keine Laufwerksangabe oder absoluten Pfad enthalten.")

    parts: list[str] = []
    for raw_part in pure.parts:
        part = str(raw_part).strip()
        if not part:
            continue
        if part in {".", ".."}:
            raise ValueError("Unterpfad darf keine '.' oder '..'-Segmente enthalten.")
        if _WIN_FORBIDDEN_SEGMENT_CHARS.search(part):
            raise ValueError(f"Unterpfad enthält ungültige Zeichen: {part}")
        cleaned = part.strip(" .")
        if not cleaned:
            raise ValueError("Unterpfad enthält leere oder ungültige Segmente.")
        if cleaned.lower() in _WIN_RESERVED_NAMES:
            raise ValueError(f"Unterpfad enthält reservierten Windows-Namen: {cleaned}")
        parts.append(cleaned)

    return "/".join(parts)


def apply_relative_move_subpath(
    base_dir: str | Path,
    relative_subpath: str | None = None,
) -> Path:
    """Haengt einen validierten relativen Unterpfad an einen Basisordner an."""
    root = Path(base_dir)
    subpath = normalize_relative_move_subpath(relative_subpath)
    if not subpath:
        return root
    return root.joinpath(*subpath.split("/"))


def _normalize_for_dir_match(text: str) -> str:
    # Strikter Serien-Match-Key: Wörter/Ziffern müssen weiter exakt stimmen.
    # Toleriert werden nur typografische bzw. dekorative Unterschiede.
    text = str(text or "")
    text = text.replace("½", "1/2")

    # '  `  ´  ’  ʼ  ʻ  ′  ʾ  ʿ -> ein einheitliches Apostroph.
    text = re.sub(r"['`\u00b4\u02bc\u02bb\u2018\u2019\u2032\u02be\u02bf]", "'", text)

    # Unicode-Bindestriche vereinheitlichen.
    text = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u207b\u2212]", "-", text)

    # Rein dekorative Randtrenner ignorieren: "Watson -" == "Watson".
    text = re.sub(r"^\s*[-/\\]+\s*", "", text)
    text = re.sub(r"\s*[-/\\]+\s*$", "", text)

    # Bindestriche, / und \\ sind für den Ordnervergleich nur Trenner und tragen keinen Inhalt.
    # Dadurch matcht z. B. "Special Ops Lioness" zuverlässig auf
    # "Special Ops - Lioness (2023)", ohne ein unsicheres Substring-Matching einzuführen.
    text = re.sub(r"[-/\\]+", "", text)

    # Weitere bereits tolerierte Satzzeichen entfernen.
    text = re.sub(r'[<>:"|?*\x00-\x1f]', "", text)
    text = re.sub(r"[_.;,\[\](){}!]+", "", text)
    text = re.sub(r"\s", "", text)
    return text.lower()

def _strip_dir_year_suffix(name: str) -> str:
    """Entfernt das Jahres-Suffix '(YYYY)' am Ende eines Ordnernamens.

    Beispiele:
      'MAO (2026)'                          → 'MAO'
      'My Gift Lvl 9999 [...] (2025)'       → 'My Gift Lvl 9999 [...]'
      'xxxxxxxdungen mao (2015)'            → 'xxxxxxxdungen mao'
      'MAO'                                 → 'MAO'
    """
    return re.sub(r"\s*\(\d{4}\)\s*$", "", name).strip()

def _dir_year_suffix(name: str) -> int | None:
    match = re.search(r"\((19\d{2}|20\d{2})\)\s*$", str(name or "").strip())
    return int(match.group(1)) if match else None
