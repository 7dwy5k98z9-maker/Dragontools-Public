# -*- coding: utf-8 -*-
"""Zentrale Versionsdefinition fuer Dragon Tools.

Dieses Modul ist absichtlich frei von Qt- und Runtime-Abhaengigkeiten, damit
Einstiegspunkt, Builder, Release-Validator und GUI dieselbe Versionsquelle
verwenden koennen, ohne Seiteneffekte zu importieren.
"""
from __future__ import annotations

APP_VERSION = "9.8"
APP_VERSION_MAJOR = 9
APP_VERSION_LABEL = f"V{APP_VERSION}"
APP_BUILD_NAME = f"DragonToolsV{APP_VERSION}"
