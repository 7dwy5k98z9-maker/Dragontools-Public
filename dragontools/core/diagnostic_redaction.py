# -*- coding: utf-8 -*-
"""Best-effort secret redaction for diagnostics and crash/error reports.

The diagnostic pipeline must preserve actionable commands and error output, but
credentials must never be copied verbatim into support artifacts.  Redaction is
intentionally dependency-free and works before Qt is available.
"""
from __future__ import annotations

import re
import json
from typing import Any, Iterable

from .secret_settings import read_secret_state
from .settings_metadata import is_sensitive_settings_key

_REDACTED = "[REDACTED]"

# Common textual forms in JSON/config/logs, e.g. api_key=..., "password": ...
_SENSITIVE_NAME = (
    r"(?:api[_-]?key|apikey|access[_-]?token|read[_-]?access[_-]?token|"
    r"bearer[_-]?token|auth[_-]?token|authorization|secret|password|passwd|pwd|pin)"
)
_KEY_VALUE_RE = re.compile(
    rf"(?P<prefix>[\"']?{_SENSITIVE_NAME}[\"']?\s*[:=]\s*)"
    r"(?P<value>\"(?:\\.|[^\"\\\r\n])*\"|'(?:\\.|[^'\\\r\n])*'|\[REDACTED\]|[^\s,;\]}]+)",
    re.IGNORECASE,
)
_CLI_VALUE_RE = re.compile(
    rf"(?P<prefix>--?{_SENSITIVE_NAME}(?:\s+|=))(?P<value>\"[^\"]*\"|'[^']*'|\S+)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"(?P<prefix>\b(?:Bearer|Basic)\s+)(?P<value>[A-Za-z0-9._~+/=-]+)", re.IGNORECASE)
_URL_SECRET_RE = re.compile(
    rf"(?P<prefix>[?&]{_SENSITIVE_NAME}=)(?P<value>[^&#\s]+)",
    re.IGNORECASE,
)


def _quoted_replacement(value: str) -> str:
    if value.strip("\"'") in {"********", "***", _REDACTED}:
        return value
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return f"{value[0]}{_REDACTED}{value[-1]}"
    return _REDACTED


def redact_sensitive_text(text: object, *, secret_values: Iterable[object] = ()) -> str:
    """Return *text* with known and structurally recognizable secrets removed."""
    result = str(text or "")

    # Replace exact current secret values first; this also catches secrets in
    # tool output where no key/flag name is printed next to the value.
    tokens = sorted(
        {
            str(value)
            for value in secret_values
            if value is not None and len(str(value)) >= 4 and str(value) != _REDACTED
        },
        key=len,
        reverse=True,
    )
    variants = {variant for token in tokens for variant in
                (token, json.dumps(token, ensure_ascii=False)[1:-1], json.dumps(token, ensure_ascii=True)[1:-1])}
    for token in sorted(variants, key=len, reverse=True):
        result = result.replace(token, _REDACTED)

    # Bearer must run before the generic ``Authorization: value`` matcher;
    # otherwise only the word "Bearer" would be replaced and the credential
    # behind it would remain visible.
    result = _BEARER_RE.sub(lambda m: m.group("prefix") + _REDACTED, result)
    result = _CLI_VALUE_RE.sub(
        lambda m: m.group("prefix") + _quoted_replacement(m.group("value")), result
    )
    result = _KEY_VALUE_RE.sub(
        lambda m: m.group("prefix") + _quoted_replacement(m.group("value")), result
    )
    result = _URL_SECRET_RE.sub(lambda m: m.group("prefix") + _REDACTED, result)
    return result


def redact_sensitive_data(value: Any) -> Any:
    """Recursively redact dictionary values whose key is credential-like."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if is_sensitive_settings_key(key_text) or _looks_sensitive_name(key_text):
                result[key_text] = _REDACTED if item not in (None, "") else item
            else:
                result[key_text] = redact_sensitive_data(item)
        return result
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item) for item in value)
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def redact_command(command: Any) -> Any:
    """Redact secrets from a command represented as list/tuple/string."""
    if isinstance(command, str):
        return redact_sensitive_text(command)
    if not isinstance(command, (list, tuple)):
        return command

    output: list[str] = []
    redact_next = False
    for raw in command:
        arg = str(raw)
        if redact_next:
            output.append(_REDACTED)
            redact_next = False
            continue
        clean = arg.lstrip("-/").split("=", 1)[0]
        if _looks_sensitive_name(clean):
            if "=" in arg:
                prefix = arg.split("=", 1)[0]
                output.append(f"{prefix}={_REDACTED}")
            else:
                output.append(arg)
                redact_next = True
            continue
        output.append(redact_sensitive_text(arg))
    return output if isinstance(command, list) else tuple(output)


def collect_settings_secret_values(settings) -> set[str]:
    """Collect raw/decrypted sensitive settings for exact-value redaction.

    Read failures are ignored deliberately: diagnostics must remain available
    even when DPAPI values cannot be decrypted in the current user context.
    """
    secrets: set[str] = set()
    try:
        keys = list(settings.allKeys())
    except Exception:
        return secrets

    for key in keys:
        key_text = str(key)
        if not is_sensitive_settings_key(key_text):
            continue
        try:
            raw = settings.value(key_text, "")
        except TypeError:
            try:
                raw = settings.value(key_text)
            except Exception:
                raw = ""
        except Exception:
            raw = ""
        raw_text = str(raw or "")
        if raw_text:
            secrets.add(raw_text)
        try:
            state = read_secret_state(settings, key_text, "")
            if state.readable and state.value:
                secrets.add(str(state.value))
        except Exception:
            continue
    return secrets


def _looks_sensitive_name(value: str) -> bool:
    normalized = str(value or "").strip().casefold().replace("-", "_")
    if not normalized:
        return False
    markers = (
        "api_key",
        "apikey",
        "access_token",
        "read_access_token",
        "bearer_token",
        "auth_token",
        "authorization",
        "secret",
        "password",
        "passwd",
        "pwd",
        "pin",
    )
    return any(marker in normalized for marker in markers)


__all__ = [
    "collect_settings_secret_values",
    "redact_command",
    "redact_sensitive_data",
    "redact_sensitive_text",
]
