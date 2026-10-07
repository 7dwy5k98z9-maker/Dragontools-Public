from __future__ import annotations

import ast
import os
import re
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dragontools.core.release_validation_privacy import _python_secret_candidates, _looks_like_secret_name, _looks_like_real_secret
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
}
TEXT_SUFFIXES = {
    ".bat",
    ".cfg",
    ".css",
    ".html",
    ".ini",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".spec",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

PRIVATE_PATTERNS = (
    ("privater Vorname", re.compile(r"\bMark(?:us|u)\b", re.IGNORECASE)),
    ("privater Nachname", re.compile("Tsch" + "erner", re.IGNORECASE)),
    ("alter Herstellername", re.compile("Mark" + "usTools", re.IGNORECASE)),
    ("privater Medienserver", re.compile("medien" + "speicher", re.IGNORECASE)),
    ("privater Arbeitsordner", re.compile("Arbeitsordner " + "codex", re.IGNORECASE)),
    ("lokaler Entwicklerpfad", re.compile(r"C:\\Users\\Mark(?:u|us)\b", re.IGNORECASE)),
    (
        "möglicher Zugangsschlüssel",
        re.compile(
            r"(api[_-]?key|read[_-]?access[_-]?token|password|secret)\s*[:=]\s*['\"][^'\"\s]{8,}",
            re.IGNORECASE,
        ),
    ),
)


def is_skipped(path: Path) -> bool:
    return any(part.casefold() in SKIP_DIRS or part.casefold().startswith(".pytest_tmp") for part in path.relative_to(ROOT).parts)


def scan_text(label: str, text: str, findings: list[str], *, python_source: bool = False) -> None:
    for description, pattern in PRIVATE_PATTERNS:
        if python_source and description == "möglicher Zugangsschlüssel":
            continue
        if match := pattern.search(text):
            if description == "möglicher Zugangsschlüssel" and _is_allowed_placeholder(match.group(0)):
                continue
            findings.append(f"{label}: {description} ({match.group(0)[:60]!r})")


def _is_allowed_placeholder(match_text: str) -> bool:
    lowered = str(match_text or "").casefold()
    return any(
        marker in lowered
        for marker in (
            "metadata/tmdb/api_key",
            "tmdb-api-secret",
            "tmdb-key",
            "dummy",
            "placeholder",
            "example",
        )
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    findings: list[str] = []
    paths = []
    for directory, names, files in os.walk(ROOT):
        names[:] = [name for name in names if name.casefold() not in SKIP_DIRS and not name.casefold().startswith(".pytest_tmp") and name.casefold() != "artifacts"]
        paths.extend(Path(directory) / name for name in files)
    for path in paths:
        if not path.is_file() or is_skipped(path):
            continue
        relative = path.relative_to(ROOT).as_posix()
        scan_text(f"Dateiname {relative}", relative, findings)
        if path.suffix.casefold() in TEXT_SUFFIXES:
            source = path.read_text(encoding="utf-8", errors="replace")
            python_source = path.suffix.casefold() == ".py"
            scan_text(relative, source, findings, python_source=python_source)
            if python_source:
                try:
                    tree = ast.parse(source, filename=relative)
                except SyntaxError:
                    findings.append(f"{relative}: Python-Syntax nicht prüfbar")
                else:
                    for name, value, line in _python_secret_candidates(tree):
                        if _looks_like_secret_name(name) and _looks_like_real_secret(value, name):
                            findings.append(f"{relative}:{line}: mögliches Python-Secret für {name!r}; Wert maskiert")
        elif path.suffix.casefold() == ".docx":
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if name.endswith((".xml", ".rels")):
                        text = archive.read(name).decode("utf-8", errors="replace")
                        scan_text(f"{relative}:{name}", text, findings)
        elif path.suffix.casefold() == ".pdf":
            scan_text(relative, path.read_bytes().decode("latin-1", errors="ignore"), findings)

    if findings:
        print("Öffentliche Datenschutzprüfung fehlgeschlagen:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print("Öffentliche Datenschutzprüfung bestanden: keine privaten Marker gefunden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
