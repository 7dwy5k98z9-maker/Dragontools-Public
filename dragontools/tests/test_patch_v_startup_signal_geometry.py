from __future__ import annotations

import queue
from pathlib import Path

from dragontools.core.callback_dispatch import invoke_callback, is_callback_like
from dragontools.worker.tool_runner import _dispatch_callbacks


GUI_DIR = Path(__file__).resolve().parents[1] / "gui"


class FakeQtSignal:
    """Signal double that reproduces PyQt6 bound-signal direct-call semantics."""

    def __init__(self) -> None:
        self.emissions: list[tuple] = []

    def __call__(self, *_args, **_kwargs):
        raise TypeError("native Qt signal is not callable")

    def emit(self, *args) -> None:
        self.emissions.append(tuple(args))


def test_callback_like_accepts_native_signal_without_direct_call():
    signal = FakeQtSignal()
    assert is_callback_like(signal) is True
    invoke_callback(signal, "payload")
    assert signal.emissions == [("payload",)]


def test_tool_runner_output_dispatch_uses_signal_emit():
    signal = FakeQtSignal()
    callbacks = queue.SimpleQueue()
    callbacks.put((signal, "ffmpeg output"))

    _dispatch_callbacks(callbacks, label="Test", log=None)

    assert signal.emissions == [("ffmpeg output",)]


def test_banner_pixmap_cannot_force_main_window_minimum_width():
    source = (GUI_DIR / "convert_widget_custom_widgets.py").read_text(encoding="utf-8")
    assert "def minimumSizeHint(self) -> QSize:" in source
    assert "return QSize(0, hint.height())" in source
