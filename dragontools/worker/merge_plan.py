"""Kompatibilitätsprüfung und Planerstellung für lossless Merge."""
from __future__ import annotations

from typing import Any

from .merge_common import container_from_path


class MergePlanMixin:
    """Entscheidet rein anhand der Analyse, ob der Merge verlustfrei zulässig ist."""

    def _check_lossless_merge_possible(
        self,
        infos: list[dict[str, Any]],
        target_container: str,
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if len(infos) < 2:
            return False, ["Mindestens zwei Eingaben erforderlich."]
        if target_container != "mkv":
            return False, [
                f"Zielcontainer '.{target_container}' wird für Merge nicht unterstützt."
            ]

        containers = {str(info["container"]).lower() for info in infos}
        if containers != {"mkv"}:
            reasons.append("Lossless MKV-Merge erlaubt nur reine MKV-Eingaben.")

        first = infos[0]
        if any(info["video_codec"] != first["video_codec"] for info in infos[1:]):
            reasons.append("Videocodec ist nicht in allen Dateien identisch.")

        first_size = (first["width"], first["height"])
        if any(
            (info["width"], info["height"]) != first_size for info in infos[1:]
        ):
            reasons.append("Auflösung ist nicht in allen Dateien identisch.")

        comparisons = (
            ("fps", "FPS ist nicht in allen Dateien identisch."),
            ("audio_structure", "Audio-Struktur ist nicht in allen Dateien identisch."),
            (
                "subtitle_structure",
                "Untertitel-Struktur ist nicht in allen Dateien identisch.",
            ),
        )
        for key, message in comparisons:
            if any(info[key] != first[key] for info in infos[1:]):
                reasons.append(message)

        return not reasons, reasons

    def _build_merge_plan(
        self,
        infos: list[dict[str, Any]],
        output_path: str,
        mode: str,
    ) -> dict[str, Any]:
        target_container = container_from_path(output_path)
        lossless_possible, reasons = self._check_lossless_merge_possible(
            infos,
            target_container,
        )
        return {
            "mode": mode,
            "target_container": target_container,
            "tool": "mkvmerge",
            "lossless_possible": lossless_possible,
            "reasons": reasons,
            "infos": infos,
            "files": [info["path"] for info in infos],
            "output_path": output_path,
        }
