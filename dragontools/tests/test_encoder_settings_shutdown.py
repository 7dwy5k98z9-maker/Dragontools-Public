from __future__ import annotations

import sys
import types
from types import SimpleNamespace


class _Signal:
    def connect(self, _callback):
        return None


class _Combo:
    def __init__(self, items=None, index: int = 0):
        self._items = list(items or [""])
        self._index = index
        self.currentIndexChanged = _Signal()
        self.currentTextChanged = _Signal()

    def currentIndex(self):
        return self._index

    def setCurrentIndex(self, value):
        self._index = int(value)

    def count(self):
        return len(self._items)

    def currentText(self):
        return self._items[self._index]

    def setCurrentText(self, value):
        idx = self.findText(value)
        if idx >= 0:
            self._index = idx

    def findText(self, value):
        try:
            return self._items.index(value)
        except ValueError:
            return -1


class _Spin:
    def __init__(self, value=0):
        self._value = value
        self.valueChanged = _Signal()

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value


class _Check:
    def __init__(self, checked=False):
        self._checked = bool(checked)
        self.toggled = _Signal()

    def isChecked(self):
        return self._checked

    def setChecked(self, value):
        self._checked = bool(value)


class _Panel:
    def __init__(self):
        self.visible = None
        self.collapsed = None

    def setVisible(self, value):
        self.visible = bool(value)
        return None

    def setCollapsed(self, value):
        self.collapsed = bool(value)
        return None


class _PersistedPanel(_Panel):
    def hasPersistedState(self):
        return True


class _Settings:
    def __init__(self):
        self.store = {}
        self.removed = []

    def value(self, key, default=None):
        return self.store.get(key, default)

    def setValue(self, key, value):
        self.store[key] = value

    def remove(self, key):
        self.removed.append(key)
        self.store.pop(key, None)

    def sync(self):
        return None


def _widgets():
    return SimpleNamespace(
        encoder_combo=_Combo(["cpu", "auto", "nvenc", "qsv", "amf"], index=2),
        scale_combo=_Combo(["original", "1080p"]),
        preset_combo=_Combo(["medium", "slow", "5", "6", "7"]),
        nv_preset=_Combo(["p6", "p7"]),
        nv_bref=_Combo(["middle"]),
        qsv_preset=_Combo(["medium"]),
        amf_qual=_Combo(["quality"]),
        x265_tune=_Combo(["none", "animation"]),
        x265_aqm=_Combo(["auto", "2"]),
        x265_preset=_Combo(["medium", "slow", "5", "6", "7"]),
        crf_spin=_Spin(23),
        nv_cq=_Spin(23),
        nv_bf=_Spin(4),
        nv_la=_Spin(32),
        nv_aq=_Spin(8),
        qsv_q=_Spin(23),
        qsv_la_depth=_Spin(32),
        amf_qp=_Spin(23),
        x265_bf=_Spin(4),
        x265_la=_Spin(32),
        x265_crf=_Spin(23),
        x265_aqs=_Spin(1.0),
        x265_psy=_Spin(2.0),
        x265_psyrdoq=_Spin(1.0),
        strip_cb=_Check(False),
        over_cb=_Check(False),
        move_cb=_Check(False),
        shut_cb=_Check(True),
        autocrop_cb=_Check(True),
        imax_detect_cb=_Check(False),
        preserve_dv_cb=_Check(True),
        preserve_hdrplus_cb=_Check(True),
        nv_spatial=_Check(True),
        nv_temporal=_Check(True),
        enc_grp=_Panel(),
        nvenc_p=_Panel(),
        qsv_p=_Panel(),
        amf_p=_Panel(),
        x265_p=_Panel(),
    )


def test_load_encoder_settings_does_not_reset_shutdown_checkbox(monkeypatch):
    fake_ui_module = types.ModuleType("dragontools.gui.encoder_settings_ui")
    fake_ui_module.EncoderSettingsUI = object
    monkeypatch.setitem(sys.modules, "dragontools.gui.encoder_settings_ui", fake_ui_module)

    from dragontools.gui.encoder_settings_controller import EncoderSettingsController
    from dragontools.gui.encoder_settings_state import EncoderSettingsState

    settings = _Settings()
    state = EncoderSettingsState()
    widgets = _widgets()
    controller = EncoderSettingsController(
        default_codec="h265",
        settings=settings,
        state=state,
        ui=SimpleNamespace(widgets=widgets),
        profile_service=SimpleNamespace(save_profile_dialog=lambda _payload: None),
        log=lambda *_args, **_kwargs: None,
        resolve_best_encoder=lambda: "nvenc",
    )

    controller.load_encoder_settings()

    assert widgets.shut_cb.isChecked() is True
    assert state.shutdown is True
    assert "encoder/h265/shutdown" not in settings.store


def test_cpu_encoder_panel_is_visible_for_h264_and_expanded(monkeypatch):
    fake_ui_module = types.ModuleType("dragontools.gui.encoder_settings_ui")
    fake_ui_module.EncoderSettingsUI = object
    monkeypatch.setitem(sys.modules, "dragontools.gui.encoder_settings_ui", fake_ui_module)

    from dragontools.gui.encoder_settings_controller import EncoderSettingsController
    from dragontools.gui.encoder_settings_state import EncoderSettingsState

    settings = _Settings()
    state = EncoderSettingsState()
    widgets = _widgets()
    widgets.encoder_combo.setCurrentIndex(0)  # CPU
    controller = EncoderSettingsController(
        default_codec="h264",
        settings=settings,
        state=state,
        ui=SimpleNamespace(widgets=widgets),
        profile_service=SimpleNamespace(save_profile_dialog=lambda _payload: None),
        log=lambda *_args, **_kwargs: None,
        resolve_best_encoder=lambda: "nvenc",
    )

    controller.refresh_enc_panel()

    assert widgets.enc_grp.visible is True
    assert widgets.enc_grp.collapsed is False
    assert widgets.x265_p.visible is True
    assert widgets.nvenc_p.visible is False
    assert state.encoder_options["encoder"] == "cpu"


def test_cpu_encoder_panel_does_not_override_persisted_collapsed_state(monkeypatch):
    fake_ui_module = types.ModuleType("dragontools.gui.encoder_settings_ui")
    fake_ui_module.EncoderSettingsUI = object
    monkeypatch.setitem(sys.modules, "dragontools.gui.encoder_settings_ui", fake_ui_module)

    from dragontools.gui.encoder_settings_controller import EncoderSettingsController
    from dragontools.gui.encoder_settings_state import EncoderSettingsState

    settings = _Settings()
    state = EncoderSettingsState()
    widgets = _widgets()
    widgets.encoder_combo.setCurrentIndex(0)  # CPU
    widgets.enc_grp = _PersistedPanel()
    controller = EncoderSettingsController(
        default_codec="h265",
        settings=settings,
        state=state,
        ui=SimpleNamespace(widgets=widgets),
        profile_service=SimpleNamespace(save_profile_dialog=lambda _payload: None),
        log=lambda *_args, **_kwargs: None,
        resolve_best_encoder=lambda: "nvenc",
    )

    controller.refresh_enc_panel()

    assert widgets.enc_grp.visible is True
    assert widgets.enc_grp.collapsed is None
    assert widgets.x265_p.visible is True
    assert state.encoder_options["encoder"] == "cpu"


def test_reset_defaults_resets_cpu_encoder_fields(monkeypatch):
    fake_ui_module = types.ModuleType("dragontools.gui.encoder_settings_ui")
    fake_ui_module.EncoderSettingsUI = object
    monkeypatch.setitem(sys.modules, "dragontools.gui.encoder_settings_ui", fake_ui_module)

    from dragontools.gui.encoder_settings_controller import EncoderSettingsController
    from dragontools.gui.encoder_settings_state import EncoderSettingsState

    settings = _Settings()
    state = EncoderSettingsState()
    widgets = _widgets()
    widgets.encoder_combo.setCurrentIndex(0)  # CPU
    widgets.x265_crf.setValue(31)
    widgets.x265_bf.setValue(2)
    widgets.x265_la.setValue(12)
    controller = EncoderSettingsController(
        default_codec="h265",
        settings=settings,
        state=state,
        ui=SimpleNamespace(widgets=widgets),
        profile_service=SimpleNamespace(save_profile_dialog=lambda _payload: None),
        log=lambda *_args, **_kwargs: None,
        resolve_best_encoder=lambda: "nvenc",
    )

    controller.reset_to_defaults()

    assert widgets.x265_crf.value() == 22
    assert widgets.x265_bf.value() == 8
    assert widgets.x265_la.value() == 40
    assert state.encoder_options["encoder"] == "cpu"
    assert settings.store["encoder/h265/crf"] == 22
    assert settings.store["encoder/h265/x265_crf"] == 22


def test_assistant_profile_applies_cpu_profile_and_saves(monkeypatch):
    fake_ui_module = types.ModuleType("dragontools.gui.encoder_settings_ui")
    fake_ui_module.EncoderSettingsUI = object
    monkeypatch.setitem(sys.modules, "dragontools.gui.encoder_settings_ui", fake_ui_module)

    from dragontools.core.codec_profile_assistant import profile_for_assistant_key
    from dragontools.gui.encoder_settings_controller import EncoderSettingsController
    from dragontools.gui.encoder_settings_state import EncoderSettingsState

    settings = _Settings()
    state = EncoderSettingsState()
    widgets = _widgets()
    service = SimpleNamespace(
        assistant_profile_dialog=lambda _codec: profile_for_assistant_key(
            "h265", "h265_anime_small_cpu"
        ),
        save_profile_dialog=lambda _payload: None,
    )
    controller = EncoderSettingsController(
        default_codec="h265",
        settings=settings,
        state=state,
        ui=SimpleNamespace(widgets=widgets),
        profile_service=service,
        log=lambda *_args, **_kwargs: None,
        resolve_best_encoder=lambda: "nvenc",
    )

    controller.apply_assistant_profile()

    assert widgets.encoder_combo.currentIndex() == 0
    assert widgets.x265_tune.currentText() == "animation"
    assert widgets.x265_crf.value() == 21
    assert widgets.x265_bf.value() == 10
    assert widgets.x265_la.value() == 60
    assert state.encoder_options["encoder"] == "cpu"
    assert state.encoder_options["tune"] == "animation"
    assert settings.store["encoder/h265/encoder_idx"] == 0
    assert settings.store["encoder/h265/x265_tune"] == "animation"


def test_av1_assistant_profile_applies_numeric_cpu_preset(monkeypatch):
    fake_ui_module = types.ModuleType("dragontools.gui.encoder_settings_ui")
    fake_ui_module.EncoderSettingsUI = object
    monkeypatch.setitem(sys.modules, "dragontools.gui.encoder_settings_ui", fake_ui_module)

    from dragontools.core.codec_profile_assistant import profile_for_assistant_key
    from dragontools.gui.encoder_settings_controller import EncoderSettingsController
    from dragontools.gui.encoder_settings_state import EncoderSettingsState

    settings = _Settings()
    state = EncoderSettingsState()
    widgets = _widgets()
    service = SimpleNamespace(
        assistant_profile_dialog=lambda _codec: profile_for_assistant_key(
            "av1", "av1_archive_quality"
        ),
        save_profile_dialog=lambda _payload: None,
    )
    controller = EncoderSettingsController(
        default_codec="av1",
        settings=settings,
        state=state,
        ui=SimpleNamespace(widgets=widgets),
        profile_service=service,
        log=lambda *_args, **_kwargs: None,
        resolve_best_encoder=lambda: "nvenc",
    )

    controller.apply_assistant_profile()

    assert widgets.encoder_combo.currentIndex() == 0
    assert widgets.crf_spin.value() == 24
    assert widgets.x265_crf.value() == 24
    assert widgets.preset_combo.currentText() == "5"
    assert widgets.x265_preset.currentText() == "5"
    assert state.preset == "5"
    assert state.encoder_options["encoder"] == "cpu"
    assert settings.store["encoder/av1/preset"] == "5"


def test_qsv_encoder_settings_no_longer_write_legacy_checkbox_key(monkeypatch):
    fake_ui_module = types.ModuleType("dragontools.gui.encoder_settings_ui")
    fake_ui_module.EncoderSettingsUI = object
    monkeypatch.setitem(sys.modules, "dragontools.gui.encoder_settings_ui", fake_ui_module)

    from dragontools.gui.encoder_settings_controller import EncoderSettingsController
    from dragontools.gui.encoder_settings_state import EncoderSettingsState

    settings = _Settings()
    settings.store["encoder/h265/qsv_la"] = False
    state = EncoderSettingsState()
    widgets = _widgets()
    widgets.encoder_combo.setCurrentIndex(3)  # QSV
    controller = EncoderSettingsController(
        default_codec="h265",
        settings=settings,
        state=state,
        ui=SimpleNamespace(widgets=widgets),
        profile_service=SimpleNamespace(save_profile_dialog=lambda _payload: None),
        log=lambda *_args, **_kwargs: None,
        resolve_best_encoder=lambda: "nvenc",
    )

    controller.save_encoder_settings()

    assert "encoder/h265/qsv_la" not in settings.store
    assert "encoder/h265/qsv_la" in settings.removed
    assert "lookahead" not in state.encoder_options
    assert state.encoder_options["lookahead_depth"] == widgets.qsv_la_depth.value()
