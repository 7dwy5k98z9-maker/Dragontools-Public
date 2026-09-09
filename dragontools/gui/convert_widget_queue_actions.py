# -*- coding: utf-8 -*-
"""Aggregation facade for ConvertWidget queue-related GUI actions.

The previous 600+ line mixin mixed drag/drop handling, queue-window state,
context diagnostics, per-file overrides, badge presentation and manual source
visual checks.  The public/private method surface remains available through
multiple focused mixins while this module stays the stable import location.
"""
from __future__ import annotations

from .convert_widget_queue_dragdrop import ConvertWidgetQueueDragDropMixin
from .convert_widget_queue_management import ConvertWidgetQueueManagementMixin
from .convert_widget_queue_window_actions import ConvertWidgetQueueWindowActionsMixin
from .convert_widget_queue_context_actions import ConvertWidgetQueueContextActionsMixin
from .convert_widget_queue_override_actions import ConvertWidgetQueueOverrideActionsMixin
from .convert_widget_queue_badges import ConvertWidgetQueueBadgesMixin
from .convert_widget_source_visual_actions import ConvertWidgetSourceVisualActionsMixin


class ConvertWidgetQueueActionsMixin(
    ConvertWidgetQueueDragDropMixin,
    ConvertWidgetQueueManagementMixin,
    ConvertWidgetQueueWindowActionsMixin,
    ConvertWidgetQueueContextActionsMixin,
    ConvertWidgetQueueOverrideActionsMixin,
    ConvertWidgetQueueBadgesMixin,
    ConvertWidgetSourceVisualActionsMixin,
):
    """Stable aggregation facade; behavior lives in focused mixins."""

    pass
