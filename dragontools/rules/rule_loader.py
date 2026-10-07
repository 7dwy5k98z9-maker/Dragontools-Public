from __future__ import annotations

import copy
import json
import logging
import sys
from inspect import signature
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..core.config_migration import UnsupportedConfigSchemaError, sanitize_config_for_persistence, write_json_atomic
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
        logging.getLogger(__name__).debug("Unterdrückte Best-Effort-Ausnahme in _report_visible_warning.", exc_info=True)


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


def _default_copy(default: dict[str, Any] | None) -> dict[str, Any]:
    """Return an isolated fallback tree.

    Rule dictionaries contain nested lists/dicts and are frequently passed on
    to migrators/editors.  A shallow ``dict(default)`` would let a caller
    mutate the module-level fallback for every later load in the same process.
    """
    return copy.deepcopy(default or {})


def _load_json_rules_result(
    path: str | Path,
    default: dict[str, Any] | None = None,
    *,
    context: str | None = None,
    reporter: Callable | None = None,
) -> tuple[dict[str, Any], bool]:
    """Load one JSON object and report whether the file itself was usable."""
    p = Path(path)
    if not p.exists():
        _report_visible_warning(
            f"Regeldatei fehlt: {p}{f' ({context})' if context else ''} -> Fallback/Defaults aktiv.",
            reporter=reporter,
        )
        return _default_copy(default), False
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        if str(context or "").startswith("user:"):
            _quarantine_user_rules(p, reason=f"JSON/Encoding: {exc}", reporter=reporter)
        _report_visible_warning(
            f"Regeldatei konnte nicht gelesen/geparst werden: {p}{f' ({context})' if context else ''} | {exc} -> Fallback/Defaults aktiv.",
            reporter=reporter,
        )
        return _default_copy(default), False
    except OSError as exc:
        _report_visible_warning(
            f"Regeldatei konnte nicht gelesen werden: {p}{f' ({context})' if context else ''} | {exc} -> Fallback/Defaults aktiv.",
            reporter=reporter,
        )
        return _default_copy(default), False

    if isinstance(raw, dict):
        return raw, True
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
    return _default_copy(default), False


def load_json_rules(
    path: str | Path,
    default: dict[str, Any] | None = None,
    *,
    context: str | None = None,
    reporter: Callable | None = None,
) -> dict[str, Any]:
    return _load_json_rules_result(
        path,
        default,
        context=context,
        reporter=reporter,
    )[0]


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
        raw, user_file_valid = _load_json_rules_result(
            user_path,
            default,
            context=f"user:{name}",
            reporter=reporter,
        )
        # Callers such as the Rules dialog intentionally do not pass a Python
        # fallback.  A corrupt/unreadable user file must then fall through to
        # the packaged default JSON instead of turning the active rules into
        # an empty mapping.  When an explicit fallback was supplied, preserve
        # the long-standing behavior and migrate that fallback below.
        if not user_file_valid and default is None:
            default_path = _default_rules_path(name)
            if default_path.exists():
                default_raw, default_valid = _load_json_rules_result(
                    default_path,
                    None,
                    context=f"default:{name}",
                    reporter=reporter,
                )
                if default_valid:
                    try:
                        return _apply_migrator(
                            default_raw,
                            migrator,
                            source_path=default_path,
                            reporter=reporter,
                        )
                    except UnsupportedConfigSchemaError as exc:
                        _report_visible_warning(
                            f"Default-Regeldatei verwendet ein nicht unterstütztes neueres Schema: "
                            f"{default_path} | {exc}.",
                            reporter=reporter,
                        )
            return {}
        try:
            migrated = _apply_migrator(raw, migrator, source_path=user_path, reporter=reporter)
        except UnsupportedConfigSchemaError as exc:
            _report_visible_warning(
                f"Regeldatei verwendet ein neueres Schema und bleibt unverändert: {user_path} | {exc} "
                "-> sichere Defaults aktiv.",
                reporter=reporter,
            )
            return _default_copy(default)
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
        try:
            return _apply_migrator(raw, migrator, source_path=default_path, reporter=reporter)
        except UnsupportedConfigSchemaError as exc:
            _report_visible_warning(
                f"Default-Regeldatei verwendet ein nicht unterstütztes neueres Schema: {default_path} | {exc}.",
                reporter=reporter,
            )
            return _default_copy(default)

    _report_visible_warning(
        f"Weder Nutzer- noch Default-Regeldatei gefunden für '{name}' -> Fallback/Defaults aktiv.",
        reporter=reporter,
    )

    return _default_copy(default)


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
