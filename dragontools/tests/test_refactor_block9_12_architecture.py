from __future__ import annotations

import ast
from pathlib import Path

import dragontools.core.models as models
import dragontools.core.media_analyzer as media_analyzer
import dragontools.worker.media_contract as media_contract
import dragontools.worker.output_verifier as output_verifier
import dragontools.core.online_metadata_tvdb_resolver as tvdb_resolver


def _lines(module) -> list[str]:
    return Path(module.__file__).read_text(encoding="utf-8").splitlines()


def _function_size(module, name: str) -> int:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    node = next(item for item in ast.walk(tree) if isinstance(item, ast.FunctionDef) and item.name == name)
    return int(node.end_lineno or node.lineno) - node.lineno + 1


def test_models_only_reexports_override_normalizer() -> None:
    source = Path(models.__file__).read_text(encoding="utf-8")
    assert "from .file_override_normalization import normalize_override_dict" in source
    assert "def normalize_override_dict" not in source
    assert len(_lines(models)) < 220


def test_override_normalization_is_split_into_small_steps() -> None:
    import dragontools.core.file_override_normalization as module

    assert len(_lines(module)) < 230
    assert _function_size(module, "normalize_override_dict") < 70
    assert _function_size(module, "_normalize_subtitle_tracks") < 55


def test_media_analyzer_is_orchestration_facade() -> None:
    core = Path(media_analyzer.__file__).parent
    assert (core / "media_analyzer_metadata.py").exists()
    assert (core / "media_analyzer_result.py").exists()
    assert len(_lines(media_analyzer)) < 150
    assert _function_size(media_analyzer, "analyze_media") < 50


def test_media_contract_and_output_verifier_are_split_by_responsibility() -> None:
    worker = Path(media_contract.__file__).parent
    for name in (
        "media_contract_builder.py",
        "media_contract_types.py",
        "output_probe.py",
        "output_contract_verifier.py",
    ):
        assert (worker / name).exists()
    assert len(_lines(media_contract)) < 100
    assert _function_size(media_contract, "build_expected_media_contract") < 45
    assert len(_lines(output_verifier)) < 220
    assert _function_size(output_verifier, "verify") < 65


def test_tvdb_candidate_search_is_no_longer_in_resolver() -> None:
    core = Path(tvdb_resolver.__file__).parent
    candidates = core / "online_metadata_tvdb_candidates.py"
    assert candidates.exists()
    assert len(_lines(tvdb_resolver)) < 200
    assert _function_size(tvdb_resolver, "resolve_episode_candidates") < 10
    assert len(candidates.read_text(encoding="utf-8").splitlines()) < 230
