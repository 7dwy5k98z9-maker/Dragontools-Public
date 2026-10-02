from fractions import Fraction
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dragontools.worker.duration_packet_integrity import PacketIntegrityResult
from dragontools.worker.duration_repair_models import MediaTimingInfo
from dragontools.worker.duration_timestamp_candidate_service import TimestampCandidateService
from dragontools.tests.test_patch_ba_source_timing_reference import _ok_verify


@pytest.mark.parametrize('container', ['mkv', 'mp4'])
@pytest.mark.parametrize('packet_ok,available,accepted', [
    (True, True, True), (False, True, False), (False, False, False), (True, False, False)])
def test_commit_requires_both_positive_and_available_evidence(tmp_path, container, packet_ok, available, accepted):
    out = tmp_path / ('before.' + container)
    tmp = tmp_path / ('candidate.' + container)
    out.write_bytes(b'O' * 2048)
    tmp.write_bytes(b'N' * 2048)
    timing = MediaTimingInfo(path=str(out), container_duration_s=10, video_duration_s=10,
        video_frame_count=250, frame_rate=Fraction(25), video_stream_count=1)
    runtime = SimpleNamespace(ffprobe_path='ffprobe', log=Mock(),
        run_tool=Mock(return_value=SimpleNamespace(returncode=0)),
        output_verifier=SimpleNamespace(verify=Mock(return_value=_ok_verify(10))),
        replace_file=Mock(side_effect=lambda src, dst: src.replace(dst)))
    guard = SimpleNamespace(validate=Mock(return_value=SimpleNamespace(ok=True, messages=[], confirmed_kinds=set())))
    service = TimestampCandidateService(runtime, SimpleNamespace(get_media_timing_info=lambda p: timing), guard)
    service._archive = SimpleNamespace(archive=Mock())
    service._validator._packet_integrity = SimpleNamespace(validate=Mock(
        return_value=PacketIntegrityResult(packet_ok, available, () if accepted else ('hash unavailable',))))
    result = service.attempt(out=out, tmp=tmp, command=[], label='test', method='test',
        container=container, before=timing, before_ffprobe=None, before_mediainfo=None,
        expected_duration_ms=10000, source_has_audio=False, timing_summary=[], source_reference=timing)
    assert result.repaired is accepted
    assert out.read_bytes() == (b'N' if accepted else b'O') * 2048
    assert runtime.replace_file.call_count == int(accepted)
    assert service._archive.archive.call_count == int(not accepted)
