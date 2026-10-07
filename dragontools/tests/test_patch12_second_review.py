"""Safety boundaries missing from the first subtitle review."""

import json
import os
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from dragontools.subtitle import extractor, injector
from dragontools.core.bitmap_subtitle_ocr import (
    BitmapOcrCue,
    BitmapSubtitlePacket,
    finalize_ocr_report,
    normalize_packets,
    parse_tesseract_tsv,
    write_pending_draft,
)


def result(**values):
    return NS(
        **dict(
            dict(
                ok=True,
                returncode=0,
                stdout="",
                stderr="",
                aborted=False,
                timed_out=False,
            ),
            **values,
        )
    )


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "{}",
        '{"streams":null}',
        '{"streams":[{},{}]}',
        '{"streams":[{"index":2},{"index":2}]}',
    ],
)
def test_missing_or_ambiguous_subtitle_inventory_is_not_zero(monkeypatch, payload):
    monkeypatch.setattr(injector, "run_tool", lambda *_a, **_k: result(stdout=payload))
    assert injector._probe_subtitle_count("source", ffprobe="ffprobe") is None


@pytest.mark.parametrize("flag", ["aborted", "timed_out"])
def test_stopped_probe_is_not_success(monkeypatch, flag):
    monkeypatch.setattr(
        injector,
        "run_tool",
        lambda *_a, **_k: result(stdout='{"streams":[]}', **{flag: True}),
    )
    assert injector._probe_subtitle_count("source", ffprobe="ffprobe") is None


def install_race(monkeypatch, target):
    rename, replace = os.rename, os.replace

    def raced(operation):
        def call(src, dst, *args, **kwargs):
            if Path(dst) == target:
                target.write_bytes(b"FOREIGN")
            return operation(src, dst, *args, **kwargs)

        return call

    monkeypatch.setattr(os, "rename", raced(rename))
    monkeypatch.setattr(os, "replace", raced(replace))


def test_injection_commit_cannot_replace_a_last_instant_destination(
    monkeypatch, tmp_path
):
    output, stage = tmp_path / "out.mkv", tmp_path / "stage.mkv"
    stage.write_bytes(b"VERIFIED")
    install_race(monkeypatch, output)
    try:
        assert injector._commit_staging(stage, output, overwrite=False) is False
    except FileExistsError:
        pass
    assert output.read_bytes() == b"FOREIGN"
    assert stage.read_bytes() == b"VERIFIED"


@pytest.mark.parametrize("flag", ["aborted", "timed_out"])
def test_extraction_stopped_with_rc_zero_does_not_publish(monkeypatch, tmp_path, flag):
    target = tmp_path / "out.srt"

    def run(cmd, **kwargs):
        Path(cmd[-1]).write_text("1\n00:00:01,000 --> 00:00:02,000\nHallo\n")
        return result(**{flag: True})

    monkeypatch.setattr(extractor, "run_tool", run)
    assert extractor.extract_with_ffmpeg("video.mkv", 2, str(target)) is False
    assert not target.exists()


@pytest.mark.parametrize('operation',['extract','ffmpeg','mkvmerge'])
def test_subtitle_output_rejects_source_alias_even_with_overwrite(monkeypatch, tmp_path,operation):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"ORIGINAL")
    called = []

    def run(cmd, **kwargs):
        called.append(cmd)
        Path(cmd[cmd.index('-o')+1] if '-o' in cmd else cmd[-1]).write_bytes(b"subtitle")
        return result()

    monkeypatch.setattr(extractor, "run_tool", run)
    monkeypatch.setattr(injector, 'run_tool', run)
    if operation=='extract':
        assert not extractor.extract_with_ffmpeg(str(source), 2, str(source), overwrite=True)
    elif operation=='ffmpeg':
        assert not injector.inject_with_ffmpeg(str(source),'sub.srt',str(source),overwrite=True,existing_subtitle_count=0)
    else:
        assert not injector.inject_with_mkvmerge(str(source),'sub.srt',str(source),overwrite=True)
    assert source.read_bytes() == b"ORIGINAL" and called == []


@pytest.mark.parametrize(
    "corruption", ["extra_video", "missing_audio", "wrong_subtitle", "missing_dv"]
)
def test_injection_requires_actual_media_contract(monkeypatch, tmp_path, corruption):
    source = tmp_path / "source.mkv"
    sub = tmp_path / "source.de.srt"
    output = tmp_path / "out.mkv"
    source.write_bytes(b"ORIGINAL")
    sub.write_text("subtitle")
    video = {
        "index": 0,
        "codec_type": "video",
        "codec_name": "h264",
        "width": 128,
        "height": 72,
    }
    audio = {
        "index": 1,
        "codec_type": "audio",
        "codec_name": "aac",
        "channels": 2,
        "tags": {"language": "eng"},
        "disposition": {"default": 1, "forced": 0},
    }
    subtitle = {
        "index": 2,
        "codec_type": "subtitle",
        "codec_name": "subrip",
        "tags": {"language": "deu", "title": "Deutsch"},
        "disposition": {"forced": 0, "default": 0},
    }
    streams = [video, audio, subtitle]
    if corruption == "extra_video":
        streams.append(dict(video, index=3))
    if corruption == "missing_audio":
        streams.remove(audio)
    if corruption == "wrong_subtitle":
        streams[-1] = dict(subtitle, codec_name="ass")
    if corruption == "missing_dv":
        video["side_data_list"] = [
            {
                "side_data_type": "DOVI configuration record",
                "dv_profile": 8,
                "rpu_present_flag": 1,
                "bl_present_flag": 1,
            }
        ]
        streams[0] = dict(video, side_data_list=[])

    def run(cmd, **kwargs):
        if "-show_entries" in cmd and "-select_streams" in cmd:
            return result(stdout='{"streams":[]}')
        if "-show_streams" in cmd:
            path = Path(cmd[-1])
            rows = (
                [video, audio]
                if path == source
                else [subtitle]
                if path == sub
                else streams
            )
            return result(
                stdout=json.dumps(
                    {
                        "streams": rows,
                        "format": {"format_name": "matroska" if path != sub else "srt"},
                    }
                )
            )
        Path(cmd[-1]).write_bytes(b"NOT_EMPTY")
        return result()

    monkeypatch.setattr(injector, "run_tool", run)
    # Verification owns its tool boundary; do not replace verification itself.
    import importlib

    try:
        verification = importlib.import_module(
            "dragontools.subtitle.media_verification"
        )
    except ModuleNotFoundError:
        verification = None
    if verification:
        monkeypatch.setattr(verification, "run_tool", run)
    assert (
        injector.inject_with_ffmpeg(
            str(source), str(sub), str(output), ffprobe="ffprobe"
        )
        is False
    )
    assert source.read_bytes() == b"ORIGINAL" and not output.exists()


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "150"])
def test_invalid_ocr_confidence_is_not_accepted(value):
    text, confidence = parse_tesseract_tsv(
        f"page_num\tblock_num\tpar_num\tline_num\tconf\ttext\n1\t1\t1\t1\t{value}\tHallo\n"
    )
    assert text == "" and confidence == 0


@pytest.mark.parametrize(
    "start,end", [(float("nan"), 2), (1, float("inf")), (-1, 2), (2, 1)]
)
def test_invalid_packet_geometry_is_rejected(start, end):
    with pytest.raises(ValueError):
        normalize_packets([BitmapSubtitlePacket(start, end)])


@pytest.mark.parametrize("start,end", [(1, float("nan")), (3, 1)])
def test_invalid_review_cue_cannot_leave_an_empty_final(
    monkeypatch, tmp_path, start, end
):
    media = tmp_path / "Film.mkv"
    media.write_bytes(b"original")
    draft = write_pending_draft(
        media_path=media,
        stream_ordinal=1,
        stream_index=2,
        codec="pgs",
        source_language="de",
        forced=False,
        cues=[BitmapOcrCue(1, 1, 2, "Hallo", 0.9)],
        min_confidence=0.75,
    )
    path = Path(draft.report_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cues"][0].update(start_s=start, end_s=end)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        finalize_ocr_report(path, ["Hallo"])
    assert not list(tmp_path.glob("*.srt"))
    assert Path(draft.draft_path).exists() and path.exists()


def test_abort_during_last_ocr_does_not_publish(monkeypatch, tmp_path):
    from dragontools.worker import bitmap_subtitle_ocr_service as module

    worker = NS(abort_requested=False, abort_type=None)
    service = module.BitmapSubtitleOcrService(
        settings=NS(value=lambda _key, default, **_k: default),
        tools=NS(),
        worker=worker,
    )
    issue = NS(
        path=str(tmp_path / "Film.mkv"), stream_index=2, stream_ordinal=1, codec="pgs"
    )
    monkeypatch.setattr(module, "tool_available", lambda *_: True)
    monkeypatch.setattr(
        service, "_probe_packets", lambda *_: [BitmapSubtitlePacket(1, 2)]
    )
    monkeypatch.setattr(service, "_validate_tesseract_languages", lambda *_: None)
    monkeypatch.setattr(service, "_render_subtitle_image", lambda *_: True)

    def ocr(*_):
        worker.abort_requested = True
        worker.abort_type = "sofort"
        return "Hallo", 0.95

    monkeypatch.setattr(service, "_ocr_image", ocr)
    target = tmp_path / "out.srt"
    with pytest.raises(RuntimeError, match="abgebrochen"):
        service.create_srt(issue, target)
    assert not target.exists()


@pytest.mark.parametrize("container", ["mov", "m4v"])
@pytest.mark.parametrize("strip", [False, True])
def test_iso_container_uses_same_subtitle_policy(container, strip):
    from dragontools.worker.converter_subtitle_args import build_subtitle_args
    from dragontools.core.models import SubtitleStream

    stream = SubtitleStream(
        index=2, codec="subrip", language="de", forced=False, title="Deutsch"
    )
    rules = {"mp4_sidecars_enabled": False, "mode": "keep_all"}
    worker = NS(
        log=lambda *_: None, _logger=NS(decision=lambda *_: None), subtitle_rules=rules
    )
    mi = NS(subtitle_streams=[stream], audio_streams=[], duration_s=10)
    if strip:
        from dragontools.worker.converter_strip_subtitles import (
            build_strip_subtitle_args,
        )

        args = build_strip_subtitle_args(worker, mi, {}, container)
    else:
        _burn, args = build_subtitle_args(
            worker, "input", mi, {}, container=container, subtitle_rules=rules
        )
    assert "mov_text" in args and "copy" not in args


@pytest.mark.parametrize("backup", [False, True])
def test_sidecar_last_instant_conflict_preserves_foreign_file_and_recovery(
    monkeypatch, tmp_path, backup
):
    from dragontools.worker import subtitle_sidecar_service as module
    from dragontools.worker import subtitle_movtext_backup as mov
    from dragontools.worker.subtitle_sidecar_targets import SidecarTarget

    stream = NS(
        index=2,
        codec="mov_text" if backup else "subrip",
        language="de",
        forced=False,
        default=False,
        title="",
    )
    target = tmp_path / ("Film.de.mov_text.mp4" if backup else "Film.de.srt")

    def run(cmd, **_kwargs):
        Path(cmd[-1]).write_bytes(b"VERIFIED")
        return result()

    monkeypatch.setattr(module, "run_tool", run)
    monkeypatch.setattr(mov, "run_tool", run)
    try:
        from dragontools.worker import subtitle_sidecar_exporter
    except ImportError:
        subtitle_sidecar_exporter = None
    if subtitle_sidecar_exporter:
        monkeypatch.setattr(
            subtitle_sidecar_exporter, "verify_subtitle_export", lambda *_a, **_k: True
        )
    service = module.SubtitleSidecarService(
        ffmpeg_path="ffmpeg", subtitle_rules={}, log=lambda *_: None
    )
    install_race(monkeypatch, target)
    if backup:
        export = service.export_mov_text_backup_result(
            input_path="source.mp4", output_base=tmp_path / "Film", streams=[stream]
        )
        assert not export.complete and not export.exported_paths
    else:
        planned = SidecarTarget(
            stream, "de", ("de", False), None, str(target), ("-c:s", "srt"), "subrip"
        )
        ok, failure, aborted = service._export_target("source.mkv", planned)
        assert not ok and failure and not aborted
    assert target.read_bytes() == b"FOREIGN"
    assert len(list(tmp_path.glob("*.dragontools-*"))) == 1


def test_movtext_timeout_with_zero_returncode_is_failure(monkeypatch, tmp_path):
    from dragontools.worker import subtitle_movtext_backup as module

    stream = NS(
        index=2, codec="mov_text", language="de", forced=False, default=False, title=""
    )

    def run(cmd, **_kwargs):
        Path(cmd[-1]).write_bytes(b"partial")
        return result(timed_out=True)

    monkeypatch.setattr(module, "run_tool", run)
    export = module.export_mov_text_backup(
        ffmpeg_path="ffmpeg",
        input_path="source.mp4",
        output_base=tmp_path / "Film",
        streams=[stream],
    )
    assert not export.complete and not export.exported_paths
    assert not list(tmp_path.glob("*.mp4"))


def test_ocr_uses_the_current_worker_for_tool_execution(monkeypatch, tmp_path):
    from dragontools.worker import bitmap_subtitle_ocr_service as module

    worker = NS(abort_requested=False, abort_type=None)
    service = module.BitmapSubtitleOcrService(
        settings=NS(value=lambda _key, default, **_k: default),
        tools=NS(),
        worker=worker,
    )

    def run(_cmd, **kwargs):
        assert kwargs.get("worker") is worker
        return result()

    monkeypatch.setattr(module, "run_analysis_tool", run)
    assert service._ocr_image(tmp_path / "cue.png", "tesseract") == ("", 0)


def test_review_rejects_a_changed_source_file(tmp_path):
    media = tmp_path / "Film.mkv"
    media.write_bytes(b"original")
    draft = write_pending_draft(
        media_path=media,
        stream_ordinal=1,
        stream_index=2,
        codec="pgs",
        source_language="de",
        forced=False,
        cues=[BitmapOcrCue(1, 1, 2, "Hallo", 0.9)],
        min_confidence=0.75,
    )
    media.write_bytes(b"changed media content")
    with pytest.raises(ValueError, match="Quelldatei"):
        finalize_ocr_report(draft.report_path, ["Hallo"])
    assert not list(tmp_path.glob("*.srt"))


def test_subtitle_conversion_cannot_overwrite_an_existing_output(tmp_path):
    from dragontools.subtitle.converter import srt_to_txt

    source = tmp_path / "source.srt"
    target = tmp_path / "out.txt"
    source.write_text("1\n00:00:01,000 --> 00:00:02,000\nHallo\n")
    target.write_text("USER")
    with pytest.raises(FileExistsError):
        srt_to_txt(source, target)
    assert target.read_text() == "USER"


@pytest.mark.parametrize("format", ["srt", "ass"])
def test_malformed_cue_cannot_be_silently_discarded(tmp_path, format):
    from dragontools.subtitle.converter import subtitle_to_txt

    source = tmp_path / f"source.{format}"
    target = tmp_path / "out.txt"
    content = (
        "1\n00:00:01,000 --> 00:00:02,000\nHallo\n\n2\nBROKEN --> TIME\nWelt\n"
        if format == "srt"
        else "[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Hallo\nDialogue: broken\n"
    )
    source.write_text(content)
    with pytest.raises(ValueError):
        subtitle_to_txt(source, target)
    assert not target.exists()


def test_invalid_text_encoding_cannot_be_replaced_silently(tmp_path):
    from dragontools.subtitle.converter import srt_to_txt

    source = tmp_path / "source.srt"
    source.write_bytes(b"1\n00:00:01,000 --> 00:00:02,000\nGr\xfc\xdfe\n")
    with pytest.raises(ValueError, match="Kodierung"):
        srt_to_txt(source)


@pytest.mark.parametrize("parent", ["third_party", "Programme"])
def test_bundled_tesseract_is_discovered_without_global_path(
    monkeypatch, tmp_path, parent
):
    from dragontools.core.tool_paths import find_tool

    target = tmp_path / parent / "Tesseract-OCR" / "tesseract.exe"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"tool")
    monkeypatch.setenv("PATH", "")
    assert (
        Path(find_tool("tesseract.exe", "tesseract", base=tmp_path, exe_dir=tmp_path))
        == target
    )


def test_tagger_cannot_report_a_proven_absent_change_as_success(monkeypatch):
    from dragontools.subtitle import tagger

    monkeypatch.setattr(
        tagger,
        "get_tool_paths",
        lambda: NS(mkvpropedit="mkvpropedit", mkvmerge="mkvmerge"),
    )

    def run(cmd, **_kwargs):
        if "-J" in cmd:
            return result(
                stdout='{"tracks":[{"id":0,"type":"subtitles","properties":{"language":"eng","forced_track":false}}]}'
            )
        return result()

    monkeypatch.setattr(tagger, "run_analysis_tool", run)
    assert tagger.set_track_language("film.mkv", 0, "de") is False


def test_logging_failure_after_verified_publish_does_not_turn_success_into_failure(
    monkeypatch, tmp_path
):
    output = tmp_path / "out.mkv"
    def run(cmd, **_kwargs):
        Path(cmd[cmd.index('-o')+1]).write_bytes(b"verified")
        return result(returncode=1)

    def logger(_message):
        raise RuntimeError("logging failed")

    monkeypatch.setattr(injector, "run_tool", run)
    monkeypatch.setattr(injector, "verify_injection", lambda *_a, **_k: True,raising=False)
    monkeypatch.setattr(injector,'build_injection_plan',lambda *_a,**_k:NS(source_streams=(),new_subtitle_index=0),raising=False)
    monkeypatch.setattr(injector,'_identify',lambda _tool,path,_worker:
        [{'id':0,'type':'subtitles'}] if path=='sub.srt' else [],raising=False)
    assert injector.inject_with_mkvmerge('source.mkv','sub.srt',str(output),logger=logger)
    assert output.read_bytes() == b"verified"
