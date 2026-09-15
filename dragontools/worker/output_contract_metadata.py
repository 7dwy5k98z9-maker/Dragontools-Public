# -*- coding: utf-8 -*-
"""Dynamic-metadata verification for expected media contracts."""
from __future__ import annotations

from .media_contract_types import ExpectedMediaContract


def verify_dynamic_metadata_contract(result, contract: ExpectedMediaContract) -> list[str]:
    messages: list[str] = []
    if contract.require_hdr and not result.has_hdr:
        messages.append("HDR-Vertrag verletzt: HDR ist im finalen Videostream nicht nachweisbar.")
    if contract.require_dolby_vision and not result.has_dolby_vision:
        messages.append("Dolby-Vision-Vertrag verletzt: Dolby Vision ist im finalen Videostream nicht nachweisbar.")
    if contract.require_hdr10plus and not result.has_hdr10plus:
        messages.append("HDR10+-Vertrag verletzt: HDR10+ ist im finalen Videostream nicht nachweisbar.")
    return messages
