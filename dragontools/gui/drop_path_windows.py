from __future__ import annotations

from ..core.paths import normalize_user_path


def extract_itemidlist_bytes(data: bytes, offset: int) -> bytes:
    """Eine vollständige ITEMIDLIST (PIDL) aus einer CIDA-Payload lesen."""
    result = bytearray()
    pos = offset
    while pos + 2 <= len(data):
        cb = int.from_bytes(data[pos : pos + 2], "little")
        if cb == 0:
            result.extend(b"\x00\x00")
            break
        if pos + cb > len(data):
            break
        result.extend(data[pos : pos + cb])
        pos += cb
    return bytes(result)


def resolve_shell_idlist_to_paths(data: bytes, log_fn=None, *, debug: bool = False) -> list[str]:
    """Windows CIDA/PIDL via Shell API zu lokalen Pfaden auflösen."""
    import ctypes

    shell32 = ctypes.windll.shell32
    shell32.ILCombine.restype = ctypes.c_void_p
    shell32.ILCombine.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    shell32.ILFree.restype = None
    shell32.ILFree.argtypes = [ctypes.c_void_p]
    shell32.SHGetPathFromIDListW.restype = ctypes.c_bool
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]

    cidl = int.from_bytes(data[0:4], "little")
    if cidl == 0 or len(data) < 4 + (cidl + 1) * 4:
        return []
    offsets = [int.from_bytes(data[4 + i * 4 : 8 + i * 4], "little") for i in range(cidl + 1)]
    parent_pidl_bytes = extract_itemidlist_bytes(data, offsets[0])
    if not parent_pidl_bytes:
        return []

    paths: list[str] = []
    max_path_buf = 32767
    for i in range(1, cidl + 1):
        item_pidl_bytes = extract_itemidlist_bytes(data, offsets[i])
        if not item_pidl_bytes:
            continue
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
