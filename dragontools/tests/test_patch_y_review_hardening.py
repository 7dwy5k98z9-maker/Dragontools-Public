from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_audit_write_failure_is_logged(monkeypatch, caplog):
    from dragontools.core import audit_log

    monkeypatch.setattr(
        audit_log,
        "settings_change_log_dir",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    with caplog.at_level(logging.WARNING, logger="dragontools.core.audit_log"):
        assert audit_log.append_audit_event("Test") is None

    assert any("Audit" in record.getMessage() for record in caplog.records)


def test_settings_access_failure_is_logged_and_falls_back(caplog):
    from dragontools.core.settings_access import settings_value

    class BrokenSettings:
        def value(self, *_args, **_kwargs):
            raise RuntimeError("broken settings backend")

    with caplog.at_level(logging.DEBUG, logger="dragontools.core.settings_access"):
        assert settings_value(BrokenSettings(), "test/key", "fallback") == "fallback"

    assert any("test/key" in record.getMessage() for record in caplog.records)


def test_crash_guard_install_failure_is_visible(monkeypatch, capfd):
    from dragontools.core import crash_guard

    monkeypatch.setattr(crash_guard, "_installed", False)
    monkeypatch.setattr(
        crash_guard,
        "log_base_from_settings",
        lambda: (_ for _ in ()).throw(OSError("logging root unavailable")),
    )

    assert crash_guard.install_crash_guard("9.8.5") is None
    captured = capfd.readouterr()
    assert "CrashGuard konnte nicht initialisiert werden" in captured.err


def test_private_marker_scan_reports_unreadable_file(tmp_path, monkeypatch):
    from dragontools.core import release_validation_package as package

    target = tmp_path / "help.html"
    target.write_text("clean", encoding="utf-8")
    original_read_text = Path.read_text

    def broken_read_text(self, *args, **kwargs):
        if self == target:
            raise OSError("access denied")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", broken_read_text)

    checks = package._scan_private_markers(tmp_path)
    assert any(
        check.status == "warn"
        and check.title == "Datenschutz: Datei nicht lesbar"
        and "help.html" in check.detail
        for check in checks
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI is only available on Windows")
def test_real_windows_dpapi_roundtrip():
    from dragontools.core import secret_settings

    plain = "DragonTools-DPAPI-Roundtrip-äöü-9.8.5"
    protected = secret_settings._dpapi_protect(plain)

    assert protected.startswith("dpapi:v1:")
    assert protected != plain
    assert plain not in protected
    assert secret_settings._dpapi_unprotect(protected) == plain


def test_source_zip_bat_writes_portable_entry_names_and_rejects_backslashes():
    source = (ROOT / "DragonTools_Source_ZIP.bat").read_text(encoding="utf-8")

    assert ".CreateEntry($entryName" in source
    assert ".Replace('\\','/')" in source
    assert "$badSeparators=" in source
    assert "ZIP entries use invalid backslash separators" in source
    assert "CreateFromDirectory" not in source
