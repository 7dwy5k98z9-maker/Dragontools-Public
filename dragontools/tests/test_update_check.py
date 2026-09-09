from __future__ import annotations

import json

import pytest

from dragontools.core.update_check import (
    UPDATE_RELEASES_URL,
    is_newer_version,
    parse_release_response,
    version_tuple,
)


@pytest.mark.parametrize(
    ("candidate", "current", "expected"),
    [
        ("9.9", "9.8", True),
        ("v9.8.1", "9.8", True),
        ("10.0", "9.99", True),
        ("9.8", "9.8.0", False),
        ("9.7.9", "9.8", False),
    ],
)
def test_version_comparison(candidate, current, expected):
    assert is_newer_version(candidate, current) is expected


def test_version_tuple_rejects_untrusted_text():
    with pytest.raises(ValueError):
        version_tuple("release-latest")


def test_parse_release_response_reports_new_release():
    payload = json.dumps(
        {
            "tag_name": "v9.9",
            "name": "DragonTools V9.9",
            "body": "Neue Funktionen und Fehlerkorrekturen.",
            "html_url": "https://github.com/7dwy5k98z9-maker/Dragontools-Releases/releases/tag/v9.9",
            "published_at": "2026-10-01T12:00:00Z",
        }
    )

    result = parse_release_response(payload, "9.8")

    assert result.ok is True
    assert result.update_available is True
    assert result.release is not None
    assert result.release.version == "9.9"


def test_parse_release_response_rejects_non_github_download_page():
    payload = json.dumps(
        {
            "tag_name": "v9.9",
            "html_url": "https://example.invalid/download",
        }
    )

    result = parse_release_response(payload, "9.8")

    assert result.ok is True
    assert result.release is not None
    assert result.release.page_url == UPDATE_RELEASES_URL


def test_parse_release_response_handles_invalid_json():
    result = parse_release_response("not json", "9.8")

    assert result.ok is False
    assert result.update_available is False
