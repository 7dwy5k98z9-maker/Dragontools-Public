"""One sanitization boundary for every support-package text member."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .diagnostic_redaction import redact_sensitive_text

_QUOTED_PATH = re.compile(
    r'''(?P<quote>["'])(?:[A-Z]:[\\/]+|[\\/]{2}|/)(?:\\.|[^"'\\\r\n])*(?P=quote)''',
    re.IGNORECASE,
)
_PATH_PREFIX = re.compile(
    r'(?<![A-Za-z0-9])(?:[A-Z]:[\\/]+|[\\/]{2}|\[(?:PRIVATE_PATH|USER_PROFILE)\][\\/]+)(?:[^\\/\r\n"<>|]*[\\/]+)*',
    re.IGNORECASE,
)
_POSIX_PREFIX = re.compile(r'''(?<![A-Za-z0-9:/\]])/(?:[^/\s"'<>|]+/)+''')


class DiagnosticSanitizer:
    def __init__(self, *, secret_values=(), private_roots=()):
        self.secret_values = tuple(secret_values)
        roots = {str(Path.home()), *(str(root) for root in private_roots)}
        variants = {}
        for root in roots:
            if not root or root in {"/", "\\"} or len(root) <= 3:
                continue
            for variant in (root, root.replace("\\", "/"), json.dumps(root, ensure_ascii=False)[1:-1]):
                variants[variant] = "[PRIVATE_PATH]"
        self.roots = sorted(variants, key=len, reverse=True)

    def __call__(self, text):
        result = redact_sensitive_text(text, secret_values=self.secret_values)
        for root in self.roots:
            result = re.sub(re.escape(root), lambda _match: "[PRIVATE_PATH]", result, flags=re.IGNORECASE)
        # Foreign user profiles in historical logs must also remain anonymous.
        result = re.sub(r"(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\r\n\"']+", "[USER_PROFILE]", result)
        result = re.sub(r'''/(?:home|Users)/[^/\s"']+''', "[USER_PROFILE]", result)
        result = _QUOTED_PATH.sub(lambda match: match.group("quote") + "[PRIVATE_PATH]" + match.group("quote"), result)
        result = _PATH_PREFIX.sub(lambda _match: "[PRIVATE_PATH]/", result)
        result = _POSIX_PREFIX.sub(lambda _match: "[PRIVATE_PATH]/", result)
        return result
