"""Rollback only children proven unstarted; retain every physically live child."""


def child_may_be_running(child):
    probe = getattr(child, "isRunning", None)
    if not callable(probe):
        return False
    try:
        return bool(probe())
    except Exception:
        return True


def release_unstarted_child(registry, queue, child, assigned_keys):
    registry.active_workers.discard(child)
    registry.postprocessing_workers.discard(child)
    try:
        registry.workers.remove(child)
    except ValueError:
        pass
    for key in assigned_keys:
        if queue.assigned.get(key) is child:
            queue.assigned.pop(key, None)
