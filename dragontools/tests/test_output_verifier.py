from __future__ import annotations

import json
from types import SimpleNamespace


def _patch_probe(monkeypatch, payload: dict, returncode: int = 0, stderr: str = ""):
    import dragontools.worker.output_verifier as module

    def fake_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=returncode,
            stdout=json.dumps(payload),
            stderr=stderr,
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)


def test_output_verifier_accepts_video_audio_and_plausible_duration(tmp_path, monkeypatch):
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 2048)
    _patch_probe(
        monkeypatch,
        {
            "format": {"format_name": "matroska,webm", "duration": "100.0"},
            "streams": [
                {"codec_type": "video", "codec_name": "hevc"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        },
    )

    result = OutputVerifier(ffprobe_path="ffprobe").verify(
        str(out),
        "mkv",
        expected_duration_ms=100_000,
        source_has_audio=True,
    )

    assert result.ok is True
    assert result.video_stream_count == 1
    assert result.audio_stream_count == 1


def test_output_verifier_rejects_missing_audio_when_source_had_audio(tmp_path, monkeypatch):
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 2048)
    _patch_probe(
        monkeypatch,
        {
            "format": {"format_name": "matroska,webm", "duration": "100.0"},
            "streams": [{"codec_type": "video", "codec_name": "hevc"}],
        },
    )

    result = OutputVerifier(ffprobe_path="ffprobe").verify(
        str(out),
        "mkv",
        expected_duration_ms=100_000,
        source_has_audio=True,
    )

    assert result.ok is False
    assert any("keine Audiospur" in message for message in result.messages)


def test_output_verifier_rejects_implausibly_short_duration(tmp_path, monkeypatch):
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 2048)
    _patch_probe(
        monkeypatch,
        {
            "format": {"format_name": "matroska,webm", "duration": "50.0"},
            "streams": [
                {"codec_type": "video", "codec_name": "hevc"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        },
    )

    result = OutputVerifier(ffprobe_path="ffprobe").verify(
        str(out),
        "mkv",
        expected_duration_ms=100_000,
        source_has_audio=True,
    )

    assert result.ok is False
    assert any("Dauer" in message or "dauer" in message for message in result.messages)


def test_output_verifier_uses_configurable_duration_tolerance(tmp_path, monkeypatch):
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 2048)
    _patch_probe(
        monkeypatch,
        {
            "format": {"format_name": "matroska,webm", "duration": "130.0"},
            "streams": [
                {"codec_type": "video", "codec_name": "hevc"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        },
    )

    strict = OutputVerifier(
        ffprobe_path="ffprobe",
        duration_max_ratio=1.10,
        duration_max_extra_s=0,
    ).verify(str(out), "mkv", expected_duration_ms=100_000, source_has_audio=True)
    relaxed = OutputVerifier(
        ffprobe_path="ffprobe",
        duration_max_ratio=1.50,
        duration_max_extra_s=0,
    ).verify(str(out), "mkv", expected_duration_ms=100_000, source_has_audio=True)

    assert strict.ok is False
    assert relaxed.ok is True


def test_output_verifier_reports_missing_output_file(tmp_path):
    from dragontools.worker.output_verifier import OutputVerifier

    result = OutputVerifier(ffprobe_path="ffprobe").verify(str(tmp_path / "fehlt.mkv"), "mkv")

    assert result.ok is False
    assert any("fehlt" in message for message in result.messages)


def _contract(**kwargs):
    from dragontools.worker.media_contract import ExpectedMediaContract

    defaults = dict(
        container="mkv",
        video_codec="hevc",
        video_stream_count=1,
        audio_tracks=(),
        subtitle_tracks=(),
        min_video_bit_depth=10,
        require_hdr=False,
        require_dolby_vision=False,
        require_hdr10plus=False,
    )
    defaults.update(kwargs)
    return ExpectedMediaContract(**defaults)


def test_output_verifier_contract_rejects_missing_planned_audio_track(tmp_path, monkeypatch):
    from dragontools.worker.media_contract import ExpectedAudioTrack
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 2048)
    _patch_probe(monkeypatch, {
        "format": {"format_name": "matroska,webm", "duration": "100"},
        "streams": [
            {"codec_type": "video", "codec_name": "hevc", "pix_fmt": "yuv420p10le"},
            {"codec_type": "audio", "codec_name": "eac3", "channels": 6, "tags": {"language": "deu"}},
        ],
    })
    contract = _contract(audio_tracks=(
        ExpectedAudioTrack("eac3", 6, "de"),
        ExpectedAudioTrack("aac", 2, "de"),
    ))

    result = OutputVerifier(ffprobe_path="ffprobe").verify(
        str(out), "mkv", expected_duration_ms=100_000, source_has_audio=True,
        expected_contract=contract,
    )

    assert result.ok is False
    assert result.audio_ok is False
    assert any("Audiospur-Anzahl" in msg for msg in result.messages)


def test_output_verifier_contract_rejects_audio_codec_channels_and_language(tmp_path, monkeypatch):
    from dragontools.worker.media_contract import ExpectedAudioTrack
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 2048)
    _patch_probe(monkeypatch, {
        "format": {"format_name": "matroska,webm", "duration": "100"},
        "streams": [
            {"codec_type": "video", "codec_name": "hevc", "pix_fmt": "p010le"},
            {"codec_type": "audio", "codec_name": "aac", "channels": 2, "tags": {"language": "eng"}},
        ],
    })
    contract = _contract(audio_tracks=(ExpectedAudioTrack("eac3", 6, "de"),))

    result = OutputVerifier(ffprobe_path="ffprobe").verify(
        str(out), "mkv", expected_duration_ms=100_000, source_has_audio=True,
        expected_contract=contract,
    )

    assert result.ok is False
    text = "\n".join(result.messages)
    assert "Codec abweichend" in text
    assert "Kanalzahl abweichend" in text
    assert "Sprache abweichend" in text


def test_output_verifier_accepts_undetermined_audio_without_language_tag(tmp_path, monkeypatch):
    from dragontools.worker.media_contract import ExpectedAudioTrack
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 2048)
    _patch_probe(monkeypatch, {
        "format": {"format_name": "matroska,webm", "duration": "100"},
        "streams": [
            {"codec_type": "video", "codec_name": "hevc", "pix_fmt": "yuv420p10le"},
            {"codec_type": "audio", "codec_name": "aac", "channels": 2, "tags": {}},
        ],
    })
    contract = _contract(audio_tracks=(ExpectedAudioTrack("aac", 2, "und"),))

    result = OutputVerifier(ffprobe_path="ffprobe").verify(
        str(out), "mkv", expected_duration_ms=100_000, source_has_audio=True,
        expected_contract=contract,
    )

    assert result.ok is True
    assert result.audio_ok is True
    assert not any("Sprache abweichend" in message for message in result.messages)


def test_output_verifier_contract_rejects_subtitle_forced_mismatch(tmp_path, monkeypatch):
    from dragontools.worker.media_contract import ExpectedSubtitleTrack
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 2048)
    _patch_probe(monkeypatch, {
        "format": {"format_name": "matroska,webm", "duration": "100"},
        "streams": [
            {"codec_type": "video", "codec_name": "hevc", "pix_fmt": "yuv420p10le"},
            {
                "codec_type": "subtitle", "codec_name": "subrip",
                "tags": {"language": "deu"}, "disposition": {"forced": 0},
            },
        ],
    })
    contract = _contract(subtitle_tracks=(ExpectedSubtitleTrack("subrip", "de", True),))

    result = OutputVerifier(ffprobe_path="ffprobe").verify(
        str(out), "mkv", expected_duration_ms=100_000, expected_contract=contract,
    )

    assert result.ok is False
    assert result.subtitle_ok is False
    assert any("Forced-Flag" in msg for msg in result.messages)


def test_output_verifier_contract_rejects_8bit_hevc_when_10bit_planned(tmp_path, monkeypatch):
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 2048)
    _patch_probe(monkeypatch, {
        "format": {"format_name": "matroska,webm", "duration": "100"},
        "streams": [{"codec_type": "video", "codec_name": "hevc", "pix_fmt": "yuv420p"}],
    })

    result = OutputVerifier(ffprobe_path="ffprobe").verify(
        str(out), "mkv", expected_duration_ms=100_000, expected_contract=_contract(),
    )

    assert result.ok is False
    assert result.video_bit_depth == 8
    assert any("Bittiefe" in msg for msg in result.messages)


def test_output_verifier_contract_checks_hdr_dv_and_hdr10plus(tmp_path, monkeypatch):
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mp4"
    out.write_bytes(b"x" * 2048)
    _patch_probe(monkeypatch, {
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "100"},
        "streams": [{
            "codec_type": "video", "codec_name": "hevc", "pix_fmt": "yuv420p10le",
            "color_transfer": "smpte2084", "color_primaries": "bt2020",
            "side_data_list": [
                {"side_data_type": "DOVI configuration record", "dv_profile": 8},
                {"side_data_type": "HDR Dynamic Metadata SMPTE2094-40"},
            ],
        }],
    })
    contract = _contract(
        container="mp4", require_hdr=True, require_dolby_vision=True, require_hdr10plus=True,
    )

    result = OutputVerifier(ffprobe_path="ffprobe").verify(
        str(out), "mp4", expected_duration_ms=100_000, expected_contract=contract,
    )

    assert result.ok is True
    assert result.has_hdr is True
    assert result.has_dolby_vision is True
    assert result.has_hdr10plus is True


def test_output_verifier_accepts_semantic_hdr10plus_pipeline_evidence(tmp_path, monkeypatch):
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 2048)
    _patch_probe(monkeypatch, {
        "format": {"format_name": "matroska,webm", "duration": "100"},
        "streams": [{
            "codec_type": "video", "codec_name": "hevc", "pix_fmt": "p010le",
            "color_transfer": "smpte2084", "color_primaries": "bt2020",
        }],
    })
    contract = _contract(require_hdr=True, require_hdr10plus=True)

    result = OutputVerifier(ffprobe_path="ffprobe").verify(
        str(out), "mkv", expected_duration_ms=100_000, expected_contract=contract,
        verified_hdr10plus=True,
    )

    assert result.ok is True
    assert result.has_hdr10plus is True


def test_output_verifier_checks_actual_container_not_only_extension(tmp_path, monkeypatch):
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 2048)
    _patch_probe(monkeypatch, {
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "100"},
        "streams": [{"codec_type": "video", "codec_name": "hevc", "pix_fmt": "p010le"}],
    })

    result = OutputVerifier(ffprobe_path="ffprobe").verify(
        str(out), "mkv", expected_duration_ms=100_000, expected_contract=_contract(),
    )

    assert result.ok is False
    assert result.container_ok is False
    assert any("ffprobe-Container" in msg for msg in result.messages)


def test_output_verifier_contract_allows_intentionally_audio_free_output(tmp_path, monkeypatch):
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 2048)
    _patch_probe(monkeypatch, {
        "format": {"format_name": "matroska,webm", "duration": "100"},
        "streams": [{"codec_type": "video", "codec_name": "hevc", "pix_fmt": "p010le"}],
    })

    result = OutputVerifier(ffprobe_path="ffprobe").verify(
        str(out), "mkv", expected_duration_ms=100_000,
        source_has_audio=True,  # Quelle hatte Audio, Plan hat es aber bewusst entfernt.
        expected_contract=_contract(audio_tracks=()),
    )

    assert result.ok is True
    assert result.audio_ok is True
    assert result.audio_stream_count == 0


def test_output_verifier_accepts_verified_dv_pipeline_evidence_when_ffprobe_omits_dovi(tmp_path, monkeypatch):
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mp4"
    out.write_bytes(b"x" * 2048)
    _patch_probe(monkeypatch, {
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "100"},
        "streams": [{
            "codec_type": "video", "codec_name": "hevc", "pix_fmt": "p010le",
            "color_transfer": "smpte2084", "color_primaries": "bt2020",
        }],
    })
    contract = _contract(container="mp4", require_hdr=True, require_dolby_vision=True)

    result = OutputVerifier(ffprobe_path="ffprobe").verify(
        str(out), "mp4", expected_duration_ms=100_000, expected_contract=contract,
        verified_dolby_vision=True,
    )

    assert result.ok is True
    assert result.has_hdr is True
    assert result.has_dolby_vision is True
