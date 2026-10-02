import json
from copy import deepcopy
from fractions import Fraction
from types import SimpleNamespace

import pytest

from dragontools.worker import duration_packet_integrity as subject


def payload():
    return {'streams': [{'index': 0, 'codec_type': 'video'}, {'index': 1, 'codec_type': 'audio'},
                        {'index': 2, 'codec_type': 'subtitle'}],
            'packets': [{'stream_index': i, 'pts_time': '0', 'duration_time': '0.02',
                         'data_hash': f'SHA256:{i}'} for i in range(3)]}


def validate(monkeypatch, before, after):
    monkeypatch.setattr(subject, 'tool_available', lambda p: True)
    responses = iter([before, after])
    def run(*args, **kwargs):
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, SimpleNamespace):
            return value
        return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr='')
    return subject.PacketIntegrityVerifier(ffprobe_path='ffprobe', run_tool=run).validate(
        'before', 'after', reference_duration_s=10, frame_rate=Fraction(25))


@pytest.mark.parametrize('failure', [RuntimeError('timeout'), OSError('unreadable'),
    SimpleNamespace(returncode=1, stdout='', stderr='failed'),
    SimpleNamespace(returncode=0, stdout='{broken', stderr=''),
    {}, [], {'streams': []}, {'streams': [], 'packets': []}])
@pytest.mark.parametrize('side', ['before', 'after'])
def test_probe_failure_blocks_automatic_acceptance(monkeypatch, failure, side):
    result = validate(monkeypatch, failure if side == 'before' else payload(),
                      failure if side == 'after' else payload())
    assert not result.ok and not result.available
    assert result.messages


def test_missing_tool_blocks_acceptance(monkeypatch):
    monkeypatch.setattr(subject, 'tool_available', lambda p: False)
    result = subject.PacketIntegrityVerifier(ffprobe_path='', run_tool=None).validate(
        'before', 'after', reference_duration_s=10, frame_rate=None)
    assert not result.ok and not result.available


@pytest.mark.parametrize('damage', ['hash', 'count', 'missing_hash', 'missing_packets',
                                  'bad_index', 'no_video', 'huge_pts', 'huge_duration'])
def test_damaged_or_incomplete_evidence_is_rejected(monkeypatch, damage):
    after = deepcopy(payload())
    if damage == 'hash': after['packets'][0]['data_hash'] = 'SHA256:changed'
    if damage == 'count': after['packets'].append(dict(after['packets'][0]))
    if damage == 'missing_hash': del after['packets'][0]['data_hash']
    if damage == 'missing_packets': after['packets'] = []
    if damage == 'bad_index': after['packets'][0]['stream_index'] = 'invalid'
    if damage == 'no_video': after['streams'] = after['streams'][1:]
    if damage == 'huge_pts': after['packets'][0]['pts_time'] = '1000001'
    if damage == 'huge_duration': after['packets'][0]['duration_time'] = '99'
    assert not validate(monkeypatch, payload(), after).ok


@pytest.mark.parametrize('mode', ['identical', 'interleaved', 'empty_subtitle', 'video_only'])
def test_valid_packet_modes(monkeypatch, mode):
    before = payload()
    if mode == 'empty_subtitle': before['packets'] = before['packets'][:2]
    if mode == 'video_only':
        before['streams'] = before['streams'][:1]
        before['packets'] = before['packets'][:1]
    after = deepcopy(before)
    if mode == 'interleaved': after['packets'].reverse()
    result = validate(monkeypatch, before, after)
    assert result.ok and result.available and not result.messages
