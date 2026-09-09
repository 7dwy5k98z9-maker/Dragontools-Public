# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


DEFAULT_OUTPUT_OVERHEAD_FACTOR = 1.15
DEFAULT_MIN_FREE_AFTER_BYTES = 2 * 1024 ** 3


@dataclass(frozen=True)
class DiskSpaceIssue:
    level: str
    path: str
    free_bytes: int
    required_bytes: int
    reserve_bytes: int
    message: str


@dataclass(frozen=True)
class DiskSpaceCheckResult:
    issues: list[DiskSpaceIssue]

    @property
    def has_critical(self) -> bool:
        return any(issue.level == "critical" for issue in self.issues)

    @property
    def has_warning(self) -> bool:
        return any(issue.level == "warning" for issue in self.issues)


def check_conversion_disk_space(
    files: list[str],
    *,
    parallel_jobs: int,
    overwrite_original: bool,
    min_free_after_bytes: int = DEFAULT_MIN_FREE_AFTER_BYTES,
    output_overhead_factor: float = DEFAULT_OUTPUT_OVERHEAD_FACTOR,
) -> DiskSpaceCheckResult:
    """Schätzt den freien Platz für parallel laufende Konvertierungen.

    Dragon Tools schreibt Standard-Ausgaben und Overwrite-Tempdateien zunächst
    neben die Quelle. Deshalb wird pro Zielordner/Volume mit den größten
    gleichzeitig möglichen Eingabedateien gerechnet.
    """
    jobs = max(1, int(parallel_jobs or 1))
    groups: dict[str, list[int]] = {}
    probe_paths: dict[str, Path] = {}

    for raw in files or []:
        path = Path(str(raw))
        base_dir = path.parent if path.parent else Path(".")
        target_dir = base_dir / "__temp_overwrite__" if overwrite_original else base_dir
        usage_probe = _existing_probe_path(target_dir)
        key = _volume_key(usage_probe)
        try:
            size = max(0, path.stat().st_size)
        except OSError:
            size = 0
        groups.setdefault(key, []).append(size)
        probe_paths.setdefault(key, usage_probe)

    issues: list[DiskSpaceIssue] = []
    for key, sizes in groups.items():
        biggest = sorted(sizes, reverse=True)[: min(jobs, len(sizes))]
        required = int(sum(biggest) * max(1.0, float(output_overhead_factor)))
        reserve = max(0, int(min_free_after_bytes or 0))
        probe = probe_paths[key]
        try:
            free = int(shutil.disk_usage(probe).free)
        except OSError:
            continue

        if free < required:
            issues.append(DiskSpaceIssue(
                level="critical",
                path=str(probe),
                free_bytes=free,
                required_bytes=required,
                reserve_bytes=reserve,
                message=(
                    "Zu wenig freier Speicher für die gleichzeitig laufenden "
                    "temporären Ausgabedateien."
                ),
            ))
        elif free < required + reserve:
            issues.append(DiskSpaceIssue(
                level="warning",
                path=str(probe),
                free_bytes=free,
                required_bytes=required,
                reserve_bytes=reserve,
                message=(
                    "Speicherplatz ist knapp; nach den temporären Ausgabedateien "
                    "bleibt weniger Reserve als empfohlen."
                ),
            ))

    return DiskSpaceCheckResult(issues=issues)


def format_disk_space_issues(result: DiskSpaceCheckResult) -> str:
    lines = ["Speicherplatzprüfung vor dem Start:"]
    for issue in result.issues:
        icon = "❌" if issue.level == "critical" else "⚠️"
        lines.append(f"{icon} {issue.path}")
        lines.append(f"   Frei: {_format_bytes(issue.free_bytes)}")
        lines.append(f"   Geschätzt benötigt: {_format_bytes(issue.required_bytes)}")
        lines.append(f"   Empfohlene Reserve: {_format_bytes(issue.reserve_bytes)}")
        lines.append(f"   Hinweis: {issue.message}")
    return "\n".join(lines)


def _existing_probe_path(path: Path) -> Path:
    current = path
    while current and not current.exists():
        parent = current.parent
        if parent == current:
            break
        current = parent
    return current if current.exists() else Path.cwd()


def _volume_key(path: Path) -> str:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    anchor = resolved.anchor
    if anchor:
        return anchor.lower()
    return str(resolved)


def _format_bytes(value: int) -> str:
    amount = float(max(0, int(value or 0)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.2f} {unit}"
        amount /= 1024.0
