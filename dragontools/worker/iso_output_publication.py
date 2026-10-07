"""Private ISO extraction storage and ownership-checked multi-title publication."""
from pathlib import Path

from ..core.move_transaction import publish_staged_no_replace
from ..core.transaction_identity import receipt_matches, renamed_receipt_matches
from .utility_output_workspace import VerifiedOutputWorkspace


class ISOExtractionWorkspace(VerifiedOutputWorkspace):
    def __init__(self, output_dir, log, *, prefix='.__dragontools_makemkv_'):
        super().__init__(output_dir, log, prefix=prefix)


def require_iso_not_aborted(worker):
    if bool(getattr(worker, 'abort_requested', False)):
        raise RuntimeError('Abgebrochen vor Veröffentlichung der ISO-Ausgabe.')


def publish_iso_titles(staged_files, destinations, *, receipts, worker, publish=publish_staged_no_replace):
    installed = []
    try:
        for staged, destination in zip(staged_files, destinations, strict=True):
            require_iso_not_aborted(worker)
            receipt = receipts[staged]
            if not receipt_matches(staged, receipt):
                raise OSError('Geprüfte ISO-Ausgabe wurde vor Veröffentlichung verändert.')
            publish(staged, destination)
            installed.append((staged, destination, receipt))
            if not renamed_receipt_matches(destination, receipt):
                raise OSError('Installierte ISO-Ausgabe wurde verändert; fremder Bestand bleibt erhalten.')
        require_iso_not_aborted(worker)
    except Exception as exc:
        errors = []
        for staged, destination, receipt in reversed(installed):
            try:
                if not renamed_receipt_matches(destination, receipt):
                    raise OSError('Ausgabe gehört nicht mehr zu dieser Transaktion; wird nicht verschoben.')
                publish_staged_no_replace(destination, staged)
            except OSError as error:
                errors.append(f'{destination.name}: {error}')
        message = f'MakeMKV-Ausgaben konnten nicht vollständig veröffentlicht werden: {exc}'
        if errors:
            message += '; Rollback unvollständig: ' + '; '.join(errors)
        raise RuntimeError(message) from exc
