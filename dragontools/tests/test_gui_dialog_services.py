from __future__ import annotations

import sys
import types
from types import SimpleNamespace


class _QtObject:
    def __init__(self, *args, **kwargs) -> None:
        self.clicked = _Signal()
        self.toggled = _Signal()

    def __getattr__(self, _name):
        return _QtObject()

    def __call__(self, *args, **kwargs):
        return _QtObject()


class _Signal:
    def __init__(self) -> None:
        self.slots = []

    def connect(self, slot) -> None:
        self.slots.append(slot)


class _Spin:
    def __init__(self, value: int) -> None:
        self._value = value

    def value(self) -> int:
        return self._value


class _Check:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


def _install_pyqt_stubs(monkeypatch) -> types.ModuleType:
    pyqt6 = types.ModuleType("PyQt6")
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtgui = types.ModuleType("PyQt6.QtGui")
    qtwidgets = types.ModuleType("PyQt6.QtWidgets")

    qtcore.QSettings = _QtObject
    qtcore.Qt = SimpleNamespace(
        AlignmentFlag=SimpleNamespace(AlignRight=1),
    )
    qtgui.QFont = _QtObject

    qtwidgets.QFrame = type(
        "QFrame",
        (_QtObject,),
        {
            "Shape": SimpleNamespace(HLine=1, NoFrame=2),
            "Shadow": SimpleNamespace(Sunken=1),
        },
    )
    qtwidgets.QSizePolicy = SimpleNamespace(
        Policy=SimpleNamespace(Expanding=1, Preferred=2)
    )
    qtwidgets.QDialogButtonBox = type(
        "QDialogButtonBox",
        (_QtObject,),
        {
            "StandardButton": SimpleNamespace(Ok=1, Cancel=2),
        },
    )
    qtwidgets.QMessageBox = type(
        "QMessageBox",
        (_QtObject,),
        {
            "StandardButton": SimpleNamespace(Yes=1, No=2),
            "question": staticmethod(lambda *args, **kwargs: 2),
            "information": staticmethod(lambda *args, **kwargs: None),
        },
    )
    qtwidgets.QToolTip = SimpleNamespace(showText=lambda *args, **kwargs: None)

    for name in [
        "QDialog",
        "QVBoxLayout",
        "QHBoxLayout",
        "QGridLayout",
        "QGroupBox",
        "QLabel",
        "QListWidget",
        "QSpinBox",
        "QPushButton",
        "QScrollArea",
        "QWidget",
        "QCheckBox",
    ]:
        setattr(qtwidgets, name, _QtObject)

    monkeypatch.setitem(sys.modules, "PyQt6", pyqt6)
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", qtcore)
    monkeypatch.setitem(sys.modules, "PyQt6.QtGui", qtgui)
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", qtwidgets)
    return qtwidgets


def test_timeout_dialog_saves_minutes_and_enabled_state(monkeypatch):
    _install_pyqt_stubs(monkeypatch)

    from dragontools.core.timeout_settings import TimeoutDef
    import dragontools.gui.timeout_settings_dialog as module

    timeout_def = TimeoutDef(
        key="encoder_general",
        label="Allgemeiner Encoder-Timeout",
        default_s=300,
        category="Encoder",
        description="Test",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(module, "TIMEOUT_DEFS", [timeout_def])
    monkeypatch.setattr(
        module,
        "save_all_timeouts",
        lambda values, enabled: captured.update(values=values, enabled=enabled),
    )

    dlg = SimpleNamespace(
        _spinboxes={"encoder_general": _Spin(7)},
        _enabled_cbs={"encoder_general": _Check(False)},
        accept=lambda: captured.update(accepted=True),
    )

    module.TimeoutSettingsDialog._save_and_accept(dlg)

    assert captured["values"] == {"encoder_general": 420}
    assert captured["enabled"] == {"encoder_general": False}
    assert captured["accepted"] is True


def test_encoder_profile_service_returns_selected_assistant_profile(monkeypatch):
    qtwidgets = _install_pyqt_stubs(monkeypatch)
    captured: dict[str, object] = {}

    class _InputDialog:
        @staticmethod
        def getItem(parent, title, prompt, items, editable=False):
            captured["parent"] = parent
            captured["title"] = title
            captured["prompt"] = prompt
            captured["items"] = items
            captured["editable"] = editable
            return items[0], True

    qtwidgets.QInputDialog = _InputDialog

    from dragontools.gui.encoder_profile_service import EncoderProfileService

    logs: list[str] = []
    service = EncoderProfileService(
        profile_manager=SimpleNamespace(),
        parent_widget="parent",
        log=lambda text, *args, **kwargs: logs.append(text),
    )

    profile = service.assistant_profile_dialog("h265")

    assert profile is not None
    assert profile["label"] == "Anime Serie klein OK CPU"
    assert profile["_assistant_key"] == "h265_anime_series_small_cpu"
    assert captured["title"] == "Profil-Assistent"
    assert captured["editable"] is False
    assert "Anime Serie klein OK CPU" in captured["items"][0]
    assert any("Profil-Assistent" in entry for entry in logs)


def test_encoder_profile_service_allows_same_label_for_different_encoders(monkeypatch, tmp_path):
    qtwidgets = _install_pyqt_stubs(monkeypatch)

    class _InputDialog:
        @staticmethod
        def getItem(parent, title, prompt, items, editable=False):
            return "Allgemein", True

    qtwidgets.QInputDialog = _InputDialog

    from dragontools.core.profile_manager import ProfileManager
    from dragontools.gui.encoder_profile_service import EncoderProfileService

    manager = ProfileManager(tmp_path / "h265_profiles.json")
    service = EncoderProfileService(
        profile_manager=manager,
        parent_widget="parent",
        log=lambda *_args, **_kwargs: None,
    )

    service.save_profile_dialog({
        "codec": "h265",
        "crf": 23,
        "preset": "medium",
        "scale": "original",
        "encoder_options": {"encoder": "cpu"},
    })
    service.save_profile_dialog({
        "codec": "h265",
        "crf": 23,
        "preset": "p6",
        "scale": "original",
        "encoder_options": {"encoder": "nvenc"},
    })

    user_profiles = {
        key: value for key, value in manager.data.items()
        if not manager.is_builtin(key)
    }
    assert len(user_profiles) == 2
    assert {value["label"] for value in user_profiles.values()} == {"Allgemein"}
    assert {
        value["encoder_options"]["encoder"] for value in user_profiles.values()
    } == {"cpu", "nvenc"}


def test_profile_manager_same_label_same_encoder_reuses_existing_key(tmp_path):
    from dragontools.core.profile_manager import ProfileManager

    manager = ProfileManager(tmp_path / "h265_profiles.json")
    first_payload = {
        "label": "Allgemein",
        "codec": "h265",
        "crf": 23,
        "preset": "medium",
        "scale": "original",
        "encoder_options": {"encoder": "cpu"},
    }
    first_key = manager.key_for_user_label("Allgemein", first_payload)
    manager.set(first_key, first_payload)

    second_payload = dict(first_payload, crf=21)
    second_key = manager.key_for_user_label("Allgemein", second_payload)
    manager.set(second_key, second_payload)

    user_keys = [key for key in manager.data if not manager.is_builtin(key)]
    assert user_keys == [first_key]
    assert manager.get(first_key)["crf"] == 21


def test_profile_manager_contains_extended_h265_start_profiles(tmp_path):
    from dragontools.core.profile_manager import ProfileManager

    manager = ProfileManager(tmp_path / "h265_profiles.json")
    data = manager.data

    assert "h265_anime_series_small_cpu" in data
    assert "h265_tv_4k_medium_nvenc" in data
    assert data["h265_anime_series_small_cpu"]["encoder_options"]["bf"] == 10
