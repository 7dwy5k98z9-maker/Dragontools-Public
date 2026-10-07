"""Exclude sources already queued in another loaded converter."""
from ..core.path_syntax import path_compare_key


def available_watch_paths(widgets, *, codec, paths):
    owned = set()
    for key, widget in widgets.items():
        if key == codec:
            continue
        file_list = getattr(widget, "file_list", None)
        if file_list is not None:
            owned.update(path_compare_key(path) for path in file_list.get_paths())
    return [path for path in paths if path_compare_key(path) not in owned]
