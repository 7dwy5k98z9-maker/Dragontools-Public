"""Bind utility source analysis to the worker's existing process ownership."""
from inspect import signature, Parameter

from ..core.media_analyzer_io import AnalysisStoppedError
from .owned_probe import owned_probe_runner
from .verification_control import require_running


def owned_media_runner(worker):
    runner = owned_probe_runner(worker, label="Quellmedienanalyse")

    def owned_run(command, **kwargs):
        try:
            result = runner(command, **kwargs)
        except RuntimeError as exc:
            raise AnalysisStoppedError(str(exc)) from exc
        if result.returncode != 0:
            raise RuntimeError(result.stderr or "Quellmedienanalyse fehlgeschlagen.")
        return result

    return owned_run


def analyze_owned_media(path, tools, *, worker, analyzer):
    require_running(worker=worker)
    owned_run = owned_media_runner(worker)

    parameters = signature(analyzer).parameters
    accepts_runner = "run_process" in parameters or any(
        value.kind is Parameter.VAR_KEYWORD for value in parameters.values()
    )
    # Legacy injected analyzers remain callable; production always accepts the
    # explicit runner. Never repeat an analyzer after an internal TypeError.
    media = analyzer(path, tools, run_process=owned_run) if accepts_runner else analyzer(path, tools)
    require_running(worker=worker)
    return media
