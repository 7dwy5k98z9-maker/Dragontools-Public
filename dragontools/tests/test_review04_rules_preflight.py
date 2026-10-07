from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.batch_preflight_decisions import _warnings_for
from dragontools.core.batch_preflight_storage import _can_write_probe
from dragontools.core.models import (
    AudioStream,
    MediaInfo,
    SubtitleStream,
    VideoStream,
    normalize_override_dict,
)
from dragontools.core.rules_preview import build_rules_preview
from dragontools.gui.convert_widget_recovery import ConvertWidgetRecoveryService
from dragontools.gui.preflight_metadata_common import MetadataRequestGuard, metadata_job_identity
from dragontools.rules.audio_plan import compute_audio_track_plan
from dragontools.rules.pipeline_selector import resolve_pipeline_context
from dragontools.rules.subtitle_plan_service import compute_subtitle_plan_service
from dragontools.worker.converter_file_executor import ConverterFileExecutor
import dragontools.worker.converter_optional_runtime as optional_runtime


def _pq_media(*, dv: bool = False, hdr10plus: bool = False, codec: str = "hevc") -> MediaInfo:
    video = VideoStream(
        index=0,
        codec=codec,
        width=3840,
        height=2160,
        hdr_format="dolby_vision" if dv else ("hdr10plus" if hdr10plus else None),
        has_dolby_vision=dv,
        has_hdr10plus=hdr10plus,
        color_transfer="smpte2084",
        color_primaries="bt2020",
    )
    return MediaInfo(
        path="movie.mkv",
        audio_streams=[],
        subtitle_streams=[],
        video_streams=[video],
        is_hdr=True,
        has_hdr10plus=hdr10plus,
        dolby_vision=dv,
        dv_profile="8" if dv else None,
        dv_profile_major=8 if dv else None,
    )


def test_override_normalization_is_idempotent_for_legacy_and_warnings():
    raw = {
        "audio_action": "copy",
        "burn_mode": "selected",
        "burn_stream_index": 3,
        "subtitle_tracks": [
            {"index": 1, "keep": True, "burn_in": True},
            {"index": 2, "keep": True, "burn_in": True},
        ],
    }
    first = normalize_override_dict(raw)
    second = normalize_override_dict(first)

    assert second == first
    assert second["_legacy"] == {
        "audio_action": "copy",
        "burn_mode": "selected",
        "burn_stream_index": 3,
    }
    assert second["_warnings"] == first["_warnings"]


@pytest.mark.parametrize("value, expected", [(True, True), (False, False), ("true", True), ("0", False)])
def test_runtime_only_override_fields_survive_normalization(value, expected):
    result = normalize_override_dict(
        {"allow_suspicious_source": value, "generate_hdr10plus": value}
    )
    assert result["allow_suspicious_source"] is expected
    assert result["generate_hdr10plus"] is expected


def test_legacy_subtitle_selection_survives_worker_style_double_normalization():
    streams = [
        SubtitleStream(index=1, language="de", forced=False, title="Full", codec="subrip"),
        SubtitleStream(index=3, language="de", forced=True, title="Forced", codec="subrip"),
    ]
    normalized_once = normalize_override_dict(
        {"burn_mode": "selected", "burn_stream_index": 3}
    )
    plan = compute_subtitle_plan_service(
        streams,
        file_override=normalized_once,
        container_copy_supported=True,
    )
    assert plan.override_mode == "custom"
    assert plan.burn_sub is not None
    assert plan.burn_sub.index == 3


def test_legacy_audio_action_survives_worker_style_double_normalization():
    stream = AudioStream(
        index=1,
        language="de",
        forced=False,
        title="Deutsch",
        codec="dts",
        channels=6,
        bitrate=1_500_000,
    )
    normalized_once = normalize_override_dict({"audio_action": "copy"})
    plan = compute_audio_track_plan(
        [stream],
        file_override=normalized_once,
        container="mkv",
        rules={"language_priority": [], "force_priority": False},
        apply_language_rules=False,
    )
    assert len(plan) == 1
    assert plan[0].needs_transcode is False
    assert plan[0].target_codec == "dts"


def test_allow_suspicious_source_really_bypasses_visual_check_after_normalization():
    calls = []
    service = SimpleNamespace(check=lambda *_args, **_kwargs: calls.append(True))
    worker = SimpleNamespace(
        _services=SimpleNamespace(source_visual_check=service),
        settings=object(),
        log=lambda *_args, **_kwargs: None,
    )
    executor = ConverterFileExecutor(worker)
    override = normalize_override_dict({"allow_suspicious_source": True})

    assert executor._check_source_visual_quality("movie.mkv", override) is True
    assert calls == []


def test_per_file_hdr10plus_generator_can_enable_global_off():
    ctx = resolve_pipeline_context(
        _pq_media(),
        codec="h265",
        file_override={"generate_hdr10plus": True},
        hdr10plus_generator_enabled=False,
        hdr10plus_generator_available=True,
    )
    assert ctx["per_file_generate_hdr10plus"] is True
    assert ctx["effective_hdr10plus_generator_enabled"] is True
    assert ctx["generate_hdr10plus"] is True
    assert getattr(ctx["pipeline"], "value", ctx["pipeline"]) == "hdrplus"


def test_per_file_hdr10plus_generator_can_disable_global_on():
    ctx = resolve_pipeline_context(
        _pq_media(),
        codec="h265",
        file_override={"generate_hdr10plus": False},
        hdr10plus_generator_enabled=True,
        hdr10plus_generator_available=True,
    )
    assert ctx["per_file_generate_hdr10plus"] is False
    assert ctx["effective_hdr10plus_generator_enabled"] is False
    assert ctx["generate_hdr10plus"] is False
    assert getattr(ctx["pipeline"], "value", ctx["pipeline"]) == "standard"


def test_pipeline_context_exposes_effective_generator_flag_for_postprocessing():
    inherited = resolve_pipeline_context(
        _pq_media(),
        codec="h265",
        hdr10plus_generator_enabled=True,
        hdr10plus_generator_available=False,
    )
    assert inherited["effective_hdr10plus_generator_enabled"] is True
    assert inherited["hdr10plus_generator_available"] is False


def test_rules_preview_uses_actual_global_preserve_policy_from_encoder_options():
    preview = build_rules_preview(
        "movie.mkv",
        codec="h265",
        media_info=_pq_media(dv=True),
        default_encoder_options={"preserve_dv": False, "preserve_hdrplus": True},
    )
    assert preview["effective_preserve_dv"] is False
    assert preview["pipeline"] == "standard"


def test_rules_preview_uses_generator_policy_and_availability():
    preview = build_rules_preview(
        "movie.mkv",
        codec="h265",
        media_info=_pq_media(),
        file_override={"generate_hdr10plus": True},
        default_encoder_options={"hdr10plus_generator_enabled": False},
        hdr10plus_generator_available=True,
    )
    assert preview["effective_hdr10plus_generator_enabled"] is True
    assert preview["generate_hdr10plus"] is True
    assert preview["target_container"] == "mkv"
    assert preview["pipeline"] == "hdrplus"


def test_rules_preview_exposes_capability_warnings_and_batch_marks_them():
    preview = build_rules_preview(
        "movie.mkv",
        codec="h265",
        media_info=_pq_media(dv=True, codec="h264"),
        default_encoder_options={"preserve_dv": True},
    )
    assert preview["capability_warnings"]
    warnings, _error = _warnings_for("movie.mkv", preview)
    assert any("Dolby Vision" in warning for warning in warnings)


class _FileList:
    def add_path(self, _path: str) -> bool:
        return True

    def count(self) -> int:
        return 0


def test_recovery_preflight_forwards_current_preview_options(monkeypatch):
    import dragontools.gui.convert_widget_recovery as module

    captured = {}

    def fake_builder(*_args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(module, "build_batch_preflight_rows", fake_builder)
    state = SimpleNamespace(file_overrides={}, preflight_rows_by_path={})
    service = ConvertWidgetRecoveryService(
        state=state,
        file_list=_FileList(),
        log=lambda *_args, **_kwargs: None,
        active_worker=lambda: None,
        refresh_queue=lambda: None,
        update_label=lambda _path: None,
        default_codec="h265",
        get_subtitle_rules=lambda: {},
        overwrite_original=lambda: False,
        get_tools=lambda: "TOOLS",
        get_preview_options=lambda: {
            "default_crf": 19,
            "default_preset": "slow",
            "standard_container": "mp4",
            "dv_container": "mkv",
            "default_encoder_options": {"preserve_dv": False},
        },
    )

    service.build_preflight_report_rows(["A.mkv"], {})

    assert captured["preview_options"]["default_crf"] == 19
    assert captured["preview_options"]["standard_container"] == "mp4"
    assert captured["preview_options"]["dv_container"] == "mkv"
    assert captured["preview_options"]["default_encoder_options"]["preserve_dv"] is False


def test_write_probe_is_not_blocked_by_stale_pid_probe(tmp_path: Path):
    stale = tmp_path / f".dragontools_preflight_{os.getpid()}.tmp"
    stale.write_bytes(b"stale")

    ok, error = _can_write_probe(tmp_path)

    assert ok is True
    assert error is None
    assert stale.read_bytes() == b"stale"


def test_metadata_request_guard_invalidates_older_async_request():
    target = object()
    guard = MetadataRequestGuard()
    first = guard.begin(target)
    second = guard.begin(target)

    assert first != second
    assert guard.is_current(target, first) is False
    assert guard.is_current(target, second) is True


def test_metadata_job_identity_is_fail_closed_for_malformed_jobs():
    assert metadata_job_identity(("series", "ranma", {})) == ("series", "ranma")
    assert metadata_job_identity(None) is None
    assert metadata_job_identity(("series",)) is None
    assert metadata_job_identity(["series", "ranma"]) is None


def test_optional_runtime_probes_generator_for_per_file_enable_when_global_off(monkeypatch):
    calls = []

    class Client:
        def __init__(self, executable, **kwargs):
            calls.append((executable, kwargs))

        def probe_version(self):
            return SimpleNamespace(success=True, version="1.2.3", error="", message="")

    worker = SimpleNamespace(
        _job_state=SimpleNamespace(
            file_overrides={"movie.mkv": {"generate_hdr10plus": True}}
        ),
        log=lambda *_args, **_kwargs: None,
    )
    tools = SimpleNamespace(
        hdr10plus_generator="generator.exe",
        ffmpeg="ffmpeg.exe",
        ffprobe="ffprobe.exe",
    )
    options = {"hdr10plus_generator_enabled": False}
    monkeypatch.setattr(optional_runtime, "generator_executable_available", lambda _path: True)
    monkeypatch.setattr(optional_runtime, "HDR10PlusGeneratorClient", Client)

    optional_runtime._configure_hdr10plus_generator(worker, tools, options)

    assert len(calls) == 1
    assert options["_hdr10plus_generator_available"] is True
    assert options["_hdr10plus_generator_version"] == "1.2.3"


def test_optional_runtime_does_not_probe_generator_without_any_request(monkeypatch):
    worker = SimpleNamespace(
        _job_state=SimpleNamespace(file_overrides={}),
        log=lambda *_args, **_kwargs: None,
    )
    tools = SimpleNamespace(hdr10plus_generator="generator.exe")
    options = {"hdr10plus_generator_enabled": False}
    calls = []
    monkeypatch.setattr(
        optional_runtime,
        "generator_executable_available",
        lambda _path: calls.append(True) or True,
    )

    optional_runtime._configure_hdr10plus_generator(worker, tools, options)

    assert calls == []
    assert options["_hdr10plus_generator_available"] is False


def test_normalized_generator_and_visual_flags_remain_idempotent():
    first = normalize_override_dict(
        {"generate_hdr10plus": True, "allow_suspicious_source": True}
    )
    assert normalize_override_dict(first) == first


def test_rule_loader_fallback_is_deeply_isolated(tmp_path: Path):
    from dragontools.rules.rule_loader import load_json_rules

    default = {"nested": {"languages": ["de", "en"]}}
    loaded = load_json_rules(tmp_path / "missing.json", default=default)
    loaded["nested"]["languages"].append("ja")

    assert default == {"nested": {"languages": ["de", "en"]}}


def test_corrupt_user_rules_without_python_default_use_packaged_default(tmp_path: Path, monkeypatch):
    import dragontools.rules.rule_loader as loader

    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    user_path = rules_dir / "demo_rules.json"
    user_path.write_text("{broken", encoding="utf-8")
    packaged = tmp_path / "default_demo_rules.json"
    packaged.write_text('{"nested": {"enabled": true}}', encoding="utf-8")

    monkeypatch.setattr(loader, "_rules_dir", lambda: rules_dir)
    monkeypatch.setattr(loader, "_default_rules_path", lambda _name: packaged)

    loaded = loader.load_named_rules("demo_rules")

    assert loaded == {"nested": {"enabled": True}}
    assert not user_path.exists()
    backups = list(rules_dir.glob("demo_rules.corrupt_*.json"))
    assert len(backups) == 1


@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX mount grouping")
def test_storage_group_key_uses_posix_device_id(monkeypatch):
    import dragontools.core.batch_preflight_rows as rows

    original_stat = Path.stat

    def fake_stat(self, *args, **kwargs):
        value = str(self)
        if value.startswith("/mnt/alpha"):
            return SimpleNamespace(st_dev=11)
        if value.startswith("/mnt/beta"):
            return SimpleNamespace(st_dev=22)
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)

    assert rows._storage_group_key("/mnt/alpha/output") == "dev:11"
    assert rows._storage_group_key("/mnt/beta/output") == "dev:22"
    assert rows._storage_group_key("/mnt/alpha/other") == "dev:11"


@pytest.mark.parametrize(
    "kwargs, expected_fragment",
    [
        ({"standard_container": "avi", "dv_container": "mp4"}, "Standard-Ausgabecontainer"),
        ({"standard_container": "mkv", "dv_container": "mov"}, "DV-Ausgabecontainer"),
        ({"standard_container": "", "dv_container": "mp4"}, "Standard-Ausgabecontainer"),
    ],
)
def test_pipeline_container_selection_fails_closed_for_invalid_explicit_values(kwargs, expected_fragment):
    from dragontools.rules.pipeline_policy import resolve_target_container
    from dragontools.core.models import Pipeline

    with pytest.raises(ValueError, match=expected_fragment):
        resolve_target_container(Pipeline.STANDARD, **kwargs)


@pytest.mark.parametrize(
    "target_codec, source_codec, has_dv, has_hdr10plus, preserve_dv, preserve_hdr10plus, standard_container, dv_container, override",
    [
        ("h265", "hevc", True, False, True, True, "mkv", "mp4", {}),
        ("h265", "hevc", True, False, False, True, "mp4", "mkv", {}),
        ("h265", "hevc", False, True, True, True, "mp4", "mkv", {}),
        ("av1", "hevc", True, True, True, True, "mkv", "mp4", {}),
        ("av1", "av1", False, True, True, True, "mp4", "mkv", {}),
        ("h264", "hevc", True, True, True, True, "mkv", "mp4", {}),
        ("h265", "hevc", True, True, True, True, "mp4", "mkv", {"preserve_dv": False}),
    ],
)
def test_preview_pipeline_and_container_match_runtime_decision(
    target_codec,
    source_codec,
    has_dv,
    has_hdr10plus,
    preserve_dv,
    preserve_hdr10plus,
    standard_container,
    dv_container,
    override,
):
    from dragontools.core.settings_conversion import (
        SET_KEY_AV1_PRESERVE_DV,
        SET_KEY_AV1_PRESERVE_HDRPLUS,
        SET_KEY_OUTPUT_CONTAINER_DV,
        SET_KEY_OUTPUT_CONTAINER_STANDARD,
        SET_KEY_PRESERVE_DV,
        SET_KEY_PRESERVE_HDRPLUS,
    )
    from dragontools.worker.pipeline_decision_service import PipelineDecisionService

    mi = _pq_media(dv=has_dv, hdr10plus=has_hdr10plus, codec=source_codec)
    encoder_options = {
        "preserve_dv": preserve_dv,
        "preserve_hdrplus": preserve_hdr10plus,
        "hdr10plus_generator_enabled": False,
    }
    preview = build_rules_preview(
        "movie.mkv",
        codec=target_codec,
        media_info=mi,
        file_override=override,
        default_encoder_options=encoder_options,
        standard_container=standard_container,
        dv_container=dv_container,
    )

    class Settings:
        values = {
            SET_KEY_OUTPUT_CONTAINER_STANDARD: standard_container,
            SET_KEY_OUTPUT_CONTAINER_DV: dv_container,
            SET_KEY_PRESERVE_DV: preserve_dv,
            SET_KEY_PRESERVE_HDRPLUS: preserve_hdr10plus,
            SET_KEY_AV1_PRESERVE_DV: preserve_dv,
            SET_KEY_AV1_PRESERVE_HDRPLUS: preserve_hdr10plus,
        }

        def value(self, key, default=None, type=None):
            value = self.values.get(key, default)
            return type(value) if type is not None else value

    class Logger:
        def info(self, *_args, **_kwargs):
            return None

        def info_short(self, *_args, **_kwargs):
            return None

    class Archive:
        def archive_original(self, *_args, **_kwargs):
            return None

    service = PipelineDecisionService(
        codec=target_codec,
        encoder_options=encoder_options,
        file_overrides={"movie.mkv": override},
        settings=Settings(),
        logger=Logger(),
        archive_service=Archive(),
    )
    runtime_pipeline, runtime_container = service.select_pipeline_context("movie.mkv", mi)

    assert preview["pipeline"] == runtime_pipeline
    assert preview["target_container"] == runtime_container


def _sdr_bt709_media() -> MediaInfo:
    video = VideoStream(
        index=0,
        codec="hevc",
        width=1920,
        height=1080,
        color_transfer="bt709",
        color_primaries="bt709",
        color_space="bt709",
    )
    return MediaInfo(
        path="sdr.mkv",
        audio_streams=[],
        subtitle_streams=[],
        video_streams=[video],
        is_hdr=False,
        has_hdr10plus=False,
        dolby_vision=False,
    )


def test_rules_preview_exposes_sdr_hdr_request_without_pretending_runtime_capability():
    from dragontools.core.batch_preflight_formatting import _hdr_summary

    preview = build_rules_preview(
        "sdr.mkv",
        codec="h265",
        media_info=_sdr_bt709_media(),
        default_encoder_options={
            "sdr_hdr_enabled": True,
            "sdr_hdr_backend": "ffmpeg",
        },
    )

    assert preview["sdr_hdr_requested"] is True
    assert preview["sdr_hdr_capability_known"] is False
    assert preview["sdr_hdr_applied"] is False
    assert "Runtime-Prüfung" in _hdr_summary(preview)


def test_per_file_sdr_hdr_override_is_reflected_in_preview():
    preview = build_rules_preview(
        "sdr.mkv",
        codec="h265",
        media_info=_sdr_bt709_media(),
        file_override={"sdr_hdr": False},
        default_encoder_options={
            "sdr_hdr_enabled": True,
            "sdr_hdr_backend": "ffmpeg",
        },
    )

    assert preview["sdr_hdr_requested"] is False


def test_rules_preview_reports_sdr_hdr_applied_when_runtime_capability_is_known():
    from dragontools.core.batch_preflight_formatting import _hdr_summary

    preview = build_rules_preview(
        "sdr.mkv",
        codec="h265",
        media_info=_sdr_bt709_media(),
        default_encoder_options={
            "sdr_hdr_enabled": True,
            "sdr_hdr_backend": "ffmpeg",
            "_sdr_hdr_libplacebo_available": True,
        },
    )

    assert preview["sdr_hdr_capability_known"] is True
    assert preview["sdr_hdr_applied"] is True
    assert _hdr_summary(preview) == "SDR → HDR"
