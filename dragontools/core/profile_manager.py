# -*- coding: utf-8 -*-
"""dragontools/core/profile_manager.py – Default + User Profile"""
from __future__ import annotations
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

from .config_migration import (
    SCHEMA_VERSION_KEY,
    current_schema_version,
    migrate_encoder_profile,
    migrate_profile_collection,
    sanitize_config_for_persistence,
    write_json_atomic,
)
from .json_io import quarantine_corrupt_file

_LOG = logging.getLogger(__name__)

_DEFAULTS: dict[str, dict] = {
    # CPU
    "film_cpu":  {"label":"🎬 Film – CPU","codec":"h265","crf":22,"preset":"slow","scale":"original","encoder_options":{"encoder":"cpu","tune":"none","aq_mode":"2","aq_strength":"1.0","psy_rd":"2.0","psy_rdoq":"1.0","bf":8,"rc_lookahead":40}},
    "tv_cpu":    {"label":"📺 TV – CPU","codec":"h265","crf":22,"preset":"medium","scale":"original","encoder_options":{"encoder":"cpu","tune":"none","aq_mode":"2","aq_strength":"1.0","psy_rd":"2.0","psy_rdoq":"1.0","bf":8,"rc_lookahead":40}},
    "anime_cpu": {"label":"🎌 Anime – CPU","codec":"h265","crf":20,"preset":"slow","scale":"original","encoder_options":{"encoder":"cpu","tune":"animation","aq_mode":"2","aq_strength":"1.0","psy_rd":"2.0","psy_rdoq":"1.0","bf":8,"rc_lookahead":40}},
    # NVENC
    "film_nvenc":  {"label":"🎬 Film – NVENC","codec":"h265","crf":23,"preset":"slow","scale":"original","encoder_options":{"encoder":"nvenc","preset":"p6","cq":23,"bf":4,"bref_mode":"middle","rc_lookahead":32,"lookahead_level":"auto","multipass":"auto","aq_strength":8,"spatial_aq":True,"temporal_aq":True}},
    "tv_nvenc":    {"label":"📺 TV – NVENC","codec":"h265","crf":22,"preset":"medium","scale":"original","encoder_options":{"encoder":"nvenc","preset":"p6","cq":22,"bf":4,"bref_mode":"middle","rc_lookahead":32,"lookahead_level":"auto","multipass":"auto","aq_strength":8,"spatial_aq":True,"temporal_aq":True}},
    "anime_nvenc": {"label":"🎌 Anime – NVENC","codec":"h265","crf":20,"preset":"slow","scale":"original","encoder_options":{"encoder":"nvenc","preset":"p6","cq":20,"bf":4,"bref_mode":"middle","rc_lookahead":32,"lookahead_level":"auto","multipass":"auto","aq_strength":8,"spatial_aq":True,"temporal_aq":True}},
    # QSV
    "film_qsv":  {"label":"🎬 Film – QSV","codec":"h265","crf":23,"preset":"slow","scale":"original","encoder_options":{"encoder":"qsv","preset":"slow","q":23,"lookahead_depth":40}},
    "tv_qsv":    {"label":"📺 TV – QSV","codec":"h265","crf":22,"preset":"medium","scale":"original","encoder_options":{"encoder":"qsv","preset":"medium","q":22,"lookahead_depth":40}},
    "anime_qsv": {"label":"🎌 Anime – QSV","codec":"h265","crf":20,"preset":"slow","scale":"original","encoder_options":{"encoder":"qsv","preset":"slow","q":20,"lookahead_depth":40}},
    # AMF
    "film_amf":  {"label":"🎬 Film – AMF","codec":"h265","crf":23,"preset":"slow","scale":"original","encoder_options":{"encoder":"amf","quality":"quality","qp":23}},
    "tv_amf":    {"label":"📺 TV – AMF","codec":"h265","crf":22,"preset":"medium","scale":"original","encoder_options":{"encoder":"amf","quality":"balanced","qp":22}},
    "anime_amf": {"label":"🎌 Anime – AMF","codec":"h265","crf":20,"preset":"slow","scale":"original","encoder_options":{"encoder":"amf","quality":"quality","qp":20}},
    # AV1
    "film_av1":  {"label":"🎬 Film – AV1","codec":"av1","crf":28,"preset":"6","scale":"original","encoder_options":{"encoder":"cpu"}},
    "tv_av1":    {"label":"📺 TV – AV1","codec":"av1","crf":27,"preset":"6","scale":"original","encoder_options":{"encoder":"cpu"}},
    "anime_av1": {"label":"🎌 Anime – AV1","codec":"av1","crf":25,"preset":"5","scale":"original","encoder_options":{"encoder":"cpu"}},
    # H.264
    "film_h264":  {"label":"🎬 Film – H.264","codec":"h264","crf":22,"preset":"medium","scale":"original","encoder_options":{"encoder":"cpu"}},
    "tv_h264":    {"label":"📺 TV – H.264","codec":"h264","crf":21,"preset":"medium","scale":"original","encoder_options":{"encoder":"cpu"}},
    "anime_h264": {"label":"🎌 Anime – H.264","codec":"h264","crf":19,"preset":"slow","scale":"original","encoder_options":{"encoder":"cpu"}},
}


def _extend_defaults_with_assistant_profiles() -> None:
    try:
        from .codec_profile_assistant import assistant_profiles_for_codec

        for suggestion in assistant_profiles_for_codec("h265"):
            _DEFAULTS.setdefault(suggestion.key, dict(suggestion.profile))
    except Exception:
        # Die Assistentenprofile sind optional; ein Fehler darf die statischen
        # Built-ins nicht blockieren, muss aber fuer die Diagnose sichtbar sein.
        _LOG.exception("Optionale Assistentenprofile konnten nicht geladen werden.")


_extend_defaults_with_assistant_profiles()


def _normalise_profile_label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _slugify_profile_label(value: Any) -> str:
    text = _normalise_profile_label(value)
    text = re.sub(r"\W+", "_", text, flags=re.UNICODE).strip("_")
    return text or "profil"


def _profile_encoder(value: dict[str, Any] | None) -> str:
    if not isinstance(value, dict):
        return "cpu"
    opts = value.get("encoder_options")
    if not isinstance(opts, dict):
        opts = {}
    return str(opts.get("encoder") or "cpu").strip().lower() or "cpu"


def _profile_codec(value: dict[str, Any] | None, fallback: str) -> str:
    if not isinstance(value, dict):
        return fallback
    return str(value.get("codec") or fallback).strip().lower() or fallback


def _codec_display(codec: str) -> str:
    return {
        "h265": "H.265",
        "h264": "H.264",
        "av1": "AV1",
    }.get(str(codec or "").lower(), str(codec or "").upper())


class ProfileManager:
    def __init__(
        self,
        path: str | Path,
        *,
        reporter: Callable | None = None,
    ) -> None:
        self.path = Path(path)
        self._reporter = reporter
        self._user: dict[str, Any] = self._load()

    def _report_warning(self, message: str) -> None:
        _LOG.warning(message)
        if self._reporter is None:
            return
        try:
            self._reporter(message, "warn")
            return
        except TypeError:
            pass
        except Exception:
            _LOG.exception("Profilwarnung konnte nicht an den Reporter uebergeben werden.")
            return
        try:
            self._reporter(message)
        except Exception:
            _LOG.exception("Profilwarnung konnte nicht an den Reporter uebergeben werden.")

    def _quarantine_invalid_profile(self, reason: str) -> None:
        try:
            backup = quarantine_corrupt_file(self.path)
        except OSError as exc:
            self._report_warning(
                f"Profil-Datei ist ungueltig ({reason}), konnte aber nicht gesichert werden: "
                f"{self.path} | {exc}"
            )
            return
        backup_text = str(backup) if backup is not None else "-"
        self._report_warning(
            f"Profil-Datei ist ungueltig ({reason}) und wurde gesichert: "
            f"{self.path} -> {backup_text}. DragonTools verwendet vorerst die Standardprofile."
        )

    def _default_codec(self) -> str:
        stem = self.path.stem.lower()
        if stem.startswith("h264"):
            return "h264"
        if stem.startswith("av1"):
            return "av1"
        return "h265"

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError) as exc:
            self._quarantine_invalid_profile(f"JSON/Encoding: {exc}")
            return {}
        except OSError as exc:
            self._report_warning(f"Profil-Datei konnte nicht gelesen werden: {self.path} | {exc}")
            return {}

        if not isinstance(raw, dict):
            self._quarantine_invalid_profile(
                f"erwartet wurde ein JSON-Objekt, gefunden wurde {type(raw).__name__}"
            )
            return {}

        # Migrations-/Programmierfehler werden absichtlich nicht verschluckt.
        # Ein Releasefehler soll sichtbar werden statt still alle Profile
        # scheinbar verschwinden zu lassen.
        migrated = migrate_profile_collection(
            raw,
            default_codec=self._default_codec(),
            source_path=self.path,
        )
        if migrated.changed:
            write_json_atomic(
                self.path,
                sanitize_config_for_persistence(migrated.data),
            )
        return {
            k: v for k, v in migrated.data.items()
            if not str(k).startswith("_") and k not in _DEFAULTS and isinstance(v, dict)
        }

    def save(self) -> None:
        data = {
            SCHEMA_VERSION_KEY: current_schema_version("profiles"),
            **self._user,
        }
        write_json_atomic(self.path, data)

    @property
    def data(self) -> dict[str, Any]:
        merged = dict(_DEFAULTS); merged.update(self._user); return merged

    def defaults(self) -> dict[str, Any]: return dict(_DEFAULTS)

    def get(self, key: str) -> dict[str, Any]:
        return dict(self._user.get(key, _DEFAULTS.get(key, {})))

    def set(self, key: str, value: dict[str, Any]) -> bool:
        if key in _DEFAULTS: return False
        value = dict(value); value.pop("builtin", None)
        value, _messages = migrate_encoder_profile(
            key,
            value,
            default_codec=self._default_codec(),
        )
        self._user[key] = value; self.save(); return True

    def profile_label(self, key: str, value: dict[str, Any] | None = None) -> str:
        profile = value if isinstance(value, dict) else self.data.get(key, {})
        label = str(profile.get("label") or key).strip() if isinstance(profile, dict) else str(key)
        return label or str(key)

    def profile_context(self, value: dict[str, Any] | None) -> tuple[str, str]:
        fallback = self._default_codec()
        return _profile_codec(value, fallback), _profile_encoder(value)

    def profile_display_name(self, key: str, value: dict[str, Any] | None = None) -> str:
        profile = value if isinstance(value, dict) else self.data.get(key, {})
        codec, encoder = self.profile_context(profile if isinstance(profile, dict) else {})
        return f"{self.profile_label(key, profile)}  —  {_codec_display(codec)} / {encoder.upper()}"

    def user_display_choices(self) -> list[tuple[str, str]]:
        choices: list[tuple[str, str]] = []
        used: set[str] = set()
        for key, value in sorted(self._user.items()):
            display = self.profile_display_name(key, value)
            if display in used:
                display = f"{display}  ({key})"
            used.add(display)
            choices.append((display, key))
        return choices

    def key_for_user_label(self, label: str, value: dict[str, Any]) -> str:
        label = str(label or "").strip()
        if not label:
            label = "Profil"
        wanted_label = _normalise_profile_label(label)
        wanted_context = self.profile_context(value)

        for key, profile in self._user.items():
            if (
                _normalise_profile_label(self.profile_label(key, profile)) == wanted_label
                and self.profile_context(profile) == wanted_context
            ):
                return key

        base = _slugify_profile_label(label)
        codec, encoder = wanted_context
        candidate_base = f"{base}_{codec}_{encoder}"
        candidate = candidate_base
        counter = 2
        while candidate in _DEFAULTS or candidate in self._user:
            candidate = f"{candidate_base}_{counter}"
            counter += 1
        return candidate

    def delete(self, key: str) -> bool:
        if key in _DEFAULTS: return False
        if key in self._user: del self._user[key]; self.save(); return True
        return False

    def is_builtin(self, key: str) -> bool: return key in _DEFAULTS
    def all_keys(self) -> list[str]: return list(self.data.keys())
    def keys_for_encoder(self, encoder: str) -> list[str]:
        return [k for k in _DEFAULTS if k.endswith(f"_{encoder}")]
