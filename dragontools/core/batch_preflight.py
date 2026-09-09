from __future__ import annotations

"""Compatibility facade for batch preflight functionality.

The implementation is split by responsibility: formatting, decision/warning
logic, row construction/storage checks, and report rendering. Existing imports
from :mod:`dragontools.core.batch_preflight` remain stable.
"""

from .batch_preflight_decisions import (
    OLD_CONTAINER_EXTENSIONS,
    _decision_reasons,
    _strip_only_warnings,
    _warnings_for,
)
from .batch_preflight_formatting import (
    _audio_stream_summary, _audio_summary, _bitrate_label, _channel_label,
    _hdr_summary, _pipeline_summary, _profile_summary, _stream_list_label,
    _subtitle_summary, _target_summary, _text, _value, _video_summary,
)
from .batch_preflight_report import (
    _report_block, _report_values, default_batch_preflight_report_path,
    format_batch_preflight_report,
)
from .batch_preflight_rows import (
    PROBLEM_SEVERITIES, PreviewBuilder, _annotate_batch_storage,
    _append_row_warning, _error_row, _row_from_preview, _set_row_problem,
    _storage_group_key, build_batch_preflight_rows, split_problem_rows,
)

__all__ = [
    "build_batch_preflight_rows", "split_problem_rows",
    "default_batch_preflight_report_path", "format_batch_preflight_report",
]
