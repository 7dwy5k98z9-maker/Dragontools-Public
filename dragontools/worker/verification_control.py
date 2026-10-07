"""Shared stop gate for probes, semantic verification and repair commits."""


def stopped(result=None, worker=None):
    if getattr(result, 'aborted', False) is True or getattr(result, 'timed_out', False) is True:
        return True
    state = getattr(worker, '_control_state', None) or worker
    return bool(getattr(state, 'abort_requested', False)
                and getattr(state, 'abort_type', None) == 'sofort')


def require_running(result=None, worker=None):
    if stopped(result, worker):
        raise RuntimeError('Medienprüfung/Reparatur abgebrochen oder zeitüberschritten.')
