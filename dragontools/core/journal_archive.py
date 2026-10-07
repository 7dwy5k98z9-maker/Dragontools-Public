"""Durable archive publication preserving corrupt journal bytes and late targets."""
from datetime import datetime
import json
import os
from pathlib import Path
import re
from tempfile import mkstemp
import uuid

from .json_io import atomic_write_json
from .move_transaction import publish_staged_no_replace
from .transaction_identity import stat_identity


def _component(value):
    text = re.sub(r'[^\w .()-]', '_', str(value or 'unknown'), flags=re.UNICODE)
    return text.strip(' .')[:100] or 'unknown'


def archive_journal(path, *, status, data=None, write=atomic_write_json):
    path = Path(path)
    original_identity = stat_identity(path)
    raw = path.read_bytes()
    if data is None:
        try:
            parsed = json.loads(raw.decode('utf-8-sig'))
            data = parsed if isinstance(parsed, dict) else None
        except (UnicodeError, ValueError):
            data = None
    folder = path.parent / 'Abgeschlossen'
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().isoformat(timespec='seconds')
    if data is not None:
        data = dict(data, active=False, status=str(status or 'ignored'), finished_at=stamp, updated_at=stamp)
    run_id = data.get('run_id', path.stem) if data is not None else path.stem
    target = folder / f'{_component(run_id)}_{_component(status)}_{uuid.uuid4().hex[:12]}.json'
    descriptor, name = mkstemp(prefix='.archive-', suffix='.json', dir=folder)
    os.close(descriptor)
    stage = Path(name)
    try:
        if data is None:
            with stage.open('wb') as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        else:
            write(stage, data)
        publish_staged_no_replace(stage, target)
        if stat_identity(path) != original_identity:
            raise OSError('Aktives Journal wurde während der Archivierung geändert; Original bleibt erhalten.')
        path.unlink()
        return target
    finally:
        stage.unlink(missing_ok=True)
