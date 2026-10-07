"""Real tool roundtrips for subtitle codecs, flags and bitmap preservation."""

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from dragontools.tests.ci_requirements import external_media_environment, _resolve_tool
from dragontools.subtitle.injector import inject_with_ffmpeg, inject_with_mkvmerge
from dragontools.subtitle.extractor import extract_with_ffmpeg
from dragontools.core.media_analyzer import analyze_media
from dragontools.core.lang_codes import canonical_lang
from dragontools.core.media_library_fix_queue import MediaLibraryFixIssue
from dragontools.worker.subtitle_movtext_backup import export_mov_text_backup
from dragontools.worker.subtitle_sidecar_service import SubtitleSidecarService
from dragontools.worker.bitmap_subtitle_ocr_service import BitmapSubtitleOcrService

pytestmark = pytest.mark.media_integration


def run(command):
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    assert (
        result.returncode in {0, 1}
        if "mkvmerge" in Path(command[0]).name
        else result.returncode == 0
    ), result.stderr[-3000:]
    return result


@pytest.fixture
def tools():
    env = external_media_environment()
    merge = _resolve_tool("DRAGONTOOLS_MKVMERGE", "mkvmerge.exe", "mkvmerge")
    extract = _resolve_tool("DRAGONTOOLS_MKVEXTRACT", "mkvextract.exe", "mkvextract")
    tess = _resolve_tool("DRAGONTOOLS_TESSERACT", "tesseract.exe", "tesseract")
    if not env.ffmpeg or not env.ffprobe:
        pytest.skip("FFmpeg/FFprobe unavailable")
    return NS(
        ffmpeg=env.ffmpeg,
        ffprobe=env.ffprobe,
        mkvmerge=merge,
        mkvextract=extract,
        tesseract=tess,
    )


def probe(path, tools):
    return json.loads(
        run(
            [
                tools.ffprobe,
                "-v",
                "error",
                "-show_streams",
                "-show_data_hash",
                "sha256",
                "-show_format",
                "-of",
                "json",
                str(path),
            ]
        ).stdout
    )


def text_subtitle(path, codec="srt"):
    content = (
        "1\n00:00:00,500 --> 00:00:02,000\nHallo Welt\n"
        if codec == "srt"
        else "[Script Info]\nScriptType: v4.00+\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.50,0:00:02.00,Default,,0,0,0,,Hallo Welt\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def video(path, tools, sub=None, *, mp4=False):
    args = [
        tools.ffmpeg,
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:size=1280x720:rate=25:duration=3",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=48000:cl=stereo",
    ]
    if sub:
        args += ["-i", str(sub)]
    args += [
        "-t",
        "3",
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
        "-metadata:s:a:0",
        "language=eng",
        "-disposition:a:0",
        "default",
    ]
    if sub:
        args += [
            "-map",
            "2:s:0",
            "-c:s",
            "mov_text" if mp4 else "srt",
            "-metadata:s:s:0",
            "language=eng",
            "-metadata:s:s:0",
            "title=Existing",
            "-metadata:s:s:0",
            "handler_name=Existing",
            "-disposition:s:0",
            "default",
        ]
    run([*args, str(path)])
    return path


@pytest.mark.parametrize(
    "backend,codec,container",
    [
        ("ffmpeg", "srt", "mkv"),
        ("mkvmerge", "srt", "mkv"),
        ("ffmpeg", "ass", "mkv"),
        ("ffmpeg", "srt", "mp4"),
    ],
)
def test_real_injection_preserves_existing_tracks_and_adds_only_one_subtitle(
    tmp_path, tools, backend, codec, container
):
    if backend == "mkvmerge" and not tools.mkvmerge:
        pytest.skip("mkvmerge unavailable")
    old = text_subtitle(tmp_path / "old.srt")
    source = video(
        tmp_path / f"Quelle ä.{container}", tools, old, mp4=container == "mp4"
    )
    new = text_subtitle(tmp_path / f"neu ü.{codec}", codec)
    output = tmp_path / f"Ausgabe ü.{container}"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    logs = []
    kwargs = dict(
        language="de",
        forced=True,
        title="Deutsch Neu",
        logger=logs.append,
        ffprobe=tools.ffprobe,
    )
    if backend == "mkvmerge":
        ok = inject_with_mkvmerge(
            str(source), str(new), str(output), mkvmerge=tools.mkvmerge, **kwargs
        )
    else:
        ok = inject_with_ffmpeg(
            str(source),
            str(new),
            str(output),
            ffmpeg=tools.ffmpeg,
            subtitle_codec="mov_text" if container == "mp4" else None,
            **kwargs,
        )
    assert ok, logs
    rows = probe(output, tools)["streams"]
    assert sum(row["codec_type"] == "video" for row in rows) == 1
    assert sum(row["codec_type"] == "audio" for row in rows) == 1
    subs = [row for row in rows if row["codec_type"] == "subtitle"]
    assert len(subs) == 2 and subs[0]["tags"]["language"] == "eng"
    assert (
        canonical_lang(subs[1]["tags"]["language"]) == canonical_lang("de")
        and subs[1]["disposition"]["forced"] == 1
    )
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("backend", ["ffmpeg", "mkvmerge"])
def test_real_mp4_handler_title_survives_mkv_injection(tmp_path, tools, backend):
    if backend == "mkvmerge" and not tools.mkvmerge:
        pytest.skip("mkvmerge unavailable")
    source = video(tmp_path / "source.mp4", tools, mp4=True)
    before = probe(source, tools)["streams"]
    audio = next(row for row in before if row["codec_type"] == "audio")
    expected = audio["tags"]["handler_name"]
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    subtitle = text_subtitle(tmp_path / "new.srt")
    output = tmp_path / "result.mkv"
    logs = []
    function = inject_with_ffmpeg if backend == "ffmpeg" else inject_with_mkvmerge
    tool = {"ffmpeg": tools.ffmpeg} if backend == "ffmpeg" else {"mkvmerge": tools.mkvmerge}
    assert function(str(source), str(subtitle), str(output), ffprobe=tools.ffprobe,
                    logger=logs.append, **tool), logs
    actual = next(row for row in probe(output, tools)["streams"] if row["codec_type"] == "audio")
    assert actual["tags"]["title"] == expected
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


def test_real_movtext_conversion_and_lossless_backup(tmp_path, tools):
    sub = text_subtitle(tmp_path / "sub.srt")
    source = video(tmp_path / "Quelle ü.mp4", tools, sub, mp4=True)
    rows = probe(source, tools)["streams"]
    index = next(row["index"] for row in rows if row["codec_type"] == "subtitle")
    output = tmp_path / "out.srt"
    logs = []
    assert extract_with_ffmpeg(
        str(source),
        index,
        str(output),
        ffmpeg=tools.ffmpeg,
        codec_args=["-c:s", "srt"],
        logger=logs.append,
    ), logs
    assert "Hallo Welt" in output.read_text(encoding="utf-8")
    media = analyze_media(str(source), tools)
    result = export_mov_text_backup(
        ffmpeg_path=tools.ffmpeg,
        input_path=str(source),
        output_base=tmp_path / "Backup",
        streams=media.subtitle_streams,
        worker=NS(tools=tools),
        log=lambda message, *_: logs.append(message),
    )
    assert result.complete, result.failure_summary()
    backup = probe(result.exported_paths[0], tools)["streams"]
    assert len(backup) == 1 and backup[0]["codec_name"] == "mov_text"


def segment(time, kind, payload=b""):
    stamp = int(time * 90000).to_bytes(4, "big")
    return (
        b"PG"
        + stamp
        + stamp
        + bytes([kind])
        + len(payload).to_bytes(2, "big")
        + payload
    )


def pgs_fixture(path, qapp):
    from PyQt6.QtGui import QImage, QPainter, QFont, QFontDatabase
    from PyQt6.QtCore import Qt

    system_font = Path("C:/Windows/Fonts/arial.ttf")
    if system_font.is_file():
        assert QFontDatabase.addApplicationFont(str(system_font)) >= 0
    image = QImage(600, 100, QImage.Format.Format_Grayscale8)
    image.fill(0)
    painter = QPainter(image)
    painter.setPen(Qt.GlobalColor.white)
    painter.setFont(QFont("Arial", 48))
    painter.drawText(20, 75, "Hallo Welt")
    painter.end()
    rle = bytearray()
    for y in range(image.height()):
        x = 0
        while x < image.width():
            color = 1 if image.pixelColor(x, y).red() > 128 else 0
            end = x + 1
            while end < image.width() and (
                image.pixelColor(end, y).red() > 128
            ) == bool(color):
                end += 1
            length = end - x
            flag = (
                (0x80 if color else 0)
                | (0x40 if length > 63 else 0)
                | ((length >> 8) if length > 63 else length)
            )
            rle += bytes([0, flag])
            if length > 63:
                rle += bytes([length & 255])
            if color:
                rle += bytes([1])
            x = end
        rle += b"\0\0"
    dimensions = (1280).to_bytes(2, "big") + (720).to_bytes(2, "big")
    pcs = (
        dimensions
        + b"\x10\x00\x01\x80\x00\x00\x01"
        + b"\x00\x01\x00\x00"
        + (340).to_bytes(2, "big")
        + (570).to_bytes(2, "big")
    )
    window = (
        b"\x01\x00"
        + (340).to_bytes(2, "big")
        + (570).to_bytes(2, "big")
        + (600).to_bytes(2, "big")
        + (100).to_bytes(2, "big")
    )
    palette = b"\x00\x00" + bytes([0, 16, 128, 128, 0, 1, 235, 128, 128, 255])
    bitmap = (600).to_bytes(2, "big") + (100).to_bytes(2, "big") + rle
    ods = b"\x00\x01\x00\xc0" + len(bitmap).to_bytes(3, "big") + bitmap
    clear = dimensions + b"\x10\x00\x02\x00\x00\x00\x00"
    content = (
        segment(0.5, 0x16, pcs)
        + segment(0.5, 0x17, window)
        + segment(0.5, 0x14, palette)
        + segment(0.5, 0x15, ods)
        + segment(0.5, 0x80)
    )
    path.write_bytes(content + segment(2, 0x16, clear) + segment(2, 0x80))
    return path


def test_real_pgs_original_sidecar_and_full_ocr(tmp_path, tools, qapp):
    if not all([tools.mkvmerge, tools.mkvextract, tools.tesseract]):
        pytest.skip("Bitmap extraction/OCR tools unavailable")
    pgs = pgs_fixture(tmp_path / "Deutsch.sup", qapp)
    base = video(tmp_path / "video.mkv", tools)
    source = tmp_path / "Quelle ü.mkv"
    run([tools.mkvmerge, "-o", str(source), str(base), "--language", "0:deu", str(pgs)])
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    media = analyze_media(str(source), tools)
    settings = NS(value=lambda _key, default, **_kwargs: default)
    worker = NS(tools=tools, settings=settings, abort_requested=False, abort_type=None)
    logs = []
    service = SubtitleSidecarService(
        ffmpeg_path=tools.ffmpeg,
        subtitle_rules={},
        worker=worker,
        log=lambda message, *_: logs.append(message),
    )
    result = service.export_sidecars_result(
        input_path=str(source),
        output_base=tmp_path / "Sidecar",
        media_info=media,
        container="mp4",
    )
    assert result.complete, result.failure_summary()
    assert Path(result.exported_paths[0]).suffix == ".sup"
    track = media.subtitle_streams[0]
    issue = MediaLibraryFixIssue(
        media_id=0,
        path=str(source),
        title="PGS",
        item_type="video",
        issue_type="ocr",
        action="ocr_bitmap_subtitle",
        problem="OCR",
        action_label="OCR",
        stream_index=track.index,
        stream_ordinal=1,
        codec=track.codec,
        language="de",
    )
    ocr = BitmapSubtitleOcrService(
        settings=settings,
        tools=tools,
        worker=worker,
        log=lambda message, *_: logs.append(message),
    )
    target = ocr.create_srt(issue, tmp_path / "OCR.srt")
    text = target.read_text(encoding="utf-8")
    assert "Hallo Welt" in text, (text, logs)
    assert "00:00:00,500 --> 00:00:02,000" in text
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


def vobsub_fixture(path):
    # A four-by-four white DVD subpicture, with separate top/bottom fields.
    pixels = b"\x11\x11\x11\x11"
    commands = b"\x01\x03\x32\x10\x04\xff\xf0\x05\x00\x00\x03\x00\x00\x03\x06\x00\x04\x00\x06\xff"
    second = 8 + 4 + len(commands)
    control = b"\x00\x00" + second.to_bytes(2, "big") + commands
    control += (90).to_bytes(2, "big") + second.to_bytes(2, "big") + b"\x02\xff"
    spu = (
        (4 + len(pixels) + len(control)).to_bytes(2, "big")
        + b"\x00\x08"
        + pixels
        + control
    )
    pts = 45000
    pts_bytes = bytes(
        [
            0x21 | ((pts >> 29) & 0x0E),
            (pts >> 22) & 255,
            ((pts >> 14) & 0xFE) | 1,
            (pts >> 7) & 255,
            ((pts << 1) & 0xFE) | 1,
        ]
    )
    payload = b"\x80\x80\x05" + pts_bytes + b"\x20" + spu
    packet = (
        bytes.fromhex("000001ba44000400040189c3f800")
        + b"\x00\x00\x01\xbd"
        + len(payload).to_bytes(2, "big")
        + payload
    )
    path.with_suffix(".sub").write_bytes(packet)
    path.write_text(
        "# VobSub index file, v7 (do not modify this line!)\nsize: 1280x720\n"
        "palette: " + ",".join(["000000", "ffffff"] + ["000000"] * 14) + "\n"
        "id: de, index: 0\ntimestamp: 00:00:00:500, filepos: 000000000\n",
        encoding="utf-8",
    )
    return path


def subtitle_packet_hashes(path, tools):
    payload = json.loads(
        run(
            [
                tools.ffprobe,
                "-v",
                "error",
                "-select_streams",
                "s",
                "-show_packets",
                "-show_data_hash",
                "sha256",
                "-show_entries",
                "packet=pts_time,data_hash",
                "-of",
                "json",
                str(path),
            ]
        ).stdout
    )
    return [(float(row["pts_time"]), row["data_hash"]) for row in payload["packets"]]


def test_real_vobsub_sidecar_preserves_bitmap_and_palette(tmp_path, tools):
    if not tools.mkvmerge:
        pytest.skip("MKVToolNix unavailable")
    sub = vobsub_fixture(tmp_path / "Deutsch.idx")
    base = video(tmp_path / "video.mkv", tools)
    source = tmp_path / "Quelle ü.mkv"
    run([tools.mkvmerge, "-o", str(source), str(base), str(sub)])
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    media = analyze_media(str(source), tools)
    worker = NS(tools=tools)
    service = SubtitleSidecarService(
        ffmpeg_path=tools.ffmpeg, subtitle_rules={}, worker=worker, log=lambda *_: None
    )
    result = service.export_sidecars_result(
        input_path=str(source),
        output_base=tmp_path / "Sidecar",
        media_info=media,
        container="mp4",
    )
    assert result.complete, result.failure_summary()
    output = Path(result.exported_paths[0])
    assert output.suffix == ".mks"
    assert subtitle_packet_hashes(output, tools) == subtitle_packet_hashes(
        source, tools
    )
    original = next(
        row
        for row in probe(source, tools)["streams"]
        if row["codec_type"] == "subtitle"
    )
    exported = probe(output, tools)["streams"][0]
    assert (
        exported["codec_name"] == "dvd_subtitle"
        and exported["extradata_size"] == original["extradata_size"]
    )
    assert exported["extradata_hash"] == original["extradata_hash"]
    # Decode the actual preserved bitmap, rather than trusting packet hashes alone.
    rendered = tmp_path / "dvd.png"
    run(
        [
            tools.ffmpeg,
            "-y",
            "-v",
            "error",
            "-i",
            str(base),
            "-i",
            str(output),
            "-ss",
            "0.7",
            "-filter_complex",
            "[0:v:0][1:s:0]overlay[out]",
            "-map",
            "[out]",
            "-frames:v",
            "1",
            str(rendered),
        ]
    )
    assert (
        rendered.stat().st_size > 100
        and hashlib.sha256(source.read_bytes()).hexdigest() == digest
    )
    from PyQt6.QtGui import QImage
    assert QImage(str(rendered)).pixelColor(1,1).red() > 128


def test_real_tagger_verifies_language_and_forced_flag(tmp_path, tools, monkeypatch):
    from dragontools.subtitle import tagger

    if not tools.mkvmerge:
        pytest.skip("MKVToolNix unavailable")
    executable = Path(tools.mkvmerge).with_name(
        "mkvpropedit.exe" if Path(tools.mkvmerge).suffix == ".exe" else "mkvpropedit"
    )
    if not executable.is_file():
        pytest.skip("mkvpropedit unavailable")
    source = video(tmp_path / "source.mkv", tools, text_subtitle(tmp_path / "sub.srt"))
    inventory = json.loads(run([tools.mkvmerge, "-J", str(source)]).stdout)["tracks"]
    ordinal = next(
        index for index, row in enumerate(inventory) if row["type"] == "subtitles"
    )
    monkeypatch.setattr(
        tagger,
        "get_tool_paths",
        lambda: NS(mkvmerge=tools.mkvmerge, mkvpropedit=str(executable)),
    )
    assert tagger.set_track_language(str(source), ordinal, "de")
    assert tagger.set_forced_flag(str(source), ordinal, True)
    subtitle = next(
        row
        for row in probe(source, tools)["streams"]
        if row["codec_type"] == "subtitle"
    )
    assert (
        canonical_lang(subtitle["tags"]["language"]) == canonical_lang("de")
        and subtitle["disposition"]["forced"] == 1
    )


def test_real_forced_german_burn_and_regular_german_srt_copy(tmp_path, tools):
    from dragontools.worker.converter_stream_args import ConverterStreamArgsHelper
    from dragontools.worker.converter_subtitle_args import build_subtitle_args
    import numpy as np

    forced = text_subtitle(tmp_path / "forced.srt")
    regular = text_subtitle(tmp_path / "regular.srt")
    base = video(tmp_path / "base.mkv", tools)
    source = tmp_path / "source.mkv"
    run(
        [
            tools.ffmpeg,
            "-y",
            "-v",
            "error",
            "-i",
            str(base),
            "-i",
            str(forced),
            "-i",
            str(regular),
            "-map",
            "0",
            "-map",
            "1:s",
            "-map",
            "2:s",
            "-c",
            "copy",
            "-metadata:s:s:0",
            "language=deu",
            "-metadata:s:s:1",
            "language=deu",
            "-disposition:s:0",
            "forced",
            "-disposition:s:1",
            "default",
            str(source),
        ]
    )
    media = analyze_media(str(source), tools)
    first, second = media.subtitle_streams
    override = {
        "subtitle_mode": "custom",
        "subtitle_tracks": [
            {"index": first.index, "burn_in": True, "keep": False},
            {"index": second.index, "burn_in": False, "keep": True},
        ],
    }
    worker = NS(
        tools=tools,
        log=lambda *_: None,
        _logger=NS(decision=lambda *_: None),
        _burn_sub_tmp=None,
    )
    output = tmp_path / "out.mkv"
    burn, subs = build_subtitle_args(
        worker, str(source), media, override, container="mkv", subtitle_rules={}
    )
    assert burn.index == first.index
    helper = ConverterStreamArgsHelper(worker)
    try:
        visual = helper.text_burn_vf_args(str(source), str(output), burn, [], [])
        run(
            [
                tools.ffmpeg,
                "-y",
                "-v",
                "error",
                "-i",
                str(source),
                *visual,
                "-map",
                "0:a",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-c:a",
                "copy",
                *subs,
                str(output),
            ]
        )
        rows = probe(output, tools)["streams"]
        copied = [row for row in rows if row["codec_type"] == "subtitle"]
        assert (
            len(copied) == 1
            and copied[0]["codec_name"] == "subrip"
            and not copied[0]["disposition"]["forced"]
        )
        assert canonical_lang(copied[0]["tags"]["language"]) == canonical_lang("de")
        # Decode the picture without using its optional soft subtitle track.
        result = subprocess.run(
            [
                tools.ffmpeg,
                "-v",
                "error",
                "-ss",
                "1",
                "-i",
                str(output),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-pix_fmt",
                "gray",
                "-f",
                "rawvideo",
                "pipe:1",
            ],
            capture_output=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert np.frombuffer(result.stdout, dtype=np.uint8).max() > 128
    finally:
        if worker._burn_sub_tmp:
            Path(worker._burn_sub_tmp).unlink(missing_ok=True)


def test_actual_ocr_child_is_owned_and_stops_on_immediate_abort(tmp_path):
    import sys, threading, time

    script = tmp_path / "child.py"
    script.write_text(
        'import time\nfrom pathlib import Path\nPath(__file__).with_suffix(".ready").write_text("ready")\ntime.sleep(4)\nprint("page_num\\tblock_num\\tpar_num\\tline_num\\tconf\\ttext")\n'
    )
    worker = NS(
        abort_requested=False,
        abort_type=None,
        current_process=None,
        _process_lock=threading.RLock(),
    )
    service = BitmapSubtitleOcrService(
        settings=NS(value=lambda _key, default, **_k: default),
        tools=NS(),
        worker=worker,
    )
    observed = []

    def abort():
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if (
                script.with_suffix(".ready").exists()
                and worker.current_process is not None
            ):
                break
            time.sleep(0.01)
        observed.append(worker.current_process)
        worker.abort_requested = True
        worker.abort_type = "sofort"

    timer = threading.Timer(0.01, abort)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="abgebrochen"):
            service._ocr_image(script, sys.executable)
    finally:
        timer.cancel()
    assert time.monotonic() - started < 3
    assert observed and observed[0] is not None and observed[0].poll() is not None
    assert worker.current_process is None
