"""Shared context actions for the converter list and its separate queue window."""
from ..core.callback_dispatch import best_effort_callback
from ..core.path_syntax import display_name

_PAUSE_PREFIX = "⏸ Pausiert · "


def file_pause_caption(text, *, worker, path):
    text = str(text).removeprefix(_PAUSE_PREFIX)
    return _PAUSE_PREFIX + text if file_worker_is_paused(worker, path) else text


def update_file_pause_row(file_list, *, worker, path):
    if file_list is None:
        return
    item = file_list.item_for_path(path)
    if item is not None:
        item.setText(file_pause_caption(item.text(), worker=worker, path=path))


def file_worker_is_paused(worker, path):
    query = getattr(worker, "file_pause_state", None)
    if not callable(query):
        return False
    try:
        return query(path) is True
    except Exception:
        return False


def add_file_worker_pause_action(menu, path, *, worker_provider, refresh, log=None, source_list=None):
    worker = worker_provider()
    query = getattr(worker, "file_pause_state", None)
    setter = getattr(worker, "set_file_paused", None)
    token_provider = getattr(worker, "file_control_token", None)
    if not all(callable(method) for method in (query, setter, token_provider)):
        return False
    paused = query(path)
    token = token_provider(path)
    if paused is None or token is None:
        return False
    def change():
        if worker_provider() is not worker:
            best_effort_callback(log, "Worker-Zuordnung hat sich geändert; bitte das Menü erneut öffnen.", "info")
            return
        if setter(path, not paused, expected_worker=token):
            verb = "pausiert" if not paused else "fortgesetzt"
            best_effort_callback(log, f"Worker {verb}: {display_name(path)}", "info")
            update_file_pause_row(source_list, worker=worker, path=path)
            refresh()
        else:
            best_effort_callback(log, "Diese Datei besitzt keinen steuerbaren Worker mehr oder die Gesamtpause ist aktiv.", "info")
    action = menu.addAction("▶ Worker fortsetzen" if paused else "⏸ Worker pausieren", change)
    global_pause = bool(getattr(worker, "is_paused", False))
    action.setEnabled(not global_pause)
    action.setToolTip("Zuerst die Gesamtpause aufheben." if global_pause
        else "Steuert nur den Worker dieser Videodatei. Andere Worker arbeiten weiter.")
    return True


def show_file_worker_menu(file_list, pos, *, worker_provider, refresh, allow_control, source_list=None):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QMenu
    item = file_list.itemAt(pos)
    if item is None or not allow_control():
        return
    menu = QMenu(file_list)
    path = item.data(Qt.ItemDataRole.UserRole)
    if add_file_worker_pause_action(menu, path, worker_provider=worker_provider, refresh=refresh,
                                   source_list=source_list or file_list):
        menu.exec(file_list.mapToGlobal(pos))
