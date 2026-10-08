"""Font attachments without a codec must not block verified subtitle muxing."""
import json
import hashlib
from pathlib import Path

import pytest

from dragontools.subtitle import media_verification as verification
from dragontools.subtitle.tool_logging import log_tool_error
from dragontools.worker.tool_runner import ToolRunResult


def _probe(monkeypatch, rows):
    monkeypatch.setattr(verification, "run_tool", lambda *args, **kwargs:
                        ToolRunResult(["ffprobe"], 0, stdout=json.dumps({"streams": rows})))
    return verification.probe_streams("film.mkv", ffprobe="ffprobe")


@pytest.mark.parametrize("kind", ["attachment", "data"])
def test_codec_optional_for_non_playable_streams(monkeypatch, kind):
    rows = _probe(monkeypatch, [
        {"index": 0, "codec_type": "video", "codec_name": "hevc"},
        {"index": 1, "codec_type": kind,
         "tags": {"filename": "font.ttf", "mimetype": "font/ttf"}},
    ])
    assert len(rows) == 2
    assert rows[1]["codec_type"] == kind
    assert rows[1]["tags"]["filename"] == "font.ttf"
    assert "codec_name" not in rows[1]


@pytest.mark.parametrize("kind", ["video", "audio", "subtitle", None])
def test_missing_playable_codec_or_stream_type_still_rejected(monkeypatch, kind):
    with pytest.raises(ValueError, match=r"film\.mkv; Spur 0"):
        _probe(monkeypatch, [{"index": 0, "codec_type": kind}])


def test_attachment_loss_is_still_rejected(monkeypatch):
    from dragontools.worker.media_contract_types import ExpectedMediaContract
    video = {"index": 0, "codec_type": "video", "codec_name": "hevc"}
    font = {"index": 1, "codec_type": "attachment", "tags": {"filename": "font.ttf"}}
    plan = verification.SubtitleInjectionPlan(
        (video, font), ExpectedMediaContract("mkv", "hevc", 1, (), ()), 0)
    _probe(monkeypatch, [video])
    with pytest.raises(ValueError, match="attachment-Spuren wurden verändert"):
        verification.verify_injection("out.mkv", plan, ffprobe="ffprobe")
    _probe(monkeypatch, [video, font])
    assert verification.verify_injection("out.mkv", plan, ffprobe="ffprobe")


def test_media_validation_error_does_not_claim_tool_start_failure():
    messages = []
    log_tool_error(messages.append, "mkvmerge.exe", None, exc=ValueError("unvollständige Videospur"))
    assert "unvollständige Videospur" in messages[0]
    assert "konnte nicht gestartet" not in messages[0]


@pytest.mark.media_integration
@pytest.mark.parametrize("backend", ["mkvmerge", "ffmpeg"])
def test_real_font_ttf_attachment_survives_subtitle_injection(tmp_path, backend):
    from dragontools.tests.test_patch12_real_media import run, video, text_subtitle, probe
    from dragontools.tests.ci_requirements import external_media_environment, _resolve_tool
    from types import SimpleNamespace
    from dragontools.subtitle.injector import inject_with_mkvmerge, inject_with_ffmpeg

    environment = external_media_environment()
    merge = _resolve_tool("DRAGONTOOLS_MKVMERGE", "mkvmerge.exe", "mkvmerge")
    if not environment.ffmpeg or not environment.ffprobe or not merge:
        pytest.skip("FFmpeg/FFprobe/MKVToolNix unavailable")
    tools = SimpleNamespace(ffmpeg=environment.ffmpeg, ffprobe=environment.ffprobe, mkvmerge=merge)
    fonts = [Path(r"C:\Windows\Fonts\arial.ttf"),
             Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    font = next((path for path in fonts if path.is_file()), None)
    if font is None:
        pytest.skip("No system font available")
    plain = video(tmp_path / "plain.mkv", tools, text_subtitle(tmp_path / "old.srt"))
    source = tmp_path / "with-font.mkv"
    run([merge, "-o", str(source), str(plain), "--attachment-mime-type", "font/ttf",
         "--attachment-name", "font.ttf", "--attach-file", str(font)])
    subtitle = text_subtitle(tmp_path / "new.ass", "ass")
    output = tmp_path / "injected.mkv"
    before = probe(source, tools)["streams"]
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    logs = []
    function = inject_with_mkvmerge if backend == "mkvmerge" else inject_with_ffmpeg
    options = {"mkvmerge": merge} if backend == "mkvmerge" else {"ffmpeg": tools.ffmpeg}
    assert function(str(source), str(subtitle), str(output), language="deu", title="Deutsch GPT",
                    ffprobe=tools.ffprobe, logger=logs.append, **options), logs
    after = probe(output, tools)["streams"]
    def attachments(rows):
        return [(row["tags"]["filename"], row["tags"]["mimetype"], row["extradata_hash"])
                for row in rows if row["codec_type"] == "attachment"]
    assert attachments(before) == attachments(after)
    assert len(attachments(after)) == 1
    assert sum(row["codec_type"] == "subtitle" for row in after) == 2
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
