# -*- coding: utf-8 -*-
"""Strukturierte Änderungshistorie und deterministische Seiteneinteilung.

V9 nutzt bevorzugt ``CHANGELOG.json``. Legacy-TXT-Dateien bleiben lesbar,
damit V8/V7 und ältere V9-Pakete weiterhin geöffnet werden können.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable


CHANGELOG_FORMAT_VERSION = 1
DEFAULT_PAGE_LINE_BUDGET = 40
DEFAULT_WRAP_COLUMNS = 104


@dataclass(frozen=True)
class ChangelogSection:
    title: str
    blocks: tuple[str, ...]
    icon: str = "📌"


@dataclass(frozen=True)
class ChangelogDocument:
    title: str
    sections: tuple[ChangelogSection, ...]
    source_format: str


def _blocks_from_lines(lines: Iterable[str]) -> tuple[str, ...]:
    blocks: list[str] = []
    current: list[str] = []
    for raw in lines:
        line = str(raw).rstrip()
        if not line.strip():
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return tuple(block for block in blocks if block)


def parse_legacy_changelog(text: str, *, title: str = "Änderungshistorie") -> ChangelogDocument:
    """Liest das bisherige ``=== Abschnitt ===``-TXT-Format."""
    overview_lines: list[str] = []
    sections: list[ChangelogSection] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines
        if current_title is None:
            return
        sections.append(
            ChangelogSection(
                title=current_title,
                blocks=_blocks_from_lines(current_lines),
            )
        )
        current_lines = []

    for raw in str(text or "").splitlines():
        match = re.match(r"^===\s*(.+?)\s*===\s*$", raw)
        if match:
            if current_title is None:
                overview_lines = list(current_lines)
                current_lines = []
            else:
                flush()
            current_title = match.group(1).strip()
            continue
        current_lines.append(raw)

    if current_title is None:
        overview_lines = list(current_lines)
    else:
        flush()

    overview = ChangelogSection(
        title="Überblick",
        icon="📋",
        blocks=_blocks_from_lines(overview_lines),
    )
    return ChangelogDocument(
        title=title,
        sections=(overview, *sections),
        source_format="txt",
    )


def _section_from_json(raw: Any) -> ChangelogSection | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    if not title:
        return None
    icon = str(raw.get("icon") or "📌").strip() or "📌"
    blocks_raw = raw.get("blocks")
    if isinstance(blocks_raw, list):
        blocks = tuple(str(item).strip() for item in blocks_raw if str(item).strip())
    elif isinstance(blocks_raw, str):
        blocks = _blocks_from_lines(blocks_raw.splitlines())
    else:
        blocks = ()
    return ChangelogSection(title=title, icon=icon, blocks=blocks)


def load_changelog(path: str | Path, *, title: str = "Änderungshistorie") -> ChangelogDocument:
    source = Path(path)
    if source.suffix.lower() != ".json":
        return parse_legacy_changelog(source.read_text(encoding="utf-8", errors="replace"), title=title)

    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("CHANGELOG.json muss ein JSON-Objekt enthalten")
    version = int(raw.get("format_version", 0) or 0)
    if version != CHANGELOG_FORMAT_VERSION:
        raise ValueError(
            f"Nicht unterstützte CHANGELOG-Formatversion {version}; "
            f"erwartet {CHANGELOG_FORMAT_VERSION}"
        )
    sections = tuple(
        section
        for section in (_section_from_json(item) for item in raw.get("sections", []))
        if section is not None
    )
    if not sections:
        raise ValueError("CHANGELOG.json enthält keine Abschnitte")
    doc_title = str(raw.get("title") or title).strip() or title
    return ChangelogDocument(title=doc_title, sections=sections, source_format="json")


def estimate_block_lines(block: str, *, wrap_columns: int = DEFAULT_WRAP_COLUMNS) -> int:
    """Schätzt die visuelle Zeilenhöhe eines Textblocks konservativ.

    Die GUI verwendet eine feste Inhaltsfläche. Durch die Schätzung werden
    Einträge möglichst als Ganzes auf eine Seite gesetzt und der Inhaltsbereich
    benötigt im Normalfall keine Scrollbar.
    """
    wrap = max(40, int(wrap_columns))
    total = 0
    for raw in str(block or "").splitlines() or [""]:
        text = raw.strip()
        if not text:
            total += 1
            continue
        # Überschriften/Nummernpunkte erhalten etwas zusätzlichen Abstand.
        overhead = 1 if re.match(r"^(?:V?\d+(?:[.)-]|\s)|[A-ZÄÖÜ][^:]{0,60}:$)", text) else 0
        total += max(1, math.ceil(len(text) / wrap)) + overhead
    return max(1, total)


def _split_oversized_block(block: str, *, line_budget: int, wrap_columns: int) -> list[str]:
    lines = str(block or "").splitlines()
    if not lines:
        return [""]
    parts: list[str] = []
    current: list[str] = []
    used = 0
    for line in lines:
        line_cost = estimate_block_lines(line, wrap_columns=wrap_columns)
        if current and used + line_cost > line_budget:
            parts.append("\n".join(current).strip())
            current = []
            used = 0
        current.append(line)
        used += line_cost
    if current:
        parts.append("\n".join(current).strip())
    return [part for part in parts if part]


def paginate_blocks(
    blocks: Iterable[str],
    *,
    line_budget: int = DEFAULT_PAGE_LINE_BUDGET,
    wrap_columns: int = DEFAULT_WRAP_COLUMNS,
) -> tuple[tuple[str, ...], ...]:
    """Teilt einen Abschnitt in feste Seiten, bevorzugt an Blockgrenzen."""
    budget = max(8, int(line_budget))
    pages: list[tuple[str, ...]] = []
    current: list[str] = []
    used = 0

    for raw in blocks:
        block = str(raw or "").strip()
        if not block:
            continue
        candidates = [block]
        cost = estimate_block_lines(block, wrap_columns=wrap_columns)
        if cost > budget:
            candidates = _split_oversized_block(
                block,
                line_budget=budget,
                wrap_columns=wrap_columns,
            )

        for candidate in candidates:
            candidate_cost = estimate_block_lines(candidate, wrap_columns=wrap_columns)
            separator_cost = 1 if current else 0
            if current and used + separator_cost + candidate_cost > budget:
                pages.append(tuple(current))
                current = []
                used = 0
                separator_cost = 0
            current.append(candidate)
            used += separator_cost + candidate_cost

    if current:
        pages.append(tuple(current))
    return tuple(pages or [tuple()])
