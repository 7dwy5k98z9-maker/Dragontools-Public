"""Canonical server paths without erasing POSIX filename identity."""
import posixpath
import ntpath
from .path_syntax import is_windows_style_path


def normalize_path(value):
    text=str(value or '').strip().replace('\\','/')
    if not text:
        return ''
    return ntpath.normpath(text).replace('\\', '/') if is_windows_style_path(text) else posixpath.normpath(text)


def path_key(value):
    path=normalize_path(value)
    return path.casefold() if is_windows_style_path(path) else path
