"""Canonical, owned per-file options for live queue mutations."""
from copy import deepcopy

from .worker_contracts import normalize_worker_path


def override_key(mapping: dict, path: str) -> str:
    wanted = normalize_worker_path(path)
    return next((key for key in mapping if normalize_worker_path(key) == wanted), path)


def set_file_override(mapping: dict, path: str, override: dict) -> None:
    key = override_key(mapping, path)
    value = deepcopy(override or {})
    # Remove legacy aliases too, so exact lookup and canonical lookup agree.
    wanted = normalize_worker_path(path)
    for alias in list(mapping):
        if alias != key and normalize_worker_path(alias) == wanted:
            del mapping[alias]
    mapping[key] = value
