from __future__ import annotations

import ast
from pathlib import Path
import zipfile

from dragontools.core.renamer_metadata_browser import (
    ExplicitSeriesFileMapping,
    MetadataBrowserEpisode,
    MetadataBrowserHit,
)


ROOT = Path(__file__).parents[2]
GUI_SOURCE = ROOT / "dragontools" / "gui" / "movie_renamer_metadata_browser.py"


def _source() -> str:
    text = GUI_SOURCE.read_text(encoding="utf-8")
    ast.parse(text)
    for name in ['movie_renamer_browser_mapping.py', 'movie_renamer_browser_runtime.py']:
        module = (GUI_SOURCE.parent / name).read_text(encoding='utf-8')
        ast.parse(module)
        text += '\n' + module
    return text


def test_browser_pins_movie_selection_instead_of_using_incidental_result_row() -> None:
    source = _source()
    assert "self._current_movie_hit: MetadataBrowserHit | None = None" in source
    assert "self._current_movie_hit = hit" in source
    assert "hit = self._current_movie_hit" in source
    assert "mit 'Film auswählen' aktivieren" in source


def test_browser_blocks_semantic_mapping_controls_while_metadata_is_in_flight() -> None:
    source = _source()
    for widget in (
        "self.kind_combo",
        "self.query_edit",
        "self.results",
        "self.load_hit_btn",
        "self.season_combo",
        "self.assign_btn",
        "self.auto_assign_btn",
        "self.import_btn",
    ):
        assert widget in source
    assert "Bitte die laufende Metadaten-Abfrage abwarten." in source
    assert "lambda payload, expected_kind=kind: self._on_search_results(expected_kind, payload)" in source
    assert "if self._kind() != expected_kind:" in source


def test_browser_clears_stale_episode_rows_before_series_or_season_requests() -> None:
    source = _source()
    # One clear when changing the selected series, another when changing season.
    assert source.count("self._episodes = []") >= 2
    assert source.count("self.episode_table.setRowCount(0)") >= 4
    assert "The old episode table must never remain assignable" in source
    assert "A season switch is asynchronous" in source


def test_auto_assign_does_not_silently_replace_movie_mapping() -> None:
    source = _source()
    block_start = source.index("def _auto_assign")
    block_end = source.index("def _clear_selected_mappings", block_start)
    block = source[block_start:block_end]
    assert "not in self._series_mappings" in block
    assert "not in self._movie_mappings" in block


def test_invalid_provider_episode_span_is_user_visible_and_preserves_old_mapping_until_validated() -> None:
    source = _source()
    start = source.index("def _assign_paths_to_episode")
    end = source.index("def _mapping_conflict", start)
    block = source[start:end]
    assert "except ValueError as exc:" in block
    mapping_pos = block.index("mapping = ExplicitSeriesFileMapping")
    pop_pos = block.index("self._movie_mappings.pop(key, None)")
    assert mapping_pos < pop_pos


def test_core_rejects_gapped_multi_episode_provider_span() -> None:
    hit = MetadataBrowserHit(kind="series", provider="tmdb", provider_id=1, title="Serie")
    episodes = (
        MetadataBrowserEpisode(season=1, episode=1, title="Eins"),
        MetadataBrowserEpisode(season=1, episode=3, title="Drei"),
    )
    try:
        ExplicitSeriesFileMapping(Path("raw.mkv"), hit, 1, episodes)
    except ValueError as exc:
        assert "aufeinanderfolgenden" in str(exc)
    else:  # pragma: no cover - contract guard
        raise AssertionError("Gapped episode span must be rejected")


def test_user_documentation_mentions_metadata_browser_quick_toggles_and_container_preview() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    help_html = (ROOT / "help.html").read_text(encoding="utf-8")
    for text in (readme, help_html):
        assert "Metadaten-Browser" in text
        assert "HDR+ Generator" in text
        assert "Watch-Folder" in text
        assert "Ausgabecontainer" in text

    docx_path = ROOT / "DragonToolsV9_Dokumentation.docx"
    with zipfile.ZipFile(docx_path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    assert "Metadaten-Browser" in xml
    assert "Zuordnung in Renamer übernehmen" in xml
    assert "Ausgabecontainer" in xml


def test_release_statistics_fallback_matches_current_source_inventory() -> None:
    from dataclasses import replace
    from dragontools.core.project_info import RELEASE_STATISTICS, collect_project_statistics

    current = collect_project_statistics(ROOT)
    assert current.dynamic is True
    assert replace(current, dynamic=False) == RELEASE_STATISTICS
