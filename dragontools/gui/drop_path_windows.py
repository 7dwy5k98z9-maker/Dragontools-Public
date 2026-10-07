from __future__ import annotations

from ..core.path_syntax import normalize_user_path


def extract_itemidlist_bytes(data: bytes, offset: int) -> bytes:
    """Eine vollständige ITEMIDLIST (PIDL) aus einer CIDA-Payload lesen."""
    if not isinstance(offset, int) or offset < 0 or offset + 2 > len(data):
        return b""
    result = bytearray()
    pos = offset
    while pos + 2 <= len(data):
        cb = int.from_bytes(data[pos : pos + 2], "little")
        if cb == 0:
            result.extend(b"\x00\x00")
            return bytes(result)
        if cb < 2 or pos + cb > len(data):
            return b""
        result.extend(data[pos : pos + cb])
        pos += cb
    return b""  # Never pass an unterminated partial list to native code.


def _cida_pidls(data):
    """Validate all offsets and complete lists before loading any Shell API."""
    if len(data) < 12:
        return []
    count = int.from_bytes(data[:4], "little")
    header_size = 4 + (count + 1) * 4
    if count == 0 or header_size > len(data):
        return []
    offsets = [int.from_bytes(data[4 + i * 4:8 + i * 4], "little") for i in range(count + 1)]
    if any(offset < header_size or offset + 2 > len(data) for offset in offsets):
        return []
    lists = [extract_itemidlist_bytes(data, offset) for offset in offsets]
    return lists if all(lists) else []


def resolve_shell_idlist_to_paths(data: bytes, log_fn=None, *, debug: bool = False) -> list[str]:
    """Windows CIDA/PIDL via Shell API zu lokalen Pfaden auflösen."""
    pidls = _cida_pidls(data)
    if not pidls:
        return []
    import ctypes

    shell32 = ctypes.windll.shell32
    shell32.ILCombine.restype = ctypes.c_void_p
    shell32.ILCombine.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    shell32.ILFree.restype = None
    shell32.ILFree.argtypes = [ctypes.c_void_p]
    shell32.SHGetPathFromIDListW.restype = ctypes.c_bool
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]

    parent_pidl_bytes = pidls[0]
    paths: list[str] = []
    max_path_buf = 32767
    for i, item_pidl_bytes in enumerate(pidls[1:], start=1):
        parent_buf = ctypes.create_string_buffer(parent_pidl_bytes)
        item_buf = ctypes.create_string_buffer(item_pidl_bytes)
        combined = shell32.ILCombine(parent_buf, item_buf)
        if not combined:
            _debug(log_fn, debug, f"Drag&Drop: ILCombine returned NULL für Item {i}")
            continue
        try:
            path_buf = ctypes.create_unicode_buffer(max_path_buf)
            ok = False
            try:
                shell32.SHGetPathFromIDListEx.restype = ctypes.c_bool
                shell32.SHGetPathFromIDListEx.argtypes = [
                    ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint
                ]
                ok = bool(shell32.SHGetPathFromIDListEx(combined, path_buf, max_path_buf, 0))
            except (AttributeError, OSError):
                pass
            if not ok:
                ok = bool(shell32.SHGetPathFromIDListW(combined, path_buf))
            if ok and path_buf.value:
                normalized = normalize_user_path(path_buf.value)
                if normalized:
                    _debug(log_fn, debug, f"Drag&Drop: Shell IDList → {normalized}")
                    paths.append(normalized)
            else:
                _debug(log_fn, debug, f"Drag&Drop: Shell IDList Item {i} – SHGetPath schlug fehl")
        finally:
            shell32.ILFree(combined)
    return paths


def _debug(log_fn, enabled: bool, message: str) -> None:
    if enabled and callable(log_fn):
        log_fn(message, "warn")
