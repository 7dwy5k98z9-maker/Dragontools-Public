# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _lines(relative: str) -> list[str]:
    return (ROOT / relative).read_text(encoding="utf-8").splitlines()


def test_v6_timing_analyzer_is_a_small_facade():
    lines = _lines("dragontools/worker/duration_timing_analyzer.py")
    text = "\n".join(lines)
    assert len(lines) <= 120
    assert "duration_timing_sources" in text
    assert "duration_timing_mapping" in text
    assert "duration_timing_inference" in text


def test_v6_jellyfin_metadata_public_module_is_a_facade():
    lines = _lines("dragontools/core/media_library_jellyfin_metadata.py")
    text = "\n".join(lines)
    assert len(lines) <= 60
    assert "media_library_jellyfin_metadata_loader" in text
    assert "media_library_jellyfin_metadata_writer" in text
    assert "media_library_jellyfin_metadata_types" in text


def test_v6_search_enrichment_public_module_is_a_facade():
    lines = _lines("dragontools/core/media_library_search_enrichment.py")
    text = "\n".join(lines)
    assert len(lines) <= 60
    assert "media_library_search_streams" in text
    assert "media_library_search_fields" in text


def test_v6_subtitle_selection_public_module_is_a_facade():
    lines = _lines("dragontools/rules/subtitle_selection.py")
    text = "\n".join(lines)
    assert len(lines) <= 80
    assert "subtitle_selection_common" in text
    assert "subtitle_selection_priority" in text
    assert "subtitle_selection_sidecar" in text


def test_v6_remux_and_merge_have_explicit_output_verifiers():
    mp4 = "\n".join(_lines("dragontools/worker/mp4_remux_thread.py"))
    merge = "\n".join(_lines("dragontools/worker/merge_executor.py"))
    assert "MP4RemuxOutputVerifier" in mp4
    assert "MergeOutputVerifier" in merge
