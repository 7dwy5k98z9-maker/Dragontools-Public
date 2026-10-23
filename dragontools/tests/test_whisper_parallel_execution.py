import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from dragontools.core import language_detection as language
from dragontools.core import whisper_execution as execution


@pytest.fixture(autouse=True)
def isolated_pool(monkeypatch):
    monkeypatch.setattr(execution, '_EXECUTION_LOCK', threading.Lock())
    monkeypatch.setattr(execution, '_MODELS', execution.OrderedDict())
    monkeypatch.setattr(language.FasterWhisperLanguageDetector, 'available', staticmethod(lambda: True))
    monkeypatch.setattr(language, 'resolve_whisper_model_reference', lambda **kw: kw['model_name'])


def test_seven_parallel_workers_share_model_and_retry_lazy_cuda_failure_on_cpu(monkeypatch):
    created, active, maximum, messages = [], [0], [0], []
    barrier = threading.Barrier(7)
    class Model:
        def __init__(self, reference, *, device, compute_type):
            self.device = device
            created.append((device, compute_type))
        def transcribe(self, path, **kwargs):
            def segments():
                active[0] += 1
                maximum[0] = max(maximum[0], active[0])
                try:
                    if self.device == 'cuda':
                        raise RuntimeError('Library cublas64_12.dll is not found or cannot be loaded')
                    time.sleep(0.015)
                    yield object()
                finally:
                    active[0] -= 1
            return segments(), SimpleNamespace(language='ja', language_probability=.99)
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(language.FasterWhisperLanguageDetector, '_preferred_backend',
                        staticmethod(lambda: ('cuda', 'float16')))
    def detect(index):
        detector = language.FasterWhisperLanguageDetector(log=lambda *a: messages.append(a), wait_timeout_s=3)
        barrier.wait(timeout=3)
        evidence = detector.detect_file(f'worker-{index}.wav')
        return evidence, detector.backend
    with ThreadPoolExecutor(max_workers=7) as workers:
        results = list(workers.map(detect, range(7)))
    assert created == [('cuda', 'float16'), ('cpu', 'int8')]
    assert maximum[0] == 1
    assert len(results) == 7
    assert all(item.language == 'ja' and backend == 'cpu/int8' for item, backend in results)
    assert any('wartet' in message for message, _ in messages)


def test_waiting_for_whisper_is_abortable():
    cancelled, waiting = threading.Event(), threading.Event()
    errors = []
    def wait():
        try:
            with execution.whisper_execution_slot(
                abort_check=cancelled.is_set, log=lambda *a: waiting.set(), timeout_s=3
            ):
                pytest.fail('Cancelled request must not run')
        except Exception as exc:
            errors.append(exc)
    with execution.whisper_execution_slot(abort_check=lambda: False, log=lambda *a: None):
        thread = threading.Thread(target=wait, daemon=True)
        thread.start()
        assert waiting.wait(1)
        cancelled.set()
        thread.join(1)
        assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], InterruptedError)


def test_waiting_for_whisper_has_a_deadline():
    with execution.whisper_execution_slot(abort_check=lambda: False, log=lambda *a: None):
        with pytest.raises(TimeoutError, match='Wartezeit'):
            with execution.whisper_execution_slot(abort_check=lambda: False,
                                                  log=lambda *a: None, timeout_s=0):
                pytest.fail('Occupied slot was entered')


def test_failure_releases_slot_for_next_worker(monkeypatch):
    class Model:
        def __init__(self, *a, **kw):
            pass
        def transcribe(self, path, **kw):
            if path == 'bad.wav':
                raise ValueError('invalid sample')
            return iter(()), SimpleNamespace(language='de', language_probability=.98)
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(language.FasterWhisperLanguageDetector, '_preferred_backend',
                        staticmethod(lambda: ('cpu', 'int8')))
    first = language.FasterWhisperLanguageDetector()
    with pytest.raises(ValueError):
        first.detect_file('bad.wav')
    second = language.FasterWhisperLanguageDetector(wait_timeout_s=0)
    assert second.detect_file('good.wav').language == 'de'


def test_distinct_model_settings_do_not_share_wrong_model(monkeypatch):
    created = []
    class Model:
        def __init__(self, reference, **kw):
            created.append(reference)
        def transcribe(self, *a, **kw):
            return iter(()), SimpleNamespace(language='de', language_probability=.98)
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(language.FasterWhisperLanguageDetector, '_preferred_backend',
                        staticmethod(lambda: ('cpu', 'int8')))
    for model in ['small', 'tiny', 'small']:
        language.FasterWhisperLanguageDetector(model_name=model).detect_file('audio.wav')
    assert created == ['small', 'tiny']
