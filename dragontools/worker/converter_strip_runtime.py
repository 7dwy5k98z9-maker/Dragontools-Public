from __future__ import annotations


def job(worker):
    return getattr(worker, "_job_state", None)


def subtitle_rules(worker):
    state = job(worker)
    return state.subtitle_rules if state is not None else getattr(worker, "subtitle_rules")


def tools(worker):
    services = getattr(worker, "_services", None)
    value = getattr(services, "tools", None) if services is not None else None
    return value if value is not None else getattr(worker, "tools")


def progress(worker):
    services = getattr(worker, "_services", None)
    value = getattr(services, "progress", None) if services is not None else None
    return value if value is not None else getattr(worker, "_progress")
