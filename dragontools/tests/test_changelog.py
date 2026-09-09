from __future__ import annotations

import json


def test_parse_legacy_changelog_keeps_overview_and_sections():
    from dragontools.core.changelog import parse_legacy_changelog

    doc = parse_legacy_changelog(
        "Kopfzeile\n\nZweite Zeile\n\n=== 04 Konverter ===\n01) Punkt\n     - Detail\n"
    )

    assert doc.source_format == "txt"
    assert [s.title for s in doc.sections] == ["Überblick", "04 Konverter"]
    assert doc.sections[0].blocks == ("Kopfzeile", "Zweite Zeile")
    assert "Detail" in doc.sections[1].blocks[0]


def test_json_changelog_is_preferred_structured_source(tmp_path):
    from dragontools.core.changelog import load_changelog

    path = tmp_path / "CHANGELOG.json"
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "title": "Dragon Tools",
                "sections": [
                    {"title": "Überblick", "icon": "📋", "blocks": ["A", "B"]},
                    {"title": "04 Konverter", "icon": "🎬", "blocks": ["01) Test\n- Detail"]},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    doc = load_changelog(path)

    assert doc.source_format == "json"
    assert doc.title == "Dragon Tools"
    assert doc.sections[1].icon == "🎬"
    assert doc.sections[1].blocks[0].startswith("01) Test")


def test_paginate_blocks_splits_long_sections_without_losing_order():
    from dragontools.core.changelog import paginate_blocks

    blocks = tuple(f"{i:02d}) Eintrag {i}\n- " + ("Detail " * 22) for i in range(1, 13))
    pages = paginate_blocks(blocks, line_budget=10, wrap_columns=50)

    assert len(pages) > 1
    flattened = [block for page in pages for block in page]
    assert flattened == [block.rstrip() for block in blocks]
    assert all(page for page in pages)
