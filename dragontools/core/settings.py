# -*- coding: utf-8 -*-
"""Backward-compatible settings facade.

The implementation is split by responsibility. New production code should
import from the dedicated ``settings_*`` modules; this module remains stable
for plugins, old call sites and external scripts.
"""
from __future__ import annotations

from .settings_app import *  # noqa: F401,F403
from .settings_access import *  # noqa: F401,F403
from .settings_storage import *  # noqa: F401,F403
from .settings_conversion import *  # noqa: F401,F403
from .settings_metadata import *  # noqa: F401,F403
from .settings_media_library import *  # noqa: F401,F403
from .settings_postprocess import *  # noqa: F401,F403
from .settings_jellyfin import *  # noqa: F401,F403
from .settings_watch import *  # noqa: F401,F403
from .settings_notifications import *  # noqa: F401,F403

# Explicit list keeps wildcard consumers deterministic and documents that this
# file is a compatibility surface, not the ownership location of settings.
__all__ = [name for name in globals() if not name.startswith("_")]
