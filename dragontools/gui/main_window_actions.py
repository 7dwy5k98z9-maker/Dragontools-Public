# -*- coding: utf-8 -*-
"""Aggregations-Fassade für die fachlich getrennten MainWindow-Aktionen.

Die konkrete GUI-Aktionslogik lebt in fokussierten Mixins. ``MainWindow`` erbt
eine einzige klar benannte Sammelgrenze, ohne dass hier erneut
eine Sammelklasse mit hunderten Zeilen entsteht.
"""
from __future__ import annotations

from .main_window_backup_actions import MainWindowBackupActionsMixin
from .main_window_convert_actions import MainWindowConvertActionsMixin
from .main_window_help_actions import MainWindowHelpActionsMixin
from .main_window_metadata_actions import MainWindowMetadataActionsMixin
from .main_window_profile_actions import MainWindowProfileActionsMixin
from .main_window_settings_actions import MainWindowSettingsActionsMixin
from .main_window_system_actions import MainWindowSystemActionsMixin


class MainWindowActionsMixin(
    MainWindowConvertActionsMixin,
    MainWindowBackupActionsMixin,
    MainWindowSettingsActionsMixin,
    MainWindowMetadataActionsMixin,
    MainWindowHelpActionsMixin,
    MainWindowSystemActionsMixin,
    MainWindowProfileActionsMixin,
):
    """Stabile Sammel-Fassade ohne eigene Fachlogik."""

    pass
