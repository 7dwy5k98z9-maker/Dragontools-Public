# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import QFrame


def _hr() -> QFrame:
    f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("color:#c0c0c0;"); return f

# ===========================================================================
# TAB 1: Serien-Erkennung
# ===========================================================================
