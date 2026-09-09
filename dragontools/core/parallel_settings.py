# -*- coding: utf-8 -*-
from __future__ import annotations

from .type_utils import _safe_int
from .settings import (
    DEFAULT_PARALLEL_CPU_JOBS,
    DEFAULT_PARALLEL_GPU_JOBS,
    MAX_PARALLEL_JOBS,
    SET_KEY_PARALLEL_DEFAULTS_MIGRATED,
    SET_KEY_PARALLEL_CPU_JOBS,
    SET_KEY_PARALLEL_GPU_JOBS,
)


GPU_ENCODERS = {"nvenc", "qsv", "amf"}
_OLD_DEFAULT_PARALLEL_CPU_JOBS = 2
_OLD_DEFAULT_PARALLEL_GPU_JOBS = 4


def clamp_parallel_jobs(value, default: int) -> int:
    number = _safe_int(value, int(default))
    return max(1, min(MAX_PARALLEL_JOBS, int(default) if number is None else number))


def is_gpu_encoder(encoder: str) -> bool:
    return str(encoder or "").strip().lower() in GPU_ENCODERS


def _contains(settings, key: str) -> bool:
    contains = getattr(settings, "contains", None)
    if not callable(contains):
        return False
    try:
        return bool(contains(key))
    except Exception:
        return False


def _value_as_int(settings, key: str, default: int) -> int:
    try:
        value = settings.value(key, default)
    except Exception:
        value = default
    number = _safe_int(value, default)
    return default if number is None else number


def migrate_parallel_defaults(settings) -> None:
    """Migriert alte konservative Parallel-Defaults einmalig auf CPU 1 / GPU 2."""
    set_value = getattr(settings, "setValue", None)
    if not callable(set_value) or _contains(settings, SET_KEY_PARALLEL_DEFAULTS_MIGRATED):
        return

    cpu_present = _contains(settings, SET_KEY_PARALLEL_CPU_JOBS)
    gpu_present = _contains(settings, SET_KEY_PARALLEL_GPU_JOBS)
    cpu_value = _value_as_int(settings, SET_KEY_PARALLEL_CPU_JOBS, _OLD_DEFAULT_PARALLEL_CPU_JOBS)
    gpu_value = _value_as_int(settings, SET_KEY_PARALLEL_GPU_JOBS, _OLD_DEFAULT_PARALLEL_GPU_JOBS)

    if not cpu_present or cpu_value == _OLD_DEFAULT_PARALLEL_CPU_JOBS:
        set_value(SET_KEY_PARALLEL_CPU_JOBS, DEFAULT_PARALLEL_CPU_JOBS)
    if not gpu_present or gpu_value == _OLD_DEFAULT_PARALLEL_GPU_JOBS:
        set_value(SET_KEY_PARALLEL_GPU_JOBS, DEFAULT_PARALLEL_GPU_JOBS)
    set_value(SET_KEY_PARALLEL_DEFAULTS_MIGRATED, True)


def parallel_jobs_for_encoder(settings, encoder: str, *, file_count: int | None = None) -> int:
    """Liest die Parallelitätsgrenze passend zum gewählten Encoder."""
    migrate_parallel_defaults(settings)
    if is_gpu_encoder(encoder):
        key = SET_KEY_PARALLEL_GPU_JOBS
        default = DEFAULT_PARALLEL_GPU_JOBS
    else:
        key = SET_KEY_PARALLEL_CPU_JOBS
        default = DEFAULT_PARALLEL_CPU_JOBS

    try:
        value = settings.value(key, default, type=int)
    except TypeError:
        value = settings.value(key, default)
    jobs = clamp_parallel_jobs(value, default)
    if file_count is not None:
        jobs = min(jobs, max(1, int(file_count)))
    return jobs


def split_files_for_parallel_workers(files: list[str], jobs: int) -> list[list[str]]:
    """Verteilt Dateien rundlaufend auf Worker, damit frühe Queue-Dateien sofort starten."""
    clean_files = [str(path) for path in files if str(path or "")]
    worker_count = min(clamp_parallel_jobs(jobs, 1), max(1, len(clean_files)))
    chunks: list[list[str]] = [[] for _ in range(worker_count)]
    for index, path in enumerate(clean_files):
        chunks[index % worker_count].append(path)
    return [chunk for chunk in chunks if chunk]
