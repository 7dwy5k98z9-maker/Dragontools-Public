from __future__ import annotations

import os

from ..core.paths import is_video_file, normalize_user_path, strip_long_path_prefix, to_long_path


def iter_video_files_in_folder(folder_path: str) -> tuple[list[str], int]:
    """Rekursiv Videodateien sammeln; lange Windows-Pfade transparent behandeln."""
    folder = normalize_user_path(folder_path)
    if not folder:
        return [], 0

    walk_root = to_long_path(folder) if os.name == "nt" else folder
    video_paths: list[str] = []
    ignored_count = 0
    for current_root, _dirs, files in os.walk(walk_root):
        visible_root = strip_long_path_prefix(current_root)
        for name in files:
            path = normalize_user_path(os.path.join(visible_root, name))
            if is_video_file(path):
                video_paths.append(path)
            else:
                ignored_count += 1
    return sorted(video_paths), ignored_count
