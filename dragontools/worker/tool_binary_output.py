"""File-backed binary capture, with explicit completeness limits."""
from __future__ import annotations
import os
import tempfile


class BinaryOutputCapture:
    def __init__(self):
        self.stdout = tempfile.TemporaryFile()
        try:
            self.stderr = tempfile.TemporaryFile()
        except BaseException:
            self.stdout.close()
            raise

    def overflow(self, limit):
        return any(os.fstat(stream.fileno()).st_size > limit for stream in (self.stdout, self.stderr))

    def read(self, limit):
        self.stdout.seek(0)
        stdout = self.stdout.read(limit)
        error_size = os.fstat(self.stderr.fileno()).st_size
        self.stderr.seek(max(0, error_size - 256 * 1024))
        stderr = self.stderr.read(256 * 1024)
        if error_size > 256 * 1024:
            stderr = b"[Diagnoseausgabe gekuerzt]\n" + stderr
        truncated = os.fstat(self.stdout.fileno()).st_size > limit
        if truncated:
            stderr += b"\nStandardausgabe ueberschreitet Speichergrenze; Ausgabe nicht vollstaendig."
        if error_size > limit:
            stderr += b"\nDiagnoseausgabe ueberschreitet Speichergrenze; Ausgabe nicht vollstaendig."
        return stdout, stderr, truncated or error_size > limit

    def close(self):
        self.stdout.close()
        self.stderr.close()
