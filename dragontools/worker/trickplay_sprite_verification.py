"""Decode generated JPEGs and check their commanded tile geometry before install."""
from pathlib import Path
import re


def verify_command_sprites(command):
    if not command or not str(command[-1]).endswith('%d.jpg'):
        return True
    from PyQt6.QtGui import QImageReader
    try:
        filters = str(command[command.index('-vf') + 1])
        geometry = re.search(r'scale=(\d+):-2,tile=(\d+)x(\d+)', filters)
        if geometry is None:
            return False
        width, columns, rows = map(int, geometry.groups())
        count = 0
        for image in Path(command[-1]).parent.glob('*.jpg'):
            count += 1
            if count > 100_000 or image.is_symlink() or image.stat().st_size > 64 * 1024 * 1024:
                return False
            reader = QImageReader(str(image), b'jpeg')
            size = reader.size()
            if size.width() != width * columns or size.height() < 2 * rows or size.height() % rows:
                return False
            if size.width() * size.height() > 64_000_000 or reader.read().isNull():
                return False
        return count > 0
    except (OSError, ValueError, IndexError):
        return False
