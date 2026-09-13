from __future__ import annotations

import zipfile

from dragontools.core.settings import (
    SET_KEY_METADATA_TMDB_API_KEY,
    SET_KEY_METADATA_TMDB_READ_TOKEN,
)


class _Settings:
    def __init__(self):
        self._store = {
            "a/key": "value",
            SET_KEY_METADATA_TMDB_API_KEY: "tmdb-api-secret",
            SET_KEY_METADATA_TMDB_READ_TOKEN: "tmdb-read-token-secret",
        }

    def allKeys(self):
        return list(self._store)

    def value(self, key, default=None):
        return self._store.get(key, default)


def test_create_diagnostic_package_collects_logs_and_settings(tmp_path, monkeypatch):
    import dragontools.core.diagnostic_package as module

    log = tmp_path / "Logging" / "2026" / "08-August" / "run.txt"
    error = tmp_path / "Logging" / "2026" / "08-August" / "ErrorReports" / "error.txt"
    crash = tmp_path / "Logging" / "2026" / "08-August" / "CrashReports" / "crash.txt"
    verbose = tmp_path / "VerboseLog" / "verbose.txt"
    for path in (log, error, crash, verbose):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")

    monkeypatch.setattr(module, "log_base_from_settings", lambda _settings: tmp_path)
    monkeypatch.setattr(module, "verbose_log_dir_from_settings", lambda _settings: tmp_path / "VerboseLog")
    monkeypatch.setattr(module, "_tool_diagnostics_text", lambda: "tools ok\n")
    monkeypatch.setattr(module, "_extended_systemtest_text", lambda: "systemtest ok\n")

    target = module.create_diagnostic_package(
        tmp_path / "diag.zip",
        settings=_Settings(),
        documents_dir=tmp_path,
    )

    with zipfile.ZipFile(target) as zf:
        names = set(zf.namelist())

    assert "manifest.json" in names
    assert "settings.json" in names
    assert "tools.txt" in names
    assert "extended_systemtest.txt" in names
    assert any(name.startswith("logs/normal/") for name in names)
    assert any(name.startswith("logs/error/") for name in names)
    assert any(name.startswith("logs/crash/") for name in names)
    assert any(name.startswith("logs/verbose/") for name in names)

    with zipfile.ZipFile(target) as zf:
        settings_text = zf.read("settings.json").decode("utf-8")

    assert "tmdb-api-secret" not in settings_text
    assert "tmdb-read-token-secret" not in settings_text
    assert "********" in settings_text
