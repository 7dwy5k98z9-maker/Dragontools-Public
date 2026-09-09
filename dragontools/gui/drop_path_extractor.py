# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
from urllib.parse import unquote, urlparse

from ..core.paths import (
    display_name,
    is_video_file,
    normalize_user_path,
    strip_long_path_prefix,
    to_long_path,
)

_WINDOWS_PATH_RE = re.compile(
    r"(\\\\\?\\UNC\\[^\x00\r\n]+|\\\\\?\\[A-Za-z]:\\[^\x00\r\n]+|\\\\[^\x00\r\n]+|[A-Za-z]:\\[^\x00\r\n]+)"
)
DND_DEBUG = False
_WARNED_DROP_MESSAGES: set[tuple[int, str]] = set()


def _log_drop_message(log_fn, message: str) -> None:
    if callable(log_fn):
        log_fn(message, "warn")


def _warn_non_video_file(log_fn, path: str) -> None:
    visible = display_name(path)
    _log_drop_message(log_fn, f"Keine Videodatei: {visible}")


def _iter_video_files_in_folder(folder_path: str) -> tuple[list[str], int]:
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


def _mime_has_file_payload(mime) -> bool:
    if mime.hasUrls():
        return True
    if mime.hasText():
        return True
    formats = list(mime.formats() or [])
    if any("FileNameW" in fmt or "FileName" in fmt for fmt in formats):
        return True
    # Windows: Shell IDList Array wird für sehr lange Pfade (>~260 Zeichen) gesendet,
    # wenn Qt weder URLs noch FileNameW liefern kann.
    if os.name == "nt" and any("Shell IDList Array" in fmt for fmt in formats):
        return True
    return False


def _debug_mime_data(log_fn, method_name: str, mime) -> None:
    if not DND_DEBUG:
        return
    urls = mime.urls()
    formats = list(mime.formats() or [])
    _log_drop_message(
        log_fn,
        f"{method_name}: hasUrls={mime.hasUrls()} hasText={mime.hasText()} "
        f"formats={formats} url_count={len(urls)}",
    )
    for idx, url in enumerate(urls):
        _log_drop_message(log_fn, f"{method_name}: url[{idx}].toString()={url.toString()}")
        _log_drop_message(log_fn, f"{method_name}: url[{idx}].toLocalFile()={url.toLocalFile()}")
    if mime.hasText():
        text = mime.text()
        if text:
            _log_drop_message(log_fn, f"{method_name}: mime.text()={text}")
    for fmt in formats:
        if 'value="FileNameW"' in fmt or 'value="FileName"' in fmt:
            raw = bytes(mime.data(fmt))
            _log_drop_message(
                log_fn,
                f"{method_name}: {fmt} raw_len={len(raw)} head128={raw[:128].hex()}",
            )


def _resolve_drop_logger(widget) -> object:
    for obj in (widget, widget.parent(), widget.window()):
        if obj is None:
            continue
        log_fn = getattr(obj, "_log", None)
        if callable(log_fn):
            return log_fn
        owner = getattr(obj, "owner", None)
        log_fn = getattr(owner, "_log", None) if owner is not None else None
        if callable(log_fn):
            return log_fn
    return None


def _reconstruct_local_path_from_url(url) -> str:
    raw_url = url.toString()
    return _reconstruct_local_path_from_url_string(raw_url)


def _reconstruct_local_path_from_url_string(raw_url: str) -> str:
    if not raw_url:
        return ""
    parsed = urlparse(raw_url)
    if parsed.scheme.lower() != "file":
        return ""

    path = unquote(parsed.path or "")
    if os.name == "nt":
        if parsed.netloc:
            win_path = path.replace("/", "\\")
            return "\\\\" + parsed.netloc + win_path
        path = path.replace("/", "\\")
        if len(path) >= 3 and path[0] == "\\" and path[2] == ":":
            path = path[1:]
        return path
    return unquote((parsed.netloc or "") + path)


def _extract_dropped_local_path(url, log_fn=None) -> str:
    local = url.toLocalFile()
    if local:
        return normalize_user_path(local)

    raw_url = url.toString()
    if DND_DEBUG and raw_url:
        _log_drop_message(log_fn, f"Drag&Drop-URL ohne lokalen Pfad: {raw_url}")

    reconstructed = _reconstruct_local_path_from_url(url)
    if reconstructed:
        return normalize_user_path(reconstructed)
    return ""


def _extract_candidate_paths_from_text(text: str) -> list[str]:
    candidates: list[str] = []
    for part in text.replace("\x00", "\n").splitlines():
        part = part.strip().strip('"')
        if not part:
            continue
        for match in _WINDOWS_PATH_RE.findall(part):
            candidate = match.strip().strip('"')
            if candidate:
                candidates.append(candidate)
        if not candidates and (
            part.startswith("\\\\")
            or part.startswith("\\\\?\\")
            or re.match(r"^[A-Za-z]:\\", part)
        ):
            candidates.append(part)
    return candidates


def _decode_windows_filename_payload(data: bytes, *, utf16: bool) -> list[str]:
    decoded_variants: list[str] = []
    try:
        decoded = data.decode("utf-16-le", errors="ignore") if utf16 else data.decode(errors="ignore")
        decoded_variants.append(decoded.replace("\x00", "\n"))
    except Exception:
        pass
    if utf16:
        try:
            decoded_variants.append(data.decode(errors="ignore").replace("\x00", "\n"))
        except Exception:
            pass

    paths: list[str] = []
    for decoded in decoded_variants:
        for candidate in _extract_candidate_paths_from_text(decoded):
            if candidate:
                paths.append(candidate)
    return paths


def _extract_paths_from_mime_data(mime, log_fn=None) -> list[str]:
    paths: list[str] = []

    urls = list(mime.urls())
    if urls:
        for url in urls:
            path = _extract_dropped_local_path(url, log_fn=log_fn)
            if path:
                paths.append(path)
    elif mime.hasUrls():
        if DND_DEBUG:
            _log_drop_message(
                log_fn,
                "Drag&Drop: hasUrls=True, aber url_count=0; fallback auf FileNameW/FileName",
            )

    if paths:
        return paths

    formats = list(mime.formats() or [])
    preferred_formats = [fmt for fmt in formats if 'value="FileNameW"' in fmt]
    fallback_formats = [fmt for fmt in formats if 'value="FileName"' in fmt]
    for fmt in preferred_formats + fallback_formats:
        raw = bytes(mime.data(fmt))
        if DND_DEBUG:
            _log_drop_message(log_fn, f"Drag&Drop: prüfe {fmt} raw_len={len(raw)} head128={raw[:128].hex()}")
        decoded = _decode_windows_filename_payload(raw, utf16=("FileNameW" in fmt))
        for entry in decoded:
            candidate = entry.strip().strip('"')
            if not candidate:
                continue
            normalized = normalize_user_path(candidate)
            long_path = to_long_path(normalized)
            if os.path.isfile(long_path) or os.path.isdir(long_path):
                paths.append(normalized)
            else:
                if DND_DEBUG:
                    visible = strip_long_path_prefix(normalized)
                    _log_drop_message(
                        log_fn,
                        f"Drag&Drop: Kandidat aus {fmt} existiert nicht (Länge {len(visible)}): {visible}",
                    )
        if paths:
            return paths

    raw_text = mime.text().strip() if mime.hasText() else ""
    if raw_text:
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        for line in lines or [raw_text]:
            candidates = _extract_candidate_paths_from_text(line)
            if not candidates and line.lower().startswith("file:"):
                reconstructed = _reconstruct_local_path_from_url_string(line)
                if reconstructed:
                    candidates = [reconstructed]
            if not candidates:
                candidates = [line]
            for candidate in candidates:
                normalized = normalize_user_path(candidate)
                long_path = to_long_path(normalized)
                if normalized and (os.path.isfile(long_path) or os.path.isdir(long_path)):
                    paths.append(normalized)
                else:
                    if DND_DEBUG:
                        visible = strip_long_path_prefix(normalized or candidate)
                        _log_drop_message(
                            log_fn,
                            f"Drag&Drop: Text-Kandidat existiert nicht (Länge {len(visible)}): {visible}",
                        )

    # Letzte Fallback-Option: Shell IDList Array (Windows, Pfade > ~260 Zeichen).
    # Windows Explorer sendet dieses PIDL-Format, wenn der Pfad zu lang für FileNameW/URL ist.
    if not paths:
        paths = _extract_paths_from_shell_idlist(mime, log_fn=log_fn)

    return paths


def _extract_itemidlist_bytes(data: bytes, offset: int) -> bytes:
    """
    Liest eine vollständige ITEMIDLIST (PIDL) aus dem Byte-Array.
    Eine ITEMIDLIST besteht aus SHITEMID-Einträgen {cb (2 Bytes), abID[cb-2]},
    abgeschlossen durch einen 2-Byte-Nullterminator.
    """
    result = bytearray()
    pos = offset
    while pos + 2 <= len(data):
        cb = int.from_bytes(data[pos : pos + 2], "little")
        if cb == 0:
            result.extend(b"\x00\x00")  # Null-Terminator mitschreiben
            break
        if pos + cb > len(data):
            break
        result.extend(data[pos : pos + cb])
        pos += cb
    return bytes(result)


def _resolve_shell_idlist_to_paths(data: bytes, log_fn=None) -> list[str]:
    """
    Parst eine CIDA-Struktur (Shell IDList Array) und loest die enthaltenen
    PIDLs über die Windows Shell API zu Dateipfaden auf.

    CIDA-Aufbau:
        UINT  cidl          – Anzahl Items (ohne Parent)
        UINT  aoffset[0]    – Offset zum Parent-Ordner-PIDL
        UINT  aoffset[1..n] – Offsets zu den Item-PIDLs
    """
    import ctypes

    shell32 = ctypes.windll.shell32

    # KRITISCH: restype muss c_void_p sein, sonst wird der 64-bit-Pointer
    # auf Windows x64 auf 32 bit abgeschnitten → Absturz oder Garbage-Adresse.
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

    parent_pidl_bytes = _extract_itemidlist_bytes(data, offsets[0])
    if not parent_pidl_bytes:
        return []

    paths: list[str] = []
    MAX_PATH_BUF = 32767  # Windows UNICODE_STRING Limit

    for i in range(1, cidl + 1):
        item_pidl_bytes = _extract_itemidlist_bytes(data, offsets[i])
        if not item_pidl_bytes:
            continue

        # Puffer für ILCombine anlegen (kopiert intern, kein Shell-Heap nötig)
        parent_buf = ctypes.create_string_buffer(parent_pidl_bytes)
        item_buf = ctypes.create_string_buffer(item_pidl_bytes)

        combined = shell32.ILCombine(parent_buf, item_buf)
        if not combined:
            if DND_DEBUG:
                _log_drop_message(log_fn, f"Drag&Drop: ILCombine returned NULL für Item {i}")
            continue

        try:
            path_buf = ctypes.create_unicode_buffer(MAX_PATH_BUF)

            # SHGetPathFromIDListEx (Vista+) unterstützt große Puffer;
            # ebenfalls restype setzen um 64-bit-Pointer-Truncation zu vermeiden.
            ok = False
            try:
                shell32.SHGetPathFromIDListEx.restype = ctypes.c_bool
                shell32.SHGetPathFromIDListEx.argtypes = [
                    ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint
                ]
                ok = bool(shell32.SHGetPathFromIDListEx(combined, path_buf, MAX_PATH_BUF, 0))
            except (AttributeError, OSError):
                pass

            # Fallback auf SHGetPathFromIDListW für ältere Windows-Versionen
            if not ok:
                ok = bool(shell32.SHGetPathFromIDListW(combined, path_buf))

            if ok and path_buf.value:
                normalized = normalize_user_path(path_buf.value)
                if normalized:
                    if DND_DEBUG:
                        _log_drop_message(log_fn, f"Drag&Drop: Shell IDList → {normalized}")
                    paths.append(normalized)
            else:
                if DND_DEBUG:
                    _log_drop_message(log_fn, f"Drag&Drop: Shell IDList Item {i} – SHGetPath schlug fehl")
        finally:
            shell32.ILFree(combined)

    return paths


def _extract_paths_from_shell_idlist(mime, log_fn=None) -> list[str]:
    """
    Windows-only: Liest Shell IDList Array aus den MIME-Daten und loest
    die enthaltenen PIDLs zu Dateipfaden auf.

    Windows Explorer sendet dieses Format anstelle von FileNameW/URLs,
    wenn Dateinamen oder Pfade zu lang sind (typischerweise > ~260 Zeichen
    oder bei langen Ordnernamen).
    """
    if os.name != "nt":
        return []

    shell_idlist_fmt = None
    for fmt in mime.formats() or []:
        if "Shell IDList Array" in fmt:
            shell_idlist_fmt = fmt
            break

    if shell_idlist_fmt is None:
        return []

    raw = bytes(mime.data(shell_idlist_fmt))
    if DND_DEBUG:
        _log_drop_message(
            log_fn,
            f"Drag&Drop: Shell IDList Array gefunden – len={len(raw)} head={raw[:32].hex()}",
        )

    if len(raw) < 8:
        return []

    try:
        return _resolve_shell_idlist_to_paths(raw, log_fn=log_fn)
    except Exception as exc:
        if DND_DEBUG:
            _log_drop_message(log_fn, f"Drag&Drop: Shell IDList Array Fehler: {exc}")
        return []


def _warn_drop_once(log_fn, mime, key: str, message: str) -> None:
    marker = (id(mime), key)
    if marker in _WARNED_DROP_MESSAGES:
        return
    _WARNED_DROP_MESSAGES.add(marker)
    _log_drop_message(log_fn, message)


def _log_drop_rejection(log_fn, mime, visible: str) -> None:
    if _is_long_path_dragdrop_failure(mime):
        _warn_drop_once(
            log_fn,
            mime,
            "long_path",
            "Dateiname oder Pfad ist zu lang für Drag & Drop. "
            "Bitte Datei über den '+ Dateien'-Button hinzufügen.",
        )
        return
    _warn_drop_once(
        log_fn,
        mime,
        "generic",
        "Drag & Drop konnte keine verwertbare Datei übernehmen.",
    )
    if DND_DEBUG and visible:
        _log_drop_message(
            log_fn,
            f"Drag&Drop-Pfad konnte nicht übernommen werden (Länge {len(visible)}): {visible}",
        )


def _is_long_path_dragdrop_failure(mime) -> bool:
    if not mime.hasUrls():
        return False
    if len(list(mime.urls())) != 0:
        return False

    # Wenn Shell IDList Array vorhanden ist, können wir es jetzt selbst auflösen –
    # also kein echter Fehler mehr.
    if os.name == "nt" and any("Shell IDList Array" in fmt for fmt in (mime.formats() or [])):
        return False

    found_filename_payload = False
    for fmt in mime.formats() or []:
        if 'value="FileNameW"' in fmt or 'value="FileName"' in fmt:
            found_filename_payload = True
            raw = bytes(mime.data(fmt))
            if len(raw) != 0:
                return False
    return found_filename_payload


def _log_long_path_dragdrop_warning(log_fn, mime) -> None:
    if not _is_long_path_dragdrop_failure(mime):
        return
    _warn_drop_once(
        log_fn,
        mime,
        "long_path",
        "Dateiname oder Pfad ist zu lang für Drag & Drop. "
        "Bitte Datei über den '+ Dateien'-Button hinzufügen.",
    )
