"""Ownership and atomic publication for subtitle jobs."""

import os
from pathlib import Path

from ..core.move_transaction import publish_staged_no_replace
from ..worker.hdr_metadata_file_ownership import metadata_output_conflicts_with_sources
from ..worker.verification_control import stopped


def reject_source_output(output, *sources):
    return metadata_output_conflicts_with_sources(output, *sources)


def publish_subtitle_stage(stage, output, *, overwrite=False):
    """Keep a verified stage on publication failure for recovery."""
    if overwrite:
        os.replace(stage, output)
    else:
        publish_staged_no_replace(stage, output)


def valid_stream_indices(rows):
    if not isinstance(rows, list):
        raise ValueError("Untertitelinventar enthält kein streams-Array.")
    indices = [row.get("index") if isinstance(row, dict) else None for row in rows]
    if any(type(index) is not int or index < 0 for index in indices):
        raise ValueError("Untertitelinventar enthält ungültige Streamindizes.")
    if len(indices) != len(set(indices)):
        raise ValueError("Untertitelinventar enthält doppelte Streamindizes.")
    return indices
