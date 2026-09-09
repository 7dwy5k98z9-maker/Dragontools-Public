from __future__ import annotations

import json
import re
from pathlib import Path


def _fs(b):
    for u in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {u}"
        b //= 1024
    return f"{b:.1f} TB"


def _fd(s):
    s = int(s)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _parse_crop(crop_filter: str | None):
    """'crop=W:H:X:Y' → (w,h,x,y) oder None."""
    if not crop_filter:
        return None
    m = re.match(r"crop=(\d+):(\d+):(\d+):(\d+)", crop_filter.strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))) if m else None


def _level5_json(src_w, src_h, cw, ch, cx, cy, path: Path) -> dict:
    """
    Erstellt eine dovi_tool-editor JSON im active_area-Format,
    passend zu der funktionierenden manuellen Crop-JSON.

    Beispiel:
    {
      "active_area": {
        "presets": [
          {
            "id": 0,
            "left": 0,
            "right": 0,
            "top": 276,
            "bottom": 276
          }
        ],
        "edits": {
          "all": 0
        }
      }
    }
    """

    def even(v: int) -> int:
        return max(0, (int(v) // 2) * 2)

    left = even(cx)
    right = even(src_w - cw - cx)
    top = even(cy)
    bottom = even(src_h - ch - cy)

    edit_json = {
        "active_area": {
            "presets": [
                {
                    "id": 0,
                    "left": left,
                    "right": right,
                    "top": top,
                    "bottom": bottom,
                }
            ],
            "edits": {
                "all": 0
            }
        }
    }

    path.write_text(json.dumps(edit_json, indent=2), encoding="utf-8")

    return {
        "active_area_left_offset": left,
        "active_area_right_offset": right,
        "active_area_top_offset": top,
        "active_area_bottom_offset": bottom,
    }


