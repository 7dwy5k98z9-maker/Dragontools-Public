from __future__ import annotations

import hashlib
import random
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.worker.dv_edge_frame_repair import (
    DVEdgeFrameRepair, EdgeExtras, append_output_filter,
    locate_black_edge_extras, timeline_matches,
)
from dragontools.worker.dv_pipeline_context import DVWorkFiles
from dragontools.worker.dv_runtime_models import DVEncoderConfig
from dragontools.worker.dv_partial_frame_repair import inspect_hevc_irap


BLACK = bytes(144)


def _pictures(count=180):
    rng = random.Random(708)
    return [BLACK] * 10 + [bytes(rng.randrange(30, 210) for _ in range(144))
                           for _ in range(count - 20)] + [BLACK] * 10


@pytest.mark.parametrize("head,tail", [(0, 1), (0, 5), (1, 0), (5, 0), (2, 3)])
def test_locates_only_verified_black_edge_extensions(head, tail):
    source = _pictures()
    encoded = [BLACK] * head + source + [BLACK] * tail
    assert locate_black_edge_extras(source, encoded) == EdgeExtras(head, tail)


def test_rejects_interior_insertion_even_when_both_edges_are_black():
    source = _pictures()
    encoded = source[:90] + [source[89]] + source[90:]
    assert locate_black_edge_extras(source, encoded) is None


@pytest.mark.parametrize("encoded", [[BLACK] * 100, [bytes([255]) * 144] * 100])
def test_no_luminance_or_alignment_evidence_is_not_accepted(encoded):
    source = [BLACK] * 99
    assert locate_black_edge_extras(source, encoded) is None


def test_visible_extra_frames_are_not_removed():
    source = _pictures()
    assert locate_black_edge_extras(source, source + [source[80]]) is None


def test_six_extra_frames_and_empty_source_are_rejected():
    source = _pictures()
    assert locate_black_edge_extras(source, source + [BLACK] * 6) is None
    assert locate_black_edge_extras([], [BLACK]) is None


def test_candidate_with_corrupted_middle_picture_is_rejected():
    source = _pictures()
    candidate = list(source)
    candidate[90] = BLACK
    assert not timeline_matches(source, candidate)


def test_appends_trim_after_complex_overlay_and_maps_only_new_output():
    cmd = ["ffmpeg", "-i", "movie.mkv", "-filter_complex",
           "[0:v:0]crop=64:64:0:0[v];[v][0:s:0]overlay[vout]",
           "-map", "[vout]", "-c:v", "libx265", "-an", "out.hevc"]
    result = append_output_filter(cmd, "trim=start_frame=10:end_frame=90")
    assert result[result.index("-map") + 1] == "[_dv_edge_checked]"
    assert "[vout]trim=start_frame=10:end_frame=90[_dv_edge_checked]" in result[result.index("-filter_complex") + 1]
    assert cmd[cmd.index("-map") + 1] == "[vout]"


def test_unknown_graph_mapping_fails_closed():
    with pytest.raises(ValueError):
        append_output_filter(["ffmpeg", "-filter_complex", "[0:v]null[vout]",
                              "-map", "0:v:0", "out.hevc"], "scale=16:9")


def _state(tmp_path):
    files = DVWorkFiles.create(tmp_path / "dv")
    files.root.mkdir()
    source = tmp_path / "movie.mkv"
    request = SimpleNamespace(input_path=str(source), profile_major=8,
                              vf_args=["-map", "0:v:0", "-vf", "crop=64:64:0:0"])
    return SimpleNamespace(request=request, files=files, effective_vf_args=request.vf_args,
                           frame_recovery_applied=False)


def _config():
    return DVEncoderConfig(codec="h265", crf=22, preset="fast",
                           options={"encoder": "cpu", "bf": 8})


class _Runner:
    def __init__(self):
        self.last_count = None
        self.commands = []

    def run(self, cmd, **kwargs):
        self.commands.append(cmd)
        result = subprocess.run([str(v) for v in cmd], capture_output=True,
                                encoding="utf-8", errors="replace", timeout=90,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise AssertionError(result.stderr[-6000:])
        counts = re.findall(r"^frame=(\d+)", result.stdout, re.MULTILINE)
        self.last_count = int(counts[-1]) if counts else None
        return result.returncode

    def probe_ms(self, _path):
        return 7500

    def run_p(self, cmd, *_args, **_kwargs):
        return self.run(cmd)

    def take_output_frame_count(self, *_args, **_kwargs):
        return self.last_count


@pytest.fixture
def ffmpeg():
    from dragontools.tests.ci_requirements import external_media_environment
    path = external_media_environment().ffmpeg
    if not path:
        pytest.skip("real FFmpeg not available")
    return path


def _make_source(ffmpeg, state, count=180):
    # Enlarge deterministic fingerprint pixels to 64x64. Brightness and texture
    # change at every frame, with a genuine black lead-in and lead-out.
    raw = Path(state.request.input_path).with_suffix(".gray")
    pictures = _pictures(count)
    with raw.open("wb") as out:
        for picture in pictures:
            out.write(bytes(picture[min(8, y * 9 // 64) * 16 + x // 4]
                            for y in range(64) for x in range(64)))
    cmd = [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray",
           "-video_size", "64x64", "-framerate", "24000/1001", "-i", str(raw),
           "-vf", "gblur=sigma=2", "-c:v", "ffv1", "-pix_fmt", "yuv420p10le", state.request.input_path]
    _Runner().run(cmd)
    return len(pictures)


@pytest.mark.media_integration
@pytest.mark.parametrize("head,tail,open_gop,complex_graph", [
    (0, 1, 1, False), (0, 5, 1, False), (2, 0, 0, False),
    (1, 2, 0, False), (0, 1, 1, True),
])
def test_real_b_frame_hevc_edge_repair(tmp_path, ffmpeg, monkeypatch,
                                      head, tail, open_gop, complex_graph):
    state = _state(tmp_path)
    count = _make_source(ffmpeg, state)
    if complex_graph:
        # Exercise the same explicit graph-output path as subtitle overlays;
        # two video branches with an overlay do not need external PGS fixtures.
        state.effective_vf_args = ["-filter_complex",
            "[0:v:0]split=2[v][bg];[bg]crop=16:16:0:0[sub];[v][sub]overlay=0:0[vout]",
            "-map", "[vout]"]
    runner = _Runner()
    logs = []
    repair = DVEdgeFrameRepair(tools=SimpleNamespace(ffmpeg=ffmpeg), encoder_config=_config(),
                               progress_runner=runner, log=lambda *args: logs.append(args),
                               verbose_log=lambda *args: logs.append(args))
    production_plan = repair._plan

    def bounded_plan(state, output):
        cmd = production_plan(state, output)
        idx = cmd.index("-x265-params") + 1
        cmd[idx] += f":keyint=48:min-keyint=48:scenecut=0:open-gop={open_gop}:pools=1:frame-threads=1"
        return cmd

    monkeypatch.setattr(repair, "_plan", bounded_plan)
    cmd = append_output_filter(repair._plan(state, state.files.enc_hevc),
                               f"tpad=start={head}:stop={tail}:color=black")
    assert runner.run(cmd) == 0
    assert inspect_hevc_irap(state.files.enc_hevc)[2] == count + head + tail
    previous = hashlib.sha256(state.files.enc_hevc.read_bytes()).hexdigest()
    assert repair.attempt(state=state, runner=runner, expected_rpu_frames=count,
                          actual_encode_frames=count + head + tail), logs
    assert inspect_hevc_irap(state.files.enc_hevc)[2] == count
    assert hashlib.sha256((state.files.root / "encoded_frame_mismatch.hevc").read_bytes()).hexdigest() == previous
    assert state.frame_recovery_applied
    assert state.frame_recovery_final_count == count
    # Ensure candidate decode actually used strict error handling.
    checks = [cmd for cmd in runner.commands if str(cmd[-1]).endswith("edge_candidate.gray")]
    assert checks and "-xerror" in checks[0] and "explode" in checks[0]


def test_existing_backup_is_never_overwritten(tmp_path):
    state = _state(tmp_path)
    state.files.enc_hevc.write_bytes(b"current")
    backup = state.files.root / "encoded_frame_mismatch.hevc"
    backup.write_bytes(b"first")
    repair = DVEdgeFrameRepair(tools=SimpleNamespace(ffmpeg="ffmpeg"), encoder_config=_config(),
                               progress_runner=None, log=lambda *_: None, verbose_log=lambda *_: None)
    assert not repair.attempt(state=state, runner=None, expected_rpu_frames=100, actual_encode_frames=101)
    assert backup.read_bytes() == b"first"
    assert state.files.enc_hevc.read_bytes() == b"current"


@pytest.mark.media_integration
def test_real_existing_missing_frame_repair_still_works(tmp_path, ffmpeg, monkeypatch):
    import dragontools.worker.dv_partial_frame_repair as module
    from dataclasses import replace
    state = _state(tmp_path)
    count = _make_source(ffmpeg, state, count=1200)
    runner = _Runner()
    logs = []
    real_plan = module.build_dv_encode_command

    def bounded_plan(**kwargs):
        plan = real_plan(**kwargs)
        cmd = list(plan.command)
        idx = cmd.index("-x265-params") + 1
        cmd[idx] += ":keyint=48:min-keyint=48:scenecut=0:open-gop=0:pools=1:frame-threads=1"
        return replace(plan, command=cmd)

    monkeypatch.setattr(module, "build_dv_encode_command", bounded_plan)
    plan = bounded_plan(ffmpeg_path=ffmpeg, encoder_config=_config(),
                        input_path=state.request.input_path, output_hevc=state.files.enc_hevc,
                        vf_args=state.effective_vf_args, profile_major=8)
    # Simulate three dropped source pictures in a bounded interior interval.
    cmd = append_output_filter(plan.command, "select='not(eq(n,480)+eq(n,530)+eq(n,580))'")
    runner.run(cmd)
    assert inspect_hevc_irap(state.files.enc_hevc)[2] == count - 3
    repair = module.DVPartialFrameRepair(tools=SimpleNamespace(ffmpeg=ffmpeg),
        encoder_config=_config(), progress_runner=runner,
        log=lambda *args: logs.append(args), verbose_log=lambda *args: logs.append(args))
    assert repair.attempt(state=state, runner=runner, expected_rpu_frames=count,
                          actual_encode_frames=count - 3), logs
    assert inspect_hevc_irap(state.files.enc_hevc)[2] == count
    assert (state.files.root / "encoded_frame_mismatch.hevc").exists()


def test_early_parity_guard_routes_extra_pictures_to_edge_repair(tmp_path, monkeypatch):
    from dragontools.tests.test_patch_dv_frame_mismatch_recovery import _service, _state as guard_state
    service = _service(tmp_path)
    state = guard_state(tmp_path, frame_count=103)
    calls = []
    monkeypatch.setattr(service, "_attempt_edge_frame_repair", lambda *_a, **kw: calls.append(kw) or True)
    monkeypatch.setattr(service, "_attempt_partial_frame_repair", lambda *_a, **_kw: pytest.fail("unexpected deletion repair"))
    assert service.ensure_frame_parity_or_recover(state, object(), probe_rpu_frame_count=lambda *_: 100)
    assert calls == [{"expected_rpu_frames": 100, "actual_encode_frames": 103}]
    assert state.encoded_frame_evidence.count == 100
    assert state.encoded_frame_evidence.source == "ffmpeg_edge_repair_validated"


def test_partial_decoder_also_rejects_concealed_errors():
    from dragontools.worker.dv_partial_frame_repair import DVPartialFrameRepair
    repair = DVPartialFrameRepair(tools=SimpleNamespace(ffmpeg="ffmpeg"), encoder_config=_config(),
                                 progress_runner=None, log=lambda *_: None, verbose_log=lambda *_: None)
    cmd = repair._fingerprint_command(input_path="source.hevc", output_path=Path("frames.gray"))
    assert cmd.index("-xerror") < cmd.index("-i")
    assert cmd[cmd.index("-err_detect") + 1] == "explode"


def test_partial_validation_distinguishes_black_from_white_despite_equal_dhash(tmp_path):
    from dragontools.worker.dv_partial_frame_repair import fingerprint_luma_matches, read_dhash_file
    source = tmp_path / "source.gray"
    candidate = tmp_path / "candidate.gray"
    source.write_bytes(bytes(72) + bytes([255]) * 72)
    candidate.write_bytes(bytes(144))
    assert read_dhash_file(source) == read_dhash_file(candidate)
    assert not fingerprint_luma_matches(source, candidate)
    candidate.write_bytes(source.read_bytes())
    assert fingerprint_luma_matches(source, candidate)


def test_partial_repair_also_preserves_an_existing_backup(tmp_path):
    from dragontools.worker.dv_partial_frame_repair import DVPartialFrameRepair
    state = _state(tmp_path)
    state.files.enc_hevc.write_bytes(b"current")
    backup = state.files.root / "encoded_frame_mismatch.hevc"
    backup.write_bytes(b"first")
    repair = DVPartialFrameRepair(tools=SimpleNamespace(ffmpeg="ffmpeg"), encoder_config=_config(),
                                 progress_runner=None, log=lambda *_: None, verbose_log=lambda *_: None)
    assert not repair.attempt(state=state, runner=None, expected_rpu_frames=101, actual_encode_frames=100)
    assert backup.read_bytes() == b"first"
    assert state.files.enc_hevc.read_bytes() == b"current"


def test_failed_candidate_install_restores_original(tmp_path, monkeypatch):
    import dragontools.worker.dv_edge_frame_repair as module
    from dragontools.worker.dv_partial_frame_repair import IrapPoint
    state = _state(tmp_path)
    original_bytes = b"old-encode" * 20
    state.files.enc_hevc.write_bytes(original_bytes)
    source = _pictures(100)
    encoded = source + [BLACK]
    repair = DVEdgeFrameRepair(tools=SimpleNamespace(ffmpeg="ffmpeg"), encoder_config=_config(),
                               progress_runner=None, log=lambda *_: None, verbose_log=lambda *_: None)

    def fingerprints(_runner, _state, _input, output, *, source=False):
        if output.name == "edge_encoded.gray":
            return encoded
        return _pictures(100)

    def segment(_state, output, start, end):
        output.write_bytes(b"replacement")
        return True

    monkeypatch.setattr(repair, "_fingerprint", fingerprints)
    monkeypatch.setattr(repair, "_encode_segment", segment)
    monkeypatch.setattr(module, "inspect_hevc_irap", lambda path:
        ([IrapPoint(60, 50, 21)], b"headers", 100 if path.name == "encoded_edge_repair.hevc" else 101))
    native_replace = Path.replace

    def fail_install(path, destination):
        if path.name == "encoded_edge_repair.hevc":
            raise OSError("simulated candidate install failure")
        return native_replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_install)
    assert not repair.attempt(state=state, runner=None, expected_rpu_frames=100, actual_encode_frames=101)
    assert state.files.enc_hevc.read_bytes() == original_bytes
    assert not state.frame_recovery_applied


def test_rejected_candidate_never_replaces_the_original(tmp_path, monkeypatch):
    import dragontools.worker.dv_edge_frame_repair as module
    from dragontools.worker.dv_partial_frame_repair import IrapPoint
    state = _state(tmp_path)
    state.files.enc_hevc.write_bytes(b"old-encode" * 20)
    original_bytes = state.files.enc_hevc.read_bytes()
    repair = DVEdgeFrameRepair(tools=SimpleNamespace(ffmpeg="ffmpeg"), encoder_config=_config(),
                               progress_runner=None, log=lambda *_: None, verbose_log=lambda *_: None)
    def fingerprints(_runner, _state, _input, output, *, source=False):
        if output.name == "edge_encoded.gray":
            return _pictures(100) + [BLACK]
        if output.name == "edge_candidate.gray":
            return [BLACK] * 100
        return _pictures(100)
    def segment(_state, output, start, end):
        output.write_bytes(b"bad-candidate")
        return True
    monkeypatch.setattr(repair, "_fingerprint", fingerprints)
    monkeypatch.setattr(repair, "_encode_segment", segment)
    monkeypatch.setattr(module, "inspect_hevc_irap", lambda _:
                        ([IrapPoint(60, 50, 21)], b"headers", 101))
    assert not repair.attempt(state=state, runner=None, expected_rpu_frames=100, actual_encode_frames=101)
    assert state.files.enc_hevc.read_bytes() == original_bytes
    assert not (state.files.root / "encoded_frame_mismatch.hevc").exists()
