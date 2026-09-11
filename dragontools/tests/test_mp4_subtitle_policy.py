from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from dragontools.core.models import SubtitleStream
from dragontools.rules.subtitle_rules import (
    SubtitlePlan,
    any_sidecar_export_enabled,
    build_mp4_subtitle_storage_plan,
    migrate_subtitle_rules,
    mp4_sidecars_enabled,
    text_to_srt_sidecar_enabled,
)


def _sub(index: int, codec: str, *, forced: bool = False, title: str = "") -> SubtitleStream:
    return SubtitleStream(
        index=index,
        language="de",
        forced=forced,
        title=title,
        codec=codec,
    )


def _plan(*streams: SubtitleStream, burn_sub=None) -> SubtitlePlan:
    return SubtitlePlan(
        override_mode="auto",
        burn_sub=burn_sub,
        keep_streams=tuple(streams),
        external_streams=tuple(streams),
    )


def test_legacy_dv_sidecar_setting_migrates_to_global_mp4_setting():
    rules = migrate_subtitle_rules({"dv_extract_external_subs": "0"})
    assert rules["mp4_sidecars_enabled"] is False
    assert rules["dv_extract_external_subs"] is False
    assert mp4_sidecars_enabled(rules) is False


def test_new_sidecar_flags_are_migrated_and_gate_non_mp4_exports():
    rules = migrate_subtitle_rules({
        "additional_sidecars_enabled": "true",
        "text_to_srt_sidecar_enabled": "1",
    })

    assert rules["_schema_version"] == 6
    assert rules["additional_sidecars_enabled"] is True
    assert text_to_srt_sidecar_enabled(rules) is True
    assert any_sidecar_export_enabled({}, container="mkv") is False
    assert any_sidecar_export_enabled(rules, container="mkv") is True


def test_mp4_sidecars_enabled_exports_all_selected_subtitle_types():
    srt = _sub(2, "subrip")
    ass = _sub(3, "ass")
    pgs = _sub(4, "hdmv_pgs_subtitle")
    vob = _sub(5, "dvd_subtitle")

    storage = build_mp4_subtitle_storage_plan(
        _plan(srt, ass, pgs, vob),
        subtitle_rules={"mp4_sidecars_enabled": True},
    )

    assert storage.internal_streams == ()
    assert [s.index for s in storage.external_streams] == [2, 3, 4, 5]


def test_mp4_sidecars_disabled_keeps_text_internal_and_bitmap_external():
    srt = _sub(2, "subrip")
    ass = _sub(3, "ass")
    pgs = _sub(4, "hdmv_pgs_subtitle")
    vob = _sub(5, "vobsub")

    storage = build_mp4_subtitle_storage_plan(
        _plan(srt, ass, pgs, vob),
        subtitle_rules={"mp4_sidecars_enabled": False},
    )

    assert [s.index for s in storage.internal_streams] == [2, 3]
    assert [s.index for s in storage.external_streams] == [4, 5]


def test_mp4_remux_policy_preserves_burn_candidate_when_no_burn_is_possible():
    forced = _sub(2, "subrip", forced=True)
    storage = build_mp4_subtitle_storage_plan(
        _plan(burn_sub=forced),
        subtitle_rules={"mp4_sidecars_enabled": False},
        preserve_burn_candidate=True,
    )
    assert [s.index for s in storage.internal_streams] == [2]
    assert storage.external_streams == ()


def test_converter_stream_args_transcodes_text_to_mov_text_and_leaves_pgs_for_sidecar():
    from dragontools.worker.converter_stream_args import ConverterStreamArgsHelper

    worker = SimpleNamespace(
        subtitle_rules={"mp4_sidecars_enabled": False},
        log=lambda *_args, **_kwargs: None,
        _logger=SimpleNamespace(decision=lambda *_args, **_kwargs: None),
    )
    helper = ConverterStreamArgsHelper(worker)
    srt = _sub(2, "subrip")
    ass = _sub(3, "ass", forced=True)
    pgs = _sub(4, "hdmv_pgs_subtitle")
    plan = _plan(srt, ass, pgs)
    mi = SimpleNamespace(subtitle_streams=[srt, ass, pgs], audio_streams=[], duration_s=60.0)

    with patch(
        "dragontools.rules.subtitle_rules.compute_subtitle_plan",
        return_value=plan,
    ):
        burn, args = helper.sub_args("input.mkv", mi, {}, container="mp4")

    assert burn == []
    joined = " ".join(str(v) for v in args)
    assert "0:2" in joined and "0:3" in joined
    assert "0:4" not in joined
    assert args.count("mov_text") == 2
    assert "forced" in args


def test_sidecar_service_exports_only_bitmap_when_global_mp4_sidecars_are_off(tmp_path):
    from dragontools.worker.subtitle_sidecar_service import SubtitleSidecarService

    srt = _sub(2, "subrip")
    pgs = _sub(4, "hdmv_pgs_subtitle")
    plan = _plan(srt, pgs)
    mi = SimpleNamespace(subtitle_streams=[srt, pgs], audio_streams=[], duration_s=60.0)
    service = SubtitleSidecarService(
        ffmpeg_path="ffmpeg",
        subtitle_rules={"mp4_sidecars_enabled": False},
        log=lambda *_args, **_kwargs: None,
    )

    def fake_run(cmd, **_kwargs):
        Path(cmd[-1]).write_bytes(b"pgs")
        return MagicMock(returncode=0, stderr=b"")

    with (
        patch("dragontools.worker.subtitle_sidecar_service.compute_subtitle_plan", return_value=plan),
        patch("dragontools.worker.subtitle_sidecar_service.run_tool", side_effect=fake_run),
    ):
        result = service.export_sidecars_result(
            input_path="input.mkv",
            output_base=tmp_path / "Film",
            media_info=mi,
        )

    assert result.complete is True
    assert result.planned_stream_indices == (4,)
    assert len(result.exported_paths) == 1
    assert result.exported_paths[0].endswith(".sup")


def test_dv_mp4_internal_job_converts_ass_and_srt_to_srt_for_mp4box():
    from dragontools.worker.dv_subtitle_mux_service import DVSubtitleMuxService

    srt = _sub(2, "subrip")
    ass = _sub(3, "ass")
    pgs = _sub(4, "hdmv_pgs_subtitle")
    plan = _plan(srt, ass, pgs)
    mi = SimpleNamespace(subtitle_streams=[srt, ass, pgs], audio_streams=[], duration_s=60.0)
    service = DVSubtitleMuxService(
        ffmpeg_path="ffmpeg",
        subtitle_rules={"mp4_sidecars_enabled": False},
        log=lambda *_args, **_kwargs: None,
    )

    with patch("dragontools.worker.dv_subtitle_mux_service.compute_subtitle_plan", return_value=plan):
        jobs = service.build_internal_mp4_jobs(mi, {})

    assert [j.stream_index for j in jobs] == [2, 3]
    assert all(j.ext == ".srt" for j in jobs)
    assert all(j.codec_args == ("-c:s", "srt") for j in jobs)
