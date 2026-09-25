from pathlib import Path

from dragontools.gui.convert_widget_override_apply import merge_dialog_override


ROOT = Path(__file__).resolve().parents[1]


def test_batch_file_settings_copy_dialog_fields_but_preserve_non_dialog_state():
    existing = {
        "encoder_profile": {"key": "anime", "label": "Anime"},
        "future_queue_flag": "keep-me",
        "processing_mode": "strip_only",
        "audio_mode": "custom",
        "audio_tracks": [{"index": 1, "mode": "drop"}],
    }
    template = {
        "audio_mode": "auto",
        "subtitle_mode": "auto",
        "imax": True,
        "sdr_hdr": True,
        "generate_hdr10plus": False,
    }

    result = merge_dialog_override(existing, template)

    assert result["encoder_profile"] == existing["encoder_profile"]
    assert result["future_queue_flag"] == "keep-me"
    assert result["audio_mode"] == "auto"
    assert result["subtitle_mode"] == "auto"
    assert result["imax"] is True
    assert result["sdr_hdr"] is True
    assert result["generate_hdr10plus"] is False
    assert "processing_mode" not in result
    assert "audio_tracks" not in result


def test_batch_file_settings_deepcopy_track_lists():
    template = {
        "audio_mode": "custom",
        "audio_tracks": [{"index": 1, "mode": "custom", "codec": "eac3"}],
    }
    result = merge_dialog_override({}, template)
    result["audio_tracks"][0]["codec"] = "aac"
    assert template["audio_tracks"][0]["codec"] == "eac3"


def test_context_menu_and_dialog_are_wired_for_multi_selection():
    context = (ROOT / "gui" / "convert_widget_queue_context_actions.py").read_text(encoding="utf-8")
    dialog = (ROOT / "gui" / "convert_widget_override_dialog.py").read_text(encoding="utf-8")
    target = (ROOT / "gui" / "convert_widget_queue_target_actions.py").read_text(encoding="utf-8")

    assert "Datei-Einstellungen für Auswahl" in context
    assert "lambda paths=tuple(selected_paths): self._edit_override(paths)" in context
    assert "for path in paths:" in dialog
    assert "merge_dialog_override(state.file_overrides.get(path), ov)" in dialog
    assert "[clicked_path, *[path for path in selected if path != clicked_path]]" in target
