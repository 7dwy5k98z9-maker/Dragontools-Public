from __future__ import annotations

from types import SimpleNamespace

from dragontools.core.quality_target import QualityTargetConfig, adaptive_quality_search
from dragontools.worker.quality_target_integration import apply_automatic_quality_target
from dragontools.worker.quality_target_service import AutomaticQualityTargetService


def test_quality_target_config_normalizes_range_and_limits():
    cfg = QualityTargetConfig.from_encoder_options({
        "quality_target_enabled": True,
        "quality_target_vmaf": 105,
        "quality_target_samples": 99,
        "quality_target_sample_duration_s": 1,
        "quality_target_min": 35,
        "quality_target_max": 12,
    })
    assert cfg.enabled is True
    assert cfg.target_vmaf == 100.0
    assert cfg.sample_count == 10
    assert cfg.sample_duration_s == 2.0
    assert (cfg.min_quality, cfg.max_quality) == (12, 35)


def test_adaptive_search_returns_max_immediately_when_it_passes():
    calls = []
    selected, evaluations, met = adaptive_quality_search(
        min_quality=18,
        max_quality=30,
        target_vmaf=95.0,
        evaluate=lambda q: calls.append(q) or 96.0,
    )
    assert selected == 30
    assert met is True
    assert calls == [30]
    assert [item.quality for item in evaluations] == [30]


def test_adaptive_search_finds_highest_passing_integer():
    # Q25 = 95.1, Q26 = 94.4; gesucht ist damit exakt Q25.
    def score(q: int) -> float:
        return 100.0 - (q - 18) * 0.7

    selected, evaluations, met = adaptive_quality_search(
        min_quality=18,
        max_quality=30,
        target_vmaf=95.0,
        evaluate=score,
    )
    assert selected == 25
    assert met is True
    measured = {item.quality for item in evaluations}
    assert 18 in measured and 30 in measured and 25 in measured


def test_adaptive_search_fails_closed_when_even_minimum_misses_target():
    selected, _evaluations, met = adaptive_quality_search(
        min_quality=18,
        max_quality=30,
        target_vmaf=99.0,
        evaluate=lambda _q: 97.0,
    )
    assert selected is None
    assert met is False


def test_quality_option_mapping_is_encoder_specific():
    base = {"encoder": "nvenc", "cq": 23}
    assert AutomaticQualityTargetService.options_for_quality(base, 26)["cq"] == 26
    assert AutomaticQualityTargetService.options_for_quality({"encoder": "qsv"}, 24)["q"] == 24
    assert AutomaticQualityTargetService.options_for_quality({"encoder": "amf"}, 21)["qp"] == 21
    assert AutomaticQualityTargetService.options_for_quality({"encoder": "cpu"}, 20)["crf"] == 20
    assert base["cq"] == 23  # Eingabe darf nicht mutiert werden.


class _NoopRunner:
    def run(self, *_args, **_kwargs):
        raise AssertionError("Runner darf in diesem Test nicht aufgerufen werden")


class _NoopMetrics:
    pass


def _service(*, log=None):
    return AutomaticQualityTargetService(
        tools=SimpleNamespace(ffmpeg="ffmpeg", ffprobe="ffprobe"),
        process_runner=_NoopRunner(),
        metrics=_NoopMetrics(),
        log=log or (lambda *_args: None),
        is_aborted=lambda: False,
    )


def test_hdr_source_skips_automatic_target_and_keeps_fixed_value():
    service = _service()
    media = SimpleNamespace(is_hdr=True, has_dv=False, has_hdrplus=False, duration_s=100.0, primary_video=None)
    result = service.resolve(
        input_path="movie.mkv",
        media_info=media,
        codec="h265",
        fixed_quality=23,
        preset="p6",
        encoder_options={"encoder": "nvenc", "quality_target_enabled": True},
        scale_mode="original",
    )
    assert result.attempted is True
    assert result.applied is False
    assert "HDR" in result.reason



def test_unknown_duration_skips_search_fail_closed():
    service = _service()
    media = SimpleNamespace(is_hdr=False, has_dv=False, has_hdrplus=False, duration_s=0.0, primary_video=None)
    result = service.resolve(
        input_path="movie.mkv", media_info=media, codec="h265", fixed_quality=23, preset="medium",
        encoder_options={"encoder": "cpu", "quality_target_enabled": True}, scale_mode="original",
    )
    assert result.attempted is True
    assert result.applied is False
    assert "laufzeit" in result.reason.casefold()


def test_service_binary_search_applies_measured_quality(monkeypatch):
    logs = []
    service = _service(log=lambda msg, level="info": logs.append((level, msg)))
    media = SimpleNamespace(is_hdr=False, has_dv=False, has_hdrplus=False, duration_s=1800.0, primary_video=None)

    monkeypatch.setattr(service, "_encode_segment", lambda **_kwargs: None)

    def fake_measure(_input, output_path, _segment):
        q = int(output_path.split("q")[-1].split("_")[0])
        return 100.0 - (q - 18) * 0.7

    monkeypatch.setattr(service, "_measure_vmaf", fake_measure)
    result = service.resolve(
        input_path="movie.mkv",
        media_info=media,
        codec="h265",
        fixed_quality=23,
        preset="p6",
        encoder_options={
            "encoder": "nvenc",
            "cq": 23,
            "quality_target_enabled": True,
            "quality_target_vmaf": 95.0,
            "quality_target_samples": 3,
            "quality_target_sample_duration_s": 10,
            "quality_target_min": 18,
            "quality_target_max": 30,
        },
        scale_mode="original",
    )
    assert result.applied is True
    assert result.selected_quality == 25
    assert result.selected_vmaf is not None and result.selected_vmaf >= 95.0
    assert any("CQ 25" in message for _level, message in logs)


def test_workflow_integration_updates_only_current_effective_settings():
    class Service:
        @staticmethod
        def resolve(**_kwargs):
            return SimpleNamespace(
                attempted=True, applied=True, selected_quality=25,
                selected_vmaf=95.4, reason="Ziel erreicht",
            )

        @staticmethod
        def options_for_quality(options, value):
            data = dict(options); data["cq"] = value; return data

    ctx = SimpleNamespace(
        strip_only=False,
        input_path="a.mkv",
        analysis=SimpleNamespace(),
        effective_codec="h265",
        effective_crf=23,
        effective_preset="p6",
        effective_encoder_options={"encoder": "nvenc", "cq": 23},
        effective_scale_mode="original",
    )
    apply_automatic_quality_target(ctx, Service())
    assert ctx.effective_crf == 25
    assert ctx.effective_encoder_options["cq"] == 25
    assert ctx.quality_target_applied is True
    assert ctx.quality_target_vmaf == 95.4


def test_workflow_integration_keeps_fixed_value_when_target_not_applied():
    class Service:
        @staticmethod
        def resolve(**_kwargs):
            return SimpleNamespace(
                attempted=True, applied=False, selected_quality=None,
                selected_vmaf=None, reason="nicht erreichbar",
            )

    ctx = SimpleNamespace(
        strip_only=False, input_path="a.mkv", analysis=SimpleNamespace(),
        effective_codec="h265", effective_crf=23, effective_preset="medium",
        effective_encoder_options={"encoder": "cpu"}, effective_scale_mode="original",
    )
    apply_automatic_quality_target(ctx, Service())
    assert ctx.effective_crf == 23
    assert ctx.effective_encoder_options == {"encoder": "cpu"}
    assert ctx.quality_target_applied is False
    assert ctx.quality_target_reason == "nicht erreichbar"
