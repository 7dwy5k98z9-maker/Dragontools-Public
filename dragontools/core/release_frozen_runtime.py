"""Native frozen checks exercise the same modules required by source validation."""
from importlib import import_module


def verify_runtime_imports():
    from .release_validation_package import _SMOKE_MODULES
    names = []
    for path in _SMOKE_MODULES:
        module_path = path.parent if path.name == '__init__.py' else path.with_suffix('')
        names.append('dragontools.' + module_path.as_posix().replace('/', '.'))
    for name in dict.fromkeys(names):
        import_module(name)


def verify_opencv_image_backend():
    from .audio_video_frame_analysis import _signature_from_gray_frame
    from .audio_video_frame_analysis import frame_similarity
    frame = bytes((x * 3 + y * 5) % 256 for y in range(80) for x in range(128))
    signature = _signature_from_gray_frame(frame, 128, 80, 0.0)
    if signature.backend != 'opencv' or frame_similarity(signature, signature) < 0.999:
        raise RuntimeError('Native OpenCV-Bildanalyse erfüllt den Runtime-Vertrag nicht.')

