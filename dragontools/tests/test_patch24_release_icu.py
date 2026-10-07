import sys
import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows ICU build contract')


def bundle(tmp_path, monkeypatch, *, compatible=False, system_valid=True):
    from dragontools.core import release_qt_icu as module
    root = tmp_path / 'Daten'
    qt = root / 'PyQt6/Qt6/bin/Qt6Core.dll'
    qt.parent.mkdir(parents=True)
    qt.write_bytes(b'qt')
    candidate = root / 'icuuc.dll'
    candidate.write_bytes(b'foreign ICU')
    monkeypatch.setattr(module, '_required_icu_symbols', lambda _path: {b'u_getVersion'})
    def exports(path):
        if path == candidate:
            return {b'u_getVersion'} if compatible else {b'u_getVersion_78'}
        return {b'u_getVersion'} if system_valid else set()
    monkeypatch.setattr(module, '_exported_symbols', exports)
    return module, root, candidate


def test_icu_cleanup_keeps_compatible_library(tmp_path, monkeypatch):
    module, root, candidate = bundle(tmp_path, monkeypatch, compatible=True)
    assert not module.remove_conflicting_windows_icu(root)
    assert candidate.read_bytes() == b'foreign ICU'


def test_icu_cleanup_removes_only_proven_incompatible_root_copy(tmp_path, monkeypatch):
    module, root, candidate = bundle(tmp_path, monkeypatch)
    sibling = root / 'icudt78.dll'
    sibling.write_bytes(b'keep unrelated library')
    assert module.remove_conflicting_windows_icu(root)
    assert not candidate.exists() and sibling.read_bytes() == b'keep unrelated library'
    assert (root / 'PyQt6/Qt6/bin/Qt6Core.dll').read_bytes() == b'qt'


def test_icu_cleanup_keeps_artifact_when_system_provider_is_invalid(tmp_path, monkeypatch):
    module, root, candidate = bundle(tmp_path, monkeypatch, system_valid=False)
    with pytest.raises(RuntimeError):
        module.remove_conflicting_windows_icu(root)
    assert candidate.read_bytes() == b'foreign ICU'


def test_icu_cleanup_keeps_concurrently_changed_library(tmp_path, monkeypatch):
    module, root, candidate = bundle(tmp_path, monkeypatch)
    original = module._exported_symbols
    def exports(path):
        result = original(path)
        if path == candidate:
            candidate.write_bytes(b'foreign concurrent change')
        return result
    monkeypatch.setattr(module, '_exported_symbols', exports)
    with pytest.raises(RuntimeError):
        module.remove_conflicting_windows_icu(root)
    assert candidate.read_bytes() == b'foreign concurrent change'


def test_ci_and_official_build_use_same_icu_policy():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    for path in [root / 'build_v9.bat', root / '.github/workflows/tests.yml']:
        assert 'python -m dragontools.core.release_qt_icu' in path.read_text(encoding='utf-8').lower().replace('"%python_exe%"', 'python')


@pytest.mark.parametrize('relative', ['build_v9.bat', '.github/workflows/tests.yml'])
def test_whisper_build_collects_modules_binaries_data_without_readable_source(relative):
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    text = (root / relative).read_text(encoding='utf-8')
    for package in ['faster_whisper', 'ctranslate2']:
        assert '--collect-all ' + package not in text
        for kind in ['submodules', 'binaries', 'data']:
            assert '--collect-' + kind + ' ' + package in text
