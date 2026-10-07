"""Private storage keeps verified outputs and cleans only its own directory."""
from pathlib import Path
import shutil
import tempfile
from ..core.transaction_identity import object_identity, same_object, path_receipt, receipt_matches, renamed_receipt_matches
from ..core.move_transaction import publish_staged_no_replace
from .log_dispatch import dispatch_log

class VerifiedOutputWorkspace:
    def __init__(self, output_dir, log, *, prefix='.__dragontools_utility_'):
        self.root = Path(tempfile.mkdtemp(prefix=prefix, dir=str(output_dir)))
        self.identity = object_identity(self.root)
        self.verified = {}
        self.published = False
        self.log = log

    def __enter__(self):
        return self.root

    def mark_verified(self, path):
        self.verified[Path(path)] = path_receipt(path)

    def publish_verified(self, staged, destination, *, require_current):
        require_current()
        receipt = self.verified.get(Path(staged))
        if not receipt_matches(staged, receipt):
            raise RuntimeError('Geprüfte Ausgabe wurde verändert.')
        require_current()
        publish_staged_no_replace(staged, destination)
        if not renamed_receipt_matches(destination, receipt):
            raise RuntimeError('Veröffentlichte Ausgabe stimmt nicht mit dem Prüfergebnis überein.')
        self.published = True

    def __exit__(self, *_):
        if self.verified and not self.published:
            dispatch_log(self.log, f'Geprüfte Zwischenergebnisse bleiben zur Wiederherstellung erhalten: {self.root}', 'warn')
            return False
        if same_object(self.root, self.identity):
            try:
                shutil.rmtree(self.root)
            except OSError as exc:
                dispatch_log(self.log, f'Tempordner konnte nicht bereinigt werden: {self.root}: {exc}', 'warn')
        return False

