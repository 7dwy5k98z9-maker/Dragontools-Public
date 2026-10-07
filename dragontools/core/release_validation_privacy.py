from __future__ import annotations

import ast
import html
import io
import re
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .release_packaging import iter_public_source_files
from .release_validation_common import ReleaseCheck
from .release_private_paths import USER_PATH_PATTERN
from .release_document_privacy import docx_searchable_text, pdf_hidden_text

def _iter_release_text_files(root: Path) -> Iterable[Path]:
    """Iterate non-Python text artifacts from the canonical public inventory.

    Python source is inspected separately with AST-aware rules so the privacy
    scanner can catch embedded credentials without flagging setting-key
    constants or its own test/regex fixtures.
    """
    text_suffixes = frozenset({
        ".bat", ".cfg", ".html", ".ini", ".json", ".md", ".toml",
        ".txt", ".xml", ".yaml", ".yml",
    })
    for path in iter_public_source_files(root):
        if path.suffix.casefold() in text_suffixes:
            yield path


def _iter_release_python_files(root: Path) -> Iterable[Path]:
    for path in iter_public_source_files(root):
        if path.suffix.casefold() == ".py":
            yield path


def _iter_release_docx_files(root: Path) -> Iterable[Path]:
    for path in iter_public_source_files(root):
        if path.suffix.casefold() == ".docx":
            yield path


def _iter_release_pdf_files(root: Path) -> Iterable[Path]:
    for path in iter_public_source_files(root):
        if path.suffix.casefold() == ".pdf":
            yield path


_PYTHON_SECRET_MARKERS = (
    "api_key", "api_token", "access_token", "bearer_token",
    "client_secret", "password", "passwd",
)
_SECRET_NAME_IGNORE_PREFIXES = ("set_key_", "secret_mode_")
_SECRET_PLACEHOLDER_MARKERS = (
    "example", "dummy", "placeholder", "changeme", "replace_me",
    "your_", "your-", "test-key", "test-token", "wrong-password",
    "very-good-password", "strong-password", "old-manual-token",
    "plain-cli-secret", "plain-extra-secret",
)


def _normalized_secret_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").casefold()).strip("_")


def _looks_like_secret_name(name: str) -> bool:
    normalized = _normalized_secret_name(name)
    if not normalized or normalized.startswith(_SECRET_NAME_IGNORE_PREFIXES):
        return False
    return any(marker in normalized for marker in _PYTHON_SECRET_MARKERS)


def _looks_like_real_secret(value: str, name: str = "") -> bool:
    token = str(value or "").strip()
    password = _normalized_secret_name(name).split('_')[-1] in {'password', 'passwd'}
    if len(token) < (8 if password else 12) or any(char.isspace() for char in token):
        return False
    folded = token.casefold()
    if any(marker in folded for marker in _SECRET_PLACEHOLDER_MARKERS):
        return False
    if folded in {"api_key", "api-token", "access_token", "bearer_token", "password"}:
        return False
    # Slash-only symbolic setting paths such as metadata/tmdb/api_key are not secrets.
    if "/" in token and not any(char.isdigit() for char in token):
        return False
    return True


def _constant_string(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [target.attr]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for item in target.elts:
            names.extend(_target_names(item))
        return names
    return []


def _python_secret_candidates(tree: ast.AST) -> Iterable[tuple[str, str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = _constant_string(node.value)
            if value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in _target_names(target):
                    yield name, value, getattr(node, "lineno", 0)
        elif isinstance(node, ast.Dict):
            for key_node, value_node in zip(node.keys, node.values):
                key = _constant_string(key_node)
                value = _constant_string(value_node)
                if key is not None and value is not None:
                    yield key, value, getattr(value_node, "lineno", getattr(node, "lineno", 0))
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                value = _constant_string(keyword.value)
                if keyword.arg and value is not None:
                    yield keyword.arg, value, getattr(keyword.value, "lineno", getattr(node, "lineno", 0))


def _scan_python_secrets(root: Path) -> list[ReleaseCheck]:
    findings: list[ReleaseCheck] = []
    for path in _iter_release_python_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        for name, value, line in _python_secret_candidates(tree):
            if not _looks_like_secret_name(name) or not _looks_like_real_secret(value, name):
                continue
            findings.append(ReleaseCheck(
                "error",
                "Datenschutz: mögliches Python-Secret",
                f"{path.relative_to(root)}:{line} enthält ein hart codiertes Literal für {name!r}.",
            ))
            break
    return findings



_PRIVATE_NAME_PATTERN = r"\bMark" + r"us\b|\bMark" + r"u\b"
_PRIVATE_WORKDIR_PATTERN = "Arbeitsordner " + "codex"
_PRIVATE_SERVER_PATTERN = r"(?:\\\\|//)medien" + "speicher"

_PRIVATE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("lokaler Benutzerpfad", USER_PATH_PATTERN),
    ("persönlicher Name", re.compile(_PRIVATE_NAME_PATTERN, re.IGNORECASE)),
    ("Arbeitsordner-Pfad", re.compile(_PRIVATE_WORKDIR_PATTERN, re.IGNORECASE)),
    ("Netzwerk-Medienpfad", re.compile(_PRIVATE_SERVER_PATTERN, re.IGNORECASE)),
    ("temporärer Codex-Pfad", re.compile(r"AppData\\Local\\Temp\\codex-", re.IGNORECASE)),
    ("mögliches Secret", re.compile(
        r"(api[_-]?key|api[_-]?token|read[_-]?access[_-]?token|access[_-]?token|bearer[_-]?token|client[_-]?secret|password|passwd)"
        r"\s*[:=]\s*['\"][^'\"\s]{8,}",
        re.IGNORECASE,
    )),
)


def _docx_searchable_text(path: Path) -> str:
    return docx_searchable_text(path)


def _document_private_findings(text: str, relative: Path, kind: str) -> list[ReleaseCheck]:
    findings = []
    for label, pattern in _PRIVATE_PATTERNS:
        if label != "mögliches Secret" and pattern.search(text):
            findings.append(ReleaseCheck("error", f"Datenschutz {kind}: {label}",
                f"{relative} enthält einen privaten Marker."))
    for match in _TEXT_SECRET_PATTERN.finditer(text):
        if _looks_like_real_secret(match[2], match[1]):
            findings.append(ReleaseCheck("error", f"Datenschutz {kind}: mögliches Secret",
                f"{relative} enthält ein mögliches Secret für {match[1]!r}; Wert maskiert."))
    return findings


def _scan_docx_private_markers(root: Path) -> list[ReleaseCheck]:
    findings: list[ReleaseCheck] = []
    for path in _iter_release_docx_files(root):
        try:
            text = _docx_searchable_text(path)
        except Exception as exc:
            findings.append(ReleaseCheck(
                "error",
                "Datenschutz: DOCX nicht prüfbar",
                f"{path.relative_to(root)} konnte nicht vollständig geprüft werden: {exc}",
            ))
            continue
        findings.extend(_document_private_findings(text, path.relative_to(root), "DOCX"))
    return findings


@lru_cache(maxsize=8)
def _pdf_searchable_text_cached(pdf_bytes: bytes) -> str:
    # Cache by the actual artifact bytes: copied/extracted release trees reuse the
    # same validation result, while any content change necessarily invalidates it.
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
    chunks: list[str] = []
    metadata = reader.metadata
    if metadata:
        chunks.extend(str(value) for value in metadata.values() if value is not None)
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
    chunks.append(pdf_hidden_text(reader))
    return "\n".join(chunks)


def _scan_pdf_private_markers(root: Path) -> list[ReleaseCheck]:
    pdfs = list(_iter_release_pdf_files(root))
    if not pdfs:
        return []
    try:
        import pypdf  # noqa: F401 - dependency gate for fail-closed PDF scanning
    except ImportError:
        return [ReleaseCheck(
            "error",
            "Datenschutz: PDF-Prüfung nicht verfügbar",
            "pypdf fehlt; öffentliche PDF-Artefakte können nicht auf private Marker geprüft werden. "
            "Installiere requirements-build.txt bzw. requirements-test.txt.",
        )]

    findings: list[ReleaseCheck] = []
    for path in pdfs:
        rel = path.relative_to(root)
        try:
            text = _pdf_searchable_text_cached(path.read_bytes())
        except Exception as exc:
            findings.append(ReleaseCheck(
                "error",
                "Datenschutz: PDF nicht prüfbar",
                f"{rel} konnte nicht vollständig geprüft werden: {exc}",
            ))
            continue
        findings.extend(_document_private_findings(text, rel, "PDF"))
    return findings


_TEXT_SECRET_PATTERN = re.compile(
    r"(?<![\w])['\"]?([a-z0-9_.-]*(?:api[_-]?key|api[_-]?token|read[_-]?access[_-]?token|access[_-]?token|bearer[_-]?token|client[_-]?secret|password|passwd)[a-z0-9_.-]*)['\"]?"
    r"\s*[:=]\s*['\"]?([^'\"\s,;}\]]{8,})", re.IGNORECASE)


def _scan_private_markers(root: Path, *, check_pdf_privacy: bool = True) -> list[ReleaseCheck]:
    try:
        return _scan_private_markers_unchecked(root, check_pdf_privacy=check_pdf_privacy)
    except (OSError, RuntimeError) as exc:
        return [ReleaseCheck('error', 'Datenschutz: Inventar nicht prüfbar', str(exc))]


def _scan_private_markers_unchecked(root: Path, *, check_pdf_privacy: bool = True) -> list[ReleaseCheck]:
    findings: list[ReleaseCheck] = []
    for path in _iter_release_text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            findings.append(ReleaseCheck("warn", "Datenschutz: Datei nicht lesbar",
                f"{path.relative_to(root)} konnte nicht geprüft werden: {exc}"))
            continue
        for label, pattern in _PRIVATE_PATTERNS:
            if label == "mögliches Secret":
                continue
            if pattern.search(text):
                findings.append(ReleaseCheck("warn", f"Datenschutz: {label}",
                    f"{path.relative_to(root)} enthält einen privaten Marker."))
        for match in _TEXT_SECRET_PATTERN.finditer(text):
            if _looks_like_real_secret(match[2], match[1]):
                findings.append(ReleaseCheck("error", "Datenschutz: mögliches Secret",
                    f"{path.relative_to(root)} enthält ein mögliches Secret für {match[1]!r}; Wert maskiert."))
    findings.extend(_scan_docx_private_markers(root))
    if check_pdf_privacy:
        findings.extend(_scan_pdf_private_markers(root))
    else:
        findings.append(ReleaseCheck(
            "ok", "Datenschutz: PDF-Prüfung ausgelassen",
            "Privater Build: PDF-Inhalte werden nicht auf private Marker geprüft; die übrigen Prüfungen bleiben aktiv.",
        ))
    findings.extend(_scan_python_secrets(root))
    if not findings:
        findings.append(ReleaseCheck(
            "ok",
            "Datenschutz-/Release-Check",
            "Keine offensichtlichen privaten Marker oder hart codierten Python-Secrets im Release-Inventar gefunden.",
        ))
    return findings
