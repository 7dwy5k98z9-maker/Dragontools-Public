from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def _verify_result(*, duration_ok: bool, duration_s: float = 50.0):
    from dragontools.worker.workflow_engine import WorkflowVerifyResult

    return WorkflowVerifyResult(
        exists=True,
        size_ok=True,
        container_ok=True,
        probe_ok=True,
        video_ok=True,
        audio_ok=True,
        duration_ok=duration_ok,
        format_name="matroska,webm",
        duration_s=duration_s,
        video_stream_count=1,
        audio_stream_count=1,
        messages=[] if duration_ok else ["Ausgabedauer ist nicht plausibel."],
    )


class _Verifier:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def verify(self, output_path, container, *, expected_duration_ms=None, source_has_audio=False):
        self.calls.append((output_path, container, expected_duration_ms, source_has_audio))
        return self.result


def test_duration_repair_remuxes_mkv_and_accepts_fixed_duration(tmp_path, monkeypatch):
    import dragontools.worker.duration_repair_service as module
    from dragontools.worker.duration_repair_service import DurationRepairService

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 2048)
    mkvmerge = tmp_path / "mkvmerge.exe"
    mkvmerge.write_text("fake", encoding="utf-8")
    verifier = _Verifier(_verify_result(duration_ok=True, duration_s=100.0))
    logs = []

    def fake_run(cmd, **kwargs):
        tmp = cmd[cmd.index("-o") + 1]
        with open(tmp, "wb") as handle:
            handle.write(b"remuxed" * 400)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    service = DurationRepairService(
        mkvmerge_path=str(mkvmerge),
        output_verifier=verifier,
        log=lambda msg, level="info": logs.append((level, msg)),
        run_tool_fn=_tool_runner_from_subprocess(fake_run),
    )
    outcome = service.repair(
        output_path=str(out),
        base_dir=tmp_path,
        container="mkv",
        expected_duration_ms=100_000,
        source_has_audio=True,
        initial_result=_verify_result(duration_ok=False, duration_s=50.0),
    )

    assert outcome.repaired is True
    assert outcome.archived_path is None
    assert verifier.calls == [(str(out), "mkv", 100_000, True)]
    assert out.read_bytes().startswith(b"remuxed")
    assert any("korrigiert" in msg for _, msg in logs)


def test_duration_repair_archiviert_wenn_remux_dauer_falsch_bleibt(tmp_path, monkeypatch):
    import dragontools.worker.duration_repair_service as module
    from dragontools.worker.duration_repair_service import DurationRepairService

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 2048)
    archive = tmp_path / "Archiv"
    archive.mkdir()
    (archive / "film.mkv").write_bytes(b"existing")
    mkvmerge = tmp_path / "mkvmerge.exe"
    mkvmerge.write_text("fake", encoding="utf-8")
    verifier = _Verifier(_verify_result(duration_ok=False, duration_s=51.0))

    def fake_run(cmd, **kwargs):
        tmp = cmd[cmd.index("-o") + 1]
        with open(tmp, "wb") as handle:
            handle.write(b"still-bad" * 400)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    service = DurationRepairService(
        mkvmerge_path=str(mkvmerge),
        output_verifier=verifier,
        log=lambda *_: None,
        run_tool_fn=_tool_runner_from_subprocess(fake_run),
    )
    outcome = service.repair(
        output_path=str(out),
        base_dir=tmp_path,
        container="mkv",
        expected_duration_ms=100_000,
        source_has_audio=True,
        initial_result=_verify_result(duration_ok=False, duration_s=50.0),
    )

    assert outcome.repaired is False
    assert outcome.keep_failed_output is True
    assert not out.exists()
    assert outcome.archived_path == str(archive / "film_1.mkv")
    assert (archive / "film_1.mkv").exists()
    assert outcome.remux_duration_s == 51.0


def test_duration_repair_greift_nur_bei_passendem_mkv_oder_mp4_laufzeitfehler(tmp_path):
    from dragontools.worker.duration_repair_service import DurationRepairService

    service = DurationRepairService(
        mkvmerge_path="mkvmerge",
        output_verifier=_Verifier(_verify_result(duration_ok=True)),
        log=lambda *_: None,
    )
    result = _verify_result(duration_ok=False)
    assert service.can_repair(output_path=str(tmp_path / "film.mkv"), container="mkv", verify_result=result)
    assert service.can_repair(output_path=str(tmp_path / "film.mp4"), container="mp4", verify_result=result)
    assert not service.can_repair(output_path=str(tmp_path / "film.mkv"), container="mp4", verify_result=result)
    assert not service.can_repair(output_path=str(tmp_path / "film.mp4"), container="mkv", verify_result=result)
    result.audio_ok = False
    assert not service.can_repair(output_path=str(tmp_path / "film.mkv"), container="mkv", verify_result=result)



def test_duration_repair_remuxes_mp4_with_mp4box(tmp_path, monkeypatch):
    import dragontools.worker.duration_repair_service as module
    from dragontools.worker.duration_repair_service import DurationRepairService

    out = tmp_path / "film.mp4"
    out.write_bytes(b"x" * 2048)
    mp4box = tmp_path / "MP4Box.exe"
    mp4box.write_text("fake", encoding="utf-8")
    verifier = _Verifier(_verify_result(duration_ok=True, duration_s=100.0))
    commands = []

    def fake_run(cmd, **kwargs):
        commands.append(list(cmd))
        target = cmd[cmd.index("-new") + 1]
        with open(target, "wb") as handle:
            handle.write(b"mp4box-remuxed" * 300)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    service = DurationRepairService(
        mkvmerge_path="",
        mp4box_path=str(mp4box),
        output_verifier=verifier,
        log=lambda *_: None,
        timestamp_repair_enabled=False,
        run_tool_fn=_tool_runner_from_subprocess(fake_run),
    )
    outcome = service.repair(
        output_path=str(out),
        base_dir=tmp_path,
        container="mp4",
        expected_duration_ms=100_000,
        source_has_audio=True,
        initial_result=_verify_result(duration_ok=False, duration_s=50.0),
    )

    assert outcome.repaired is True
    assert commands
    assert commands[0][0] == str(mp4box)
    assert "-new" in commands[0] and "-add" in commands[0]
    assert str(out) in commands[0]
    assert out.read_bytes().startswith(b"mp4box-remuxed")


def test_mp4_timestamp_repair_command_uses_mp4box_not_mkvtoolnix_or_ffmpeg():
    from fractions import Fraction
    from dragontools.worker.duration_repair_service import DurationRepairService

    service = DurationRepairService(
        mkvmerge_path="mkvmerge",
        mp4box_path="MP4Box",
        ffmpeg_path="ffmpeg",
        output_verifier=_Verifier(_verify_result(duration_ok=True)),
        log=lambda *_: None,
    )
    cmd = service._build_timestamp_repair_command(
        Path("film.mp4"),
        Path("film.fixed.mp4"),
        Fraction(24000, 1001),
        container="mp4",
    )

    assert cmd[0] == "MP4Box"
    assert "mkvmerge" not in cmd
    assert "ffmpeg" not in cmd
    assert any(part.endswith(":fps=24000/1001") for part in cmd)

def test_duration_repair_kann_deaktiviert_werden(tmp_path):
    from dragontools.worker.duration_repair_service import DurationRepairService

    service = DurationRepairService(
        mkvmerge_path="mkvmerge",
        output_verifier=_Verifier(_verify_result(duration_ok=True)),
        log=lambda *_: None,
        normal_remux_enabled=False,
        timestamp_repair_enabled=False,
    )
    result = _verify_result(duration_ok=False)

    assert not service.can_repair(
        output_path=str(tmp_path / "film.mkv"),
        container="mkv",
        verify_result=result,
    )


def test_workflow_verify_akzeptiert_erfolgreiche_laufzeitreparatur(tmp_path):
    from dragontools.worker.duration_repair_service import DurationRepairOutcome
    from dragontools.worker.workflow_verification_service import WorkflowVerificationService

    bad = _verify_result(duration_ok=False, duration_s=50.0)
    fixed = _verify_result(duration_ok=True, duration_s=100.0)

    class Repairer:
        def can_repair(self, **kwargs):
            return True

        def repair(self, **kwargs):
            return DurationRepairOutcome(
                attempted=True,
                repaired=True,
                verify_result=fixed,
                remux_duration_s=100.0,
                message="ok",
            )

    class Logger:
        def __init__(self):
            self.lines = []

        def info(self, msg):
            self.lines.append(("info", msg))

        def error(self, msg):
            self.lines.append(("error", msg))

    logger = Logger()
    svc = WorkflowVerificationService(
        output_verifier=_Verifier(bad),
        duration_repair_service=Repairer(),
        logger=logger,
    )
    ctx = SimpleNamespace(
        output_path=str(tmp_path / "film.mkv"),
        base_dir=tmp_path,
        container="mkv",
        duration_ms=100_000,
        analysis=SimpleNamespace(audio_streams=[object()]),
    )

    svc.verify(ctx)

    assert ctx.verify_result is fixed
    assert ctx.duration_repair_attempted is True
    assert ctx.duration_after_ffmpeg_s == 50.0
    assert ctx.duration_after_remux_s == 100.0
    assert any("Output-Validierung OK" in msg for _, msg in logger.lines)


def _timing_probe_json(
    *,
    container_duration: float,
    video_duration: float,
    frame_rate: str = "24000/1001",
    frames: int = 34563,
    audio_duration: float = 1441.47,
    subtitle_duration: float | None = 1437.0,
    audio_count: int = 1,
    subtitle_count: int = 1,
) -> str:
    import json

    streams = [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "hevc",
            "duration": str(video_duration),
            "nb_read_frames": str(frames),
            "avg_frame_rate": frame_rate,
            "r_frame_rate": frame_rate,
            "has_b_frames": "4",
            "start_time": "0.000000",
        }
    ]
    for idx in range(audio_count):
        streams.append(
            {
                "index": idx + 1,
                "codec_type": "audio",
                "codec_name": "eac3",
                "duration": str(audio_duration),
                "start_time": "0.000000",
            }
        )
    for idx in range(subtitle_count):
        duration = subtitle_duration if subtitle_duration is not None else audio_duration
        streams.append(
            {
                "index": idx + 10,
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "tags": {"DURATION": f"00:23:{duration - 1380:.3f}"},
            }
        )
    return json.dumps(
        {
            "format": {"format_name": "matroska,webm", "duration": str(container_duration)},
            "streams": streams,
            "chapters": [{"start_time": "0.000000", "end_time": str(audio_duration)}],
        }
    )


class _PathAwareVerifier:
    def __init__(self, fixed_paths: set[str], *, good_duration: float = 1441.56):
        self.fixed_paths = fixed_paths
        self.good_duration = good_duration
        self.calls = []

    def verify(self, output_path, container, *, expected_duration_ms=None, source_has_audio=False):
        from pathlib import Path

        self.calls.append((output_path, container, expected_duration_ms, source_has_audio))
        if str(Path(output_path)) in self.fixed_paths:
            return _verify_result(duration_ok=True, duration_s=self.good_duration)
        return _verify_result(duration_ok=False, duration_s=4_296_408.0)


def _fake_tool(path):
    path.write_text("fake", encoding="utf-8")
    return str(path)


def _tool_runner_from_subprocess(fake_run):
    from dragontools.worker.tool_runner import ToolRunResult

    def _runner(cmd, **kwargs):
        run = fake_run(cmd, **kwargs)
        return ToolRunResult(
            command=[str(part) for part in cmd],
            returncode=int(getattr(run, "returncode", 0)),
            stdout=str(getattr(run, "stdout", "") or ""),
            stderr=str(getattr(run, "stderr", "") or ""),
        )

    return _runner


def test_detect_timestamp_problem_repariert_korrektes_23976_video_nicht():
    from fractions import Fraction

    from dragontools.worker.duration_repair_service import MediaTimingInfo, detect_timestamp_problem

    info = MediaTimingInfo(
        path="film.mkv",
        container_duration_s=1441.56,
        video_duration_s=1441.56,
        audio_duration_s=1441.47,
        video_frame_count=34563,
        frame_rate=Fraction(24000, 1001),
        frame_rate_mode="CFR",
    )

    problem = detect_timestamp_problem(info, expected_duration_s=1441.56)

    assert problem.should_repair is False


def test_detect_timestamp_problem_repariert_korrektes_25fps_video_nicht():
    from fractions import Fraction

    from dragontools.worker.duration_repair_service import MediaTimingInfo, detect_timestamp_problem

    info = MediaTimingInfo(
        path="film.mkv",
        container_duration_s=1440.0,
        video_duration_s=1440.0,
        audio_duration_s=1438.5,
        video_frame_count=36_000,
        frame_rate=Fraction(25, 1),
        frame_rate_mode="CFR",
    )

    problem = detect_timestamp_problem(info, expected_duration_s=1440.0)

    assert problem.should_repair is False


def test_timestamp_repair_nutzt_setts_nach_erfolglosem_remux_23976(tmp_path, monkeypatch):
    import dragontools.worker.duration_repair_service as module
    from dragontools.worker.duration_repair_service import DurationRepairService

    out = tmp_path / "film.mkv"
    out.write_bytes(b"original" * 500)
    mkvmerge = _fake_tool(tmp_path / "mkvmerge.exe")
    ffmpeg = _fake_tool(tmp_path / "ffmpeg.exe")
    ffprobe = _fake_tool(tmp_path / "ffprobe.exe")
    fixed_paths: set[str] = set()
    commands = []

    def fake_run(cmd, **kwargs):
        commands.append(list(cmd))
        exe = Path(cmd[0]).name.lower()
        if exe == "mkvmerge.exe":
            tmp = Path(cmd[cmd.index("-o") + 1])
            tmp.write_bytes(b"remuxed" * 500)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if exe == "ffprobe.exe":
            target = str(Path(cmd[-1]))
            if target in fixed_paths:
                stdout = _timing_probe_json(
                    container_duration=1441.56,
                    video_duration=1441.56,
                    audio_count=2,
                    subtitle_count=2,
                )
            else:
                stdout = _timing_probe_json(
                    container_duration=4_296_408.0,
                    video_duration=4_296_408.0,
                    audio_count=2,
                    subtitle_count=2,
                )
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        if exe == "ffmpeg.exe" and "-bsfs" in cmd:
            return SimpleNamespace(returncode=0, stdout="setts\n", stderr="")
        if exe == "ffmpeg.exe":
            target = Path(cmd[-1])
            target.write_bytes(b"fixed" * 500)
            fixed_paths.add(str(target))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    service = DurationRepairService(
        mkvmerge_path=mkvmerge,
        ffmpeg_path=ffmpeg,
        ffprobe_path=ffprobe,
        output_verifier=_PathAwareVerifier(fixed_paths),
        log=lambda *_: None,
        run_tool_fn=_tool_runner_from_subprocess(fake_run),
    )

    outcome = service.repair(
        output_path=str(out),
        base_dir=tmp_path,
        container="mkv",
        expected_duration_ms=1_441_560,
        source_has_audio=True,
        initial_result=_verify_result(duration_ok=False, duration_s=4_296_408.0),
    )

    setts_commands = [cmd for cmd in commands if Path(cmd[0]).name.lower() == "ffmpeg.exe" and "-bsf:v:0" in cmd]
    assert outcome.repaired is True
    assert outcome.timestamp_fixed is True
    assert outcome.timestamp_fix_attempted is True
    assert out.read_bytes().startswith(b"fixed")
    assert setts_commands
    assert "setts=pts=N*1001/24000/TB:dts=N*1001/24000/TB:duration=1001/24000/TB" in setts_commands[0]
    assert "-c" in setts_commands[0] and "copy" in setts_commands[0]
    assert "-map" in setts_commands[0] and "0" in setts_commands[0]


def test_setts_filter_nutzt_25fps_dynamisch():
    from fractions import Fraction

    from dragontools.worker.duration_repair_service import _setts_filter_for_fps

    assert _setts_filter_for_fps(Fraction(25, 1)) == (
        "setts=pts=N*1/25/TB:dts=N*1/25/TB:duration=1/25/TB"
    )


def test_vfr_datei_startet_keine_blinde_cfr_timestamp_reparatur(tmp_path, monkeypatch):
    import json

    import dragontools.worker.duration_repair_service as module
    from dragontools.worker.duration_repair_service import DurationRepairService

    out = tmp_path / "film.mkv"
    out.write_bytes(b"original" * 500)
    mkvmerge = _fake_tool(tmp_path / "mkvmerge.exe")
    ffmpeg = _fake_tool(tmp_path / "ffmpeg.exe")
    ffprobe = _fake_tool(tmp_path / "ffprobe.exe")
    mediainfo = _fake_tool(tmp_path / "MediaInfo.exe")
    fixed_paths: set[str] = set()
    commands = []

    def fake_run(cmd, **kwargs):
        commands.append(list(cmd))
        exe = Path(cmd[0]).name.lower()
        if exe == "mkvmerge.exe":
            tmp = Path(cmd[cmd.index("-o") + 1])
            tmp.write_bytes(b"remuxed" * 500)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if exe == "ffprobe.exe":
            return SimpleNamespace(
                returncode=0,
                stdout=_timing_probe_json(
                    container_duration=4_296_408.0,
                    video_duration=4_296_408.0,
                    frames=35_000,
                ),
                stderr="",
            )
        if exe == "mediainfo.exe":
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "media": {
                            "track": [
                                {"@type": "General", "Duration": "4296408000"},
                                {
                                    "@type": "Video",
                                    "FrameRate_Mode": "Variable",
                                    "FrameCount": "35000",
                                    "FrameRate": "23.976",
                                },
                            ]
                        }
                    }
                ),
                stderr="",
            )
        if exe == "ffmpeg.exe" and "-bsfs" in cmd:
            return SimpleNamespace(returncode=0, stdout="setts\n", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    service = DurationRepairService(
        mkvmerge_path=mkvmerge,
        ffmpeg_path=ffmpeg,
        ffprobe_path=ffprobe,
        mediainfo_path=mediainfo,
        output_verifier=_PathAwareVerifier(fixed_paths),
        log=lambda *_: None,
        run_tool_fn=_tool_runner_from_subprocess(fake_run),
    )

    outcome = service.repair(
        output_path=str(out),
        base_dir=tmp_path,
        container="mkv",
        expected_duration_ms=1_441_560,
        source_has_audio=True,
        initial_result=_verify_result(duration_ok=False, duration_s=4_296_408.0),
    )

    assert outcome.repaired is False
    assert outcome.timestamp_fix_attempted is False
    assert outcome.archived_path is not None
    assert not any(Path(cmd[0]).name.lower() == "ffmpeg.exe" and "-bsf:v:0" in cmd for cmd in commands)


def test_fehlgeschlagene_timestamp_reparatur_archiviert_ausgabe_und_entfernt_tmp(tmp_path, monkeypatch):
    import dragontools.worker.duration_repair_service as module
    from dragontools.worker.duration_repair_service import DurationRepairService

    out = tmp_path / "film.mkv"
    out.write_bytes(b"original" * 500)
    mkvmerge = _fake_tool(tmp_path / "mkvmerge.exe")
    ffmpeg = _fake_tool(tmp_path / "ffmpeg.exe")
    ffprobe = _fake_tool(tmp_path / "ffprobe.exe")
    fixed_paths: set[str] = set()

    def fake_run(cmd, **kwargs):
        exe = Path(cmd[0]).name.lower()
        if exe == "mkvmerge.exe":
            tmp = Path(cmd[cmd.index("-o") + 1])
            tmp.write_bytes(b"remuxed" * 500)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if exe == "ffprobe.exe":
            return SimpleNamespace(
                returncode=0,
                stdout=_timing_probe_json(
                    container_duration=4_296_408.0,
                    video_duration=4_296_408.0,
                    subtitle_count=0,
                ),
                stderr="",
            )
        if exe == "ffmpeg.exe" and "-bsfs" in cmd:
            return SimpleNamespace(returncode=0, stdout="setts\n", stderr="")
        if exe == "ffmpeg.exe":
            return SimpleNamespace(returncode=1, stdout="", stderr="setts failed")
        raise AssertionError(cmd)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    service = DurationRepairService(
        mkvmerge_path=mkvmerge,
        ffmpeg_path=ffmpeg,
        ffprobe_path=ffprobe,
        output_verifier=_PathAwareVerifier(fixed_paths),
        log=lambda *_: None,
        run_tool_fn=_tool_runner_from_subprocess(fake_run),
    )

    outcome = service.repair(
        output_path=str(out),
        base_dir=tmp_path,
        container="mkv",
        expected_duration_ms=1_441_560,
        source_has_audio=True,
        initial_result=_verify_result(duration_ok=False, duration_s=4_296_408.0),
    )

    assert outcome.repaired is False
    assert outcome.timestamp_fix_attempted is True
    assert outcome.archived_path is not None
    archived = Path(outcome.archived_path)
    assert archived.exists()
    assert archived.read_bytes().startswith(b"remuxed")
    assert not list(tmp_path.glob("*.timestamp_fix_*.mkv"))




def test_abweichende_ffprobe_framerates_werden_nicht_blind_als_cfr_behandelt():
    from fractions import Fraction

    from dragontools.worker.duration_repair_service import DurationRepairService, MediaTimingInfo

    service = DurationRepairService(
        mkvmerge_path="",
        output_verifier=SimpleNamespace(_ffprobe_path=""),
        log=lambda *_: None,
    )
    info = MediaTimingInfo(
        path="film.mkv",
        container_duration_s=4_296_408.0,
        video_duration_s=4_296_408.0,
        audio_duration_s=1441.47,
        video_frame_count=34563,
        frame_rate=Fraction(24000, 1001),
        avg_frame_rate=Fraction(24000, 1001),
        real_frame_rate=Fraction(25, 1),
    )

    assert service._infer_frame_rate_mode(info) == "unknown"



def test_media_info_vfr_pts_ausreisser_wird_ueber_quell_dauer_sicher_repariert(tmp_path, monkeypatch):
    import json

    import dragontools.worker.duration_repair_service as module
    from dragontools.worker.duration_repair_service import DurationRepairService

    out = tmp_path / "film.mkv"
    out.write_bytes(b"original" * 500)
    mkvmerge = _fake_tool(tmp_path / "mkvmerge.exe")
    ffmpeg = _fake_tool(tmp_path / "ffmpeg.exe")
    ffprobe = _fake_tool(tmp_path / "ffprobe.exe")
    mediainfo = _fake_tool(tmp_path / "MediaInfo.exe")
    fixed_paths: set[str] = set()
    commands = []

    def damaged_mediainfo_json():
        return json.dumps(
            {
                "media": {
                    "track": [
                        {"@type": "General", "Duration": "4296408"},
                        {
                            "@type": "Video",
                            "Format": "HEVC",
                            "Duration": "4296408",
                            "FrameRate_Mode": "Variable",
                            "FrameRate": "0.008",
                            "FrameCount": "34563",
                        },
                        {"@type": "Audio", "Duration": "1441470"},
                        {"@type": "Text", "Duration": "1436900"},
                        {"@type": "Text", "Duration": "1436900"},
                    ]
                }
            }
        )

    def fixed_mediainfo_json():
        return json.dumps(
            {
                "media": {
                    "track": [
                        {"@type": "General", "Duration": "1441565"},
                        {
                            "@type": "Video",
                            "Format": "HEVC",
                            "Duration": "1441565",
                            "FrameRate_Mode": "Constant",
                            "FrameRate": "23.976",
                            "FrameCount": "34563",
                        },
                        {"@type": "Audio", "Duration": "1441470"},
                        {"@type": "Text", "Duration": "1436900"},
                        {"@type": "Text", "Duration": "1436900"},
                    ]
                }
            }
        )

    def fake_run(cmd, **kwargs):
        commands.append(list(cmd))
        exe = Path(cmd[0]).name.lower()
        if exe == "mkvmerge.exe":
            tmp = Path(cmd[cmd.index("-o") + 1])
            tmp.write_bytes(b"remuxed" * 500)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if exe == "ffprobe.exe":
            target = str(Path(cmd[-1]))
            if target in fixed_paths:
                return SimpleNamespace(
                    returncode=0,
                    stdout=_timing_probe_json(
                        container_duration=1441.565,
                        video_duration=1441.565,
                        frames=34563,
                        audio_duration=1441.47,
                        subtitle_duration=1436.9,
                        audio_count=1,
                        subtitle_count=2,
                    ),
                    stderr="",
                )
            return SimpleNamespace(returncode=1, stdout="", stderr="broken pts")
        if exe == "mediainfo.exe":
            target = str(Path(cmd[-1]))
            stdout = fixed_mediainfo_json() if target in fixed_paths else damaged_mediainfo_json()
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        if exe == "ffmpeg.exe" and "-bsfs" in cmd:
            return SimpleNamespace(returncode=0, stdout="setts\n", stderr="")
        if exe == "ffmpeg.exe":
            target = Path(cmd[-1])
            target.write_bytes(b"fixed" * 500)
            fixed_paths.add(str(target))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    service = DurationRepairService(
        mkvmerge_path=mkvmerge,
        ffmpeg_path=ffmpeg,
        ffprobe_path=ffprobe,
        mediainfo_path=mediainfo,
        output_verifier=_PathAwareVerifier(fixed_paths, good_duration=1441.565),
        log=lambda *_: None,
        run_tool_fn=_tool_runner_from_subprocess(fake_run),
    )

    outcome = service.repair(
        output_path=str(out),
        base_dir=tmp_path,
        container="mkv",
        expected_duration_ms=1_441_400,
        source_has_audio=True,
        initial_result=_verify_result(duration_ok=False, duration_s=4_296_408.0),
    )

    setts_commands = [cmd for cmd in commands if Path(cmd[0]).name.lower() == "ffmpeg.exe" and "-bsf:v:0" in cmd]
    assert outcome.repaired is True
    assert outcome.timestamp_fixed is True
    assert outcome.archived_path is None
    assert setts_commands
    assert "setts=pts=N*1001/24000/TB:dts=N*1001/24000/TB:duration=1001/24000/TB" in setts_commands[0]
    assert any("abgeleitet" in line for line in outcome.timing_summary or [])



def test_timinganalyse_nutzt_mediainfo_framecount_ohne_ffprobe_count_frames(tmp_path, monkeypatch):
    import json

    import dragontools.worker.duration_repair_service as module
    from dragontools.worker.duration_repair_service import DurationRepairService

    media = tmp_path / "film.mkv"
    media.write_bytes(b"x" * 2048)
    ffprobe = _fake_tool(tmp_path / "ffprobe.exe")
    mediainfo = _fake_tool(tmp_path / "MediaInfo.exe")
    commands = []

    def fake_run(cmd, **kwargs):
        commands.append(list(cmd))
        exe = Path(cmd[0]).name.lower()
        if exe == "mediainfo.exe":
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "media": {
                            "track": [
                                {"@type": "General", "Duration": "1441565"},
                                {
                                    "@type": "Video",
                                    "Duration": "1441565",
                                    "FrameRate_Mode": "Constant",
                                    "FrameRate": "23.976",
                                    "FrameCount": "34563",
                                },
                                {"@type": "Audio", "Duration": "1441470"},
                            ]
                        }
                    }
                ),
                stderr="",
            )
        if exe == "ffprobe.exe":
            assert "-count_frames" not in cmd
            return SimpleNamespace(
                returncode=0,
                stdout=_timing_probe_json(
                    container_duration=1441.565,
                    video_duration=1441.565,
                    frames=34563,
                    audio_duration=1441.47,
                ),
                stderr="",
            )
        raise AssertionError(cmd)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    service = DurationRepairService(
        mkvmerge_path="",
        ffprobe_path=ffprobe,
        mediainfo_path=mediainfo,
        output_verifier=SimpleNamespace(_ffprobe_path=ffprobe),
        log=lambda *_: None,
    )

    info = service.get_media_timing_info(str(media), expected_duration_s=1441.565)

    assert info.video_frame_count == 34563
    assert info.frame_rate_mode == "CFR"
    assert any(Path(cmd[0]).name.lower() == "mediainfo.exe" for cmd in commands)
    assert any(Path(cmd[0]).name.lower() == "ffprobe.exe" for cmd in commands)


def test_workflow_duration_repair_keeps_verified_dynamic_metadata_evidence(tmp_path):
    from dragontools.worker.duration_repair_service import DurationRepairOutcome
    from dragontools.worker.workflow_verification_service import WorkflowVerificationService

    bad = _verify_result(duration_ok=False, duration_s=50.0)
    fixed = _verify_result(duration_ok=True, duration_s=100.0)
    seen = {}

    class Repairer:
        def can_repair(self, **kwargs):
            return True

        def repair(self, **kwargs):
            seen.update(kwargs)
            return DurationRepairOutcome(attempted=True, repaired=True, verify_result=fixed)

    class Logger:
        def info(self, _msg):
            pass

        def error(self, _msg):
            pass

    class EvidenceVerifier:
        def verify(self, *_args, **_kwargs):
            return bad

    svc = WorkflowVerificationService(
        output_verifier=EvidenceVerifier(),
        duration_repair_service=Repairer(),
        logger=Logger(),
    )
    ctx = SimpleNamespace(
        output_path=str(tmp_path / "film.mkv"), base_dir=tmp_path, container="mkv",
        duration_ms=100_000, analysis=SimpleNamespace(audio_streams=[]),
        pipeline_verified_hdr10plus=True, pipeline_verified_dolby_vision=True,
        expected_media_contract=None,
    )

    svc.verify(ctx)

    assert seen["verified_hdr10plus"] is True
    assert seen["verified_dolby_vision"] is True
