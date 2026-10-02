from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterable

from .release_packaging import iter_public_source_files
from .release_validation_common import ReleaseCheck

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


_PYTHON_SECRET_MARKERS = (
    "api_key", "api_token", "access_token", "bearer_token",
    "client_secret", "password", "passwd",
)
_SECRET_NAME_IGNORE_PREFIXES = ("set_key_", "default_", "secret_mode_")
_SECRET_PLACEHOLDER_MARKERS = (
    "example", "dummy", "placeholder", "changeme", "replace_me",
    "your_", "your-", "test-key", "test-token", "wrong-password",
    "very-good-password",
)


def _normalized_secret_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").casefold()).strip("_")


def _looks_like_secret_name(name: str) -> bool:
    normalized = _normalized_secret_name(name)
    if not normalized or normalized.startswith(_SECRET_NAME_IGNORE_PREFIXES):
        return False
    return any(marker in normalized for marker in _PYTHON_SECRET_MARKERS)


def _looks_like_real_secret(value: str) -> bool:
    token = str(value or "").strip()
    if len(token) < 12 or any(char.isspace() for char in token):
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
            if not _looks_like_secret_name(name) or not _looks_like_real_secret(value):
                continue
            findings.append(ReleaseCheck(
                "warn",
                "Datenschutz: mögliches Python-Secret",
                f"{path.relative_to(root)}:{line} enthält ein hart codiertes Literal für {name!r}.",
            ))
            break
    return findings



_PRIVATE_NAME_PATTERN = "".join(('\\bMark', 'us\\b|\\bMark', 'u\\b'))
_PRIVATE_WORKDIR_PATTERN = "".join(('Arbeitsordner ', 'codex'))
_PRIVATE_SERVER_PATTERN = "".join(('(?:\\\\\\\\|//)medien', 'speicher'))

_PRIVATE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("lokaler Benutzerpfad", re.compile(r"C:\\Users\\[^\\\r\n]+", re.IGNORECASE)),
    ("persönlicher Name", re.compile(_PRIVATE_NAME_PATTERN, re.IGNORECASE)),
    ("Arbeitsordner-Pfad", re.compile(_PRIVATE_WORKDIR_PATTERN, re.IGNORECASE)),
    ("Netzwerk-Medienpfad", re.compile(_PRIVATE_SERVER_PATTERN, re.IGNORECASE)),
    ("temporärer Codex-Pfad", re.compile(r"AppData\\Local\\Temp\\codex-", re.IGNORECASE)),
    ("möglicher API-Key", re.compile(r"(api[_-]?key|read[_-]?access[_-]?token)\s*[:=]\s*['\"][^'\"\s]{8,}", re.IGNORECASE)),
)


def _scan_private_markers(root: Path) -> list[ReleaseCheck]:
    findings: list[ReleaseCheck] = []
    for path in _iter_release_text_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            try:
                rel = path.relative_to(root)
            except (OSError, ValueError):
                rel = path
            findings.append(
                ReleaseCheck(
                    "warn",
                    "Datenschutz: Datei nicht lesbar",
                    f"{rel} konnte nicht geprüft werden: {exc}",
                )
            )
            continue
        for label, pattern in _PRIVATE_PATTERNS:
            match = pattern.search(text)
            if match:
                findings.append(
                    ReleaseCheck(
                        "warn",
                        f"Datenschutz: {label}",
                        f"{path.relative_to(root)} enthält '{match.group(0)[:80]}'",
                    )
                )
                break
    findings.extend(_scan_python_secrets(root))
    if not findings:
        findings.append(ReleaseCheck(
            "ok",
            "Datenschutz-/Release-Check",
            "Keine offensichtlichen privaten Marker oder hart codierten Python-Secrets im Release-Inventar gefunden.",
        ))
    return findings
