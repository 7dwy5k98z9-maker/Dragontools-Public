from __future__ import annotations

import ast
from pathlib import Path

import dragontools.core.models as models
import dragontools.core.media_analyzer as media_analyzer
import dragontools.worker.media_contract as media_contract
import dragontools.worker.output_verifier as output_verifier
import dragontools.core.online_metadata_tvdb_resolver as tvdb_resolver


def test_models_only_reexports_override_normalizer() -> None:
    source = Path(models.__file__).read_text(encoding="utf-8")
    assert "from .file_override_normalization import normalize_override_dict" in source
    assert "def normalize_override_dict" not in source


def test_media_analyzer_is_orchestration_facade() -> None:
    core = Path(media_analyzer.__file__).parent
    assert (core / "media_analyzer_metadata.py").exists()
    assert (core / "media_analyzer_result.py").exists()


def test_media_contract_and_output_verifier_are_split_by_responsibility() -> None:
    worker = Path(media_contract.__file__).parent
    for name in (
        "media_contract_builder.py",
        "media_contract_types.py",
        "output_probe.py",
        "output_contract_verifier.py",
    ):
        assert (worker / name).exists()


def test_tvdb_candidate_search_is_no_longer_in_resolver() -> None:
    core = Path(tvdb_resolver.__file__).parent
    candidates = core / "online_metadata_tvdb_candidates.py"
    assert candidates.exists()
