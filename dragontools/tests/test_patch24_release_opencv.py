from pathlib import Path
import pytest


def test_native_opencv_packaging_keeps_other_dependencies_and_paths(tmp_path):
    from extras.release_pyinstaller import native_opencv_arguments
    native = tmp_path / 'native module ü' / 'cv2.pyd'
    native.parent.mkdir()
    native.write_bytes(b'fake native extension')
    arguments = ['--hidden-import', 'cv2', '--collect-submodules=cv2', '--collect-data', 'cv2',
        '--collect-submodules', 'cryptography', '--name', 'DragonTools', 'DragonToolsV9.py']
    result = native_opencv_arguments(arguments, native)
    assert result == ['--collect-data', 'cv2', '--collect-submodules', 'cryptography', '--name',
        'DragonTools', 'DragonToolsV9.py', '--exclude-module', 'cv2', '--add-binary', str(native) + ';.']
    assert arguments[0:2] == ['--hidden-import', 'cv2']


def test_native_opencv_packaging_rejects_python_loader_instead_of_native_extension(tmp_path):
    from extras.release_pyinstaller import native_opencv_arguments
    source = tmp_path / '__init__.py'
    source.write_text('VALUE=1\n', encoding='utf-8')
    with pytest.raises(RuntimeError):
        native_opencv_arguments([], source)
    assert source.read_text(encoding='utf-8') == 'VALUE=1\n'


def test_native_source_image_smoke_exercises_opencv_features():
    from dragontools.core.release_frozen_runtime import verify_opencv_image_backend
    verify_opencv_image_backend()


def test_both_builders_use_source_free_native_opencv_wrapper():
    root = Path(__file__).resolve().parents[2]
    for path in [root / 'build_v9.bat', root / '.github/workflows/tests.yml']:
        assert '-m extras.release_pyinstaller' in path.read_text(encoding='utf-8')
