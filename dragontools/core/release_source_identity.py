"""Bind the privacy gate and ZIP contents to one source inventory."""
from .transaction_identity import path_receipt, receipt_matches


def capture_source_inventory(paths):
    return {path: path_receipt(path) for path in paths}


def require_source_inventory(inventory, paths):
    if set(inventory) != set(paths):
        raise RuntimeError('Source-Inventar wurde während der Release-Prüfung verändert.')
    for path, receipt in inventory.items():
        if not receipt_matches(path, receipt):
            raise RuntimeError(f'Source-Datei wurde nach der Datenschutzprüfung verändert: {path.name}')
