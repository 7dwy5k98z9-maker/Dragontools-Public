"""Merge and disc extraction require proof through the final publication."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from dragontools.tests.test_review17_iso_merge_remux import _merge_info, _Signal, _Logger
import pytest


def test_merge_cannot_skip_output_verification_without_analyzed_inputs(tmp_path):
    from dragontools.worker.merge_executor import MergeExecutorMixin
    host = MergeExecutorMixin()
    host._log = lambda *a: None
    assert not host._verify_merge_output(tmp_path / 'unverified.mkv', [])


def test_merge_contract_requires_hdr_and_forced_audio(tmp_path, monkeypatch):
    from dragontools.worker import merge_executor as module
    host = module.MergeExecutorMixin()
    host.tools = SimpleNamespace(ffprobe='ffprobe')
    host._log = lambda *a: None
    host.abort_requested = False
    verifier = Mock()
    verifier.verify.return_value = SimpleNamespace(ok=True)
    monkeypatch.setattr(module, 'MergeOutputVerifier', lambda **kw: verifier)
    info = _merge_info(transfer='smpte2084')
    info['dynamic_hdr'] = dict(hdr_format='dolby_vision', hdr10plus=True, dolby_vision=True, dv_profile=8)
    info['audio_structure'][0]['forced'] = True
    assert host._verify_merge_output(tmp_path / 'out.mkv', [info, info])
    contract = verifier.verify.call_args.kwargs['expected_contract']
    assert contract.require_hdr and contract.require_dolby_vision and contract.require_hdr10plus
    assert contract.audio_tracks[0].forced is True


def test_merge_plan_is_a_deep_snapshot():
    from dragontools.worker.merge_plan import MergePlanMixin
    infos = [_merge_info(), _merge_info()]
    plan = MergePlanMixin()._build_merge_plan(infos, 'output.mkv', 'lossless')
    infos[0]['audio_structure'][0]['codec'] = 'mp3'
    assert plan['infos'][0]['audio_structure'][0]['codec'] == 'aac'


def test_merge_verified_media_survives_late_destination_collision(tmp_path, monkeypatch):
    from dragontools.worker import merge_executor as module
    class Host(module.MergeExecutorMixin):
        tools = SimpleNamespace(mkvmerge='mkvmerge')
        abort_requested = False
        _logger = _Logger()
        file_progress = _Signal()
        progress = _Signal()
        def _log(self, *a):
            pass
        def _verify_merge_output(self, *a):
            destination.write_bytes(b'FOREIGN')
            return True
    destination = tmp_path / 'out.mkv'
    def run(command, **kw):
        Path(command[command.index('-o') + 1]).write_bytes(b'VERIFIED MERGE')
        return SimpleNamespace(aborted=False, timed_out=False, ok=True, returncode=0)
    monkeypatch.setattr(module, 'run_tool', run)
    assert not Host()._merge_mkv_lossless(['a.mkv', 'b.mkv'], str(destination), infos=[_merge_info()])
    assert destination.read_bytes() == b'FOREIGN'
    assert any(path.read_bytes() == b'VERIFIED MERGE' for path in tmp_path.rglob('*.mkv') if path != destination)


@pytest.mark.parametrize('verified', [True, False])
def test_mkvmerge_warning_requires_output_verification_before_publication(tmp_path, monkeypatch, verified):
    from dragontools.worker import merge_executor as module
    source = tmp_path / 'input.mkv'
    source.write_bytes(b'SOURCE')
    destination = tmp_path / 'output.mkv'
    verifier = Mock(return_value=verified)
    class Host(module.MergeExecutorMixin):
        tools = SimpleNamespace(mkvmerge='mkvmerge')
        abort_requested = False
        _logger = _Logger()
        _verify_merge_output = staticmethod(verifier)
        def _log(self, *a):
            pass
    def run(command, **kw):
        Path(command[command.index('-o') + 1]).write_bytes(b'PROPOSED MERGE')
        return SimpleNamespace(aborted=False, timed_out=False, ok=False, returncode=1)
    monkeypatch.setattr(module, 'run_tool', run)
    assert Host()._merge_mkv_lossless([str(source)], str(destination), infos=[_merge_info()]) is verified
    verifier.assert_called_once()
    assert destination.exists() is verified
    assert source.read_bytes() == b'SOURCE'


def test_iso_fallback_abort_during_verification_prevents_publication(tmp_path, monkeypatch):
    from dragontools.worker import iso_ffmpeg_fallback_service as module
    source = tmp_path / 'source.m2ts'
    source.write_bytes(b'SOURCE')
    destination = tmp_path / 'output.mkv'
    worker = SimpleNamespace(abort_requested=False, abort_type='sofort')
    inspector = SimpleNamespace(ffmpeg_fallback_candidate=lambda _: ({'mode': 'file', 'path': source}, None),
        unique_fallback_output=lambda *a: destination)
    service = module.ISOFFmpegFallbackService(tools=SimpleNamespace(ffprobe='ffprobe'),
        inspector=inspector, worker=worker, log=lambda *a: None, progress=lambda *a: None)
    monkeypatch.setattr(service, 'ensure_ffmpeg', lambda: 'ffmpeg')
    def verify(*a, **kw):
        worker.abort_requested = True
        return SimpleNamespace(ok=True, messages=())
    monkeypatch.setattr(module, 'OutputVerifier', lambda **kw: SimpleNamespace(verify=verify))
    # The new source contract hook is injected only for this cancellation case.
    monkeypatch.setattr(service, '_source_contract', lambda *a: (SimpleNamespace(audio_stream_count=0), 1000, 0), raising=False)
    def run(command, **kw):
        Path(command[-1]).write_bytes(b'VALID MEDIA' * 512)
        return 0, []
    result = service.extract(str(source), str(tmp_path), run_ffmpeg=run)
    assert not result.ok
    assert not destination.exists()


@pytest.mark.parametrize('title_id', [True, -1, 1.8, '1'])
def test_makemkv_rejects_non_native_title_ids_before_execution(tmp_path, monkeypatch, title_id):
    from dragontools.tests.test_patch17_second_review import _makemkv_service
    service, worker, run = _makemkv_service(tmp_path, monkeypatch)
    adapter = Mock(side_effect=run)
    result = service.extract_titles('disc.iso', [title_id], str(tmp_path), run_makemkv=adapter)
    assert not result.ok
    adapter.assert_not_called()


def test_makemkv_scan_preserves_robot_escaped_title_names(tmp_path):
    from dragontools.worker.iso_makemkv_service import ISOMakeMKVService
    service = ISOMakeMKVService(tools=object(), inspector=SimpleNamespace(makemkv_source=lambda _: 'iso:source'),
        worker=SimpleNamespace(), log=lambda *a: None, progress=lambda *a: None)
    result = service.scan_titles(str(tmp_path / 'disc.iso'), run_makemkv=lambda *a, **kw: (0, [
        r'TINFO:0,2,0,"Titel, \"Deutsch\""', 'TINFO:0,8,0,"00:01:10.500"']))
    assert result.titles[0]['name'] == 'Titel, "Deutsch"'
    assert result.titles[0]['duration'] == 70


def test_makemkv_verification_uses_the_duration_of_each_exact_selected_title(tmp_path, monkeypatch):
    from dragontools.tests.test_patch17_second_review import _makemkv_service
    service, worker, run = _makemkv_service(tmp_path, monkeypatch)
    source = str(tmp_path / 'disc.iso')
    scan = service.scan_titles(source, run_makemkv=lambda *a, **kw: (0, [
        'TINFO:1,8,0,"00:01:00"', 'TINFO:4,8,0,"00:04:00"']))
    assert len(scan.titles) == 2
    seen = []
    from dragontools.worker import iso_makemkv_service as module
    def verify(path, *a, **kw):
        seen.append((Path(path).name, kw.get('expected_duration_ms')))
        return SimpleNamespace(ok=True, messages=())
    monkeypatch.setattr(module, 'OutputVerifier', lambda **kw: SimpleNamespace(verify=verify))
    result = service.extract_titles(source, [4, 1], str(tmp_path), run_makemkv=run)
    assert result.ok
    assert sorted(seen) == [('title01.mkv', 60_000), ('title04.mkv', 240_000)]
