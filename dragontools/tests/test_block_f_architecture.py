from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_move_preflight_uses_existing_shared_ui_helper():
    path = ROOT / "dragontools" / "gui" / "move_preflight_controller.py"
    source = path.read_text(encoding="utf-8")
    assert "from .file_list_utils import set_file_list_item_text" not in source
    assert "from .ui_helpers import set_file_list_item_text" in source
