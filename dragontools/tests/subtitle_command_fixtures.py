"""Isolate argv/result tests from media I/O; media verification has separate tests."""

from types import SimpleNamespace
import pytest

COMMAND_TESTS = {
    "test_subtitle_injector_uses_configured_mkvmerge_path",
    "test_subtitle_injector_mp4_text_mode_maps_only_video_audio_and_new_subtitle",
    "test_subtitle_extract_with_ffmpeg_accepts_codec_args",
    "test_dv_auto_exportiert_keep_subs_als_sidecars",
    "test_dv_custom_export_respektiert_keep_auswahl",
    "test_mkvmerge_warning_output_is_committed",
    "test_ffmpeg_injection_failure_does_not_poison_retry_target",
    "test_mp4_injection_preserves_existing_subtitles_and_converts_only_new_track",
    "test_erfolgreich_exportierte_subs_in_liste",
    "test_structured_result_marks_partial_export_as_incomplete",
    "test_ass_sidecar_can_also_export_srt_variant",
    "test_mkv_text_to_srt_exports_only_srt_variant",
    "test_mkv_mov_text_can_export_srt_sidecar",
    "test_sidecar_service_exports_only_bitmap_when_global_mp4_sidecars_are_off",
    "test_extract_uses_shared_runner_and_worker",
    "test_ffmpeg_inject_uses_shared_runner",
    "test_mp4_injection_sets_language_and_forced_on_new_subtitle_without_probe",
    "test_mkv_ffmpeg_fallback_targets_appended_subtitle_after_existing_tracks",
    "test_ffmpeg_injection_explicitly_clears_forced_on_new_track",
    "test_metadata_applied_to_new_track",
    "test_mov_text_backup_is_lossless_subtitle_only_mp4",
    "test_pgs_ocr_failure_keeps_successfully_exported_original",
}


@pytest.fixture(autouse=True)
def subtitle_command_validation(monkeypatch, request):
    if request.node.originalname not in COMMAND_TESTS:
        return
    from dragontools.subtitle import injector, extractor
    from dragontools.worker import subtitle_sidecar_exporter

    def plan(*args, **kwargs):
        return SimpleNamespace(
            source_streams=(),
            new_subtitle_index=kwargs.get("existing_subtitle_count") or 0,
        )

    monkeypatch.setattr(injector, "build_injection_plan", plan)
    monkeypatch.setattr(injector, "verify_injection", lambda *_a, **_k: True)
    monkeypatch.setattr(
        injector,
        "_identify",
        lambda _tool, path, _worker: (
            [{"id": 0, "type": "subtitles"}]
            if str(path).lower().endswith((".srt", ".ass", ".sup"))
            else []
        ),
    )
    monkeypatch.setattr(extractor, "verify_extraction", lambda *_a, **_k: True)
    monkeypatch.setattr(
        subtitle_sidecar_exporter, "verify_subtitle_export", lambda *_a, **_k: True
    )
