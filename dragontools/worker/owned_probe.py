"""Adapt subprocess-shaped analysis calls to the existing owned tool runner."""
from .tool_runner import run_tool
from .verification_control import require_running


def owned_probe_runner(worker, *, label='Medienprüfung'):
    def run(command, *, timeout=60, **_options):
        require_running(worker=worker)
        result = run_tool(command, label=label, timeout_s=timeout, worker=worker)
        require_running(result, worker)
        return result
    return run
