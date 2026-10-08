"""Common worker ownership sources for application close and Windows restart."""
from types import SimpleNamespace

from .convert_override_lifecycle import active_override_loaders
from .media_info_dialog import active_media_info_workers
from .jellyfin_refresh_dispatch import active_jellyfin_workers
from ..worker.source_visual_thread import active_source_visual_workers
from .quality_worker_lifecycle import active_quality_workers


def application_worker_sources(window):
    widgets = getattr(window, "_tab_widgets", {}) or {}
    values = widgets.values() if hasattr(widgets, "values") else widgets
    sources = list(values)
    for provider in (active_override_loaders, active_media_info_workers,
                     active_source_visual_workers, active_jellyfin_workers, active_quality_workers):
        sources.append(SimpleNamespace(iter_shutdown_workers=provider))
    sources.append(SimpleNamespace(iter_shutdown_workers=lambda: (
        getattr(window, "_metadata_action_thread", None),
        getattr(window, "_move_journal_recovery_thread", None),
    )))
    controller = getattr(window, "_watch_folder_controller", None)
    if controller is not None:
        sources.append(controller)
    return sources
