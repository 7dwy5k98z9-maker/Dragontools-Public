# -*- coding: utf-8 -*-
"""Regression matrix for the canonical conversion-artifact hand-off contract."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from dragontools.core.conversion_artifacts import (
    ArtifactRegistry,
    ConversionArtifactBundle,
    publish_bundle_to_worker,
)
from dragontools.gui.conversion_session_state import ConversionSessionState
from dragontools.worker.parallel_converter_state import ParallelResultState


@pytest.mark.parametrize(
    "case,sidecars,postprocess",
    [
        ("mkv-internal", [], []),
        ("mp4-subtitle-sidecar", ["film.de.srt"], []),
        ("mp4-bitmap-sidecar", ["film.de.sup"], []),
        ("dv5-fallback", ["film.nfo", "film.trickplay"], [{"kind": "nfo", "status": "created"}]),
        ("dv7-remux", ["film.de.srt"], []),
        ("dv8-remux", ["film.de.srt", "film.nfo"], [{"kind": "nfo", "status": "created"}]),
        ("dv7-to-dv81", ["film.trickplay"], [{"kind": "trickplay", "status": "created"}]),
        ("nfo-only", ["film.nfo"], [{"kind": "nfo", "status": "created"}]),
        ("trickplay-only", ["film.trickplay"], [{"kind": "trickplay", "status": "created"}]),
        ("nfo-trickplay", ["film.nfo", "film.trickplay"], [{"kind": "nfo", "status": "created"}, {"kind": "trickplay", "status": "created"}]),
        ("subtitle-nfo-trickplay", ["film.de.srt", "film.nfo", "film.trickplay"], [{"kind": "nfo", "status": "created"}, {"kind": "trickplay", "status": "created"}]),
        ("no-companions", [], []),
    ],
)
def test_artifact_registry_matrix_is_lossless(case, sidecars, postprocess):
    registry = ArtifactRegistry()
    registry.sidecar_outputs["in.mkv"] = list(sidecars)
    registry.postprocess_outputs["in.mkv"] = [dict(item) for item in postprocess]

    bundle = registry.bundle("in.mkv", output_path="out.mkv", status="✅")

    assert list(bundle.sidecars) == sidecars, case
    assert [dict(item) for item in bundle.postprocess] == postprocess, case
    assert bundle.output_path == "out.mkv"
    assert bundle.status == "✅"


def test_empty_worker_maps_remain_live_views_when_bundle_is_published():
    worker = SimpleNamespace(
        _sidecar_outputs={}, _postprocess_outputs={}, _failure_details={}
    )
    bundle = ConversionArtifactBundle(
        input_path="in.mkv",
        output_path="out.mkv",
        sidecars=("out.nfo", "out.trickplay"),
        postprocess=({"kind": "nfo", "status": "created"},),
        status="✅",
    )

    publish_bundle_to_worker(worker, bundle)

    assert worker._sidecar_outputs["in.mkv"] == ["out.nfo", "out.trickplay"]
    assert worker._postprocess_outputs["in.mkv"][0]["kind"] == "nfo"


def test_parallel_result_state_syncs_one_atomic_bundle_from_child():
    child_registry = ArtifactRegistry()
    child_registry.sidecar_outputs["in.mkv"] = ["out.de.srt", "out.nfo"]
    child_registry.postprocess_outputs["in.mkv"] = [{"kind": "nfo", "status": "created"}]
    child_registry.failure_details["in.mkv"] = {"message": "diagnostic only"}
    child = SimpleNamespace(_session_state=SimpleNamespace(artifacts=child_registry))

    state = ParallelResultState()
    state.sync_from_child(child, "in.mkv")

    assert state.sidecar_outputs["in.mkv"] == ["out.de.srt", "out.nfo"]
    assert state.postprocess_outputs["in.mkv"][0]["kind"] == "nfo"
    assert state.failure_details["in.mkv"]["message"] == "diagnostic only"


def test_gui_move_map_is_derived_from_terminal_artifact_bundle():
    state = ConversionSessionState()
    state.sidecar_outputs_by_video["recovered.mkv"] = ["recovered.nfo"]
    state.artifacts_by_input["in.mkv"] = ConversionArtifactBundle(
        input_path="in.mkv",
        output_path="out.mkv",
        sidecars=("out.de.srt", "out.nfo", "out.trickplay"),
        status="✅",
    )

    move_map = state.sidecars_for_move()

    assert move_map["recovered.mkv"] == ["recovered.nfo"]
    assert move_map["out.mkv"] == ["out.de.srt", "out.nfo", "out.trickplay"]


def test_non_success_bundle_does_not_enter_move_map():
    state = ConversionSessionState()
    state.artifacts_by_input["bad.mkv"] = ConversionArtifactBundle(
        input_path="bad.mkv",
        output_path="bad-out.mkv",
        sidecars=("bad.nfo",),
        status="❌",
    )
    assert "bad-out.mkv" not in state.sidecars_for_move()


def test_architecture_uses_canonical_artifact_registry_and_move_bundle_bridge():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    converter_state = (root / "dragontools/worker/converter_thread_state.py").read_text(encoding="utf-8")
    dv_thread = (root / "dragontools/worker/dv_remux_thread.py").read_text(encoding="utf-8")
    gui_events = (root / "dragontools/gui/conversion_result_file_events.py").read_text(encoding="utf-8")
    regular_move = (root / "dragontools/gui/move_regular_lifecycle.py").read_text(encoding="utf-8")
    incremental_move = (root / "dragontools/gui/move_incremental_lifecycle.py").read_text(encoding="utf-8")

    assert "artifacts: ArtifactRegistry" in converter_state
    assert "self._artifacts = ArtifactRegistry()" in dv_thread
    assert "ConversionArtifactBundle.from_worker" in gui_events
    assert "sidecar_outputs_by_video=state.sidecars_for_move()" in regular_move
    assert "sidecar_outputs_by_video=state.sidecars_for_move()" in incremental_move
