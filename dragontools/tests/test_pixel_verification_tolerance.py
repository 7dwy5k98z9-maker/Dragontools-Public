from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.worker.media_contract_types import ExpectedMediaContract
from dragontools.worker.output_contract_video import evaluate_video_contract, verify_video_contract
from dragontools.worker.workflow_engine import WorkflowVerifyResult
from dragontools.worker.workflow_output_commit import WorkflowOutputCommitCoordinator
from dragontools.worker.workflow_verification_service import WorkflowVerificationService


def _contract(*, width: int | None = None, height: int | None = None, dv: bool = False) -> ExpectedMediaContract:
    return ExpectedMediaContract(
        container="mkv",
        video_codec="hevc",
        video_stream_count=1,
        audio_tracks=(),
        subtitle_tracks=(),
        min_video_bit_depth=10,
        require_dolby_vision=dv,
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


def test_final_pixel_check_warns_for_one_or_two_pixels() -> None:
    exact = evaluate_video_contract(_contract(width=3840, height=1608), [_video(width=3840, height=1608)])
    assert exact.errors == ()
    assert exact.warnings == ()
    assert exact.geometry_max_delta == 0

    one = evaluate_video_contract(_contract(width=3840, height=1608), [_video(width=3840, height=1607)])
    assert one.errors == ()
    assert one.geometry_max_delta == 1
    assert one.geometry_severity == "minor"
    assert any("WARNUNG" in message and "1 Pixel" in message for message in one.warnings)

    two = evaluate_video_contract(_contract(width=3840, height=1608), [_video(width=3840, height=1606)])
    assert two.errors == ()
    assert two.geometry_max_delta == 2
    assert any("2 Pixel" in message for message in two.warnings)
    # Compatibility API exposes only blocking contract errors.
    assert verify_video_contract(_contract(width=3840, height=1608), [_video(width=3840, height=1606)]) == []


def test_final_pixel_check_blocks_three_pixels_and_more() -> None:
    review = evaluate_video_contract(_contract(width=3840, height=1608), [_video(width=3840, height=1605)])
    assert review.geometry_max_delta == 3
    assert review.geometry_severity == "review"
    assert any("3 Pixel" in message for message in review.errors)

    major = evaluate_video_contract(_contract(width=3840, height=1608), [_video(width=3840, height=1602)])
    assert major.geometry_max_delta == 6
    assert major.geometry_severity == "major"
    assert major.errors


class _Logger:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.infos: list[str] = []

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def info(self, message: str) -> None:
        self.infos.append(message)


class _Verifier:
    def __init__(self, result: WorkflowVerifyResult) -> None:
        self.result = result

    def verify(self, *_args, **_kwargs) -> WorkflowVerifyResult:
        return self.result


class _NoRepair:
    def can_repair(self, **_kwargs) -> bool:
        return False


def _valid_result(*, delta: int, contract_ok: bool, expected_h: int = 1608) -> WorkflowVerifyResult:
    return WorkflowVerifyResult(
        exists=True,
        size_ok=True,
        container_ok=True,
        probe_ok=True,
        video_ok=True,
        audio_ok=True,
        subtitle_ok=True,
        contract_ok=contract_ok,
        contract_non_geometry_ok=True,
        metadata_ok=True,
        duration_ok=True,
        expected_width=3840,
        expected_height=expected_h,
        actual_width=3840,
        actual_height=expected_h - delta,
        geometry_max_delta=delta,
        geometry_severity="minor" if delta <= 2 else "review" if delta <= 4 else "major",
        messages=[] if contract_ok else [f"FEHLER: Video-Hoehe abweichend ({delta} Pixel)."],
        warnings=[] if delta == 0 else [f"WARNUNG: Geometrie {delta} Pixel abweichend."],
    )


def _ctx(tmp_path: Path, *, result: WorkflowVerifyResult, dv: bool = False, rpu_ok: bool = False):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"source")
    output_dir = tmp_path / "work"
    output_dir.mkdir(exist_ok=True)
    output = output_dir / "result.mkv"
    output.write_bytes(b"encoded-result")
    return SimpleNamespace(
        analysis=SimpleNamespace(audio_streams=[]),
        expected_media_contract=_contract(width=3840, height=1608, dv=dv),
        duration_ms=1000,
        output_path=str(output),
        container="mkv",
        input_path=str(source),
        base_dir=tmp_path,
        pipeline="dv" if dv else "standard",
        pipeline_verified_hdr10plus=False,
        pipeline_verified_dolby_vision=dv,
        pipeline_verified_dv_crop_alignment=rpu_ok,
        effective_crop_filter="crop=3840:1608:0:276" if dv else "crop=3840:1608:0:276",
        keep_failed_output=False,
        verify_result=result,
    )


def test_two_pixel_difference_is_warning_and_replace_remains_allowed(tmp_path: Path) -> None:
    result = _valid_result(delta=2, contract_ok=True)
    logger = _Logger()
    service = WorkflowVerificationService(output_verifier=_Verifier(result), duration_repair_service=_NoRepair(), logger=logger)
    ctx = _ctx(tmp_path, result=result)

    service.verify(ctx)

    assert not getattr(ctx, "verification_archive_required", False)
    assert any("2 Pixel" in message for message in logger.warnings)


def test_dv_two_pixel_difference_requires_verified_rpu_alignment(tmp_path: Path) -> None:
    result = _valid_result(delta=2, contract_ok=True)
    logger = _Logger()
    service = WorkflowVerificationService(output_verifier=_Verifier(result), duration_repair_service=_NoRepair(), logger=logger)
    ctx = _ctx(tmp_path, result=result, dv=True, rpu_ok=False)

    service.verify(ctx)

    assert ctx.verification_archive_required is True
    assert ctx.verification_archive_with_postprocess is True
    assert ctx.dv_rpu_alignment_checked is True
    assert ctx.dv_rpu_alignment_ok is False


def test_dv_two_pixel_difference_passes_when_final_crop_rpu_is_verified(tmp_path: Path) -> None:
    result = _valid_result(delta=2, contract_ok=True)
    logger = _Logger()
    service = WorkflowVerificationService(output_verifier=_Verifier(result), duration_repair_service=_NoRepair(), logger=logger)
    ctx = _ctx(tmp_path, result=result, dv=True, rpu_ok=True)

    service.verify(ctx)

    assert not getattr(ctx, "verification_archive_required", False)
    assert ctx.dv_rpu_alignment_ok is True
    assert any("DV-RPU-Geometrie OK" in message for message in result.warnings)


def test_exact_video_geometry_does_not_escalate_rpu_hash_difference(tmp_path: Path) -> None:
    result = _valid_result(delta=0, contract_ok=True)
    logger = _Logger()
    service = WorkflowVerificationService(output_verifier=_Verifier(result), duration_repair_service=_NoRepair(), logger=logger)
    ctx = _ctx(tmp_path, result=result, dv=True, rpu_ok=False)
    ctx.pipeline_final_rpu_checked = True
    ctx.pipeline_final_rpu_present = True
    ctx.pipeline_final_rpu_matches_injected = False
    ctx.pipeline_final_rpu_expected_sha256 = "a" * 64
    ctx.pipeline_final_rpu_actual_sha256 = "b" * 64
    ctx.pipeline_final_rpu_level5_offsets = ((0, 0, 2, 0),)
    ctx.pipeline_final_rpu_level5_dynamic = False
    ctx.pipeline_final_rpu_message = "Finale RPU weicht byteweise ab."

    service.verify(ctx)

    assert not getattr(ctx, "verification_archive_required", False)
    assert not getattr(ctx, "dv_rpu_alignment_checked", False)


def _dv_deviation_result(*, expected_h: int, actual_h: int) -> WorkflowVerifyResult:
    delta = abs(actual_h - expected_h)
    return WorkflowVerifyResult(
        exists=True,
        size_ok=True,
        container_ok=True,
        probe_ok=True,
        video_ok=True,
        audio_ok=True,
        subtitle_ok=True,
        contract_ok=delta <= 2,
        contract_non_geometry_ok=True,
        metadata_ok=True,
        duration_ok=True,
        expected_width=3840,
        expected_height=expected_h,
        actual_width=3840,
        actual_height=actual_h,
        geometry_max_delta=delta,
        geometry_severity="minor" if delta <= 2 else "review" if delta <= 4 else "major",
        messages=[] if delta <= 2 else [f"FEHLER: Video-Hoehe abweichend ({delta} Pixel)."],
        warnings=[f"WARNUNG: Geometrie {delta} Pixel abweichend."],
    )


def _set_final_rpu(ctx, *, offsets, hash_matches=False) -> None:
    ctx.pipeline_final_rpu_checked = True
    ctx.pipeline_final_rpu_present = True
    ctx.pipeline_final_rpu_matches_injected = hash_matches
    ctx.pipeline_final_rpu_expected_sha256 = "a" * 64
    ctx.pipeline_final_rpu_actual_sha256 = ("a" if hash_matches else "b") * 64
    ctx.pipeline_final_rpu_level5_offsets = offsets
    ctx.pipeline_final_rpu_level5_dynamic = len(offsets) > 1
    ctx.pipeline_final_rpu_message = "Finale RPU wurde ausgewertet."


def test_two_pixel_video_growth_accepts_rpu_active_area_matching_expected_crop(tmp_path: Path) -> None:
    # Soll 1606, finales Video 1608. T=2 ergibt aktive RPU-Hoehe 1606.
    result = _dv_deviation_result(expected_h=1606, actual_h=1608)
    logger = _Logger()
    service = WorkflowVerificationService(output_verifier=_Verifier(result), duration_repair_service=_NoRepair(), logger=logger)
    ctx = _ctx(tmp_path, result=result, dv=True, rpu_ok=False)
    ctx.expected_media_contract = _contract(width=3840, height=1606, dv=True)
    _set_final_rpu(ctx, offsets=((0, 0, 2, 0),), hash_matches=False)

    service.verify(ctx)

    assert not getattr(ctx, "verification_archive_required", False)
    assert ctx.dv_rpu_alignment_ok is True
    assert "Soll-Geometrie" in ctx.dv_rpu_alignment_match_mode


def test_two_pixel_video_growth_accepts_rpu_active_area_matching_actual_video(tmp_path: Path) -> None:
    # Soll 1606, finales Video 1608. L5=0 deckt die tatsaechliche 1608er Flaeche ab.
    result = _dv_deviation_result(expected_h=1606, actual_h=1608)
    logger = _Logger()
    service = WorkflowVerificationService(output_verifier=_Verifier(result), duration_repair_service=_NoRepair(), logger=logger)
    ctx = _ctx(tmp_path, result=result, dv=True, rpu_ok=False)
    ctx.expected_media_contract = _contract(width=3840, height=1606, dv=True)
    _set_final_rpu(ctx, offsets=((0, 0, 0, 0),), hash_matches=False)

    service.verify(ctx)

    assert not getattr(ctx, "verification_archive_required", False)
    assert ctx.dv_rpu_alignment_ok is True
    assert "finaler Video-Geometrie" in ctx.dv_rpu_alignment_match_mode


def test_two_pixel_video_growth_archives_when_rpu_matches_neither_expected_nor_actual(tmp_path: Path) -> None:
    # Soll 1606, Video 1608, T=4 => aktive RPU-Hoehe 1604: weder Soll noch Ist.
    result = _dv_deviation_result(expected_h=1606, actual_h=1608)
    logger = _Logger()
    service = WorkflowVerificationService(output_verifier=_Verifier(result), duration_repair_service=_NoRepair(), logger=logger)
    ctx = _ctx(tmp_path, result=result, dv=True, rpu_ok=False)
    ctx.expected_media_contract = _contract(width=3840, height=1606, dv=True)
    _set_final_rpu(ctx, offsets=((0, 0, 4, 0),), hash_matches=False)

    service.verify(ctx)

    assert ctx.verification_archive_required is True
    assert ctx.verification_archive_with_postprocess is True
    assert ctx.verification_archive_tier == "minor_rpu_geometry_mismatch"
    assert ctx.keep_failed_output is True


def test_three_to_four_pixel_difference_is_archived_with_postprocess(tmp_path: Path) -> None:
    result = _valid_result(delta=4, contract_ok=False)
    logger = _Logger()
    service = WorkflowVerificationService(output_verifier=_Verifier(result), duration_repair_service=_NoRepair(), logger=logger)
    ctx = _ctx(tmp_path, result=result)

    service.verify(ctx)

    assert ctx.verification_archive_required is True
    assert ctx.verification_archive_with_postprocess is True
    assert ctx.verification_archive_tier == "review_3_4"


def test_more_than_four_pixels_is_archived_without_postprocess(tmp_path: Path) -> None:
    result = _valid_result(delta=6, contract_ok=False)
    logger = _Logger()
    service = WorkflowVerificationService(output_verifier=_Verifier(result), duration_repair_service=_NoRepair(), logger=logger)
    ctx = _ctx(tmp_path, result=result)

    service.verify(ctx)

    assert ctx.verification_archive_required is True
    assert ctx.verification_archive_with_postprocess is False
    assert ctx.verification_archive_tier == "major_gt4"


class _PostProcess:
    def run_result(self, *, input_path: str, output_path: str, prepared_source_trickplay=None):
        out = Path(output_path)
        nfo = out.with_suffix(".nfo")
        nfo.write_text("nfo", encoding="utf-8")
        trickplay = out.parent / f"{out.stem}.trickplay"
        trickplay.mkdir(exist_ok=True)
        return SimpleNamespace(
            created_paths=[str(nfo), str(trickplay)],
            items=[
                {"kind": "nfo", "status": "created", "path": str(nfo), "message": ""},
                {"kind": "trickplay", "status": "created", "path": str(trickplay), "message": ""},
            ],
        )


class _ResultService:
    pass


class _ReplaceService:
    pass


def test_geometry_archive_bundle_contains_video_nfo_trickplay_and_reason_txt(tmp_path: Path) -> None:
    result = _valid_result(delta=4, contract_ok=False)
    ctx = _ctx(tmp_path, result=result)
    ctx.verification_archive_required = True
    ctx.verification_archive_with_postprocess = True
    ctx.verification_archive_reason = "4 Pixel Differenz; Original nicht ersetzen."
    ctx.verification_archive_tier = "review_3_4"
    ctx.sidecar_paths = []
    ctx.final_output_path = None
    ctx.replacement_archived_path = None
    ctx.replacement_blocked = False
    ctx.pipeline = "dv"
    ctx.dv_rpu_alignment_checked = True
    ctx.dv_rpu_alignment_ok = True
    ctx.dv_rpu_alignment_message = "DV-RPU-Pixelabgleich OK"
    ctx.pipeline_final_rpu_checked = True
    ctx.pipeline_final_rpu_present = True
    ctx.pipeline_final_rpu_matches_injected = False
    ctx.pipeline_final_rpu_expected_sha256 = "a" * 64
    ctx.pipeline_final_rpu_actual_sha256 = "b" * 64
    ctx.pipeline_final_rpu_level5_offsets = ((0, 0, 2, 0),)
    ctx.pipeline_final_rpu_level5_dynamic = False
    ctx.pipeline_final_rpu_message = "Finale RPU weicht ab."

    coordinator = WorkflowOutputCommitCoordinator(
        replace_service=_ReplaceService(),
        logger=_Logger(),
        result_service=_ResultService(),
        sidecar_outputs={},
        postprocess_outputs={},
        postprocess_service=_PostProcess(),
        postprocess_coordinator=None,
    )
    coordinator.replace(ctx)

    archived = Path(ctx.replacement_archived_path)
    assert archived.exists()
    assert archived.parent == tmp_path / "Archiv"
    assert archived.with_suffix(".nfo").exists()
    assert (archived.parent / f"{archived.stem}.trickplay").is_dir()
    report = Path(ctx.verification_report_path)
    csv_report = Path(ctx.verification_csv_path)
    assert report.exists()
    assert csv_report.exists()
    csv_text = csv_report.read_text(encoding="utf-8-sig")
    assert "Delta_Max;4;Pixel" in csv_text
    assert "Hash_identisch_zur_injizierten_RPU" in csv_text
    assert "RPU_Video_Max_Delta;2;Pixel" in csv_text
    assert "Area_1_Offsets;L=0,R=0,T=2,B=0;Pixel" in csv_text
    assert ("Hash_identisch_zur_injizierten_RPU;NEIN" in csv_text)
    assert "dovi_tool extract-rpu" in csv_text
    text = report.read_text(encoding="utf-8")
    assert "4 Pixel" in text
    assert "dovi_tool extract-rpu" in text
    assert "aktive Breite = Video-Breite - left - right" in text
    assert ctx.replacement_blocked is True


def test_failed_non_geometry_verification_still_archives_fail_safe(tmp_path: Path) -> None:
    source = tmp_path / "source.mkv"
    source.write_bytes(b"source")
    output_dir = tmp_path / "work"
    output_dir.mkdir()
    output = output_dir / "result.mkv"
    output.write_bytes(b"encoded-result")

    result = WorkflowVerifyResult(
        exists=True,
        size_ok=True,
        container_ok=True,
        probe_ok=True,
        video_ok=True,
        audio_ok=True,
        subtitle_ok=True,
        contract_ok=False,
        contract_non_geometry_ok=False,
        metadata_ok=True,
        duration_ok=True,
        messages=["Videocodec abweichend."],
        warnings=[],
    )
    logger = _Logger()
    service = WorkflowVerificationService(output_verifier=_Verifier(result), duration_repair_service=_NoRepair(), logger=logger)
    ctx = SimpleNamespace(
        analysis=SimpleNamespace(audio_streams=[]), expected_media_contract=None, duration_ms=1000,
        output_path=str(output), container="mkv", input_path=str(source), base_dir=tmp_path,
        pipeline_verified_hdr10plus=False, pipeline_verified_dolby_vision=False, keep_failed_output=False,
    )

    with pytest.raises(RuntimeError, match="Verify fehlgeschlagen"):
        service.verify(ctx)

    archived = Path(ctx.verification_archive_path)
    assert ctx.keep_failed_output is True
    assert archived.parent == tmp_path / "Archiv"
    assert archived.read_bytes() == b"encoded-result"
