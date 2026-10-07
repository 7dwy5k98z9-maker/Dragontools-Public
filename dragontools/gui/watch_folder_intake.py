"""Source reservations and completion ownership for Watch-Folder intake."""
from collections import defaultdict
from copy import deepcopy
from ..core.path_syntax import path_compare_key
from ..core.models import normalize_override_dict


def apply_watch_profile_overrides(overrides, paths, profile):
    if not profile:
        return
    for path in paths:
        override = dict(overrides.get(path) or {})
        override["encoder_profile"] = deepcopy(profile)
        overrides[path] = normalize_override_dict(override)


def watch_completion_callback(pending, reservations, complete):
    def callback(path, success, output_path=""):
        key = path_compare_key(path)
        candidate = reservations.get(key)
        if candidate is not None and pending.get(key) is candidate:
            complete(path, success, output_path)
    return callback


def dispatch_watch_candidates(candidates, *, pending, enqueue, complete, manual, log):
    grouped = defaultdict(list)
    for candidate in candidates:
        key = path_compare_key(candidate.path)
        candidate = pending.get(key, candidate)
        auto_start = False if manual else candidate.auto_start
        grouped[(candidate.codec, candidate.profile_key, auto_start)].append(candidate)
    queued = 0
    for (codec, profile_key, auto_start), group in grouped.items():
        reservations = {path_compare_key(candidate.path): candidate for candidate in group}
        pending.update(reservations)
        try:
            handled = {path_compare_key(path) for path in enqueue(
                codec=codec, paths=[candidate.path for candidate in group],
                profile_key=profile_key, auto_start=auto_start,
                completion_callback=watch_completion_callback(pending, reservations, complete),
            ) or []}
        except Exception:
            log.exception("Watch-Folder-Übergabe an Converter fehlgeschlagen")
            handled = set()
        for key, candidate in reservations.items():
            if key in handled:
                queued += 1
            elif pending.get(key) is candidate:
                pending.pop(key, None)
    return queued
