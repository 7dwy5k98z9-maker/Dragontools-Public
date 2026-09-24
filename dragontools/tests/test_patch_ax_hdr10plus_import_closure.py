from __future__ import annotations


def test_hdr10plus_workflow_policy_is_importable_and_callable():
    from dragontools.worker.hdr10plus_workflow_policy import (
        should_postprocess_generated_hdr10plus,
    )

    assert callable(should_postprocess_generated_hdr10plus)
    assert should_postprocess_generated_hdr10plus(
        selection={},
        strip_only=True,
        pipeline="standard",
        codec="h265",
        encoder_options={},
        generate_hdr10plus=True,
    ) is True


def test_workflow_planning_service_import_resolves_hdr10plus_policy():
    from dragontools.worker.workflow_planning_service import WorkflowPlanningService

    assert WorkflowPlanningService.__name__ == "WorkflowPlanningService"
