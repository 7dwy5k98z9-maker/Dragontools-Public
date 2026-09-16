from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.tests.test_pixel_verification_tolerance import (
    _ctx,
    _Logger,
    _NoRepair,
    _ReplaceService,
    _ResultService,
    _valid_result,
    _Verifier,
)
from dragontools.worker.dv_final_metadata_verifier import DVFinalMetadataVerifier
from dragontools.worker.workflow_output_commit import WorkflowOutputCommitCoordinator
from dragontools.worker.workflow_verification_service import WorkflowVerificationService


@pytest.mark.parametrize("delta", [0, 1, 2, 4, 6])
@pytest.mark.parametrize("failure", ["extract", "empty"])
def test_failed_final_rpu_preserves_candidate_and_original(tmp_path, delta, failure):
    result = _valid_result(delta=delta, contract_ok=delta <= 2)
    ctx = _ctx(tmp_path, result=result, dv=True, rpu_ok=True)
    state = SimpleNamespace(verified_dolby_vision=True, verified_dv_crop_alignment=True)
    logger = _Logger()
    verifier = DVFinalMetadataVerifier(
        tools=None, temp_state=None,
        rpu_service=SimpleNamespace(extract_rpu=lambda *a, **kw: failure != "extract"),
        hdr10plus_service=None, log=lambda *a: None, verbose_log=lambda *a: None,
        assert_nonempty_file=lambda *a: False,
    )
    # Preserve the pipeline's diagnostic candidate rather than invoking its
    # generic failure cleanup. The workflow below must block the actual commit.
    assert verifier._verify_dv(
        state, tmp_path / "final.hevc", tmp_path / "final.rpu",
        SimpleNamespace(adapter=lambda **kw: None), lambda p: "unused", "mkv",
    ) is True
    assert not state.verified_dolby_vision
    assert not state.verified_dv_crop_alignment
    for name in ("checked", "present", "message"):
        setattr(ctx, "pipeline_final_rpu_" + name, getattr(state, "final_rpu_" + name))
    service = WorkflowVerificationService(
        output_verifier=_Verifier(result), duration_repair_service=_NoRepair(), logger=logger,
    )
    service.verify(ctx)
    assert ctx.verification_archive_required
    assert ctx.verification_archive_tier == "final_rpu_unverified"
    assert not result.ok
    assert not ctx.pipeline_verified_dolby_vision
    assert not ctx.pipeline_verified_dv_crop_alignment
    ctx.sidecar_paths = []
    coordinator = WorkflowOutputCommitCoordinator(
        # Deliberately has no replace method: invoking destructive replace fails.
        replace_service=_ReplaceService(), logger=logger, result_service=_ResultService(),
        sidecar_outputs={}, postprocess_outputs={},
    )
    coordinator.replace(ctx)
    assert ctx.replacement_blocked and ctx.keep_failed_output
    assert not ctx.postprocess_pending
    assert Path(ctx.input_path).read_bytes() == b"source"
    assert Path(ctx.replacement_archived_path).read_bytes() == b"encoded-result"
    assert Path(ctx.verification_csv_path).is_file()
    assert Path(ctx.verification_report_path).is_file()


def test_failed_rpu_archive_keeps_candidate_when_archive_cannot_be_created(tmp_path):
    result = _valid_result(delta=0, contract_ok=True)
    ctx = _ctx(tmp_path, result=result, dv=True)
    ctx.pipeline_final_rpu_checked = True
    ctx.pipeline_final_rpu_present = False
    logger = _Logger()
    WorkflowVerificationService(
        output_verifier=_Verifier(result), duration_repair_service=_NoRepair(), logger=logger,
    ).verify(ctx)
    # A file at the archive directory path simulates an unavailable destination.
    (tmp_path / "Archiv").write_bytes(b"existing")
    ctx.sidecar_paths = []
    WorkflowOutputCommitCoordinator(
        replace_service=_ReplaceService(), logger=logger, result_service=_ResultService(),
        sidecar_outputs={}, postprocess_outputs={},
    ).replace(ctx)
    assert ctx.replacement_blocked and ctx.keep_failed_output
    assert Path(ctx.input_path).read_bytes() == b"source"
    assert Path(ctx.output_path).read_bytes() == b"encoded-result"


def test_target_change_after_dialog_updates_current_output_key():
    from dragontools.gui.convert_widget_queue_target_actions import (
        ConvertWidgetQueueTargetActionsMixin,
    )

    class Gui(ConvertWidgetQueueTargetActionsMixin):
        def _log(self, *args):
            pass

        def _refresh_queue_window(self):
            pass

        def _choose_replacement_targets(self, rows):
            self._state.planned_targets["output.mkv"] = self._state.planned_targets.pop("input.mkv")
            self._state.artifacts_by_input["input.mkv"] = SimpleNamespace(output_path="output.mkv")
            return {"input.mkv": "NEW"}

    gui = Gui()
    gui._state = SimpleNamespace(
        planned_targets={"input.mkv": "OLD"}, artifacts_by_input={}, move_thread=None,
    )
    gui._change_planned_target(("input.mkv",))
    assert gui._state.planned_targets == {"output.mkv": "NEW"}
