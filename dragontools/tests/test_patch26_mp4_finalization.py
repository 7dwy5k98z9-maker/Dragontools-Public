"""Candidate-only, validate-before-write guarantees for MP4 flag finalization."""
import os
import struct
from types import SimpleNamespace as NS

import pytest

from dragontools.worker.mp4_default_flags import finalize_mp4_defaults


def _box(kind, body):
    return struct.pack('>I4s', len(body)+8, kind)+body


def _track(handler, flags=7):
    header = b'\x00'+flags.to_bytes(3, 'big')+bytes(80)
    return _box(b'trak', _box(b'tkhd', header)+_box(b'mdia',
        _box(b'hdlr', bytes(8)+handler+bytes(12))))


def _file(*tracks):
    return _box(b'ftyp', b'isom'+bytes(8))+_box(b'moov', b''.join(tracks))+_box(b'mdat', b'untouched-media-payload')


def _contract(audio=(False,), subtitles=()):
    return NS(container='mp4', audio_tracks=[NS(default=x) for x in audio],
        subtitle_tracks=[NS(default=x) for x in subtitles])


def test_changes_only_enabled_bits_and_is_idempotent(tmp_path):
    source = tmp_path/'source.mp4'
    candidate = tmp_path/'candidate.mp4'
    original = _file(_track(b'soun', 7), _track(b'text', 6))
    source.write_bytes(original)
    candidate.write_bytes(original)
    assert finalize_mp4_defaults(candidate, _contract(subtitles=(True,)), input_path=source)==2
    updated = candidate.read_bytes()
    differences = [(a,b) for a,b in zip(original, updated) if a!=b]
    assert differences == [(7,6),(6,7)]
    assert len(updated)==len(original)
    assert source.read_bytes()==original
    assert finalize_mp4_defaults(candidate, _contract(subtitles=(True,)), input_path=source)==0
    assert candidate.read_bytes()==updated


@pytest.mark.parametrize('invalid', ['short', 'undersize', 'oversize', 'extended', 'duplicate', 'count', 'version'])
def test_invalid_structure_is_rejected_before_any_write(tmp_path, invalid):
    data = _file(_track(b'soun'))
    contract = _contract()
    if invalid=='short': data+=b'bad'
    if invalid=='undersize': data=struct.pack('>I4s', 4,b'ftyp')
    if invalid=='oversize': data=struct.pack('>I4s', 9999,b'ftyp')+bytes(20)
    if invalid=='extended': data=struct.pack('>I4s', 1,b'ftyp')+b'short'
    if invalid=='duplicate': data+=_box(b'moov', _track(b'soun'))
    if invalid=='count': contract=_contract(subtitles=(False,))
    if invalid=='version': data=data.replace(b'tkhd\x00', b'tkhd\x02')
    path = tmp_path/'candidate.mp4'
    path.write_bytes(data)
    with pytest.raises(ValueError): finalize_mp4_defaults(path, contract)
    assert path.read_bytes()==data


@pytest.mark.parametrize('alias', ['same', 'hardlink'])
def test_source_and_alias_are_never_modified(tmp_path, alias):
    source = tmp_path/'source.mp4'
    original = _file(_track(b'soun'))
    source.write_bytes(original)
    candidate = source
    if alias=='hardlink':
        candidate = tmp_path/'alias.mp4'
        os.link(source, candidate)
    with pytest.raises(ValueError, match='Originalquelle'):
        finalize_mp4_defaults(candidate, _contract(), input_path=source)
    assert source.read_bytes()==original


def test_abort_preserves_entire_candidate(tmp_path):
    path = tmp_path/'candidate.mp4'
    original = _file(_track(b'soun'))
    path.write_bytes(original)
    with pytest.raises(RuntimeError, match='abgebrochen'):
        finalize_mp4_defaults(path, _contract(), abort_check=lambda: True)
    assert path.read_bytes()==original


@pytest.mark.parametrize('malformed', [False, True])
def test_workflow_process_finishes_owned_metadata_before_verification(tmp_path, malformed):
    from dragontools.worker.workflow_services import WorkflowServices
    from dragontools.worker.workflow_models import PipelineExecutionResult
    source = tmp_path/'source.mp4'
    candidate = tmp_path/'candidate.mp4'
    original = _file(_track(b'soun'))
    source.write_bytes(original)
    rendered = b'bad' if malformed else original
    def execute(request):
        candidate.write_bytes(rendered)
        return PipelineExecutionResult(success=True)
    service = object.__new__(WorkflowServices)
    service._pipeline_executor = NS(execute=execute)
    ctx = NS(input_path=str(source), output_path=str(candidate), pipeline='standard', container='mp4',
        analysis=NS(has_dv=False), effective_crf=20, effective_encoder_options={},
        expected_media_contract=_contract(), keep_failed_output=False)
    if malformed:
        with pytest.raises(ValueError): service.process(ctx, {})
        assert ctx.keep_failed_output
        assert candidate.read_bytes()==rendered
    else:
        service.process(ctx, {})
        assert [(a,b) for a,b in zip(original,candidate.read_bytes()) if a!=b]==[(7,6)]
        assert not ctx.keep_failed_output
    assert source.read_bytes()==original
