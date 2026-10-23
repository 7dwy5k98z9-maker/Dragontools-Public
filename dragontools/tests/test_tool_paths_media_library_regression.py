from __future__ import annotations

from types import SimpleNamespace

import pytest

from dragontools.core import tool_paths
from dragontools.gui.media_library_dialog_service import MediaLibraryDialogService


class Provider(tool_paths.ToolPathSettingsProvider):
    def __init__(self, folder):
        self.folder = folder

    def get_custom_dirs(self):
        return [self.folder]

    def find_in_settings(self, tool_key, *names):
        if tool_key == 'ffmpeg':
            for name in names:
                path = self.folder / name
                if path.is_file():
                    return str(path)
        return None


@pytest.fixture
def configured_tools(tmp_path, monkeypatch):
    for name in ('ffmpeg.exe', 'ffprobe.exe'):
        (tmp_path / name).write_bytes(b'test executable path')
    monkeypatch.setattr(tool_paths, '_tool_paths_instance', None)
    monkeypatch.setattr(tool_paths, '_tool_paths_provider', None)
    provider = Provider(tmp_path)
    return tool_paths.get_tool_paths(provider=provider), provider


def test_media_library_tool_lookup_preserves_registered_provider(configured_tools):
    tools, provider = configured_tools
    settings = SimpleNamespace(value=lambda *_args, **_kwargs: '')
    assert MediaLibraryDialogService.tool_paths(settings) is tools
    assert tool_paths._tool_paths_provider is provider
    assert tools.ffmpeg == str(provider.folder / 'ffmpeg.exe')


@pytest.mark.parametrize('factory', [tool_paths.ToolPaths, tool_paths.get_tool_paths])
def test_invalid_settings_provider_does_not_corrupt_global_tools(configured_tools, factory):
    tools, provider = configured_tools
    with pytest.raises(TypeError, match='ToolPathSettingsProvider'):
        factory(SimpleNamespace(value=lambda *_args: ''))
    assert tool_paths.get_tool_paths() is tools
    assert tool_paths._tool_paths_provider is provider
    tool_paths.invalidate_tool_paths()
    assert tool_paths.get_tool_paths().ffmpeg == str(provider.folder / 'ffmpeg.exe')


def test_converter_bootstrap_after_media_library_lookup_with_real_qsettings(configured_tools, tmp_path, monkeypatch):
    QtCore = pytest.importorskip('PyQt6.QtCore')
    from dragontools.worker.converter_runtime_builder import ConverterRuntimeBuilder
    from dragontools.worker import converter_optional_runtime

    tools, provider = configured_tools
    settings = QtCore.QSettings(str(tmp_path / 'settings.ini'), QtCore.QSettings.Format.IniFormat)
    MediaLibraryDialogService.tool_paths(settings)
    monkeypatch.setattr(converter_optional_runtime, 'ffmpeg_has_libplacebo', lambda _path: False)
    monkeypatch.setattr(converter_optional_runtime, 'generator_executable_available', lambda _path: False)
    worker = SimpleNamespace(
        _job_state=SimpleNamespace(encoder_options={}, file_overrides={}),
        _services=SimpleNamespace(tools=None),
        _verbose_logger=SimpleNamespace(write=lambda _message: None),
        log_file_path=None,
        log=lambda *_args: None,
    )
    ConverterRuntimeBuilder(worker)._load_tools_and_write_debug_header()
    assert worker._services.tools is tools
    assert worker._services.tools.ffmpeg == str(provider.folder / 'ffmpeg.exe')
    assert worker._job_state.encoder_options['_sdr_hdr_libplacebo_available'] is False


def test_rejected_qsettings_registration_preserves_registered_provider(configured_tools, tmp_path):
    QtCore = pytest.importorskip('PyQt6.QtCore')
    tools, provider = configured_tools
    settings = QtCore.QSettings(str(tmp_path / 'settings.ini'), QtCore.QSettings.Format.IniFormat)
    with pytest.raises(TypeError, match='ToolPathSettingsProvider'):
        tool_paths.get_tool_paths(settings)
    assert tool_paths.get_tool_paths() is tools
    assert tool_paths._tool_paths_provider is provider
