"""Qualify a corrupt-source retry from one coherent tool failure."""
from __future__ import annotations

import re
from pathlib import PureWindowsPath
from .dv_source_rpu_check import SOURCE_RPU_STAGE, UNUSABLE_RPU_PREFIX


def is_corrupt_source_rpu_failure(result, temp_state) -> bool:
    # Prefer the explicit result as a whole. Mixing it with mutable diagnostics
    # from another command can turn a track error into an unrelated parser retry.
    explicit = any(getattr(result, field, '') for field in
                   ('failure_stage', 'tool', 'command', 'tool_output'))
    failure = result if explicit else temp_state
    stage = str(getattr(failure, 'failure_stage', '') or '').strip().casefold()
    tool = str(getattr(failure, 'tool' if explicit else 'last_tool', '') or '')
    command = str(getattr(failure, 'command' if explicit else 'last_command', '') or '')
    output = str(getattr(failure, 'tool_output' if explicit else 'stderr', '') or '')
    reason = str(getattr(failure, 'failure_reason', '') or '').casefold()
    if stage == SOURCE_RPU_STAGE.casefold():
        return reason.startswith(UNUSABLE_RPU_PREFIX.casefold())
    if stage != 'step 3/7 rpu-extraktion' or PureWindowsPath(tool).stem.casefold() != 'dovi_tool':
        return False
    if re.search(r'\bextract-rpu\b', command, re.IGNORECASE) is None:
        return False
    if any(word in reason for word in ('timeout', 'abgebrochen', 'cancel', 'aborted')):
        return False
    return re.search(r'(?im)^\s*Error:\s*Invalid RPU last byte:\s*\d+\s*$', output) is not None
