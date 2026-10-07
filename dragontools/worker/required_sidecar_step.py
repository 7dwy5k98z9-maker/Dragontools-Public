"""Failure boundary after a completed video encode or remux."""
from __future__ import annotations

from .workflow_models import PipelineExecutionResult


def finalize_required_sidecars(export_step, *, initial_sidecars=(), externalized_indices=()):
    """Report a late export failure while retaining the completed candidate."""
    paths = tuple(initial_sidecars)
    try:
        complete, exported, reason = export_step()
        paths = tuple(dict.fromkeys((*paths, *exported)))
    except Exception as exc:
        complete = False
        reason = f"Sidecar-Export unerwartet fehlgeschlagen: {exc}"
    if not complete:
        return PipelineExecutionResult(
            False, sidecar_paths=paths, failure_stage="Untertitel-Export",
            failure_reason=reason or "Sidecar-Export unvollständig.",
            preserve_failed_output=True,
            externalized_subtitle_stream_indices=tuple(externalized_indices),
        )
    return PipelineExecutionResult.succeeded(
        sidecar_paths=paths, externalized_subtitle_stream_indices=externalized_indices)
