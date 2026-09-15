# -*- coding: utf-8 -*-
"""Audio/subtitle/auxiliary stream verification for media contracts."""
from __future__ import annotations

from ..core.lang_codes import canonical_lang
from .media_contract import _audio_codec_family, _subtitle_codec_family
from .media_contract_types import ExpectedMediaContract


def compare_audio_tracks(contract: ExpectedMediaContract, streams: list[dict]) -> list[str]:
    expected = contract.audio_tracks
    if len(streams) != len(expected):
        return [f"Audiospur-Anzahl abweichend: erwartet {len(expected)}, gefunden {len(streams)}."]
    messages: list[str] = []
    for index, (planned, actual) in enumerate(zip(expected, streams), start=1):
        codec = _audio_codec_family(actual.get("codec_name"))
        if planned.codec and codec != planned.codec:
            messages.append(
                f"Audio #{index}: Codec abweichend: erwartet {planned.codec}, gefunden {codec or '<unbekannt>'}."
            )
        try:
            channels = int(actual.get("channels") or 0)
        except (TypeError, ValueError):
            channels = 0
        if planned.channels > 0 and channels != planned.channels:
            messages.append(
                f"Audio #{index}: Kanalzahl abweichend: erwartet {planned.channels}, gefunden {channels}."
            )
        expected_lang = canonical_lang(planned.language)
        if expected_lang and expected_lang != "und":
            actual_lang = canonical_lang((actual.get("tags") or {}).get("language"))
            if actual_lang != expected_lang:
                messages.append(
                    f"Audio #{index}: Sprache abweichend: erwartet {expected_lang}, "
                    f"gefunden {actual_lang or '<nicht gesetzt>'}."
                )
    return messages


def compare_subtitle_tracks(contract: ExpectedMediaContract, streams: list[dict]) -> list[str]:
    expected = contract.subtitle_tracks
    if len(streams) != len(expected):
        return [f"Untertitelspur-Anzahl abweichend: erwartet {len(expected)}, gefunden {len(streams)}."]
    messages: list[str] = []
    for index, (planned, actual) in enumerate(zip(expected, streams), start=1):
        codec = _subtitle_codec_family(actual.get("codec_name"))
        if planned.codec and codec != planned.codec:
            messages.append(
                f"Untertitel #{index}: Codec abweichend: erwartet {planned.codec}, gefunden {codec or '<unbekannt>'}."
            )
        expected_lang = canonical_lang(planned.language)
        if expected_lang and expected_lang != "und":
            actual_lang = canonical_lang((actual.get("tags") or {}).get("language"))
            if actual_lang != expected_lang:
                messages.append(
                    f"Untertitel #{index}: Sprache abweichend: erwartet {expected_lang}, "
                    f"gefunden {actual_lang or '<nicht gesetzt>'}."
                )
        actual_forced = bool((actual.get("disposition") or {}).get("forced", 0))
        if actual_forced != bool(planned.forced):
            messages.append(
                f"Untertitel #{index}: Forced-Flag abweichend: erwartet {bool(planned.forced)}, "
                f"gefunden {actual_forced}."
            )
    return messages


def verify_auxiliary_stream_contract(
    contract: ExpectedMediaContract,
    attachment_streams: list[dict] | None,
    data_streams: list[dict] | None,
) -> list[str]:
    attachments = list(attachment_streams or [])
    data = list(data_streams or [])
    messages: list[str] = []
    if contract.attachment_stream_count is not None and len(attachments) != contract.attachment_stream_count:
        messages.append(
            f"Attachment-Anzahl abweichend: erwartet {contract.attachment_stream_count}, gefunden {len(attachments)}."
        )
    if contract.data_stream_count is not None and len(data) != contract.data_stream_count:
        messages.append(
            f"Data-Stream-Anzahl abweichend: erwartet {contract.data_stream_count}, gefunden {len(data)}."
        )
    return messages
