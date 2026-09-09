from __future__ import annotations

from types import SimpleNamespace


def _audio(index=1, language="deu", codec="aac", channels=2):
    return SimpleNamespace(
        index=index,
        language=language,
        codec=codec,
        channels=channels,
    )


def _sub(index=3, language="deu", codec="subrip", forced=False):
    return SimpleNamespace(
        index=index,
        language=language,
        codec=codec,
        forced=forced,
    )


def _media(*, audio=None, subtitles=None, codec="hevc", bit_depth=10, hdr=True, dv=False, hdrplus=False):
    primary = SimpleNamespace(
        codec=codec,
        bit_depth=bit_depth,
        hdr_format="hdr10plus" if hdrplus else ("dolby_vision" if dv else ("hdr10" if hdr else None)),
        color_transfer="smpte2084" if hdr else None,
        color_primaries="bt2020" if hdr else None,
    )
    return SimpleNamespace(
        audio_streams=list(audio or []),
        subtitle_streams=list(subtitles or []),
        primary_video=primary,
        duration_s=100.0,
        is_hdr=hdr,
        has_dv=dv,
        has_hdrplus=hdrplus,
        has_hdr10plus=hdrplus,
        dolby_vision=dv,
        dv_profile_major=8 if dv else None,
        dv_profile="8" if dv else None,
        dolby_vision_profile="8" if dv else None,
        transfer_characteristics="smpte2084" if hdr else None,
    )


def test_contract_uses_audio_and_subtitle_plan(monkeypatch):
    import dragontools.worker.media_contract as module

    a = _audio()
    keep = _sub(index=4, forced=False)
    burn = _sub(index=5, forced=True)
    monkeypatch.setattr(
        module,
        "compute_audio_track_plan",
        lambda **_: [
            SimpleNamespace(target_codec="eac3", target_channels=6, stream=a),
            SimpleNamespace(target_codec="aac", target_channels=2, stream=a),
        ],
    )
    monkeypatch.setattr(
        module,
        "compute_subtitle_plan",
        lambda *_, **__: SimpleNamespace(burn_sub=burn, keep_streams=(keep,)),
    )

    contract = module.build_expected_media_contract(
        media_info=_media(audio=[a], subtitles=[keep, burn]),
        file_override={},
        container="mkv",
        pipeline="standard",
        strip_only=False,
        effective_codec="h265",
        effective_preserve_hdrplus=False,
        subtitle_rules={},
    )

    assert [track.codec for track in contract.audio_tracks] == ["eac3", "aac"]
    assert [track.channels for track in contract.audio_tracks] == [6, 2]
    assert [track.language for track in contract.audio_tracks] == ["de", "de"]
    assert len(contract.subtitle_tracks) == 1
    assert contract.subtitle_tracks[0].forced is False
    assert contract.video_codec == "hevc"
    assert contract.min_video_bit_depth == 10
    assert contract.require_hdr is True


def test_dv_contract_expects_no_internal_subtitles_and_dv_hdr10plus(monkeypatch):
    import dragontools.worker.media_contract as module

    monkeypatch.setattr(module, "compute_audio_track_plan", lambda **_: [])
    monkeypatch.setattr(
        module,
        "compute_subtitle_plan",
        lambda *_, **__: SimpleNamespace(burn_sub=None, keep_streams=(_sub(),)),
    )

    contract = module.build_expected_media_contract(
        media_info=_media(dv=True, hdrplus=True),
        file_override={},
        container="mp4",
        pipeline="dv",
        strip_only=False,
        effective_codec="h265",
        effective_preserve_hdrplus=True,
        subtitle_rules={},
    )

    assert contract.subtitle_stream_count == 0
    assert contract.require_dolby_vision is True
    assert contract.require_hdr10plus is True
    assert contract.require_hdr is True


def test_strip_only_contract_copies_burn_subtitle_and_preserves_source_video(monkeypatch):
    import dragontools.worker.media_contract as module

    burn = _sub(index=3, forced=True)
    keep = _sub(index=4, forced=False, codec="ass")
    monkeypatch.setattr(module, "compute_audio_track_plan", lambda **_: [])
    monkeypatch.setattr(
        module,
        "compute_subtitle_plan",
        lambda *_, **__: SimpleNamespace(burn_sub=burn, keep_streams=(burn, keep)),
    )

    contract = module.build_expected_media_contract(
        media_info=_media(codec="h264", bit_depth=8, hdr=False, subtitles=[burn, keep]),
        file_override={},
        container="mkv",
        pipeline="standard",
        strip_only=True,
        effective_codec="h265",
        effective_preserve_hdrplus=False,
        subtitle_rules={},
    )

    assert contract.video_codec == "h264"
    assert contract.min_video_bit_depth == 8
    assert contract.subtitle_stream_count == 2
    assert [s.codec for s in contract.subtitle_tracks] == ["subrip", "ass"]


def test_hdrplus_pipeline_requires_hdr10plus_even_without_selection_flag(monkeypatch):
    import dragontools.worker.media_contract as module

    monkeypatch.setattr(module, "compute_audio_track_plan", lambda **_: [])
    monkeypatch.setattr(
        module,
        "compute_subtitle_plan",
        lambda *_, **__: SimpleNamespace(burn_sub=None, keep_streams=()),
    )

    contract = module.build_expected_media_contract(
        media_info=_media(hdr=True, hdrplus=True),
        file_override={},
        container="mkv",
        pipeline="hdrplus",
        strip_only=False,
        effective_codec="h265",
        effective_preserve_hdrplus=False,
        subtitle_rules={},
    )

    assert contract.require_hdr10plus is True
    assert contract.require_hdr is True


def test_dv_only_contract_never_requires_hdr10plus_from_global_preserve_flag(monkeypatch):
    """Regression fuer falschen HDR10+-Verify nach erfolgreichem DV-only-Encode."""
    import dragontools.worker.media_contract as module

    monkeypatch.setattr(module, "compute_audio_track_plan", lambda **_: [])
    monkeypatch.setattr(
        module,
        "compute_subtitle_plan",
        lambda *_, **__: SimpleNamespace(burn_sub=None, keep_streams=()),
    )

    contract = module.build_expected_media_contract(
        media_info=_media(dv=True, hdrplus=False),
        file_override={},
        container="mp4",
        pipeline="dv",
        strip_only=False,
        effective_codec="h265",
        # Absichtlich True: selbst ein inkonsistenter Aufrufer darf bei einer
        # DV-only-Quelle keinen HDR10+-Vertrag erzeugen.
        effective_preserve_hdrplus=True,
        subtitle_rules={},
    )

    assert contract.require_dolby_vision is True
    assert contract.require_hdr10plus is False
    assert contract.require_hdr is True
