from __future__ import annotations

import json
import logging
import sys
from inspect import signature
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..core.config_migration import sanitize_config_for_persistence, write_json_atomic
from ..core.json_io import quarantine_corrupt_file

_LOG = logging.getLogger(__name__)
_RULES_DIAG_LOG = Path.home() / "Documents" / "DragonTools" / "Logging" / "RULES" / "rule_loader.log"


def _report_visible_warning(message: str, reporter: Callable | None = None) -> None:
    _LOG.warning(message)
    print(f"[RuleLoader] {message}", file=sys.stderr)

    try:
        _RULES_DIAG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_RULES_DIAG_LOG, "a", encoding="utf-8") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] WARN {message}\n")
    except OSError:
        pass

    if reporter is None:
        return
    try:
        reporter(message, "warn")
        return
    except TypeError:
        pass
    except Exception:
        return
    try:
        reporter(message)
    except Exception:
        pass


def _quarantine_user_rules(path: Path, *, reason: str, reporter: Callable | None = None) -> None:
    try:
        backup = quarantine_corrupt_file(path)
    except OSError as exc:
        _report_visible_warning(
            f"Ungueltige Nutzer-Regeldatei konnte nicht gesichert werden: {path} | {reason} | {exc}",
            reporter=reporter,
        )
        return
    if backup is not None:
        _report_visible_warning(
            f"Ungueltige Nutzer-Regeldatei wurde gesichert: {path} -> {backup} | {reason}",
            reporter=reporter,
        )


def _rules_dir() -> Path:
    rules_dir = Path.home() / "Documents" / "DragonTools" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    return rules_dir


def _default_rules_path(name: str) -> Path:
    return Path(__file__).parents[1] / "config" / f"default_{name}.json"


def load_json_rules(
    path: str | Path,
    default: dict[str, Any] | None = None,
    *,
    context: str | None = None,
    reporter: Callable | None = None,
) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        _report_visible_warning(
            f"Regeldatei fehlt: {p}{f' ({context})' if context else ''} -> Fallback/Defaults aktiv.",
            reporter=reporter,
        )
        return dict(default or {})
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        if str(context or "").startswith("user:"):
            _quarantine_user_rules(p, reason=f"JSON/Encoding: {exc}", reporter=reporter)
        _report_visible_warning(
            f"Regeldatei konnte nicht gelesen/geparst werden: {p}{f' ({context})' if context else ''} | {exc} -> Fallback/Defaults aktiv.",
            reporter=reporter,
        )
        return dict(default or {})
    except OSError as exc:
        _report_visible_warning(
            f"Regeldatei konnte nicht gelesen werden: {p}{f' ({context})' if context else ''} | {exc} -> Fallback/Defaults aktiv.",
            reporter=reporter,
        )
        return dict(default or {})

    if isinstance(raw, dict):
        return raw
    if str(context or "").startswith("user:"):
        _quarantine_user_rules(
            p,
            reason=f"erwartet wurde ein JSON-Objekt, gefunden wurde {type(raw).__name__}",
            reporter=reporter,
        )
    _report_visible_warning(
        f"Regeldatei ist kein JSON-Objekt: {p}{f' ({context})' if context else ''} -> Fallback/Defaults aktiv.",
        reporter=reporter,
    )
    return dict(default or {})


def _apply_migrator(
    data: dict[str, Any],
    migrator: Callable | None,
    *,
    source_path: Path,
    reporter: Callable | None = None,
) -> dict[str, Any]:
    if migrator is None:
        return data
    params = signature(migrator).parameters
    kwargs: dict[str, Any] = {}
    if "source_path" in params:
        kwargs["source_path"] = source_path
    if "reporter" in params:
        kwargs["reporter"] = reporter
    migrated = migrator(data, **kwargs)
    if hasattr(migrated, "data"):
        return dict(getattr(migrated, "data"))
    return dict(migrated or {})


def load_named_rules(
    name: str,
    default: dict[str, Any] | None = None,
    *,
    reporter: Callable | None = None,
    migrator: Callable | None = None,
) -> dict[str, Any]:
    user_path = _rules_dir() / f"{name}.json"
    if user_path.exists():
        raw = load_json_rules(user_path, default, context=f"user:{name}", reporter=reporter)
        migrated = _apply_migrator(raw, migrator, source_path=user_path, reporter=reporter)
        persistent_migrated = sanitize_config_for_persistence(migrated)
        persistent_raw = sanitize_config_for_persistence(raw)
        if migrator is not None and persistent_migrated != persistent_raw:
            try:
                write_json_atomic(user_path, persistent_migrated)
            except Exception as exc:
                _report_visible_warning(
                    f"Regeldatei konnte nach Migration nicht gespeichert werden: {user_path} | {exc}",
                    reporter=reporter,
                )
        return migrated

    default_path = _default_rules_path(name)
    if default_path.exists():
        raw = load_json_rules(default_path, default, context=f"default:{name}", reporter=reporter)
        return _apply_migrator(raw, migrator, source_path=default_path, reporter=reporter)

    _report_visible_warning(
        f"Weder Nutzer- noch Default-Regeldatei gefunden für '{name}' -> Fallback/Defaults aktiv.",
        reporter=reporter,
    )

    return dict(default or {})


def load_subtitle_rules(
    default: dict[str, Any] | None = None,
    *,
    reporter: Callable | None = None,
) -> dict[str, Any]:
    from .subtitle_rules import migrate_subtitle_rules

    return load_named_rules(
        "subtitle_rules",
        default=default,
        reporter=reporter,
        migrator=migrate_subtitle_rules,
    )
