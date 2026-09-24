# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def _media(profile: int | None, *, has_dv: bool = True):
    return SimpleNamespace(
        dv_profile_major=profile,
        dv_profile=str(profile) if profile is not None else None,
        dolby_vision=has_dv,
        has_dv=has_dv,
    )


def test_dv_remux_policy_p7_respects_mkv_keep_switch():
    from dragontools.worker.dv_remux_policy import decide_dv_remux

    keep = decide_dv_remux(_media(7), container="mkv", keep_dv7_mkv=True, encode_dv5=True)
    convert = decide_dv_remux(_media(7), container="mkv", keep_dv7_mkv=False, encode_dv5=True)
    mp4 = decide_dv_remux(_media(7), container="mp4", keep_dv7_mkv=True, encode_dv5=True)

    assert keep.action == "remux" and keep.expected_profile_major == 7
    assert convert.action == "normalize_p81" and convert.expected_profile_major == 8
    assert mp4.action == "normalize_p81" and mp4.expected_profile_major == 8


def test_dv_remux_policy_p5_encode_or_skip():
    from dragontools.worker.dv_remux_policy import decide_dv_remux

    encode = decide_dv_remux(_media(5), container="mkv", keep_dv7_mkv=False, encode_dv5=True)
    skip = decide_dv_remux(_media(5), container="mkv", keep_dv7_mkv=False, encode_dv5=False)
    assert encode.action == "encode"
    assert encode.expected_profile_major == 8
    assert skip.action == "skip"


def test_dv_remux_profile_service_uses_dovi_mode2_discard(tmp_path):
    from dragontools.worker.dv_remux_profile_service import DVRemuxProfileService

    source = tmp_path / "source.hevc"
    target = tmp_path / "p81.hevc"
    source.write_bytes(b"source")
    seen = {}

    class Runner:
        def run_abortable_capture(self, cmd, *, timeout_s=None):
            seen["cmd"] = list(cmd)
            seen["timeout"] = timeout_s
            target.write_bytes(b"converted")
            return 0, "", ""

    worker = SimpleNamespace(
        tools=SimpleNamespace(dovi_tool="dovi_tool"),
        abort_requested=False,
        abort_type=None,
        log=lambda *_a: None,
    )
    ok = DVRemuxProfileService(worker, Runner()).normalize_to_p81(source, target)
    assert ok is True
    assert seen["cmd"] == [
        "dovi_tool", "-m", "2", "convert", "--discard", str(source), "-o", str(target)
    ]
    assert seen["timeout"] is not None


def test_dv_remux_output_verifier_rejects_wrong_profile(monkeypatch):
    import dragontools.worker.dv_remux_output_verifier as module
    from dragontools.worker.media_contract_types import ExpectedMediaContract

    monkeypatch.setattr(
        module,
        "inspect_dynamic_hdr_with_mediainfo",
        lambda *_a, **_k: SimpleNamespace(
            conclusive=True,
            dolby_vision=True,
            dolby_vision_profile="7",
            warnings=(),
        ),
    )
    monkeypatch.setattr(
        module.OutputVerifier,
        "verify",
        lambda *_a, **_k: SimpleNamespace(ok=True, messages=[]),
    )
    contract = ExpectedMediaContract(
        container="mp4",
        video_codec="hevc",
        video_stream_count=1,
        audio_tracks=(),
        subtitle_tracks=(),
        require_dolby_vision=True,
        expected_dolby_vision_profile=8,
    )
    result = module.DVRemuxOutputVerifier(tools=SimpleNamespace(ffprobe="ffprobe")).verify(
        output_path="out.mp4",
        container="mp4",
        expected_duration_ms=1000,
        expected_contract=contract,
    )
    assert result.ok is False
    assert any("Profil abweichend" in msg for msg in result.messages)


def test_only_unambiguous_does_not_score_query_series_against_itself():
    from dragontools.worker.postprocess_metadata_resolution import episode_resolution

    candidate = SimpleNamespace(
        provider="tmdb",
        series_provider_id=10,
        series_tmdb_id=10,
        show_name="Completely Different",
        original_show_name="Something Else",
        query_series="Watson",
        first_air_year=2025,
        season_number=1,
        episode_number=1,
    )
    result = episode_resolution((candidate,), "Watson (2025) - S01E01.mkv")
    assert result.ambiguous is True
    assert result.suggestion is None
    assert "nicht sicher genug" in result.reason


def test_unambiguous_episode_falls_back_to_second_provider():
    from dragontools.worker.postprocess_metadata import PostProcessMetadataSession

    wrong = SimpleNamespace(
        provider="thetvdb", series_provider_id=1, series_tmdb_id=1,
        show_name="Wrong Show", original_show_name="Wrong Show", query_series="Watson",
        first_air_year=2025, season_number=1, episode_number=1,
    )
    good = SimpleNamespace(
        provider="tmdb", series_provider_id=2, series_tmdb_id=2,
        show_name="Watson", original_show_name="Watson", query_series="Watson",
        first_air_year=2025, season_number=1, episode_number=1,
    )

    class Provider:
        def __init__(self, item): self.item = item
        def refresh_episode_candidates(self, _path, limit=4): return (self.item,)

    session = object.__new__(PostProcessMetadataSession)
    session._settings = None
    session._clients = {"series": SimpleNamespace(clients=(Provider(wrong), Provider(good)))}
    import threading
    session._lock = threading.Lock()

    result = session.resolve_episode("Watson (2025) - S01E01.mkv", require_unambiguous=True)
    assert result.ambiguous is False
    assert result.suggestion is good


def test_preflight_online_lookup_forwards_known_series_year():
    from dragontools.gui.preflight_metadata_series import resolve_series_metadata
    from dragontools.gui.preflight_metadata_common import MetadataLookupCache

    seen = {}
    def suggest(name, settings, *, year=None):
        seen["name"] = name
        seen["year"] = year
        return SimpleNamespace(first_air_year=year, folder_name=f"{name} ({year})")

    result = resolve_series_metadata(
        {"series_name": "Watson", "year": 2025, "search_bases": [{"type": "tv", "base": "/tv"}]},
        settings=object(),
        online_enabled=True,
        cache=MetadataLookupCache(),
        find_series_dir_from_settings=lambda *_a, **_k: None,
        find_series_dir_candidates=lambda *_a, **_k: [],
        suggest_series_metadata_for_name=suggest,
    )
    assert seen == {"name": "Watson", "year": 2025}
    assert result.first_air_year == 2025


def test_nfo_backup_hard_failure_never_removes_live_target(tmp_path, monkeypatch):
    import dragontools.worker.nfo_commit as module

    target = tmp_path / "Film.nfo"
    target.write_text("ORIGINAL", encoding="utf-8")
    plan = module.plan_nfo_target(target, "backup")
    real_replace = module.os.replace

    def crash_on_final_install(src, dst):
        if str(dst) == str(target) and ".__pending__" in str(src):
            raise KeyboardInterrupt("simulated hard interruption")
        return real_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", crash_on_final_install)
    try:
        module.commit_nfo(plan, lambda path: path.write_text("NEW", encoding="utf-8"))
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("simulated interruption must escape")

    assert target.read_text(encoding="utf-8") == "ORIGINAL"
    assert list(tmp_path.glob("*.nfo.bak*"))


def test_dv5_fallback_forces_h265_and_dv(monkeypatch):
    import dragontools.worker.dv5_encode_fallback as module
    from dragontools.worker.converter_config import ConverterConfig

    captured = {}
    class FakeSignal:
        def connect(self, *_a): pass
    class FakeChild:
        file_progress = FakeSignal(); file_result = FakeSignal(); worker_event = FakeSignal(); dv_crop_decision_requested = FakeSignal()
        erfolgreich = 0; fehlgeschlagen = 0
        def __init__(self, files, config, shared_logger=None):
            captured["files"] = files
            captured["config"] = config
            self.erfolgreich = 0
            self.fehlgeschlagen = 0
        def run(self):
            self.erfolgreich = 1
        def request_abort(self, *_a): pass
        def pause(self): pass
        def resume(self): pass

    monkeypatch.setattr(module, "ConverterThread", FakeChild)
    config = ConverterConfig(
        codec="av1", crf=28, preset="6", scale_mode="original",
        overwrite_original=False, encoder_options={"preserve_dv": False},
    )
    signal = SimpleNamespace(emit=lambda *_a: None)
    worker = SimpleNamespace(
        _logger=object(), _active_fallback_worker=None,
        file_overrides={}, file_progress=signal, file_result=signal, worker_event=signal,
        dv_crop_decision_requested=signal,
        log=lambda *_a: None,
    )
    ok = module.DV5EncodeFallbackRunner(worker, config).run("movie.mkv")
    assert ok is True
    assert captured["config"].codec == "h265"
    assert captured["config"].strip_only is False
    assert captured["config"].encoder_options["preserve_dv"] is True
    assert captured["config"].encoder_options["preserve_hdrplus"] is False


def test_dv7_enhancement_layer_probe_reports_fel(tmp_path):
    from dragontools.worker.dv_remux_profile_service import DVRemuxProfileService

    source = tmp_path / "source.hevc"
    source.write_bytes(b"hevc")
    logs = []
    class Runner:
        calls = []
        def run_abortable_capture(self, cmd, timeout_s=None):
            self.calls.append(list(cmd))
            if "extract-rpu" in cmd:
                out = Path(cmd[cmd.index("-o") + 1])
                out.write_bytes(b"rpu")
                return 0, "", ""
            return 0, '{"dovi_profile":7,"subprofile":"FEL"}', ""
    worker = SimpleNamespace(
        tools=SimpleNamespace(dovi_tool="dovi_tool"),
        abort_requested=False, abort_type=None,
        log=lambda msg, level="info": logs.append((level, msg)),
    )
    runner = Runner()
    result = DVRemuxProfileService(worker, runner).detect_p7_enhancement_layer(source, tmp_path)
    assert result == "FEL"
    assert any("FEL erkannt" in msg for _level, msg in logs)
    assert any("-l" in call and "1" in call for call in runner.calls)
