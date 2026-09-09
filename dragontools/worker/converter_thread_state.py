# -*- coding: utf-8 -*-
"""Gebündelter Runtime-/Session-State für :class:`ConverterThread`.

Die Modelle sind absichtlich Qt-unabhängig. Sie reduzieren die zuvor flache
Menge lose gehaltener Attribute am QThread und machen Ownership explizit:

- ``ConverterJobState``: unveränderliche Laufparameter plus bewusst mutable
  Per-Datei-/Regel-Mappings.
- ``ConverterControlState``: Pause, Abort und aktueller Child-Prozess.
- ``ConverterSessionState``: Ergebnis-/Anzeige-/Diagnosezustand eines Laufs.
- ``ConverterServiceRegistry``: Composition-Root-Container für Services; keine
  Fachlogik und keine implizite Service-Erzeugung.

``NestedStateAlias`` dient ausschließlich als dünne Kompatibilitätsbrücke für
bestehende Aufrufer, die historische Worker-Attribute direkt lesen/setzen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from subprocess import Popen
import threading
from typing import Any

from .converter_config import ConverterConfig


class NestedStateAlias:
    """Descriptor für verhaltensfreie Legacy-Aliase auf ein Context-Feld."""

    __slots__ = ("_container_name", "_field_name")

    def __init__(self, container_name: str, field_name: str) -> None:
        self._container_name = container_name
        self._field_name = field_name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        container = object.__getattribute__(instance, self._container_name)
        return getattr(container, self._field_name)

    def __set__(self, instance, value) -> None:
        container = object.__getattribute__(instance, self._container_name)
        setattr(container, self._field_name, value)


@dataclass(slots=True)
class ConverterJobState:
    codec: str
    crf: int
    preset: str
    scale_mode: str
    overwrite_original: bool
    strip_only: bool
    encoder_options: dict
    file_overrides: dict
    subtitle_rules: dict
    tv_path: str | None
    anime_path: str | None
    filme_path: str | None

    @classmethod
    def from_config(cls, config: ConverterConfig) -> "ConverterJobState":
        return cls(
            codec=config.codec,
            crf=config.crf,
            preset=config.preset,
            scale_mode=config.scale_mode,
            overwrite_original=bool(config.overwrite_original),
            strip_only=bool(config.strip_only),
            encoder_options=dict(config.encoder_options or {}),
            file_overrides=dict(config.file_overrides or {}),
            subtitle_rules=dict(config.subtitle_rules or {}),
            tv_path=config.tv_path,
            anime_path=config.anime_path,
            filme_path=config.filme_path,
        )


@dataclass(slots=True)
class ConverterControlState:
    abort_requested: bool = False
    abort_type: str | None = None
    paused: bool = False
    pause_event: threading.Event = field(default_factory=threading.Event)
    current_process: Popen | None = None
    process_lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        # Historischer Worker-Vertrag: ein neuer Worker startet nicht pausiert.
        self.pause_event.set()


@dataclass(slots=True)
class ConverterSessionState:
    all_input_files: list[str]
    sidecar_outputs: dict[str, list[str]] = field(default_factory=dict)
    postprocess_outputs: dict[str, list[dict]] = field(default_factory=dict)
    failure_details: dict[str, dict] = field(default_factory=dict)
    keep_verbose_log: bool = False
    suppress_session_header: bool = False
    display_index_by_path: dict[str, int] = field(default_factory=dict)
    display_total: int | None = None
    dv_crop_decisions: dict[str, dict] = field(default_factory=dict)
    dv_crop_decision_lock: threading.Lock = field(default_factory=threading.Lock)
    run_start_ts: float | None = None


@dataclass(slots=True)
class ConverterServiceRegistry:
    """Reiner Service-Container; Service-Erzeugung bleibt in Composition Roots."""

    tools: Any = None

    progress: Any = None
    detection: Any = None
    stream_args: Any = None
    strip: Any = None

    archive: Any = None
    pipeline_decision: Any = None
    output_paths: Any = None
    replace: Any = None
    cleanup: Any = None
    encode_plan: Any = None
    result: Any = None

    hdrplus: Any = None
    media_analysis: Any = None
    standard_pipeline: Any = None
    output_verifier: Any = None
    duration_repair: Any = None
    dv_pipeline: Any = None
    av1_dv_pipeline: Any = None
    av1_hdrplus_pipeline: Any = None
    postprocess: Any = None
    postprocess_coordinator: Any = None
    source_visual_check: Any = None
    workflow_services: Any = None
    workflow_runner: Any = None
