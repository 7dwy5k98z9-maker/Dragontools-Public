from __future__ import annotations

from dragontools.core.encoder_profile_override import (
    effective_encoder_settings,
    normalize_encoder_override,
    profile_to_override,
    scoped_encoder_options,
)
from dragontools.core.models import TargetCodec, normalize_override_dict


def test_profile_to_override_rejects_wrong_codec():
    profile = {"label": "AV1 Film", "codec": "av1", "crf": 28}

    assert profile_to_override("film_av1", profile, default_codec="h265") is None


def test_profile_to_override_accepts_codec_enum_defaults():
    profile = {"label": "Film", "codec": "h265", "crf": 22}

    result = profile_to_override("film", profile, default_codec=TargetCodec.H265)

    assert result["codec"] == "h265"


def test_normalize_override_preserves_encoder_profile():
    profile = {
        "key": "film_nvenc",
        "label": "Film NVENC",
        "codec": "h265",
        "crf": 21,
        "preset": "slow",
        "scale": "1080p",
        "encoder_options": {"encoder": "nvenc", "cq": 21},
    }

    result = normalize_override_dict({"encoder_profile": profile})

    assert result["encoder_profile"]["key"] == "film_nvenc"
    assert result["encoder_profile"]["encoder_options"]["cq"] == 21


def test_effective_encoder_settings_uses_file_profile_values():
    profile = {
        "key": "film_nvenc",
        "label": "Film NVENC",
        "codec": "h265",
        "crf": 21,
        "preset": "slow",
        "scale": "1080p",
        "encoder_options": {"encoder": "nvenc", "preset": "p6", "cq": 21},
    }

    result = effective_encoder_settings(
        default_codec="h265",
        default_crf=23,
        default_preset="medium",
        default_scale_mode="original",
        default_encoder_options={"encoder": "cpu", "autocrop_enabled": True},
        file_override={"encoder_profile": profile},
    )

    assert result["codec"] == "h265"
    assert result["crf"] == 21
    assert result["preset"] == "slow"
    assert result["scale_mode"] == "1080p"
    assert result["encoder_options"]["encoder"] == "nvenc"
    assert result["encoder_options"]["autocrop_enabled"] is True
    assert result["profile_label"] == "Film NVENC"


def test_normalize_override_preserves_manual_encoder_override():
    manual = {
        "codec": "h265",
        "encoder": "nvenc",
        "quality": 19,
        "preset": "p7",
        "scale_mode": "720p",
        "encoder_options": {"encoder": "nvenc", "cq": 19, "bf": 4},
    }

    result = normalize_override_dict({"encoder_override": manual})

    assert result["encoder_override"] == manual


def test_effective_encoder_settings_manual_override_wins_over_profile_and_global():
    profile = {
        "key": "film_cpu",
        "label": "Film CPU",
        "codec": "h265",
        "crf": 21,
        "preset": "slow",
        "scale": "1080p",
        "encoder_options": {"encoder": "cpu", "aq_mode": "2"},
    }
    manual = {
        "codec": "h265",
        "encoder": "nvenc",
        "quality": 19,
        "preset": "p7",
        "scale_mode": "720p",
        "encoder_options": {
            "encoder": "nvenc",
            "cq": 19,
            "preset": "p7",
            "bf": 4,
            "rc_lookahead": 32,
        },
    }

    result = effective_encoder_settings(
        default_codec="h265",
        default_crf=23,
        default_preset="medium",
        default_scale_mode="original",
        default_encoder_options={"encoder": "cpu", "autocrop_enabled": True},
        file_override={"encoder_profile": profile, "encoder_override": manual},
    )

    assert result["codec"] == "h265"
    assert result["crf"] == 19
    assert result["preset"] == "p7"
    assert result["scale_mode"] == "720p"
    assert result["encoder_options"]["encoder"] == "nvenc"
    assert result["encoder_options"]["cq"] == 19
    assert result["encoder_options"]["autocrop_enabled"] is True
    assert result["profile_key"] == ""
    assert result["profile_label"] == "Manuell (NVENC)"


def test_effective_encoder_settings_ignores_manual_override_for_wrong_codec():
    result = effective_encoder_settings(
        default_codec="h265",
        default_crf=22,
        default_preset="medium",
        default_scale_mode="original",
        default_encoder_options={"encoder": "cpu"},
        file_override={
            "encoder_override": {
                "codec": "av1",
                "encoder": "nvenc",
                "quality": 18,
                "preset": "p7",
                "scale_mode": "1080p",
            }
        },
    )

    assert result["crf"] == 22
    assert result["encoder_options"]["encoder"] == "cpu"
    assert result["profile_label"] == ""


def test_scoped_encoder_options_do_not_leak_cpu_values_into_nvenc():
    cpu_options = {
        "encoder": "cpu",
        "aq_strength": "1.0",
        "bf": 8,
        "rc_lookahead": 40,
    }

    assert scoped_encoder_options(
        cpu_options, active_encoder="cpu", target_encoder="nvenc"
    ) == {}
    assert scoped_encoder_options(
        cpu_options, active_encoder="cpu", target_encoder="qsv"
    ) == {}
    assert scoped_encoder_options(
        cpu_options, active_encoder="cpu", target_encoder="cpu"
    ) == cpu_options


def test_scoped_encoder_options_preserve_active_nvenc_values():
    nvenc_options = {
        "encoder": "nvenc",
        "aq_strength": 8,
        "bf": 4,
        "rc_lookahead": 32,
    }

    result = scoped_encoder_options(
        nvenc_options, active_encoder="NVENC", target_encoder="nvenc"
    )

    assert result == nvenc_options
    assert result is not nvenc_options


def test_manual_override_accepts_legacy_float_string_quality():
    manual = {
        "codec": "h265",
        "encoder": "nvenc",
        "quality": "19.0",
        "preset": "p6",
        "scale_mode": "original",
        "encoder_options": {"encoder": "nvenc", "bf": "4.0"},
    }

    normalized = normalize_encoder_override(manual, default_codec="h265")

    assert normalized is not None
    assert normalized["quality"] == 19
