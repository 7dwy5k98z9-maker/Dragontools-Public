from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
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
    return any(part.casefold() in SKIP_DIRS for part in path.relative_to(ROOT).parts)


def scan_text(label: str, text: str, findings: list[str]) -> None:
    for description, pattern in PRIVATE_PATTERNS:
        if match := pattern.search(text):
            findings.append(f"{label}: {description} ({match.group(0)[:60]!r})")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or is_skipped(path):
            continue
        relative = path.relative_to(ROOT).as_posix()
        scan_text(f"Dateiname {relative}", relative, findings)
        if path.suffix.casefold() in TEXT_SUFFIXES:
            scan_text(relative, path.read_text(encoding="utf-8", errors="replace"), findings)
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
