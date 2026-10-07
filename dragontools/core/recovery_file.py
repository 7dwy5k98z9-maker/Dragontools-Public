"""Preserve recovery files without replacing concurrent archive contents."""
import errno
import os
import shutil
from pathlib import Path
from tempfile import mkstemp

from .move_copy_verification import verify_staged_file_copy
from .move_transaction import publish_staged_no_replace


def copy_recovery_file(source, target):
    source, target = Path(source), Path(target)
    identity = source.stat()
    descriptor, name = mkstemp(prefix=f'.{target.name}.archiving-', suffix='.part', dir=target.parent)
    os.close(descriptor)
    stage = Path(name)
    try:
        shutil.copy2(source, stage)
        verify_staged_file_copy(source, stage)
        publish_staged_no_replace(stage, target)
        try:
            current = source.stat()
            if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns) == (
                    identity.st_dev, identity.st_ino, identity.st_size, identity.st_mtime_ns, identity.st_ctime_ns):
                source.unlink()
        except OSError:
            pass  # A durable archive with a retained duplicate is still preserved.
    finally:
        stage.unlink(missing_ok=True)


def preserve_recovery_file(source, target):
    source, target = Path(source), Path(target)
    if not source.is_file() or source.is_symlink():
        raise ValueError('Recovery requires an owned regular file.')
    try:
        publish_staged_no_replace(source, target)
    except OSError as exc:
        if exc.errno not in {errno.EXDEV, errno.EACCES, errno.EPERM}:
            raise
        copy_recovery_file(source, target)
