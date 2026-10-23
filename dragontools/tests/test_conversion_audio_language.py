from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest

from dragontools.core.language_detection import LanguageDetectionResult
from dragontools.core.models import AudioStream, MediaInfo, VideoStream
from dragontools.rules.audio_plan import compute_audio_track_plan
from dragontools.rules.audio_rules import migrate_audio_rules
from dragontools.rules.audio_selection import unknown_audio_streams_without_priority_match
from dragontools.worker.conversion_audio_language import ConversionAudioLanguageRecovery


def _stream(index, language="und", title=""):
    return AudioStream(index, language, False, title, "dts", 2, bitrate=768000)


def _rules(**updates):
    return migrate_audio_rules({
        "language_priority": ["de"], "max_languages": 1, "tracks_per_language": 1,
        "fallback_if_no_priority_match": "keep_none", **updates,
    })


def _media(tmp_path, streams=None):
    source = tmp_path / "Serie.mkv"
    source.write_bytes(b"source file must not be edited")
    return MediaInfo(str(source), streams if streams is not None else [_stream(4), _stream(9)],
                     [], [VideoStream(0, "h264", 1920, 1080)], duration_s=1200)


class Detector:
    def __init__(self, results=None):
        self.calls = []
        self.results = results or {
            4: LanguageDetectionResult("de", .98, True),
            9: LanguageDetectionResult("ja", .97, True),
        }

    def detect(self, issue):
        self.calls.append(issue)
        result = self.results[issue.stream_index]
        if isinstance(result, Exception):
            raise result
        return result


def _recovery(detector=None, **kwargs):
    logs = []
    recovery = ConversionAudioLanguageRecovery(settings=None, tools=None,
        log=lambda *args: logs.append(args), detector=detector or Detector(), **kwargs)
    return recovery, logs


@pytest.mark.parametrize("fallback", ["keep_all", "keep_first", "keep_none"])
def test_unknown_recovery_triggers_even_when_rule_fallback_keeps_tracks(fallback):
    streams = [_stream(4), _stream(9)]
    assert unknown_audio_streams_without_priority_match(
        streams, _rules(fallback_if_no_priority_match=fallback)) == streams


@pytest.mark.parametrize("language", ["de", "deu", "ger"])
def test_existing_rule_match_skips_whisper(tmp_path, language):
    detector = Detector()
    recovery, _ = _recovery(detector)
    media = _media(tmp_path, [_stream(4, language), _stream(9)])
    assert recovery.prepare(media, rules=_rules()) is media
    assert not detector.calls


def test_known_unwanted_language_is_never_reinterpreted(tmp_path):
    detector = Detector()
    recovery, _ = _recovery(detector)
    media = _media(tmp_path, [_stream(4, "ja")])
    assert recovery.prepare(media, rules=_rules()) is media
    assert not detector.calls


def test_commentary_and_descriptive_tracks_stay_excluded():
    streams = [_stream(1, title="Regie Kommentar"), _stream(2, title="Audiodeskription"), _stream(4)]
    assert unknown_audio_streams_without_priority_match(streams, _rules()) == [streams[2]]


@pytest.mark.parametrize("override", [
    {"audio_mode": "custom", "audio_tracks": [{"index": 4, "mode": "auto"}]},
    {"audio_mode": "custom", "audio_tracks": [{"index": 4, "mode": "drop"}]},
    {"audio_action": "copy"},
])
def test_manual_audio_choice_is_not_changed(tmp_path, override):
    detector = Detector()
    recovery, _ = _recovery(detector)
    media = _media(tmp_path)
    assert recovery.prepare(media, override, rules=_rules()) is media
    assert not detector.calls


def test_confirmed_languages_reselect_and_tag_output_without_editing_source(tmp_path, monkeypatch):
    import dragontools.rules.audio_plan as audio_plan
    from dragontools.worker.converter_audio_args import build_audio_args
    rules = _rules()
    monkeypatch.setattr(audio_plan, "_load_audio_rules", lambda: rules)
    detector = Detector()
    recovery, logs = _recovery(detector)
    original = _media(tmp_path)
    assert compute_audio_track_plan(original.audio_streams, {}, "mkv", rules=rules) == []

    recovered = recovery.prepare(original, rules=rules)
    plan = compute_audio_track_plan(recovered.audio_streams, {}, "mkv", rules=rules)
    assert [decision.stream.index for decision in plan] == [4]
    assert [s.language for s in recovered.audio_streams] == ["de", "ja"]
    assert [s.language for s in original.audio_streams] == ["und", "und"]
    assert (tmp_path / "Serie.mkv").read_bytes() == b"source file must not be edited"
    assert [issue.stream_index for issue in detector.calls] == [4, 9]
    assert all(issue.duration_s == 1200 for issue in detector.calls)
    args = build_audio_args(NS(_logger=MagicMock()), recovered, {}, "mkv")
    assert "0:4" in args and "0:9" not in args
    assert "language=deu" in args
    assert any(arg.startswith("title=Deutsch ") for arg in args)
    assert any("Japanisch bestätigt" in message for message, _level in logs)
    # A replanned pipeline uses cached evidence, not another Whisper run.
    recovery.prepare(original, rules=rules)
    assert len(detector.calls) == 2


def test_uncertain_result_preserves_fallback_and_unknown_tag(tmp_path):
    detector = Detector({4: LanguageDetectionResult("de", .60, False, reason="Unsicher")})
    recovery, logs = _recovery(detector)
    media = _media(tmp_path, [_stream(4)])
    assert recovery.prepare(media, rules=_rules()) is media
    assert media.audio_streams[0].language == "und"
    assert any("nicht sicher" in message for message, _level in logs)


def test_missing_whisper_or_invalid_model_does_not_break_conversion(tmp_path):
    detector = Detector({4: RuntimeError("Whisper-Modell fehlt")})
    recovery, logs = _recovery(detector)
    media = _media(tmp_path, [_stream(4)])
    assert recovery.prepare(media, rules=_rules()) is media
    assert any("Whisper-Modell fehlt" in message for message, _level in logs)


def test_abort_discards_partial_language_changes(tmp_path):
    aborted = [False]
    detector = Detector()
    original_detect = detector.detect
    def detect(issue):
        result = original_detect(issue)
        aborted[0] = True
        return result
    detector.detect = detect
    recovery, _ = _recovery(detector, abort_check=lambda: aborted[0])
    media = _media(tmp_path)
    assert recovery.prepare(media, rules=_rules()) is media
    assert len(detector.calls) == 1
    assert [s.language for s in media.audio_streams] == ["und", "und"]


def test_untrusted_ffmpeg_indices_are_not_probed(tmp_path):
    detector = Detector()
    recovery, _ = _recovery(detector)
    media = replace(_media(tmp_path), ffmpeg_stream_indices_trusted=False)
    assert recovery.prepare(media, rules=_rules()) is media
    assert not detector.calls


@pytest.mark.parametrize("strip_only", [False, True])
def test_workflow_recovers_before_encode_planning_and_output_contract(tmp_path, monkeypatch, strip_only):
    import dragontools.rules.audio_plan as audio_plan
    from dragontools.worker.workflow_engine import WorkflowContext
    from dragontools.worker.workflow_models import WorkflowConfig
    from dragontools.worker.workflow_planning_service import WorkflowPlanningService
    rules = _rules()
    monkeypatch.setattr(audio_plan, "_load_audio_rules", lambda: rules)
    recovery, _ = _recovery()
    media = _media(tmp_path)
    prepared = []
    def prepare_encode_plan(_src, _dst, analysis, *_args, **_kwargs):
        prepared.append(analysis)
        assert analysis.audio_streams[0].language == "de"
        return NS(crop=None, encoder_options={})
    service = WorkflowPlanningService(
        config=WorkflowConfig(codec="h265", crf=23, preset="p5", scale_mode="1080p", encoder_options={}, strip_only=strip_only),
        runtime_state=NS(current_idx=1, total_count=1), logger=MagicMock(),
        pipeline_decision=NS(select_pipeline_context=lambda *_a, **_k: ("standard", "mkv"), last_selection={}),
        encode_plan=NS(prepare_encode_plan=prepare_encode_plan),
        standard_pipeline=NS(logger_start_params=lambda **_k: ("nvenc", 23, "CQ", "p5")),
        output_paths=NS(resolve_output_path=lambda *_a, **_k: (tmp_path, str(tmp_path / "out.mkv"))),
        audio_language_recovery=recovery,
    )
    ctx = WorkflowContext(media.path, analysis=media)
    service.build_plan(ctx, {})
    assert ctx.analysis.audio_streams[0].language == "de"
    assert len(prepared) == (0 if strip_only else 1)
    assert len(ctx.expected_media_contract.audio_tracks) == 1
    assert ctx.expected_media_contract.audio_tracks[0].language == "de"
