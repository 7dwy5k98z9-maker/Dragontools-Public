"""Filesystem receipts binding destructive actions to the objects they verified."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def stat_identity(path):
    info = Path(path).lstat()
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def object_identity(path):
    """Device/inode stays stable across our own rename and metadata updates."""
    return stat_identity(path)[:2]


def same_object(path, identity):
    try:
        return identity is not None and object_identity(path) == list(identity)
    except OSError:
        return False


def _content_digest(path):
    path = Path(path)
    before = stat_identity(path)
    digest = hashlib.sha256()
    if path.is_symlink():
        digest.update(b'link\0' + os.fsencode(os.readlink(path)))
    elif path.is_dir():
        digest.update(b'directory\0')
        for child in sorted(path.iterdir(), key=lambda p: p.name):
            digest.update(json.dumps(child.name, ensure_ascii=True).encode('ascii'))
            digest.update(_content_digest(child).encode('ascii'))
    else:
        digest.update(b'file\0')
        with path.open('rb') as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    if stat_identity(path) != before:
        raise OSError(f'Pfad wurde während der Prüfung verändert: {path}')
    return digest.hexdigest()


def path_receipt(path):
    """Full content, tree shape and stable stat identity, stored in JSON journals."""
    before = stat_identity(path)
    digest = _content_digest(path)
    if stat_identity(path) != before:
        raise OSError(f'Pfad wurde während der Prüfung verändert: {path}')
    receipt = {'identity': before, 'content': digest}
    if Path(path).is_dir() and not Path(path).is_symlink():
        receipt['members'] = _member_identities(Path(path))
    return receipt


def _member_identities(root):
    rows = []
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        rows.append([child.name, stat_identity(child)])
        if child.is_dir() and not child.is_symlink():
            rows.append([child.name, _member_identities(child)])
    return rows


def receipt_matches(path, receipt):
    if not isinstance(receipt, dict) or not receipt.get('identity') or not receipt.get('content'):
        return False
    try:
        return path_receipt(path) == receipt
    except (OSError, ValueError):
        return False


def renamed_receipt_matches(path, receipt):
    """A known rename can change ctime; inode and full content must still match."""
    if not isinstance(receipt, dict):
        return False
    try:
        current = path_receipt(path)
        return (current['identity'][:4] == receipt['identity'][:4]
            and current['content'] == receipt['content'] and current.get('members') == receipt.get('members'))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def validate_destination_name(name):
    if name is None:
        return
    text = str(name)
    if (not text or text in {'.', '..'} or any(c in text for c in '/\\:')
            or any(ord(c) < 32 for c in text)):
        raise ValueError('Move-Zielname muss ein einzelner Dateiname sein.')
