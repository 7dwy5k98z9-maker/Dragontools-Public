"""Reproducible SHA-256 inventory for private DragonTools source snapshots."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

MANIFEST_NAME = "SNAPSHOT_CONTENTS.json"
EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".agents",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "build",
        "dist",
        "dist-smoke",
        "third_party",
        "comfyui_windows_portable",
        "hdrtvdm",
        "projekt",
        "git release",
    }
)
EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo", ".spec", ".zip", ".sha256"})


def _excluded(relative: Path) -> bool:
    if relative.as_posix() == MANIFEST_NAME:
        return True
    parts = [part.casefold() for part in relative.parts]
    if any(part in EXCLUDED_DIR_NAMES or part.startswith(".pytest_tmp") for part in parts[:-1]):
        return True
    return relative.suffix.casefold() in EXCLUDED_SUFFIXES


def iter_snapshot_files(root: str | Path) -> list[Path]:
    base = Path(root).resolve()
    files = [
        path
        for path in base.rglob("*")
        if path.is_file() and not _excluded(path.relative_to(base))
    ]
    return sorted(files, key=lambda path: path.relative_to(base).as_posix().casefold())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_snapshot_manifest(root: str | Path, *, kind: str = "private-uncommitted-working-tree") -> dict:
    base = Path(root).resolve()
    hashes = {
        path.relative_to(base).as_posix(): sha256_file(path)
        for path in iter_snapshot_files(base)
    }
    return {
        "kind": kind,
        "created": datetime.now().astimezone().isoformat(),
        "files_sha256": hashes,
        "excluded_paths": [
            MANIFEST_NAME,
            ".git/", ".agents/", ".venv/", "venv/", "__pycache__/",
            ".pytest_cache/", ".mypy_cache/", ".ruff_cache/", ".pytest_tmp*/",
            "build/", "dist/", "dist-smoke/", "third_party/",
            "ComfyUI_windows_portable/", "HDRTVDM/", "Projekt/", "git release/",
            "*.pyc", "*.pyo", "*.spec", "*.zip", "*.sha256",
        ],
    }


def write_snapshot_manifest(root: str | Path) -> Path:
    base = Path(root).resolve()
    target = base / MANIFEST_NAME
    payload = build_snapshot_manifest(base)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def verify_snapshot_manifest(root: str | Path) -> list[str]:
    base = Path(root).resolve()
    target = base / MANIFEST_NAME
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Manifest unlesbar: {exc}"]

    expected = payload.get("files_sha256")
    if not isinstance(expected, dict):
        return ["files_sha256 fehlt oder ist kein Objekt"]

    actual_paths = {path.relative_to(base).as_posix(): path for path in iter_snapshot_files(base)}
    issues: list[str] = []
    expected_names = set(expected)
    actual_names = set(actual_paths)
    for name in sorted(expected_names - actual_names):
        issues.append(f"Manifest-Datei fehlt: {name}")
    for name in sorted(actual_names - expected_names):
        issues.append(f"Aktuelle Datei fehlt im Manifest: {name}")
    for name in sorted(expected_names & actual_names):
        actual_hash = sha256_file(actual_paths[name])
        if actual_hash != expected[name]:
            issues.append(f"SHA-256 abweichend: {name}")
    return issues


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        problems = verify_snapshot_manifest(args.root)
        if problems:
            print("\n".join(problems))
            raise SystemExit(1)
        print("Snapshot-Manifest: OK")
    else:
        print(write_snapshot_manifest(args.root))
