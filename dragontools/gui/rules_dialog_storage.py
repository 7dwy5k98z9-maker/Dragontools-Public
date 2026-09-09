# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from ..core.config_migration import sanitize_config_for_persistence, write_json_atomic
from ..core.audit_log import append_audit_event
from ..rules import audio_rules as _ar
from ..rules import move_rules as _mr
from ..rules import renamer_rules as _rr
from ..rules import subtitle_rules as _sr
from ..rules.rule_loader import load_json_rules, load_named_rules


def _rules_dir() -> Path:
    p = Path.home() / "Documents" / "DragonTools" / "rules"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load(name: str) -> dict:
    if name == "audio_rules":
        return load_named_rules(name, migrator=_ar.migrate_audio_rules)
    if name == "subtitle_rules":
        return load_named_rules(name, migrator=_sr.migrate_subtitle_rules)
    if name == "move_rules":
        return load_named_rules(name, migrator=_mr.migrate_move_rules)
    if name == "renamer_rules":
        return load_named_rules(name, migrator=_rr.migrate_renamer_rules)
    up = _rules_dir() / f"{name}.json"
    if up.exists():
        return load_json_rules(up)
    dp = Path(__file__).parents[1] / "config" / f"default_{name}.json"
    return load_json_rules(dp) if dp.exists() else {}


def _save(name: str, data: dict) -> None:
    if name == "audio_rules":
        data = _ar.migrate_audio_rules(data)
    elif name == "subtitle_rules":
        data = _sr.migrate_subtitle_rules(data)
    elif name == "move_rules":
        data = _mr.migrate_move_rules(data)
    elif name == "renamer_rules":
        data = _rr.migrate_renamer_rules(data)
    target = _rules_dir() / f"{name}.json"
    write_json_atomic(target, sanitize_config_for_persistence(data))
    append_audit_event("Regeln gespeichert", f"{name} | Datei: {target}")
    _ar.reload_rules()   # Cache invalidieren
    _rr.reload_rules()
