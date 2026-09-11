# -*- coding: utf-8 -*-
"""Worker- und Config-Erzeugung für die Conversion-GUI.

Dieses Modul hält die fachliche Abbildung der GUI-Einstellungen auf
:class:`ConverterConfig` sowie die Auswahl zwischen Single- und
Parallel-Worker außerhalb des Qt-Controllers.
"""
from __future__ import annotations

from typing import Callable

from ..rules.rule_loader import load_subtitle_rules
from ..worker.converter_config import ConverterConfig


_SCALE_MAP = {
    "original": "original",
    "4K (2160p)": "4k",
    "1080p": "1080p",
    "720p": "720p",
    "480p": "480p",
}


class ConversionConfigBuilder:
    """Baut unveränderliche Worker-Konfiguration aus GUI- und Session-Zustand."""

    def __init__(
        self,
        *,
        state,
        ui,
        default_codec: str,
        collect_encoder_options: Callable[[], dict],
        get_target_paths: Callable[[], dict[str, str]],
        log: Callable,
    ) -> None:
        self._state = state
        self._ui = ui
        self._default_codec = default_codec
        self._collect_encoder_options = collect_encoder_options
        self._get_target_paths = get_target_paths
        self._log = log

    def subtitle_rules(self) -> dict:
        fallback = {
            "language_priority": ["de", "en"],
            "max_languages": 1,
            "tracks_per_language": 1,
            "fallback_if_no_priority_match": "keep_none",
            "preferred_languages": ["de", "deu", "ger"],
            "fallback_languages": ["en", "eng"],
            "preferred_formats": ["subrip", "ass", "hdmv_pgs_subtitle", "dvd_subtitle"],
            "force_priority": True,
            "burn_in_rules": {
                "auto_burn_forced": True,
                "burn_language": "de",
                "burn_fallback": "none",
                "ask_if_ambiguous": True,
                "never_burn_if_no_audio_language": False,
                "never_burn_if_no_german_audio": False,
                "forced_plausibility": {
                    "enabled": True,
                    "warn_events_per_minute": 3.0,
                    "block_events_per_minute": 5.0,
                },
            },
            "keep_rules": {
                "keep_forced": True,
                "keep_selected_languages": True,
                "keep_regular": True,
                "keep_if_no_burn_only": False,
                "keep_all_german": True,
                "keep_german_if_no_burn": False,
                "keep_english_fallback": False,
            },
            "mp4_sidecars_enabled": True,
            "additional_sidecars_enabled": False,
            "text_to_srt_sidecar_enabled": False,
        }
        return load_subtitle_rules(default=fallback, reporter=self._log)

    def build_converter_config(self, *, encoder_options: dict | None = None) -> ConverterConfig:
        ui = self._ui
        paths = self._get_target_paths()
        return ConverterConfig(
            codec=self._default_codec,
            crf=ui.crf_spin.value(),
            preset=ui.preset_combo.currentText(),
            scale_mode=_SCALE_MAP.get(ui.scale_combo.currentText(), "original"),
            overwrite_original=ui.over_cb.isChecked(),
            strip_only=ui.strip_cb.isChecked(),
            encoder_options=dict(encoder_options or self._collect_encoder_options()),
            file_overrides=dict(self._state.file_overrides),
            tv_path=paths.get("tv") or None,
            anime_path=paths.get("anime") or None,
            filme_path=paths.get("film") or None,
            subtitle_rules=self.subtitle_rules(),
        )

    def dv_remux_options(self) -> dict:
        """Liefert die fachlichen Parameter für den DVRemuxThread."""
        return {
            "overwrite_original": bool(self._ui.over_cb.isChecked()),
            "encoder_options": self._collect_encoder_options(),
            "file_overrides": dict(self._state.file_overrides),
            "subtitle_rules": self.subtitle_rules(),
        }


class ConversionWorkerFactory:
    """Erzeugt die konkreten Worker; kennt keine Run-/UI-Lifecycle-Logik."""

    def __init__(
        self,
        *,
        config_builder: ConversionConfigBuilder,
        qt_parent,
        converter_cls=None,
        parallel_converter_cls=None,
        dv_remux_cls=None,
    ) -> None:
        self._config_builder = config_builder
        self._qt_parent = qt_parent
        self._converter_cls = converter_cls
        self._parallel_converter_cls = parallel_converter_cls
        self._dv_remux_cls = dv_remux_cls

    def create_converter(
        self,
        files: list[str],
        *,
        encoder_options: dict | None = None,
        parallel_jobs: int = 1,
    ):
        config = self._config_builder.build_converter_config(encoder_options=encoder_options)
        if int(parallel_jobs) > 1:
            parallel_cls = self._parallel_converter_cls
            if parallel_cls is None:
                from ..worker.parallel_converter_thread import ParallelConverterThread
                parallel_cls = ParallelConverterThread
            return parallel_cls(
                files,
                config,
                parallel_jobs=int(parallel_jobs),
                parent=self._qt_parent,
            )
        converter_cls = self._converter_cls
        if converter_cls is None:
            from ..worker.converter_thread import ConverterThread
            converter_cls = ConverterThread
        return converter_cls(files, config, parent=self._qt_parent)

    def create_dv_remux(self, files: list[str]):
        dv_remux_cls = self._dv_remux_cls
        if dv_remux_cls is None:
            from ..worker.dv_remux_thread import DVRemuxThread
            dv_remux_cls = DVRemuxThread

        return dv_remux_cls(
            files,
            parent=self._qt_parent,
            **self._config_builder.dv_remux_options(),
        )
