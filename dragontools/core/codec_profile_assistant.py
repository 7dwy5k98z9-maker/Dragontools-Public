# -*- coding: utf-8 -*-
"""Empfohlene Startprofile für den Codec-Profil-Assistenten."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CodecProfileSuggestion:
    key: str
    label: str
    description: str
    profile: dict[str, Any]


def _cpu_h265(
    *,
    key: str,
    label: str,
    description: str,
    crf: int,
    preset: str,
    tune: str = "none",
    lookahead: int = 40,
    bframes: int = 8,
) -> CodecProfileSuggestion:
    return CodecProfileSuggestion(
        key=key,
        label=label,
        description=description,
        profile={
            "label": label,
            "codec": "h265",
            "crf": crf,
            "preset": preset,
            "scale": "original",
            "encoder_options": {
                "encoder": "cpu",
                "tune": tune,
                "aq_mode": "2",
                "aq_strength": "1.0",
                "psy_rd": "2.0",
                "psy_rdoq": "1.0",
                "bf": bframes,
                "rc_lookahead": lookahead,
            },
        },
    )


def _nvenc(
    *,
    codec: str,
    key: str,
    label: str,
    description: str,
    cq: int,
    preset: str = "p6",
    bframes: int = 4,
    lookahead: int = 32,
) -> CodecProfileSuggestion:
    return CodecProfileSuggestion(
        key=key,
        label=label,
        description=description,
        profile={
            "label": label,
            "codec": codec,
            "crf": cq,
            "preset": "medium",
            "scale": "original",
            "encoder_options": {
                "encoder": "nvenc",
                "preset": preset,
                "cq": cq,
                "bf": bframes,
                "bref_mode": "middle",
                "rc_lookahead": lookahead,
                "lookahead_level": "auto",
                "multipass": "auto",
                "aq_strength": 8,
                "spatial_aq": True,
                "temporal_aq": True,
            },
        },
    )


def _cpu_simple(
    *,
    codec: str,
    key: str,
    label: str,
    description: str,
    crf: int,
    preset: str,
    tune: str = "none",
) -> CodecProfileSuggestion:
    options: dict[str, Any] = {"encoder": "cpu"}
    if codec == "h265":
        options.update(
            {
                "tune": tune,
                "aq_mode": "2",
                "aq_strength": "1.0",
                "psy_rd": "2.0",
                "psy_rdoq": "1.0",
                "bf": 8,
                "rc_lookahead": 40,
            }
        )
    return CodecProfileSuggestion(
        key=key,
        label=label,
        description=description,
        profile={
            "label": label,
            "codec": codec,
            "crf": crf,
            "preset": preset,
            "scale": "original",
            "encoder_options": options,
        },
    )


def _h265_start_profile_set(
    *,
    key_base: str,
    label_base: str,
    tune: str,
    cpu_small_crf: int,
    cpu_medium_crf: int,
    nvenc_small_cq: int,
    nvenc_medium_cq: int,
    lookahead: int = 40,
    bframes: int = 8,
    nvenc_lookahead: int = 32,
) -> list[CodecProfileSuggestion]:
    return [
        _cpu_h265(
            key=f"h265_{key_base}_small_cpu",
            label=f"{label_base} klein OK CPU",
            description=f"CPU/x265, CRF {cpu_small_crf}, medium - kleinere Datei, Qualität OK",
            crf=cpu_small_crf,
            preset="medium",
            tune=tune,
            lookahead=lookahead,
            bframes=bframes,
        ),
        _cpu_h265(
            key=f"h265_{key_base}_medium_cpu",
            label=f"{label_base} mittel gut CPU",
            description=f"CPU/x265, CRF {cpu_medium_crf}, medium - bessere Qualität, langsamer",
            crf=cpu_medium_crf,
            preset="medium",
            tune=tune,
            lookahead=lookahead,
            bframes=bframes,
        ),
        _nvenc(
            codec="h265",
            key=f"h265_{key_base}_small_nvenc",
            label=f"{label_base} klein OK NVENC",
            description=f"GPU/NVENC, CQ {nvenc_small_cq}, p6 - schnell, kleinere Datei",
            cq=nvenc_small_cq,
            preset="p6",
            bframes=4,
            lookahead=nvenc_lookahead,
        ),
        _nvenc(
            codec="h265",
            key=f"h265_{key_base}_medium_nvenc",
            label=f"{label_base} mittel gut NVENC",
            description=f"GPU/NVENC, CQ {nvenc_medium_cq}, p6 - schnell, bessere Qualität",
            cq=nvenc_medium_cq,
            preset="p6",
            bframes=4,
            lookahead=nvenc_lookahead,
        ),
    ]


def assistant_profiles_for_codec(codec: str) -> list[CodecProfileSuggestion]:
    codec_key = str(codec or "h265").strip().lower()
    if codec_key == "h264":
        return [
            _cpu_simple(
                codec="h264",
                key="h264_compat_balanced",
                label="H.264 kompatibel",
                description="CPU, CRF 22, medium - gute Kompatibilität",
                crf=22,
                preset="medium",
            ),
            _cpu_simple(
                codec="h264",
                key="h264_archive_quality",
                label="H.264 Archiv-Qualität",
                description="CPU, CRF 18, slow - größer, aber sauberer",
                crf=18,
                preset="slow",
            ),
            _nvenc(
                codec="h264",
                key="h264_nvenc_fast",
                label="H.264 NVENC schnell",
                description="GPU, CQ 22, p6 - schnell und kompatibel",
                cq=22,
            ),
        ]
    if codec_key == "av1":
        return [
            _cpu_simple(
                codec="av1",
                key="av1_small",
                label="AV1 klein",
                description="SVT-AV1, CRF 30, Preset 7 - kleine Dateien",
                crf=30,
                preset="7",
            ),
            _cpu_simple(
                codec="av1",
                key="av1_balanced",
                label="AV1 ausgewogen",
                description="SVT-AV1, CRF 28, Preset 6 - guter Standard",
                crf=28,
                preset="6",
            ),
            _cpu_simple(
                codec="av1",
                key="av1_archive_quality",
                label="AV1 Archiv-Qualität",
                description="SVT-AV1, CRF 24, Preset 5 - langsamer, hochwertiger",
                crf=24,
                preset="5",
            ),
            _nvenc(
                codec="av1",
                key="av1_nvenc_fast",
                label="AV1 NVENC schnell",
                description="GPU, CQ 28, p6 - schnell, falls unterstützt",
                cq=28,
            ),
        ]
    suggestions: list[CodecProfileSuggestion] = []
    suggestions.extend(_h265_start_profile_set(
        key_base="anime_series",
        label_base="Anime Serie",
        tune="animation",
        cpu_small_crf=21,
        cpu_medium_crf=20,
        nvenc_small_cq=23,
        nvenc_medium_cq=21,
        lookahead=60,
        bframes=10,
        nvenc_lookahead=40,
    ))
    suggestions.extend(_h265_start_profile_set(
        key_base="tv_series",
        label_base="TV Serie",
        tune="none",
        cpu_small_crf=23,
        cpu_medium_crf=21,
        nvenc_small_cq=24,
        nvenc_medium_cq=22,
    ))
    suggestions.extend(_h265_start_profile_set(
        key_base="anime_movie",
        label_base="Anime Film",
        tune="animation",
        cpu_small_crf=20,
        cpu_medium_crf=19,
        nvenc_small_cq=22,
        nvenc_medium_cq=20,
        lookahead=60,
        bframes=10,
        nvenc_lookahead=40,
    ))
    suggestions.extend(_h265_start_profile_set(
        key_base="tv_movie",
        label_base="TV Film",
        tune="none",
        cpu_small_crf=22,
        cpu_medium_crf=20,
        nvenc_small_cq=23,
        nvenc_medium_cq=21,
    ))
    suggestions.extend(_h265_start_profile_set(
        key_base="anime_4k",
        label_base="4K Anime",
        tune="animation",
        cpu_small_crf=21,
        cpu_medium_crf=19,
        nvenc_small_cq=22,
        nvenc_medium_cq=20,
        lookahead=60,
        bframes=10,
        nvenc_lookahead=40,
    ))
    suggestions.extend(_h265_start_profile_set(
        key_base="tv_4k",
        label_base="4K TV",
        tune="none",
        cpu_small_crf=22,
        cpu_medium_crf=20,
        nvenc_small_cq=23,
        nvenc_medium_cq=21,
    ))
    suggestions.extend([
        _cpu_h265(
            key="h265_anime_small_cpu",
            label="Anime klein",
            description="Legacy-Schnellwahl: CPU/x265, CRF 21, medium, Tune animation",
            crf=21,
            preset="medium",
            tune="animation",
            lookahead=60,
            bframes=10,
        ),
        _cpu_h265(
            key="h265_film_balanced_cpu",
            label="Film ausgewogen",
            description="Legacy-Schnellwahl: CPU/x265, CRF 22, medium - guter Allrounder",
            crf=22,
            preset="medium",
        ),
        _cpu_h265(
            key="h265_archive_quality_cpu",
            label="Archiv-Qualität",
            description="CPU/x265, CRF 20, slow - kleiner Qualitätsfokus",
            crf=20,
            preset="slow",
            lookahead=60,
        ),
        _nvenc(
            codec="h265",
            key="h265_nvenc_fast",
            label="NVENC schnell",
            description="GPU, CQ 23, p6 - schneller Standard",
            cq=23,
        ),
        _nvenc(
            codec="h265",
            key="h265_nvenc_quality",
            label="NVENC Qualität",
            description="GPU, CQ 20, p7 - größer, aber sauberer",
            cq=20,
            preset="p7",
        ),
    ])
    return suggestions


def profile_for_assistant_key(codec: str, key: str) -> dict[str, Any] | None:
    for suggestion in assistant_profiles_for_codec(codec):
        if suggestion.key == key:
            return copy.deepcopy(suggestion.profile)
    return None
