"""Confirm new live queue entries before atomically handing their settings to workers."""
from ..core.path_syntax import display_name, path_compare_key
from ..core.preflight_metadata_identity import with_planned_metadata


def worker_queue_is_running(thread) -> bool:
    if thread is None:
        return False
    probe = getattr(thread, 'isRunning', None)
    # Preserve compatibility with queue-only adapters lacking a native thread.
    return bool(probe()) if callable(probe) else True


def present_queue_paths(file_list, paths: list[str]) -> list[str]:
    getter = getattr(file_list, 'get_paths', None)
    if not callable(getter):
        return paths
    present = {path_compare_key(path) for path in getter()}
    return [path for path in paths if path_compare_key(path) in present]


def prepare_live_paths(file_list, paths: list[str], preflight) -> list[str]:
    if paths:
        preflight(paths)
    return present_queue_paths(file_list, paths)


def admit_live_queue_paths(queue, paths: list[str], *, remove_rejected, sync_order) -> list[str]:
    thread = queue.state.thread
    prepared = prepare_live_paths(queue.file_list, paths, queue.maybe_preflight_new_files)
    if queue.state.thread is not thread or not queue.guard_queue_edit_allowed('Dateien aufnehmen'):
        return []
    reset = getattr(queue.state, 'reset_file_for_requeue', None)
    if callable(reset):
        for path in prepared:
            reset(path)
    # A stopped worker's closed queue belongs to the previous run. Keep fresh
    # GUI rows for the next start instead of submitting them to that old worker.
    if not worker_queue_is_running(thread):
        return prepared
    values = with_planned_metadata(queue.state.file_overrides, getattr(queue.state, 'planned_targets', {}))
    accepted, rejected = [], []
    for path in prepared:
        try:
            override = values.get(path, {})
            add_with_override = getattr(thread, 'add_file_with_override', None)
            result = add_with_override(path, override) if callable(add_with_override) else thread.add_file(path)
            if result is False:
                rejected.append(path)
                continue
            accepted.append(path)
            if override:
                queue.state.file_overrides[path] = override
            queue.log(f'➕ Zur Queue hinzugefügt: {display_name(path)}', 'info')
        except Exception as exc:
            queue.log(f'Live-Hinzufügen fehlgeschlagen: {display_name(path)} - {exc}', 'warn')
            rejected.append(path)
    remove_rejected(rejected)
    sync_order()
    return accepted
