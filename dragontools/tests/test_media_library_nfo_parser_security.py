from __future__ import annotations

from pathlib import Path

import pytest

from dragontools.core import media_library_nfo_parser as parser
from dragontools.core.media_library_nfo_inventory import _inspect_nfo_candidate
from dragontools.core.media_library_nfo_parser import NfoParseError, parse_nfo


def test_parse_nfo_accepts_normal_metadata(tmp_path):
    nfo = tmp_path / "movie.nfo"
    nfo.write_text(
        "<movie><title>Testfilm</title><year>2026</year><uniqueid type='tmdb'>123</uniqueid></movie>",
        encoding="utf-8",
    )

    result = parse_nfo(nfo)

    assert result["nfo_type"] == "movie"
    assert result["title"] == "Testfilm"
    assert result["year"] == 2026
    assert result["provider_ids"]["tmdb"] == "123"


def test_parse_nfo_rejects_doctype(tmp_path):
    nfo = tmp_path / "movie.nfo"
    nfo.write_text("<!DOCTYPE movie><movie><title>Test</title></movie>", encoding="utf-8")

    with pytest.raises(NfoParseError, match="sicher geparst"):
        parse_nfo(nfo)


def test_parse_nfo_rejects_entity_expansion(tmp_path):
    nfo = tmp_path / "movie.nfo"
    nfo.write_text(
        '<!DOCTYPE movie [<!ENTITY a "1234567890"><!ENTITY b "&a;&a;&a;&a;">]>'
        "<movie><title>&b;</title></movie>",
        encoding="utf-8",
    )

    with pytest.raises(NfoParseError, match="sicher geparst"):
        parse_nfo(nfo)


def test_parse_nfo_rejects_oversized_file_before_xml_parse(tmp_path, monkeypatch):
    monkeypatch.setattr(parser, "MAX_NFO_BYTES", 64)
    nfo = tmp_path / "movie.nfo"
    nfo.write_bytes(b"<movie><title>" + b"x" * 100 + b"</title></movie>")

    with pytest.raises(NfoParseError, match="zu groß"):
        parse_nfo(nfo)


def test_inventory_reports_unsafe_xml_as_concrete_invalid_finding(tmp_path):
    media = tmp_path / "Film.mkv"
    media.write_bytes(b"video")
    nfo = tmp_path / "movie.nfo"
    nfo.write_text(
        '<!DOCTYPE movie [<!ENTITY x "boom">]><movie><title>&x;</title></movie>',
        encoding="utf-8",
    )
    row = {"path": str(media), "item_type": "movie", "nfo_path": str(nfo)}

    result = _inspect_nfo_candidate(row)

    assert result["status"] == "invalid"
    assert "NFO ungültig/unsicher" in result["warning"]
    assert "sicher geparst" in result["error"]
