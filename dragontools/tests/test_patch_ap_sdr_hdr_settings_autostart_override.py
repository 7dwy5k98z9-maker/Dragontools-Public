from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dragontools.core.models import normalize_override_dict
from dragontools.core.encoder_profile_override import effective_encoder_settings
import dragontools.worker.comfyui_runtime as comfy_runtime
import dragontools.worker.converter_optional_runtime as optional_runtime


def test_sdr_hdr_file_override_is_tristate_and_normalized():
    assert normalize_override_dict({})["sdr_hdr"] is None
    assert normalize_override_dict({"sdr_hdr": True})["sdr_hdr"] is True
    assert normalize_override_dict({"sdr_hdr": False})["sdr_hdr"] is False
    assert normalize_override_dict({"sdr_hdr": "true"})["sdr_hdr"] is True


def test_file_override_can_enable_or_disable_sdr_hdr_without_mutating_global_options():
    def merged(global_enabled: bool, override_value):
        base = {"sdr_hdr_enabled": global_enabled, "sdr_hdr_backend": "comfyui"}
        result = effective_encoder_settings(
            default_codec="h265",
            default_crf=23,
            default_preset="p6",
            default_scale_mode="original",
            default_encoder_options=base,
            file_override={"sdr_hdr": override_value},
        )
        return base, result["encoder_options"]

    base, enabled = merged(False, True)
    _, disabled = merged(True, False)
    _, inherited = merged(False, None)

    assert base["sdr_hdr_enabled"] is False
    assert enabled["sdr_hdr_enabled"] is True
    assert disabled["sdr_hdr_enabled"] is False
    assert inherited["sdr_hdr_enabled"] is False


def test_portable_main_py_discovers_run_nvidia_gpu_launcher(tmp_path: Path):
    portable = tmp_path / "ComfyUI_windows_portable"
    comfy_dir = portable / "ComfyUI"
    comfy_dir.mkdir(parents=True)
    main_py = comfy_dir / "main.py"
    main_py.write_text("# marker\n", encoding="utf-8")
    launcher = portable / "run_nvidia_gpu.bat"
    launcher.write_text("@echo off\n", encoding="utf-8")

    tools = SimpleNamespace(comfyui=str(main_py))
    resolved = comfy_runtime._resolve_comfyui_launcher(tools, {})
    assert resolved == launcher.resolve()


def test_explicit_comfyui_launcher_wins_and_main_py_is_not_accepted_as_start_file(tmp_path: Path):
    launcher = tmp_path / "start comfy.bat"
    launcher.write_text("@echo off\n", encoding="utf-8")
    tools = SimpleNamespace(comfyui="")
    assert comfy_runtime._resolve_comfyui_launcher(
        tools, {"comfyui_start_file": str(launcher)}
    ) == launcher.resolve()

    main_py = tmp_path / "main.py"
    main_py.write_text("# not a self-contained launcher\n", encoding="utf-8")
    assert comfy_runtime._resolve_comfyui_launcher(
        tools, {"comfyui_start_file": str(main_py)}
    ) is None


def test_comfyui_autostart_launches_once_and_polls_until_api_ready(tmp_path: Path, monkeypatch):
    launcher = tmp_path / "run_nvidia_gpu.bat"
    launcher.write_text("@echo off\n", encoding="utf-8")
    tools = SimpleNamespace(comfyui="")
    options = {
        "comfyui_start_file": str(launcher),
        "comfyui_start_wait_seconds": 30,
    }
    logs: list[tuple[str, str]] = []
    worker = SimpleNamespace(abort_requested=False, log=lambda msg, level="info": logs.append((msg, level)))

    down = SimpleNamespace(success=False, version="", device="", vram_total=None)
    up = SimpleNamespace(success=True, version="0.37.0", device="RTX 4080 SUPER", vram_total=16 * 1024**3)

    class Client:
        def __init__(self):
            self.calls = 0

        def health(self):
            self.calls += 1
            return down if self.calls == 1 else up

    launched: list[Path] = []
    monkeypatch.setattr(comfy_runtime, "_launch_file", lambda path: launched.append(path))
    monkeypatch.setattr(comfy_runtime.time, "sleep", lambda _seconds: None)
    comfy_runtime._COMFYUI_START_ATTEMPTS.clear()

    health = comfy_runtime._auto_start_and_wait(
        worker, tools, options, Client(), initial_health=down
    )
    assert health.success is True
    assert launched == [launcher.resolve()]
    assert any("Starte 'run_nvidia_gpu.bat'" in msg for msg, _ in logs)
    assert any("API nach" in msg for msg, _ in logs)


def test_per_file_sdr_hdr_request_initializes_comfyui_even_when_global_switch_is_off(monkeypatch):
    calls: list[dict] = []
    worker = SimpleNamespace(
        _job_state=SimpleNamespace(
            encoder_options={
                "sdr_hdr_enabled": False,
                "sdr_hdr_backend": "comfyui",
                "hdr10plus_generator_enabled": False,
            },
            file_overrides={"D:/one.mkv": {"sdr_hdr": True}},
        ),
        log=lambda *_args, **_kwargs: None,
    )
    tools = SimpleNamespace(ffmpeg="ffmpeg", davinci_resolve="Resolve.exe", hdr10plus_generator="HDRPlusGenerator.exe")

    monkeypatch.setattr(optional_runtime, "ffmpeg_has_libplacebo", lambda _path: True)
    monkeypatch.setattr(optional_runtime, "generator_executable_available", lambda _path: False)
    monkeypatch.setattr(optional_runtime, "_configure_hdr10plus_generator", lambda *_args: None)
    monkeypatch.setattr(
        optional_runtime,
        "configure_comfyui_runtime",
        lambda _worker, _tools, options: calls.append(dict(options)),
    )

    optional_runtime.configure_optional_runtime_features(worker, tools)
    assert len(calls) == 1
    assert calls[0]["sdr_hdr_enabled"] is False
    assert calls[0]["sdr_hdr_backend"] == "comfyui"


def test_settings_menu_exposes_direct_sdr_hdr_entry():
    root = Path(__file__).resolve().parents[2]
    menu = (root / "dragontools" / "gui" / "main_window_menus.py").read_text(encoding="utf-8")
    actions = (root / "dragontools" / "gui" / "main_window_settings_actions.py").read_text(encoding="utf-8")
    assert "SDR → HDR / ComfyUI" in menu
    assert "triggered=self._open_settings_sdr_hdr" in menu
    assert 'visible_sections=("sdr_hdr",)' in actions


def test_settings_menu_exposes_direct_hdr10plus_generator_entry():
    root = Path(__file__).resolve().parents[2]
    menu = (root / "dragontools" / "gui" / "main_window_menus.py").read_text(encoding="utf-8")
    actions = (root / "dragontools" / "gui" / "main_window_settings_actions.py").read_text(encoding="utf-8")
    help_html = (root / "help.html").read_text(encoding="utf-8")
    assert "Dragon HDR10+ Generator" in menu
    assert "triggered=self._open_settings_hdr10plus_generator" in menu
    assert 'visible_sections=("hdr10plus_generator",)' in actions
    assert 'id="sdrhdrcomfyui"' in help_html
    assert 'id="hdr10plusgenerator"' in help_html
    assert 'id="hdroverrides"' in help_html
    assert 'href="#sdrhdrcomfyui"' in help_html
    assert 'href="#hdr10plusgenerator"' in help_html
    assert 'href="#hdroverrides"' in help_html
    assert '>66.</span>ℹ️ Über Dragon Tools</h2>' in help_html
