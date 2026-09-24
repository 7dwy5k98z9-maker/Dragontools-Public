# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from dragontools.worker.encoder_args import _vid_args


@pytest.mark.parametrize(
    ("encoder", "expected_codec", "expected_pix_fmt", "extra_options"),
    [
        ("nvenc", "hevc_nvenc", "p010le", {"preset": "p6", "cq": 23, "bf": 4, "bref_mode": "middle"}),
        ("qsv", "hevc_qsv", "p010le", {"q": 23}),
        ("amf", "hevc_amf", "p010le", {"quality": "balanced", "qp": 23}),
        ("cpu", "libx265", "yuv420p10le", {}),
    ],
)
def test_h265_encoder_forciert_echtes_10bit(encoder, expected_codec, expected_pix_fmt, extra_options):
    args = _vid_args(
        "h265",
        23,
        "medium",
        {"encoder": encoder, **extra_options},
    )

    assert args[args.index("-c:v") + 1] == expected_codec
    assert args[args.index("-profile:v") + 1] == "main10"
    assert args[args.index("-pix_fmt") + 1] == expected_pix_fmt
    if encoder == "amf":
        assert args[args.index("-bitdepth") + 1] == "10"


@pytest.mark.parametrize(
    ("encoder", "expected_codec", "extra_options"),
    [
        ("nvenc", "h264_nvenc", {"preset": "p6", "cq": 22}),
        ("qsv", "h264_qsv", {"q": 22}),
        ("amf", "h264_amf", {"quality": "balanced", "qp": 22}),
        ("cpu", "libx264", {}),
    ],
)
def test_h264_bleibt_8bit_kompatibel_ohne_10bit_zwang(encoder, expected_codec, extra_options):
    args = _vid_args(
        "h264",
        22,
        "medium",
        {"encoder": encoder, **extra_options},
    )

    assert args[args.index("-c:v") + 1] == expected_codec
    assert "-pix_fmt" not in args
    assert "-profile:v" not in args
    assert "-bitdepth" not in args


def test_nvenc_lookahead_wird_ohne_bframes_nicht_gesetzt():
    args = _vid_args(
        "h265",
        23,
        "medium",
        {
            "encoder": "nvenc",
            "preset": "p6",
            "cq": 23,
            "bf": 0,
            "bref_mode": "middle",
            "rc_lookahead": 32,
        },
    )

    assert "-bf" not in args
    assert "-b_ref_mode" not in args
    assert "-rc-lookahead" not in args


def test_nvenc_auto_lookahead_level_und_multipass_werden_nicht_gesetzt():
    args = _vid_args(
        "h265",
        23,
        "medium",
        {
            "encoder": "nvenc",
            "preset": "p6",
            "cq": 23,
            "bf": 4,
            "rc_lookahead": 32,
            "lookahead_level": "auto",
            "multipass": "auto",
        },
    )

    assert "-lookahead_level" not in args
    assert "-multipass" not in args


def test_nvenc_lookahead_level_und_multipass_werden_bei_auswahl_gesetzt():
    args = _vid_args(
        "h265",
        23,
        "medium",
        {
            "encoder": "nvenc",
            "preset": "p6",
            "cq": 23,
            "bf": 4,
            "rc_lookahead": 32,
            "lookahead_level": "3",
            "multipass": "fullres",
        },
    )

    assert args[args.index("-lookahead_level") + 1] == "3"
    assert args[args.index("-multipass") + 1] == "fullres"


def test_x265_lookahead_wird_ohne_bframes_nicht_gesetzt():
    args = _vid_args(
        "h265",
        23,
        "medium",
        {
            "encoder": "cpu",
            "bf": 0,
            "rc_lookahead": 40,
        },
    )

    params = args[args.index("-x265-params") + 1]
    assert "bframes=0" in params
    assert "rc-lookahead" not in params


def test_qsv_h264_uses_la_icq_without_qscale_conflict():
    args = _vid_args(
        "h264",
        23,
        "medium",
        {
            "encoder": "qsv",
            "q": 23,
            "lookahead_depth": 40,
        },
    )

    assert args[args.index("-global_quality") + 1] == "23"
    assert "-q" not in args
    assert args[args.index("-look_ahead") + 1] == "1"
    assert args[args.index("-look_ahead_depth") + 1] == "40"


@pytest.mark.parametrize("codec", ["h265", "av1"])
def test_qsv_hevc_av1_use_extbrc_lookahead_without_h264_only_switch(codec):
    args = _vid_args(
        codec,
        23,
        "medium",
        {
            "encoder": "qsv",
            "q": 23,
            "lookahead_depth": 40,
            "_force_10bit": codec == "av1",
        },
    )

    assert args[args.index("-global_quality") + 1] == "23"
    assert "-q" not in args
    assert "-look_ahead" not in args
    assert args[args.index("-extbrc") + 1] == "1"
    assert args[args.index("-look_ahead_depth") + 1] == "40"


def test_x265_hdr10_vui_parameter_werden_bei_hdr10_ausgabe_gesetzt():
    args = _vid_args(
        "h265",
        23,
        "medium",
        {
            "encoder": "cpu",
            "_force_hdr10_vui": True,
        },
    )

    params = args[args.index("-x265-params") + 1]
    assert "colorprim=bt2020" in params
    assert "transfer=smpte2084" in params
    assert "colormatrix=bt2020nc" in params
    assert "range=limited" in params
    assert "hdr10=1" in params


def test_nvenc_legacy_string_options_are_normalized_at_ffmpeg_boundary():
    args = _vid_args(
        "h265",
        23,
        "medium",
        {
            "encoder": "nvenc",
            "preset": "p6",
            "cq": "19.0",
            "bf": "4.0",
            "rc_lookahead": "32.0",
            "aq_strength": "8.0",
            "spatial_aq": "false",
            "temporal_aq": "0",
        },
    )

    assert args[args.index("-cq") + 1] == "19"
    assert args[args.index("-bf") + 1] == "4"
    assert args[args.index("-rc-lookahead") + 1] == "32"
    assert "-spatial-aq" not in args
    assert "-temporal-aq" not in args
    assert "-spatial_aq" not in args
    assert "-temporal_aq" not in args


def test_qsv_and_amf_legacy_float_strings_become_integer_arguments():
    qsv_args = _vid_args(
        "h265", 23, "medium",
        {"encoder": "qsv", "q": "21.0", "lookahead_depth": "48.0"},
    )
    amf_args = _vid_args(
        "h265", 23, "medium",
        {"encoder": "amf", "qp": "22.0", "quality": "balanced"},
    )

    assert qsv_args[qsv_args.index("-global_quality") + 1] == "21"
    assert qsv_args[qsv_args.index("-look_ahead_depth") + 1] == "48"
    assert amf_args[amf_args.index("-qp_i") + 1] == "22"


def test_qsv_lookahead_depth_is_clamped_before_ffmpeg():
    high_args = _vid_args(
        "h265",
        23,
        "medium",
        {"encoder": "qsv", "q": 23, "lookahead_depth": 250},
    )
    low_args = _vid_args(
        "h265",
        23,
        "medium",
        {"encoder": "qsv", "q": 23, "lookahead_depth": 0},
    )

    assert high_args[high_args.index("-look_ahead_depth") + 1] == "100"
    assert low_args[low_args.index("-look_ahead_depth") + 1] == "1"


@pytest.mark.parametrize("codec", ["h264", "h265", "av1"])
def test_nvenc_aq_uses_current_canonical_ffmpeg_option_names(codec):
    args = _vid_args(
        codec,
        23,
        "medium",
        {
            "encoder": "nvenc",
            "preset": "p6",
            "cq": 23,
            "spatial_aq": True,
            "temporal_aq": True,
            "aq_strength": 10,
            "_force_10bit": codec == "av1",
        },
    )

    assert args[args.index("-spatial-aq") + 1] == "1"
    assert args[args.index("-temporal-aq") + 1] == "1"
    assert args[args.index("-aq-strength") + 1] == "10"
    assert "-spatial_aq" not in args
    assert "-temporal_aq" not in args


@pytest.mark.parametrize(
    ("codec", "expects_b_qp"),
    [("h264", True), ("h265", False), ("av1", True)],
)
def test_amf_only_emits_qp_b_for_codecs_that_expose_it(codec, expects_b_qp):
    args = _vid_args(
        codec,
        23,
        "medium",
        {
            "encoder": "amf",
            "quality": "balanced",
            "qp": 23,
            "_force_10bit": codec == "av1",
        },
    )

    assert ("-qp_b" in args) is expects_b_qp


def test_hardware_quality_values_are_clamped_to_encoder_ranges():
    nv_hevc = _vid_args("h265", 23, "medium", {"encoder": "nvenc", "cq": 63})
    nv_av1 = _vid_args("av1", 28, "medium", {"encoder": "nvenc", "cq": 99})
    qsv = _vid_args("h265", 23, "medium", {"encoder": "qsv", "q": 63, "lookahead_depth": 40})
    amf_hevc = _vid_args("h265", 23, "medium", {"encoder": "amf", "qp": 63})

    assert nv_hevc[nv_hevc.index("-cq") + 1] == "51"
    assert nv_av1[nv_av1.index("-cq") + 1] == "63"
    assert qsv[qsv.index("-global_quality") + 1] == "51"
    assert amf_hevc[amf_hevc.index("-qp_i") + 1] == "51"
    assert amf_hevc[amf_hevc.index("-qp_p") + 1] == "51"


def test_nvenc_aq_strength_is_integer_and_clamped():
    args = _vid_args(
        "h265",
        23,
        "medium",
        {
            "encoder": "nvenc",
            "spatial_aq": True,
            "aq_strength": "99.0",
        },
    )

    assert args[args.index("-aq-strength") + 1] == "15"
