"""Best-effort exception reports that cannot interrupt worker recovery."""
from __future__ import annotations

import traceback

from ..core.crash_guard import write_manual_crash_note
from .log_dispatch import dispatch_log


def report_worker_exception(log, reason: str, exc: Exception) -> str:
    """Capture the original exception before invoking fallible log callbacks."""
    try:
        detail = f"{type(exc).__name__}: {exc}"
    except Exception:
        detail = type(exc).__name__
    try:
        trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    except Exception:
        # Even traceback formatting can fail in a damaged runtime. Preserve
        # frame locations without linecache, source lookups or locals/secrets.
        frames = []
        tb = exc.__traceback__
        while tb is not None:
            code = tb.tb_frame.f_code
            frames.append(f"  {code.co_filename}:{tb.tb_lineno} in {code.co_name}")
            tb = tb.tb_next
        trace = "\n".join([detail, *frames])
    report = ""
    try:
        report = write_manual_crash_note(reason, traceback_text=trace)
    except Exception as report_exc:
        dispatch_log(log, f"Fehlerbericht konnte nicht geschrieben werden: {type(report_exc).__name__}", "error")
    dispatch_log(log, f"{reason} {detail}", "error")
    for line in trace.splitlines():
        dispatch_log(log, line, "error")
    if report:
        dispatch_log(log, f"Fehlerbericht: {report}", "error")
    return report
