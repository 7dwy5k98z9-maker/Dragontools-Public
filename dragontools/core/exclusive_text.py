"""Exclusive text output with cleanup limited to the inode this call owns."""

import os
from pathlib import Path


def write_exclusive_text(target, content):
    target = Path(target)
    identity = None
    try:
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            stat = os.fstat(handle.fileno())
            identity = (stat.st_dev, stat.st_ino)
            handle.write(content)
    except Exception:
        if identity is not None:
            try:
                stat = target.lstat()
                if (stat.st_dev, stat.st_ino) == identity:
                    target.unlink()
            except OSError:
                pass
        raise
    return target
