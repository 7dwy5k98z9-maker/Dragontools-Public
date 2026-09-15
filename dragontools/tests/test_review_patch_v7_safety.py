# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def _movie_suggestion():
    from dragontools.core.online_metadata_types import MovieMetadataSuggestion
    return MovieMetadataSuggestion(
        query_title="Film", query_year=2024, tmdb_id=1, title="Film",
        original_title="Film", release_year=2024,
    )


def test_atomic_nfo_write_preserves_existing_file_when_fsync_fails(tmp_path, monkeypatch):
    import dragontools.core.jellyfin_nfo as nfo

    target = tmp_path / "Film.nfo"
    target.write_text("ORIGINAL", encoding="utf-8")
    monkeypatch.setattr(nfo.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("disk failure")))

    try:
        nfo.write_movie_nfo(target, _movie_suggestion(), include_fileinfo=False)
    except OSError:
        pass
    else:
        raise AssertionError("fsync failure must fail closed")

    assert target.read_text(encoding="utf-8") == "ORIGINAL"
    assert not list(tmp_path.glob(".*.__dragontools_nfo__*.tmp"))


def test_nfo_backup_transaction_rolls_back_if_final_install_fails(tmp_path, monkeypatch):
    import dragontools.worker.nfo_commit as module

    target = tmp_path / "Film.nfo"
    target.write_text("ORIGINAL", encoding="utf-8")
    plan = module.plan_nfo_target(target, "backup")
    real_replace = module.os.replace
    calls = {"count": 0}

    def flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("install failed")
        return real_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", flaky_replace)

    def writer(path: Path):
        path.write_text("NEW", encoding="utf-8")

    try:
        module.commit_nfo(plan, writer)
    except OSError:
        pass
    else:
        raise AssertionError("final install failure must propagate")

    assert target.read_text(encoding="utf-8") == "ORIGINAL"
    assert not list(tmp_path.glob("*.nfo.bak*"))
    assert not list(tmp_path.glob(".*.__pending__*.tmp"))


def test_only_unambiguous_episode_rejects_equal_competing_series():
    from dragontools.worker.postprocess_metadata_resolution import episode_resolution

    a = SimpleNamespace(
        provider="tmdb", series_provider_id=10, series_tmdb_id=10,
        show_name="Watson", original_show_name="Watson", query_series="Watson",
        first_air_year=2025, season_number=1, episode_number=1,
    )
    b = SimpleNamespace(
        provider="tmdb", series_provider_id=20, series_tmdb_id=20,
        show_name="Watson", original_show_name="Watson", query_series="Watson",
        first_air_year=2025, season_number=1, episode_number=1,
    )
    result = episode_resolution((a, b), "Watson (2025) - S01E01.mkv")
    assert result.ambiguous is True
    assert result.suggestion is None
    assert "mehrdeutig" in result.reason


def test_only_unambiguous_movie_rejects_equal_competing_results():
    from dragontools.worker.postprocess_metadata_resolution import movie_ambiguity

    records = (
        {"id": 1, "title": "Dune", "release_date": "2021-09-15"},
        {"id": 2, "title": "Dune", "release_date": "2021-10-01"},
    )
    result = movie_ambiguity(records, "Dune (2021).mkv")
    assert result.ambiguous is True
    assert result.suggestion is None


def test_postprocess_passes_only_unambiguous_setting_to_metadata_session(tmp_path, monkeypatch):
    import dragontools.worker.postprocess_runner as module
    from dragontools.worker.postprocess_models import NfoSettings
    from dragontools.worker.postprocess_metadata_resolution import MetadataResolution

    video = tmp_path / "Watson - S01E01.mkv"
    video.write_bytes(b"video")
    calls = []

    class Session:
        def resolve_episode(self, path, *, require_unambiguous=False):
            calls.append(require_unambiguous)
            return MetadataResolution(None, True, "mehrdeutig", 2)

    service = module.PostProcessService(
        settings=None, tools=SimpleNamespace(ffprobe=""), log=lambda *_a: None,
        metadata_session=Session(),
    )
    result = service._create_nfo(
        input_path=str(video), output_path=video,
        cfg=NfoSettings(enabled=True, only_unambiguous=True, include_fileinfo=False, conflict_mode="overwrite"),
    )
    assert result is None
    assert calls == [True]
    assert not video.with_suffix(".nfo").exists()


def test_audio_mux_contract_contains_subtitles_attachments_and_data(monkeypatch):
    import dragontools.worker.audio_mux_plan_service as module

    monkeypatch.setattr(
        module, "probe_output",
        lambda *a, **k: SimpleNamespace(streams=(
            {"codec_type": "video"}, {"codec_type": "audio"},
            {"codec_type": "subtitle"}, {"codec_type": "attachment"},
            {"codec_type": "data"},
        )),
    )
    media = SimpleNamespace(
        primary_video=SimpleNamespace(codec="hevc", bit_depth=10, width=1920, height=1080),
        video_streams=[SimpleNamespace(codec="hevc")],
        subtitle_streams=[SimpleNamespace(codec="subrip", language="de", forced=True)],
    )
    stream = SimpleNamespace(language="de")
    decision = SimpleNamespace(target_codec="eac3", target_channels=6, stream=stream)
    tools = SimpleNamespace(ffmpeg="ffmpeg", ffprobe="ffprobe")
    contract = module.AudioMuxPlanService(tools=tools).build_expected_contract("source.mkv", media, [decision])

    assert contract.audio_stream_count == 1
    assert contract.subtitle_stream_count == 1
    assert contract.subtitle_tracks[0].forced is True
    assert contract.attachment_stream_count == 1
    assert contract.data_stream_count == 1


def test_output_contract_rejects_attachment_and_data_loss(monkeypatch, tmp_path):
    import dragontools.worker.output_verifier as module
    from dragontools.worker.media_contract_types import ExpectedMediaContract

    monkeypatch.setattr(
        module, "probe_output",
        lambda *a, **k: SimpleNamespace(
            format_name="matroska,webm", duration_s=60.0, usable=True,
            video_streams=[{"codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080}],
            audio_streams=[], subtitle_streams=[], streams=({"codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080},),
        ),
    )
    path = tmp_path / 'contract_aux_test.mkv'
    path.write_bytes(b'x' * 2048)
    try:
        contract = ExpectedMediaContract(
            container="mkv", video_codec="hevc", video_stream_count=1,
            audio_tracks=(), subtitle_tracks=(), attachment_stream_count=1, data_stream_count=1,
        )
        result = module.OutputVerifier(ffprobe_path="ffprobe").verify(str(path), "mkv", expected_duration_ms=60_000, expected_contract=contract)
        assert result.ok is False
        assert any("Attachment-Anzahl" in msg for msg in result.messages)
        assert any("Data-Stream-Anzahl" in msg for msg in result.messages)
    finally:
        path.unlink(missing_ok=True)


def test_dv_remux_verifier_passes_planned_contract_to_output_verifier(monkeypatch):
    import dragontools.worker.dv_remux_output_verifier as module
    from dragontools.worker.media_contract_types import ExpectedAudioTrack, ExpectedMediaContract

    seen = {}
    def fake_verify(self, *args, **kwargs):
        seen["contract"] = kwargs.get("expected_contract")
        return SimpleNamespace(ok=False, messages=["Audiospur-Anzahl abweichend"])
    monkeypatch.setattr(module.OutputVerifier, "verify", fake_verify)
    monkeypatch.setattr(
        module, "inspect_dynamic_hdr_with_mediainfo",
        lambda *a, **k: SimpleNamespace(conclusive=True, dolby_vision=True, warnings=()),
    )
    contract = ExpectedMediaContract(
        container="mkv", video_codec="hevc", video_stream_count=1,
        audio_tracks=(ExpectedAudioTrack("eac3", 6, "de"),), subtitle_tracks=(), require_dolby_vision=True,
    )
    result = module.DVRemuxOutputVerifier(tools=SimpleNamespace(ffprobe="ffprobe")).verify(
        output_path="out.mkv", container="mkv", expected_duration_ms=1000, expected_contract=contract,
    )
    assert seen["contract"] is contract
    assert result.ok is False
