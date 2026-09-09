from __future__ import annotations

from dragontools.core.codec_profile_assistant import (
    assistant_profiles_for_codec,
    profile_for_assistant_key,
)


def test_h265_assistant_profiles_cover_cpu_and_nvenc():
    suggestions = assistant_profiles_for_codec("h265")
    labels = {suggestion.label for suggestion in suggestions}
    keys = {suggestion.key for suggestion in suggestions}
    encoders = {
        suggestion.profile["encoder_options"]["encoder"]
        for suggestion in suggestions
    }

    assert "Anime klein" in labels
    assert "Anime Serie klein OK CPU" in labels
    assert "Anime Serie mittel gut NVENC" in labels
    assert "4K TV mittel gut CPU" in labels
    assert "TV Film klein OK NVENC" in labels
    assert "h265_anime_series_small_cpu" in keys
    assert "h265_tv_4k_medium_nvenc" in keys
    assert "NVENC schnell" in labels
    assert {"cpu", "nvenc"}.issubset(encoders)
    assert all(suggestion.profile["codec"] == "h265" for suggestion in suggestions)
    assert len(suggestions) >= 24


def test_av1_assistant_profiles_use_numeric_svt_presets():
    suggestions = assistant_profiles_for_codec("av1")
    presets = {suggestion.profile["preset"] for suggestion in suggestions}

    assert {"5", "6", "7"}.issubset(presets)
    assert all(suggestion.profile["codec"] == "av1" for suggestion in suggestions)


def test_profile_for_assistant_key_returns_copy():
    first = profile_for_assistant_key("h265", "h265_anime_small_cpu")
    second = profile_for_assistant_key("h265", "h265_anime_small_cpu")

    assert first is not None
    assert second is not None
    first["crf"] = 99
    first["encoder_options"]["encoder"] = "amf"
    assert second["crf"] == 21
    assert second["encoder_options"]["encoder"] == "cpu"


def test_anime_series_cpu_profile_uses_animation_and_more_lookahead():
    profile = profile_for_assistant_key("h265", "h265_anime_series_small_cpu")

    assert profile is not None
    assert profile["crf"] == 21
    assert profile["encoder_options"]["tune"] == "animation"
    assert profile["encoder_options"]["bf"] == 10
    assert profile["encoder_options"]["rc_lookahead"] == 60
