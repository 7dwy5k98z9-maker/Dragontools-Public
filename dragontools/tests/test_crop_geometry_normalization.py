from __future__ import annotations

import json
from pathlib import Path

from dragontools.worker.crop_geometry import (
    CropRect,
    normalize_crop_filter,
    normalize_crop_rect,
)
from dragontools.worker.dv_crop_reconcile import reconcile_dv_crop
from dragontools.worker.media_contract_types import ExpectedMediaContract
from dragontools.worker.output_contract_video import evaluate_video_contract, verify_video_contract


def _contract(*, width: int, height: int) -> ExpectedMediaContract:
    return ExpectedMediaContract(
        container="mkv",
        video_codec="hevc",
        video_stream_count=1,
        audio_tracks=(),
        subtitle_tracks=(),
        min_video_bit_depth=10,
        expected_width=width,
        expected_height=height,
    )


def _video(*, width: int, height: int) -> dict:
    return {
        "codec_name": "hevc",
        "pix_fmt": "yuv420p10le",
        "width": width,
        "height": height,
    }


def test_odd_height_expands_to_next_even_pixel() -> None:
    rect = CropRect(width=3840, height=1607, x=0, y=276)
    result = normalize_crop_rect(rect, source_width=3840, source_height=2160)
    assert result == CropRect(width=3840, height=1608, x=0, y=276)


def test_odd_origin_expands_outward_instead_of_cutting_picture() -> None:
    rect = CropRect(width=3838, height=1608, x=1, y=275)
    result = normalize_crop_rect(rect, source_width=3840, source_height=2160)
    assert result.x == 0
    assert result.y == 274
    assert result.width % 2 == 0
    assert result.height % 2 == 0
    # Original active area remains contained in the normalized area.
    assert result.x <= rect.x
    assert result.y <= rect.y
    assert result.x + result.width >= rect.x + rect.width
    assert result.y + result.height >= rect.y + rect.height


def test_crop_filter_normalization_is_deterministic() -> None:
    assert normalize_crop_filter(
        "crop=3840:1607:0:276",
        source_width=3840,
        source_height=2160,
    ) == "crop=3840:1608:0:276"


class _Level5Runner:
    def __init__(self, export_path: Path) -> None:
        self.export_path = export_path

    def run(self, _cmd, **_kwargs):
        self.export_path.write_text(
            json.dumps(
                {
                    "active_area": {
                        "presets": [
                            {
                                "id": 0,
                                "left": 0,
                                "right": 0,
                                "top": 276,
                                "bottom": 277,
                            }
                        ],
                        "edits": {"all": 0},
                    }
                }
            ),
            encoding="utf-8",
        )
        return 0


def test_dv_reconcile_normalizes_odd_rpu_area_before_encode(tmp_path: Path) -> None:
    export_path = tmp_path / "level5.json"
    rpu_path = tmp_path / "source.rpu"
    rpu_path.write_bytes(b"rpu")
    logs: list[str] = []

    result = reconcile_dv_crop(
        runner=_Level5Runner(export_path),
        dovi_tool="dovi_tool",
        rpu_path=rpu_path,
        export_path=export_path,
        source_width=3840,
        source_height=2160,
        autocrop_text="crop=3840:1607:0:276",
        input_path="movie.mkv",
        log=lambda message, _level="info": logs.append(message),
    )

    assert result.success is True
    assert result.crop is not None
    assert result.crop.as_filter() == "crop=3840:1608:0:276"
    assert any("normalisiert" in message for message in logs)


def test_final_validation_uses_minor_warning_after_normalization() -> None:
    contract = _contract(width=3840, height=1608)
    assert verify_video_contract(contract, [_video(width=3840, height=1608)]) == []

    check = evaluate_video_contract(contract, [_video(width=3840, height=1607)])
    assert check.errors == ()
    assert check.geometry_max_delta == 1
    assert any("WARNUNG" in message for message in check.warnings)
