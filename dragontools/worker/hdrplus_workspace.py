"""Own the HDR intermediate tree until success or complete recovery persistence."""
from pathlib import Path
import shutil
import tempfile
from .log_dispatch import dispatch_log
from ..core.transaction_identity import object_identity, same_object


class HDRPlusWorkspace:
    def __init__(self, parent: Path, prefix: str):
        parent.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
        self._identity = object_identity(self.root)
        self._cleanup_permitted = False

    def mark_persisted(self):
        self._cleanup_permitted = True

    def finish(self):
        if self._cleanup_permitted and same_object(self.root, self._identity):
            try:
                shutil.rmtree(self.root)
            except OSError:
                # Cleanup is best effort after a successful commit. Never undo
                # a verified result or change an archive outcome because of it.
                pass


def cleanup_subtitle_temporary(hooks, input_path, log=None):
    try:
        hooks.cleanup_tmp_sub(input_path)
    except Exception as exc:
        # Recovery of expensive video/metadata must run even when a separate
        # subtitle temporary file is locked.
        dispatch_log(log, f'HDR10+: Untertitel-Tempdatei konnte nicht bereinigt werden: {exc}', 'warn')
