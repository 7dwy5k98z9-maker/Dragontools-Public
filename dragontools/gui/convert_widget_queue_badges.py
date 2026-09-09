# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtCore import Qt

from ..core.models import normalize_override_dict
from ..core.encoder_profile_override import MODE_TO_SCALE_LABEL, normalize_encoder_override
from ..core.paths import display_name
from ..core.settings import (
    DEFAULT_NFO_ENABLED,
    DEFAULT_TRICKPLAY_ENABLED,
    SET_KEY_NFO_ENABLED,
    SET_KEY_TRICKPLAY_ENABLED,
)


class ConvertWidgetQueueBadgesMixin:

    def update_queue_label(self, path: str) -> None:
        for i in range(self._ui.file_list.count()):
            item = self._ui.file_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                item.setText(self._override_label_text(path))
                break
        self._refresh_queue_window()

    def _override_label_tags(self, path: str) -> list[str]:
        ov   = normalize_override_dict(self._state.file_overrides.get(path, {}))
        tags = self._processing_badges(path, ov)
        if ov.get("audio_mode") == "custom":
            tags.append(f"Audio:{ov.get('audio_mode')}")
        if ov.get("subtitle_mode") == "custom":
            tags.append(f"Sub:{ov.get('subtitle_mode')}")
        if ov.get("imax"):
            tags.append("IMAX")
        if ov.get("allow_suspicious_source"):
            tags.append("Quellbild erlaubt")
        profile = ov.get("encoder_profile")
        if isinstance(profile, dict):
            label = profile.get("label") or profile.get("key") or "Profil"
            tags.append(f"Profil:{label}")
        manual = normalize_encoder_override(
            ov.get("encoder_override"),
            default_codec=getattr(self, "default_codec", "h265"),
        )
        if manual:
            encoder = manual["encoder"].upper()
            q_label = {"cpu": "CRF", "nvenc": "CQ", "qsv": "Q", "amf": "QP"}[manual["encoder"]]
            scale = MODE_TO_SCALE_LABEL.get(manual["scale_mode"], manual["scale_mode"])
            tags.append(f"Encoder:{encoder} {q_label}{manual.get('quality', '-')} {scale}")
        return tags

    def _processing_badges(self, path: str, ov: dict | None = None) -> list[str]:
        ov = normalize_override_dict(ov or self._state.file_overrides.get(path, {}))
        if ov.get("processing_mode") == "strip_only":
            badges = ["Verarbeitung: Strip-Only"]
        else:
            preview = self._cached_preflight_preview(path)
            badges = [f"Encode: {self._encode_badge_label(preview)}"]
        postprocess_parts = self._postprocess_badge_parts()
        if postprocess_parts:
            badges.append(f"Postprocessing: {' + '.join(postprocess_parts)}")
        return badges

    def _encode_badge_label(self, preview: dict) -> str:
        pipeline = str(getattr(preview.get("pipeline"), "value", preview.get("pipeline") or "")).lower()
        video = dict(preview.get("video") or {})
        preserves_dv = (
            pipeline in {"dv", "av1_dv"}
            or bool(preview.get("dv_preserved"))
            or bool(video.get("has_dv") and preview.get("effective_preserve_dv"))
        )
        preserves_hdr10plus = (
            pipeline in {"hdrplus", "av1_hdrplus"}
            or bool(preview.get("hdr10plus_preserved"))
            or bool(video.get("has_hdr10plus") and preview.get("effective_preserve_hdrplus"))
        )
        if preserves_dv and preserves_hdr10plus:
            return "DV + HDR10+"
        if preserves_dv:
            return "DV"
        if preserves_hdr10plus:
            return "HDR10+"
        return "Standard"

    def _cached_preflight_preview(self, path: str) -> dict:
        rows = getattr(self._state, "preflight_rows_by_path", {}) or {}
        row = rows.get(path) or rows.get(str(path)) or {}
        preview = row.get("preview") if isinstance(row, dict) else {}
        return dict(preview or {})

    def _postprocess_enabled_for_badge(self) -> bool:
        return bool(self._postprocess_badge_parts())

    def _postprocess_badge_parts(self) -> list[str]:
        settings = getattr(self, "settings", None)
        if settings is None:
            return []
        try:
            nfo = settings.value(SET_KEY_NFO_ENABLED, DEFAULT_NFO_ENABLED, type=bool)
            trickplay = settings.value(
                SET_KEY_TRICKPLAY_ENABLED,
                DEFAULT_TRICKPLAY_ENABLED,
                type=bool,
            )
            parts: list[str] = []
            if nfo:
                parts.append("NFO")
            if trickplay:
                parts.append("Trickplay")
            return parts
        except Exception:
            return []

    def _override_label_text(self, path: str) -> str:
        tags = self._override_label_tags(path)
        return display_name(path) + (f"  [{', '.join(tags)}]" if tags else "")

    def _set_file_list_item_text(self, path: str, text: str) -> None:
        from .ui_helpers import set_file_list_item_text
        set_file_list_item_text(self._ui.file_list, path, text)
