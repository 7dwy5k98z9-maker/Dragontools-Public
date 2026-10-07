"""Status counting and authoritative queue selection for journal resume plans."""
from .path_syntax import path_compare_key

TERMINAL_PROBLEM_STATUSES = {'error', 'warn'}
RUNNING_STATUSES = {'running'}
PENDING_STATUSES = {'queued', 'unknown', ''}


def normalize_status(status):
    text = str(status or '').strip().lower()
    if '✅' in text or text in {'ok', 'success', 'done'}:
        return 'ok'
    if '⏭' in text or text in {'skip', 'skipped'}:
        return 'skipped'
    if '⚠' in text or text in {'warn', 'warning'}:
        return 'warn'
    if '❌' in text or text in {'error', 'failed', 'fail'}:
        return 'error'
    return text or 'unknown'


def dedupe_preserve_order(paths):
    seen, result = set(), []
    for path in paths:
        key = path_compare_key(str(path))
        if key not in seen:
            seen.add(key)
            result.append(str(path))
    return result


def row_for_path(files, path):
    wanted = path_compare_key(path)
    return next((raw for stored, raw in files.items()
        if path_compare_key(stored) == wanted and isinstance(raw, dict)), {})


def count_statuses(files):
    counts = dict(ok=0, skipped=0, failed=0, running=0, queued=0, unknown=0)
    aliases = {'error': 'failed', 'warn': 'failed', '': 'queued', 'unknown': 'queued'}
    for row in files.values():
        item = row if isinstance(row, dict) else {}
        status = normalize_status(item.get('status') or 'queued')
        bucket = aliases.get(status, status)
        counts[bucket if bucket in counts else 'unknown'] += 1
    return counts


def select_resume_files(data, files, *, retry_running, retry_failed):
    order = data.get('queue_order')
    paths = dedupe_preserve_order([str(path) for path in order if str(path or '')]) if isinstance(order, list) else list(files)
    selected = []
    for path in paths:
        status = normalize_status(row_for_path(files, path).get('status') or 'queued')
        if status in {'ok', 'skipped'}:
            continue
        if status in TERMINAL_PROBLEM_STATUSES and not retry_failed:
            continue
        if status in RUNNING_STATUSES and not retry_running:
            continue
        selected.append(str(path))
    return selected
