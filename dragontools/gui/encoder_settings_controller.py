# -*- coding: utf-8 -*-
from __future__ import annotations

from .encoder_settings_options import EncoderSettingsOptionsMixin
from .encoder_settings_panels import EncoderSettingsPanelMixin
from .encoder_settings_persistence import EncoderSettingsPersistenceMixin
from .encoder_settings_profiles import EncoderSettingsProfilesMixin
from .encoder_settings_state import EncoderSettingsState
from .encoder_settings_ui import EncoderSettingsUI


class EncoderSettingsController(
    EncoderSettingsPanelMixin,
    EncoderSettingsOptionsMixin,
    EncoderSettingsPersistenceMixin,
    EncoderSettingsProfilesMixin,
):
    """Composition facade for encoder settings responsibilities.

    The public API remains stable; implementation is split into focused mixins
    for panel binding, option collection, persistence, and profile/default logic.
    """

    def __init__(
        self,
        *,
        default_codec: str,
        settings,
        state: EncoderSettingsState,
        ui: EncoderSettingsUI,
        profile_service,
        log,
        resolve_best_encoder,
    ) -> None:
        self._default_codec = default_codec
        self._settings = settings
        self._state = state
        self._ui = ui
        self._profile_service = profile_service
        self._log = log
        self._resolve_best_encoder = resolve_best_encoder
