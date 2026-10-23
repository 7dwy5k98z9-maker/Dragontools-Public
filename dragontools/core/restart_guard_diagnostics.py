"""Persistent restart-protection events survive an interrupted application run."""
from datetime import datetime
from pathlib import Path
import json
import logging
import os

from .path_defaults import app_documents_dir


class RestartGuardDiagnostics:
    def __init__(self, root=None) -> None:
        folder = Path(root) if root is not None else app_documents_dir() / "Logging" / "RestartGuard"
        self.path = folder / f"restart_guard_{datetime.now():%Y%m%d}_p{os.getpid()}.jsonl"
        self.error = ""

    def record(self, event: str, **details) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            row = dict(time=datetime.now().astimezone().isoformat(), pid=os.getpid(), event=event, **details)
            with self.path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
                output.flush()
                if event in {"native_query_rejected", "native_session_end", "registration_failed"}:
                    os.fsync(output.fileno())
            self.error = ""
        except (OSError, ValueError, TypeError) as exc:
            self.error = str(exc)
            logging.getLogger(__name__).warning("Neustartschutz-Protokoll nicht verfügbar: %s", exc)
