"""Resolve NFO queries from the per-file identity owned by the conversion job."""
from ..core.preflight_metadata_identity import metadata_lookup_filename
from .job_process_owner import JobProcessOwner
from .worker_contracts import file_override_for_path


def metadata_lookup_path(worker, input_path: str) -> str:
    while isinstance(worker, JobProcessOwner):
        worker = worker.parent
    state = getattr(worker, '_job_state', None)
    overrides = getattr(state, 'file_overrides', None)
    if overrides is None:
        overrides = getattr(worker, 'file_overrides', {})
    override = file_override_for_path(overrides, input_path) or {}
    return metadata_lookup_filename(override.get('metadata_context'), input_path)
