# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from dragontools.worker import converter_detection
from dragontools.worker.converter_detection import (
    ConverterDetectionHelper,
    _autocrop_probe_offsets,
    _imax_probe_offsets,
    _sanitize_imax_interval,
)


def test_imax_probe_offsets_nutzen_einstellbares_intervall():
    assert _sanitize_imax_interval(5) == 30
    assert _sanitize_imax_interval(90) == 90
    assert _sanitize_imax_interval(999) == 600
    assert _imax_probe_offsets(400, 90) == [60, 150, 240, 330]
    assert _autocrop_probe_offsets(1500, start_s=30, interval_s=600) == [30, 630, 1230]


def test_imax_auto_erkennt_wechselnde_aktive_bildflaeche(monkeypatch):
    calls: list[int] = []

    def fake_run(cmd, **_kwargs):
        offset = int(cmd[cmd.index("-ss") + 1])
        calls.append(offset)
        if offset < 200:
            crop = "crop=1920:1080:0:0"
        else:
            crop = "crop=1920:804:0:138"
        return SimpleNamespace(stdout="", stderr=f"[Parsed_cropdetect_0] {crop}\n")

    monkeypatch.setattr(converter_detection.subprocess, "run", fake_run)

    worker = SimpleNamespace(
        tools=SimpleNamespace(ffmpeg="ffmpeg"),
        log=lambda *_args: None,
    )
    helper = ConverterDetectionHelper(worker)

    detected = helper.detect_imax_auto(
        "film.mkv",
        duration_s=400,
        source_w=1920,
        source_h=1080,
        interval_s=90,
    )

    assert detected is True
    assert calls == [60, 150, 240, 330]


def test_imax_auto_respektiert_mindestanzahl_verwertbarer_punkte(monkeypatch):
    def fake_run(cmd, **_kwargs):
        offset = int(cmd[cmd.index("-ss") + 1])
        crop = "crop=1920:1080:0:0" if offset < 200 else "crop=1920:804:0:138"
        return SimpleNamespace(stdout="", stderr=f"[Parsed_cropdetect_0] {crop}\n")

    monkeypatch.setattr(converter_detection.subprocess, "run", fake_run)

    worker = SimpleNamespace(
        tools=SimpleNamespace(ffmpeg="ffmpeg"),
        log=lambda *_args: None,
    )
    helper = ConverterDetectionHelper(worker)

    detected = helper.detect_imax_auto(
        "film.mkv",
        duration_s=400,
        source_w=1920,
        source_h=1080,
        interval_s=90,
        probe_duration_s=3,
        min_variance_percent=15,
        min_hits=5,
    )

    assert detected is False


def test_imax_auto_bleibt_aus_bei_konstanter_aktiver_bildflaeche(monkeypatch):
    def fake_run(cmd, **_kwargs):
        return SimpleNamespace(stdout="", stderr="[Parsed_cropdetect_0] crop=1920:804:0:138\n")

    monkeypatch.setattr(converter_detection.subprocess, "run", fake_run)

    worker = SimpleNamespace(
        tools=SimpleNamespace(ffmpeg="ffmpeg"),
        log=lambda *_args: None,
    )
    helper = ConverterDetectionHelper(worker)

    detected = helper.detect_imax_auto(
        "film.mkv",
        duration_s=400,
        source_w=1920,
        source_h=1080,
        interval_s=90,
    )

    assert detected is False
