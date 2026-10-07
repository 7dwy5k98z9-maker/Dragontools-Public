"""Remove only a proven incompatible root ICU copy from an owned Qt build."""
from pathlib import Path
import os
import sys


def _required_icu_symbols(qt_core):
    from pefile import PE
    with PE(str(qt_core), fast_load=True) as library:
        library.parse_data_directories(directories=[1])
        return {item.name for dependency in library.DIRECTORY_ENTRY_IMPORT
            if dependency.dll.lower() == b'icuuc.dll' for item in dependency.imports if item.name}


def _exported_symbols(path):
    from pefile import PE
    with PE(str(path), fast_load=True) as library:
        library.parse_data_directories(directories=[0])
        table = getattr(library, 'DIRECTORY_ENTRY_EXPORT', None)
        return {item.name for item in table.symbols if item.name} if table else set()


def remove_conflicting_windows_icu(data_root):
    if sys.platform != 'win32':
        return False
    root = Path(data_root).absolute()
    if root.name != 'Daten' or any(p.is_symlink() or p.is_junction() for p in (root, *root.parents)):
        raise RuntimeError('ICU-Prüfung verlangt den unverknüpften Datenordner des Builds.')
    candidate = root / 'icuuc.dll'
    qt_core = root / 'PyQt6/Qt6/bin/Qt6Core.dll'
    if not candidate.exists():
        return False
    if candidate.is_symlink() or not qt_core.is_file():
        raise RuntimeError('ICU-/Qt-Dateigrenze des Builds ist nicht prüfbar.')
    from .transaction_identity import path_receipt, receipt_matches
    receipt = path_receipt(candidate)
    required = _required_icu_symbols(qt_core)
    if not required or required <= _exported_symbols(candidate):
        return False
    system_library = Path(os.environ['SystemRoot']) / 'System32/icuuc.dll'
    if not required <= _exported_symbols(system_library):
        raise RuntimeError('Windows-System-ICU erfüllt den Qt-Vertrag nicht; Build bleibt erhalten.')
    if not receipt_matches(candidate, receipt):
        raise RuntimeError('ICU-Kopie wurde während der Prüfung verändert; kein Löschen.')
    candidate.unlink()
    return True


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: python -m dragontools.core.release_qt_icu DATA_ROOT')
    print('Qt ICU:', 'incompatible root copy removed' if remove_conflicting_windows_icu(sys.argv[1]) else 'unchanged')
