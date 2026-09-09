from __future__ import annotations

import json
from pathlib import Path

from dragontools.core.movie_renamer import build_series_rename_proposal, release_style_warnings
from dragontools.core.models import MediaInfo, VideoStream
from dragontools.rules.pipeline_selector import resolve_pipeline_context
from dragontools.worker.dv_crop_reconcile import (
    CropRect,
    automatic_choice,
    compare_crops,
    parse_level5_export,
    replace_crop_in_vf_args,
)
from dragontools.worker.dv_mp4box_muxer import DVMP4BoxMuxer


def _mi(*, dv=False, hdrplus=False) -> MediaInfo:
    video = VideoStream(
        index=0,
        codec="hevc",
        width=3840,
        height=2160,
        hdr_format="dolby_vision" if dv else "hdr10plus" if hdrplus else None,
        has_dolby_vision=dv,
        has_hdr10plus=hdrplus,
    )
    return MediaInfo(
        path="/fake/source.mkv",
        audio_streams=[],
        subtitle_streams=[],
        video_streams=[video],
        dolby_vision=dv,
        has_hdr10plus=hdrplus,
        dv_profile="8" if dv else None,
        dv_profile_major=8 if dv else None,
    )


def test_dv_crop_level5_export_wird_zu_crop_filter(tmp_path):
    exported = tmp_path / "l5.json"
    exported.write_text(json.dumps({
        "active_area": {
            "presets": [{"id": 0, "left": 0, "right": 0, "top": 276, "bottom": 276}],
            "edits": {"all": 0},
        }
    }), encoding="utf-8")
    crop, dynamic = parse_level5_export(exported, source_width=3840, source_height=2160)
    assert dynamic is False
    assert crop == CropRect(3840, 1608, 0, 276)
    assert crop.as_filter() == "crop=3840:1608:0:276"


def test_dv_crop_kleine_abweichung_nimmt_groesseren_autocrop():
    auto = CropRect(3840, 1608, 0, 276)
    rpu = CropRect(3840, 1600, 0, 280)
    comparison = compare_crops(auto, rpu, source_width=3840, source_height=2160)
    assert comparison.max_difference_px <= 20
    assert automatic_choice(comparison) == "autocrop"


def test_dv_crop_kleine_abweichung_nimmt_groesseren_rpu_crop():
    auto = CropRect(3840, 1600, 0, 280)
    rpu = CropRect(3840, 1608, 0, 276)
    comparison = compare_crops(auto, rpu, source_width=3840, source_height=2160)
    assert comparison.max_difference_px <= 20
    assert automatic_choice(comparison) == "rpu"


def test_dv_crop_grosse_abweichung_braucht_benutzerentscheidung():
    auto = CropRect(3840, 1608, 0, 276)
    rpu = CropRect(3840, 1500, 0, 330)
    comparison = compare_crops(auto, rpu, source_width=3840, source_height=2160)
    assert comparison.max_difference_px > 20
    assert comparison.needs_user_decision is True
    assert automatic_choice(comparison) == "ask"


def test_dv_crop_kein_autocrop_gegen_grossen_rpu_crop_ist_ebenfalls_konflikt():
    rpu = CropRect(3840, 1608, 0, 276)
    comparison = compare_crops(None, rpu, source_width=3840, source_height=2160)
    assert comparison.max_difference_px == 552
    assert automatic_choice(comparison) == "ask"


def test_dv_crop_dynamic_level5_wird_nicht_als_globaler_crop_verwendet(tmp_path):
    exported = tmp_path / "l5.json"
    exported.write_text(json.dumps({
        "active_area": {
            "presets": [
                {"id": 0, "left": 0, "right": 0, "top": 276, "bottom": 276},
                {"id": 1, "left": 0, "right": 0, "top": 0, "bottom": 0},
            ],
            "edits": {"0-99": 0, "100-199": 1},
        }
    }), encoding="utf-8")
    crop, dynamic = parse_level5_export(exported, source_width=3840, source_height=2160)
    assert crop is None
    assert dynamic is True


def test_dv_crop_filter_wird_in_vf_kette_korrekt_ersetzt():
    args = ["-map", "0:v:0", "-vf", "libplacebo=format=p010le,crop=3840:1600:0:280,scale=1920:800"]
    result = replace_crop_in_vf_args(args, "crop=3840:1600:0:280", "crop=3840:1608:0:276")
    assert result[-1] == "libplacebo=format=p010le,crop=3840:1608:0:276,scale=1920:800"


def test_container_policy_standard_hdrplus_und_dv_sind_getrennt():
    standard = resolve_pipeline_context(_mi(), codec="h265", standard_container="mp4", dv_container="mkv")
    hdrplus = resolve_pipeline_context(_mi(hdrplus=True), codec="h265", standard_container="mp4", dv_container="mkv")
    dv = resolve_pipeline_context(_mi(dv=True), codec="h265", standard_container="mp4", dv_container="mkv")
    assert (standard["pipeline"], standard["container"]) == ("standard", "mp4")
    assert (hdrplus["pipeline"], hdrplus["container"]) == ("hdrplus", "mp4")
    assert (dv["pipeline"], dv["container"]) == ("dv", "mkv")


def test_mp4box_mux_ist_streamingoptimiert(tmp_path):
    out = tmp_path / "out.mp4"
    injected = tmp_path / "video.hevc"
    injected.write_bytes(b"x")
    seen = []

    def run(cmd, **_kwargs):
        seen.append(list(cmd))
        return 0

    muxer = DVMP4BoxMuxer(mp4box_path="MP4Box", audio_track_name=lambda _meta: "")
    assert muxer.mux_final_output(run, output_path=str(out), injected_hevc=injected, mux_tracks=[])
    cmd = seen[0]
    assert cmd[cmd.index("-inter") + 1] == "500"


def test_manuelle_seriensuche_ueberschreibt_nur_den_suchbegriff(tmp_path):
    source = tmp_path / "Wrong.Name.S01E02.1080p.WEB-DL.mkv"
    source.write_text("x", encoding="utf-8")
    observed = {}

    def resolver(series: str, season: int, episode: int, year):
        observed.update(series=series, season=season, episode=episode, year=year)
        return [{
            "series": "Correct Series",
            "season": season,
            "episode": episode,
            "episode_title": "Die richtige Folge",
            "provider": "manual-test",
            "provider_id": 1,
            "episode_id": 2,
        }]

    proposal = build_series_rename_proposal(source, resolver=resolver, query_override="Correct Series")
    assert observed["series"] == "Correct Series"
    assert observed["season"] == 1 and observed["episode"] == 2
    assert proposal.selected is not None
    assert proposal.target_name == "Correct Series - S01E02 - Die richtige Folge.mkv"


def test_preflight_release_erkennung_markiert_punktnamen_und_technik_tags():
    warnings = release_style_warnings("Dark.Matter.2024.S02E01.German.2160p.WEB-DL.DDP5.1.H265-GRP.mkv")
    assert any("Punkte/Unterstriche" in item for item in warnings)
    assert any("Technik-Tags" in item or "Release-Gruppe" in item for item in warnings)


def test_dv_mkv_mux_hat_eigenen_timeout_und_keinen_veralteten_reextract_timeout():
    from dragontools.core.timeout_settings import TIMEOUT_DEFS

    keys = {item.key for item in TIMEOUT_DEFS}
    assert "dv_mkvmerge" in keys
    assert "dv_hevc_re_extract" not in keys


def test_series_release_group_does_not_misclassify_normal_episode_title_word():
    from dragontools.core.movie_renamer import parse_series_release_name

    parsed = parse_series_release_name(
        "Kaguya-sama Love Is War - S03E13 - Abschlussevent.mkv"
    )
    assert parsed is not None
    assert parsed.release_group == ""
    assert not any("Release-Gruppe" in item for item in release_style_warnings(parsed.source_name))


def test_series_release_group_still_detects_scene_group_after_technical_tags():
    from dragontools.core.movie_renamer import parse_series_release_name

    parsed = parse_series_release_name(
        "Dark.Matter.2024.S02E01.German.2160p.WEB-DL.DDP5.1.H265-GRP.mkv"
    )
    assert parsed is not None
    assert parsed.release_group == "GRP"


def test_preflight_and_renamer_share_series_query_and_local_title_rules():
    from dragontools.core.movie_renamer import parse_series_release_name, sanitize_filename_part
    from dragontools.core.online_metadata_common import metadata_series_folder_title

    parsed = parse_series_release_name(
        "Kaguya-sama Love Is War - S01E01 - Ich werde dich dazu bringen.mkv"
    )
    assert parsed is not None
    assert parsed.series == "Kaguya sama Love Is War"
    assert metadata_series_folder_title("Kaguya-sama: Love Is War") == sanitize_filename_part(
        "Kaguya-sama: Love Is War", fallback=""
    )
    assert metadata_series_folder_title("Kaguya-sama: Love Is War") == "Kaguya-sama Love Is War"
