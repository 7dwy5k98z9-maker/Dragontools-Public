from __future__ import annotations

from types import SimpleNamespace

import pytest

from dragontools.core.codec_utils import normalize_target_codec
from dragontools.core.models import MediaInfo, TargetCodec, VideoStream
from dragontools.rules.pipeline_selector import PipelineCapabilityError, resolve_pipeline_context
from dragontools.worker.encoder_args import _vid_args


def _media(*, source_codec="hevc", dv=False, hdrplus=False):
    hdr_format = "dolby_vision" if dv else "hdr10plus" if hdrplus else None
    video = VideoStream(
        index=0,
        codec=source_codec,
        width=3840,
        height=2160,
        hdr_format=hdr_format,
        has_hdr10plus=hdrplus,
        has_dolby_vision=dv,
    )
    return MediaInfo(
        path="film.mkv",
        audio_streams=[],
        subtitle_streams=[],
        video_streams=[video],
        has_hdr10plus=hdrplus,
        dolby_vision=dv,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (TargetCodec.H265, "h265"),
        ("hevc", "h265"),
        ("hvc1", "h265"),
        ("avc", "h264"),
        ("av01", "av1"),
    ],
)
def test_target_codec_normalization_handles_enum_and_aliases(value, expected):
    assert normalize_target_codec(value) == expected


def test_unknown_target_codec_fails_fast():
    with pytest.raises(ValueError, match="Nicht unterstützter Ziel-Codec"):
        normalize_target_codec("bogus")


@pytest.mark.parametrize("target_codec", ["h264"])
def test_dv_preserve_override_cannot_force_incompatible_target(target_codec):
    ctx = resolve_pipeline_context(
        _media(dv=True),
        codec=target_codec,
        file_override={"preserve_dv": True},
    )
    assert ctx["pipeline"] == "standard"
    assert ctx["effective_preserve_dv"] is False
    assert "dv" in ctx["ignored_hdr"]
    assert ctx["should_archive"] is True


@pytest.mark.parametrize("target_codec", ["h264"])
def test_hdrplus_preserve_override_cannot_force_incompatible_target(target_codec):
    ctx = resolve_pipeline_context(
        _media(hdrplus=True),
        codec=target_codec,
        file_override={"preserve_hdrplus": True},
    )
    assert ctx["pipeline"] == "standard"
    assert ctx["effective_preserve_hdrplus"] is False
    assert "hdr10plus" in ctx["ignored_hdr"]
    assert ctx["should_archive"] is True



def test_av1_dv_preserve_selects_dedicated_profile10_pipeline():
    ctx = resolve_pipeline_context(
        _media(dv=True), codec="av1", file_override={"preserve_dv": True}
    )
    assert ctx["pipeline"] == "av1_dv"
    assert ctx["effective_preserve_dv"] is True
    assert ctx["container"] == "mp4"
    assert ctx["should_archive"] is False


def test_av1_hdrplus_preserve_selects_dedicated_pipeline():
    ctx = resolve_pipeline_context(
        _media(hdrplus=True), codec="av1", file_override={"preserve_hdrplus": True}
    )
    assert ctx["pipeline"] == "av1_hdrplus"
    assert ctx["effective_preserve_hdrplus"] is True
    assert ctx["container"] == "mkv"
    assert ctx["should_archive"] is False
    assert any("libaom-av1" in text and "deutlich langsamer" in text for text in ctx["policy_infos"])


def test_av1_dv_has_priority_when_dv_and_hdr10plus_preservation_are_both_active():
    ctx = resolve_pipeline_context(
        _media(dv=True, hdrplus=True),
        codec="av1",
        global_preserve_dv=True,
        global_preserve_hdrplus=True,
    )
    assert ctx["pipeline"] == "av1_dv"
    assert ctx["effective_preserve_dv"] is True
    assert ctx["effective_preserve_hdrplus"] is False
    assert ctx["should_archive"] is False
    assert "hdr10plus" not in ctx["ignored_hdr"]
    assert ctx["capability_warnings"] == []
    assert any("Dolby Vision hat Priorität" in text for text in ctx["policy_infos"])


def test_explicit_av1_hdrplus_override_can_override_automatic_dv_priority():
    ctx = resolve_pipeline_context(
        _media(dv=True, hdrplus=True),
        codec="av1",
        job_pipeline="av1_hdrplus",
    )
    assert ctx["pipeline"] == "av1_hdrplus"
    assert ctx["effective_preserve_dv"] is False
    assert ctx["effective_preserve_hdrplus"] is True
    assert not any("Dolby Vision hat Priorität" in text for text in ctx["policy_infos"])
    assert any("libaom-av1" in text and "deutlich langsamer" in text for text in ctx["policy_infos"])

def test_av1_source_per_file_dv_true_cannot_reenable_dv_pipeline():
    ctx = resolve_pipeline_context(
        _media(source_codec="av1", dv=True),
        codec="h265",
        file_override={"preserve_dv": True},
    )
    assert ctx["pipeline"] == "standard"
    assert ctx["effective_preserve_dv"] is False


@pytest.mark.parametrize(
    ("pipeline", "target", "message"),
    [
        ("dv", "h264", "Dolby Vision"),
        ("hdrplus", "av1", "HDR10\\+"),
    ],
)
def test_explicit_impossible_pipeline_override_fails_before_worker(pipeline, target, message):
    media = _media(dv=pipeline == "dv", hdrplus=pipeline == "hdrplus")
    with pytest.raises(PipelineCapabilityError, match=message):
        resolve_pipeline_context(
            media,
            codec=target,
            job_pipeline=pipeline,
        )


def test_hdrplus_override_rejects_av1_source_even_when_target_is_h265():
    with pytest.raises(PipelineCapabilityError, match="HEVC/H.265-Quelle"):
        resolve_pipeline_context(
            _media(source_codec="av1", hdrplus=True),
            codec="h265",
            job_pipeline="hdrplus",
        )


def test_x265_explicit_zero_tuning_values_are_preserved():
    args = _vid_args(
        "h265",
        23,
        "medium",
        {
            "encoder": "cpu",
            "aq_mode": 0,
            "aq_strength": 0,
            "psy_rd": 0,
            "psy_rdoq": 0,
            "bf": 0,
            "rc_lookahead": 40,
        },
    )
    params = args[args.index("-x265-params") + 1]
    assert "aq-mode=0" in params
    assert "aq-strength=0" in params
    assert "psy-rd=0" in params
    assert "psy-rdoq=0" in params
    assert "bframes=0" in params
    assert "rc-lookahead" not in params


@pytest.mark.parametrize("encoder", ["cpu", "qsv", "amf", "nvenc"])
def test_all_encoders_reject_unknown_target_codec(encoder):
    with pytest.raises(ValueError, match="Ziel-Codec"):
        _vid_args("bogus", 23, "medium", {"encoder": encoder})


def test_unknown_encoder_is_not_silently_treated_as_cpu():
    with pytest.raises(ValueError, match="Encoder"):
        _vid_args("h265", 23, "medium", {"encoder": "mystery"})


def test_encoder_accepts_targetcodec_enum_without_stringification_bug():
    args = _vid_args(TargetCodec.H265, 23, "medium", {"encoder": "cpu"})
    assert args[args.index("-c:v") + 1] == "libx265"


def test_explicit_standard_override_disables_dynamic_metadata_contract_flags():
    media = _media(dv=True, hdrplus=True)
    ctx = resolve_pipeline_context(
        media,
        codec="h265",
        global_preserve_dv=True,
        global_preserve_hdrplus=True,
        job_pipeline="standard",
    )
    assert ctx["pipeline"] == "standard"
    assert ctx["effective_preserve_dv"] is False
    assert ctx["effective_preserve_hdrplus"] is False
    assert ctx["should_archive"] is False


def test_explicit_hdrplus_override_does_not_claim_dv_preservation():
    media = _media(dv=True, hdrplus=True)
    ctx = resolve_pipeline_context(
        media,
        codec="h265",
        job_pipeline="hdrplus",
    )
    assert ctx["pipeline"] == "hdrplus"
    assert ctx["effective_preserve_dv"] is False
    assert ctx["effective_preserve_hdrplus"] is True


def test_dv_hdr10plus_source_with_dv_disabled_selects_hdrplus_without_reenabling_dv():
    media = _media(dv=True, hdrplus=True)
    ctx = resolve_pipeline_context(
        media,
        codec="h265",
        file_override={"preserve_dv": False, "preserve_hdrplus": True},
    )
    assert ctx["pipeline"] == "hdrplus"
    assert ctx["effective_preserve_dv"] is False
    assert ctx["effective_preserve_hdrplus"] is True
    assert ctx["container"] == "mkv"


def test_dv_only_source_does_not_inherit_global_hdr10plus_requirement():
    """Regression: globale HDR10+-Option darf DV-only nicht zu DV+HDR10+ machen."""
    ctx = resolve_pipeline_context(
        _media(dv=True, hdrplus=False),
        codec="h265",
        global_preserve_dv=True,
        global_preserve_hdrplus=True,
    )
    assert ctx["pipeline"] == "dv"
    assert ctx["effective_preserve_dv"] is True
    assert ctx["effective_preserve_hdrplus"] is False
    assert ctx["requested_preserve_hdrplus"] is True
    assert ctx["container"] == "mp4"


def test_hdr10plus_only_source_does_not_inherit_global_dv_requirement():
    """HDR10+-only bleibt im dedizierten HDR10+-Pfad."""
    ctx = resolve_pipeline_context(
        _media(dv=False, hdrplus=True),
        codec="h265",
        global_preserve_dv=True,
        global_preserve_hdrplus=True,
    )
    assert ctx["pipeline"] == "hdrplus"
    assert ctx["effective_preserve_dv"] is False
    assert ctx["effective_preserve_hdrplus"] is True
    assert ctx["container"] == "mkv"


def test_dv_hdr10plus_source_keeps_combined_metadata_contract():
    """Nur eine echte Kombi-Quelle aktiviert DV plus HDR10+ gleichzeitig."""
    ctx = resolve_pipeline_context(
        _media(dv=True, hdrplus=True),
        codec="h265",
        global_preserve_dv=True,
        global_preserve_hdrplus=True,
    )
    assert ctx["pipeline"] == "dv"
    assert ctx["effective_preserve_dv"] is True
    assert ctx["effective_preserve_hdrplus"] is True
    assert ctx["container"] == "mp4"
