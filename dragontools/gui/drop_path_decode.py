from __future__ import annotations

import os
import re
from urllib.parse import unquote, urlparse

WINDOWS_PATH_RE = re.compile(
    r"(\\\\\?\\UNC\\[^\x00\r\n]+|\\\\\?\\[A-Za-z]:\\[^\x00\r\n]+|\\\\[^\x00\r\n]+|[A-Za-z]:\\[^\x00\r\n]+)"
)


def reconstruct_local_path_from_url_string(raw_url: str) -> str:
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


def extract_candidate_paths_from_text(text: str) -> list[str]:
    candidates: list[str] = []
    for part in text.replace("\x00", "\n").splitlines():
        part = part.strip().strip('"')
        if not part:
            continue
        for match in WINDOWS_PATH_RE.findall(part):
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


def decode_windows_filename_payload(data: bytes, *, utf16: bool) -> list[str]:
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
        paths.extend(extract_candidate_paths_from_text(decoded))
    return paths
