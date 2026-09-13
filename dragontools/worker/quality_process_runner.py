from __future__ import annotations

from ..core.timeout_settings import get_timeout
from .tool_runner import run_tool


class QualityProcessRunner:
    def __init__(self, *, worker, log, prefix: str) -> None:
        self._worker = worker
        self._log = log
        self._prefix = prefix

    def run(self, cmd: list[str], *, label: str) -> tuple[int, str, str]:
        result = run_tool(
            cmd,
            label=f"{self._prefix}: {label}",
            timeout_s=get_timeout("quality_test_process"),
            worker=self._worker,
            log=lambda message, _level="info": self._log(message),
            abort_on_request=True,
        )
        if result.aborted or bool(getattr(self._worker, "_abort", False)):
            raise RuntimeError("Abgebrochen")
        if result.timed_out:
            timeout = result.timeout_s
            if timeout is None:
                raise RuntimeError(f"{label} wurde wegen eines Timeouts beendet.")
            raise RuntimeError(f"{label} Timeout nach {float(timeout):.0f}s.")
        if not result.ok:
            raise RuntimeError(f"{label} fehlgeschlagen: {result.combined_output[:2000]}")
        return result.returncode, result.stdout, result.stderr
