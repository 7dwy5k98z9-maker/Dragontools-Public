from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_logger_disabled_remains_fail_soft(tmp_path):
    from dragontools.core.logger import DragonLogger

    logger = DragonLogger(tmp_path, log_enabled=False)
    logger.info("logging intentionally disabled")
    logger.warn("must not crash")

    assert logger.log_file is None
    assert logger.long_log_file is None
    assert logger.has_logging_failures is False


def test_logger_directory_creation_failure_remains_fail_soft(tmp_path):
    from dragontools.core.logger import DragonLogger

    not_a_directory = tmp_path / "occupied"
    not_a_directory.write_text("file", encoding="utf-8")

    logger = DragonLogger(not_a_directory, log_enabled=True)
    logger.error("logging backend unavailable")

    assert logger.log_file is None
    assert logger.long_log_file is None


def test_parallel_verbose_loggers_have_distinct_ownership(tmp_path):
    from dragontools.core.logger_verbose import VerboseLogger

    first = VerboseLogger(log_dir=tmp_path, enabled=True)
    second = VerboseLogger(log_dir=tmp_path, enabled=True)
    try:
        assert first.log_file is not None
        assert second.log_file is not None
        assert first.log_file != second.log_file
        first_path = first.log_file
        second_path = second.log_file

        first.write("first")
        second.write("second")
        assert first.discard() is True

        assert not first_path.exists()
        assert second_path.exists()
        assert "second" in second_path.read_text(encoding="utf-8")
    finally:
        first.discard()
        second.discard()


def test_tool_runner_permission_error_is_structured_result(monkeypatch):
    import dragontools.worker.tool_runner as module

    def denied(*_args, **_kwargs):
        raise PermissionError("execution denied")

    monkeypatch.setattr(module.subprocess, "Popen", denied)

    result = module.run_tool(["blocked-tool.exe", "--version"], label="Blocked")

    assert result.returncode == 126
    assert result.ok is False
    assert "Berechtigung" in result.stderr
    assert "execution denied" in result.stderr


def test_tool_runner_bytes_permission_error_is_structured_result(monkeypatch):
    import dragontools.worker.tool_runner as module

    def denied(*_args, **_kwargs):
        raise PermissionError("execution denied")

    monkeypatch.setattr(module.subprocess, "Popen", denied)

    result = module.run_tool_bytes(["blocked-tool.exe"], label="Blocked")

    assert result.returncode == 126
    assert result.ok is False
    assert b"execution denied" in result.stderr


def test_tool_availability_rejects_directory(tmp_path):
    from dragontools.core.process_runner import tool_available
    from dragontools.core.tool_diagnostics import _exists_or_which
    from dragontools.core.tool_paths import _tool_path_available

    assert tmp_path.is_dir()
    assert tool_available(str(tmp_path)) is False
    assert _exists_or_which(str(tmp_path)) is False
    assert _tool_path_available(str(tmp_path)) is False


def test_extended_cli_test_does_not_accept_error_output_as_success():
    from dragontools.core.tool_diagnostics_extended import run_extended_system_test

    rows = run_extended_system_test(
        {
            "dovi_tool": "dovi_tool.exe",
            "hdr10plus_tool": "hdr10plus_tool.exe",
        },
        runner=lambda _cmd, _timeout: (1, "fatal: startup failed"),
        path_exists=lambda path: bool(path),
    )

    relevant = {
        row["name"]: row
        for row in rows
        if row["name"] in {"dovi_tool CLI-Test", "hdr10plus_tool CLI-Test"}
    }
    assert relevant["dovi_tool CLI-Test"]["ok"] is False
    assert relevant["hdr10plus_tool CLI-Test"]["ok"] is False
    assert "fatal" in relevant["dovi_tool CLI-Test"]["detail"]


def test_late_tool_provider_registration_rebuilds_providerless_singleton(monkeypatch):
    import dragontools.core.tool_paths as module

    class Provider(module.ToolPathSettingsProvider):
        def get_custom_dirs(self):
            return []

        def find_in_settings(self, tool_key, *exe_names):
            return f"configured:{tool_key}:{exe_names[0]}"

    monkeypatch.setattr(module, "_tool_paths_instance", None)
    monkeypatch.setattr(module, "_tool_paths_provider", None)

    providerless = module.get_tool_paths()
    configured = module.get_tool_paths(provider=Provider())

    assert configured is not providerless
    assert configured.find_in_settings("ffmpeg", "ffmpeg.exe") == "configured:ffmpeg:ffmpeg.exe"


def test_posix_pause_and_resume_target_owned_process_group(monkeypatch):
    if os.name == "nt":
        pytest.skip("POSIX process-group semantics")

    import dragontools.worker.process_control as module

    proc = SimpleNamespace(pid=4321, poll=lambda: None, _dragontools_process_group=True)
    calls = []
    monkeypatch.setattr(module.os, "getpgid", lambda pid: pid + 100)
    monkeypatch.setattr(module.os, "killpg", lambda pgid, sig: calls.append((pgid, sig)))
    monkeypatch.setattr(
        module.os,
        "kill",
        lambda *_args: pytest.fail("owned process group must not pause only the parent"),
    )

    assert module.suspend_process(proc) is True
    assert module.resume_process(proc) is True

    import signal

    assert calls == [(4421, signal.SIGSTOP), (4421, signal.SIGCONT)]


def test_safe_unlink_refuses_symlink_even_when_target_is_inside_base(tmp_path):
    from dragontools.core.path_safety import safe_unlink

    target = tmp_path / "real.txt"
    link = tmp_path / "link.txt"
    target.write_text("important", encoding="utf-8")
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this host")

    assert safe_unlink(tmp_path, link) is False
    assert target.read_text(encoding="utf-8") == "important"
    assert link.is_symlink()


def test_safe_rmtree_refuses_directory_symlink(tmp_path):
    from dragontools.core.path_safety import safe_rmtree

    target = tmp_path / "real-dir"
    target.mkdir()
    (target / "important.txt").write_text("important", encoding="utf-8")
    link = tmp_path / "dir-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable on this host")

    assert safe_rmtree(tmp_path, link) is False
    assert (target / "important.txt").exists()
    assert link.is_symlink()


def test_diagnostic_package_redacts_secrets_from_logs_configs_and_journals(tmp_path, monkeypatch):
    import dragontools.core.diagnostic_package as module
    from dragontools.core.settings import SET_KEY_METADATA_TMDB_API_KEY

    secret = "tmdb-super-secret-123456"
    config_secret = "config-password-987654"

    class Settings:
        def __init__(self):
            self.store = {SET_KEY_METADATA_TMDB_API_KEY: secret, "normal/value": "ok"}

        def allKeys(self):
            return list(self.store)

        def value(self, key, default=None, **_kwargs):
            return self.store.get(key, default)

    log = tmp_path / "Logging" / "2026" / "10-Oktober" / "run.txt"
    log.parent.mkdir(parents=True)
    log.write_text(f"server echoed credential {secret}\n", encoding="utf-8")

    rules = tmp_path / "rules" / "example.json"
    rules.parent.mkdir(parents=True)
    rules.write_text(json.dumps({"password": config_secret}), encoding="utf-8")

    journal = tmp_path / "JobJournal" / "job.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({"command": f"tool --api-key {secret}"}), encoding="utf-8")

    monkeypatch.setattr(module, "log_base_from_settings", lambda _settings: tmp_path)
    monkeypatch.setattr(module, "verbose_log_dir_from_settings", lambda _settings: tmp_path / "VerboseLog")
    monkeypatch.setattr(module, "_tool_diagnostics_text", lambda: "tools ok\n")
    monkeypatch.setattr(module, "_extended_systemtest_text", lambda: "systemtest ok\n")

    target = module.create_diagnostic_package(
        tmp_path / "diag.zip", settings=Settings(), documents_dir=tmp_path
    )

    with zipfile.ZipFile(target) as zf:
        combined = "\n".join(
            zf.read(name).decode("utf-8", errors="replace")
            for name in zf.namelist()
        )

    assert secret not in combined
    assert config_secret not in combined
    assert "[REDACTED]" in combined or "********" in combined


def test_crash_state_redacts_cli_and_extra_secrets(tmp_path, monkeypatch):
    import dragontools.core.crash_guard as module

    state_file = tmp_path / "crash_state.json"
    monkeypatch.setattr(module, "_state_file", state_file)

    assert module.mark_activity(
        "tool running",
        command=["tool.exe", "--api-key", "plain-cli-secret"],
        extra={"password": "plain-extra-secret"},
    )

    text = state_file.read_text(encoding="utf-8")
    assert "plain-cli-secret" not in text
    assert "plain-extra-secret" not in text
    assert "[REDACTED]" in text


def test_error_reports_get_unique_names_for_same_stem(tmp_path):
    from dragontools.core.error_report import write_conversion_error_report

    ctx = SimpleNamespace(input_path=str(tmp_path / "movie.mkv"))
    first = write_conversion_error_report(
        ctx=ctx, reason="first", log_file=tmp_path / "run.txt"
    )
    second = write_conversion_error_report(
        ctx=ctx, reason="second", log_file=tmp_path / "run.txt"
    )

    assert first != second
    assert Path(first).exists()
    assert Path(second).exists()
    assert "first" in Path(first).read_text(encoding="utf-8")
    assert "second" in Path(second).read_text(encoding="utf-8")


def test_manual_crash_reports_get_unique_names(tmp_path, monkeypatch):
    import dragontools.core.crash_guard as module

    monkeypatch.setattr(module, "_state_dir", tmp_path)
    monkeypatch.setattr(module, "_state_file", None)

    first = Path(module.write_manual_crash_note("first"))
    second = Path(module.write_manual_crash_note("second"))

    assert first != second
    assert first.exists() and second.exists()


def test_posix_volume_key_uses_device_id():
    if os.name == "nt":
        pytest.skip("POSIX mount grouping")

    from dragontools.core.disk_space import _volume_key

    class FakePath:
        anchor = "/"

        def __init__(self, dev):
            self.dev = dev

        def resolve(self):
            return self

        def absolute(self):
            return self

        def stat(self):
            return SimpleNamespace(st_dev=self.dev)

        def __str__(self):
            return f"/fake/{self.dev}"

    assert _volume_key(FakePath(101)) != _volume_key(FakePath(202))


def test_primary_and_verbose_logs_redact_structural_secrets(tmp_path):
    from dragontools.core.logger import DragonLogger
    from dragontools.core.logger_verbose import VerboseLogger

    normal = DragonLogger(tmp_path / "normal", log_enabled=True)
    normal.error("request --api-key visible-secret-123")
    assert normal.long_log_file is not None
    normal_text = normal.long_log_file.read_text(encoding="utf-8")
    assert "visible-secret-123" not in normal_text
    assert "[REDACTED]" in normal_text

    verbose = VerboseLogger(log_dir=tmp_path / "verbose", enabled=True)
    try:
        assert verbose.log_file is not None
        verbose.write("Authorization: Bearer bearer-secret-456789")
        verbose_text = verbose.log_file.read_text(encoding="utf-8")
        assert "bearer-secret-456789" not in verbose_text
        assert "[REDACTED]" in verbose_text
    finally:
        verbose.discard()


def test_log_cleanup_blank_root_does_not_fall_back_to_cwd(tmp_path, monkeypatch):
    from dragontools.core.log_cleanup import cleanup_logs

    logging_dir = tmp_path / "Logging"
    logging_dir.mkdir()
    victim = logging_dir / "run.txt"
    victim.write_text("keep", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = cleanup_logs("")

    assert result.deleted_files == 0
    assert victim.exists()


def test_log_cleanup_skips_symlinked_log_file(tmp_path):
    from dragontools.core.log_cleanup import cleanup_logs

    log_root = tmp_path / "root"
    logging_dir = log_root / "Logging"
    logging_dir.mkdir(parents=True)
    target = logging_dir / "real.txt"
    target.write_text("keep", encoding="utf-8")
    link = logging_dir / "link.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this host")

    result = cleanup_logs(log_root)

    # The real file is a legitimate log and may be deleted; the symlink itself
    # must never be dereferenced/deleted as a different resolved file.
    assert link.is_symlink()
    assert result.skipped_files >= 1


def test_diagnostic_latest_files_tolerates_disappearing_entry(tmp_path):
    import dragontools.core.diagnostic_package as module

    alive = tmp_path / "alive.txt"
    alive.write_text("ok", encoding="utf-8")

    class Vanished:
        def stat(self):
            raise FileNotFoundError("rotated")

    selected = module._latest_from_list([Vanished(), alive], 10)
    assert selected == [alive]


def test_default_diagnostic_paths_are_unique(tmp_path):
    from dragontools.core.diagnostic_package import default_diagnostic_package_path

    first = default_diagnostic_package_path(tmp_path)
    second = default_diagnostic_package_path(tmp_path)
    assert first != second


def test_parallel_primary_loggers_do_not_share_files(tmp_path):
    from dragontools.core.logger import DragonLogger

    first = DragonLogger(tmp_path, log_enabled=True)
    second = DragonLogger(tmp_path, log_enabled=True)

    assert first.log_file is not None and second.log_file is not None
    assert first.long_log_file is not None and second.long_log_file is not None
    assert first.log_file != second.log_file
    assert first.long_log_file != second.long_log_file


def test_command_formatting_redacts_secret_options():
    from dragontools.worker.command_formatting import command_to_log_string

    text = command_to_log_string(["tool.exe", "--api-key", "command-secret-123"])
    assert "command-secret-123" not in text
    assert "[REDACTED]" in text


def test_gui_error_report_redacts_structural_secrets(tmp_path):
    from dragontools.core.gui_error_report import write_tab_load_error_report

    report = write_tab_load_error_report(
        tab_key="convert",
        tab_label="Convert",
        error=RuntimeError("request --access-token gui-secret-123"),
        traceback_text="Authorization: Bearer gui-bearer-secret-456",
        log_root=tmp_path,
    )
    text = Path(report).read_text(encoding="utf-8")
    assert "gui-secret-123" not in text
    assert "gui-bearer-secret-456" not in text
    assert "[REDACTED]" in text


def test_tool_diagnostics_nonzero_version_probe_is_not_reported_green(monkeypatch):
    import dragontools.core.tool_diagnostics as module

    monkeypatch.setattr(module, "_exists_or_which", lambda _path: True)
    monkeypatch.setattr(module, "_run_tool", lambda *_a, **_k: (7, "fatal version probe"))

    row = module.probe_tool("dovi_tool", "dovi_tool.exe")
    text = module.format_tool_diagnostics([row])

    assert row["found"] is True
    assert row["version"] == ""
    assert row["error"] == "fatal version probe"
    assert "⚠️  dovi_tool" in text
    assert "✅  dovi_tool" not in text


def test_log_cleanup_rejects_symlinked_logging_root(tmp_path):
    from dragontools.core.log_cleanup import cleanup_logs

    base = tmp_path / "base"
    base.mkdir()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    victim = unrelated / "keep.txt"
    victim.write_text("important", encoding="utf-8")
    try:
        (base / "Logging").symlink_to(unrelated, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable on this host")

    result = cleanup_logs(base)

    assert victim.exists()
    assert result.deleted_files == 0
    assert result.skipped_files >= 1


def test_diagnostic_package_does_not_follow_symlinked_log_file(tmp_path, monkeypatch):
    import dragontools.core.diagnostic_package as module

    external = tmp_path / "outside-secret.txt"
    external.write_text("password=external-super-secret", encoding="utf-8")
    logging_dir = tmp_path / "Logging"
    logging_dir.mkdir()
    link = logging_dir / "linked.txt"
    try:
        link.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this host")

    class Settings:
        def allKeys(self):
            return []

        def value(self, _key, default=None, **_kwargs):
            return default

    monkeypatch.setattr(module, "log_base_from_settings", lambda _settings: tmp_path)
    monkeypatch.setattr(
        module, "verbose_log_dir_from_settings", lambda _settings: tmp_path / "VerboseLog"
    )
    monkeypatch.setattr(module, "_tool_diagnostics_text", lambda: "tools ok\n")
    monkeypatch.setattr(module, "_extended_systemtest_text", lambda: "systemtest ok\n")

    target = module.create_diagnostic_package(
        tmp_path / "diag.zip", settings=Settings(), documents_dir=tmp_path
    )
    with zipfile.ZipFile(target) as zf:
        combined = "\n".join(
            zf.read(name).decode("utf-8", errors="replace") for name in zf.namelist()
        )

    assert "external-super-secret" not in combined


def test_windows_plain_timeout_terminates_owned_tree(monkeypatch):
    import dragontools.worker.process_control as process_control
    import dragontools.worker.tool_process_lifecycle as lifecycle

    calls = []

    class FakeProc:
        pid = 9876

        def poll(self):
            return None

        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            return 0

        def terminate(self):
            pytest.fail("successful taskkill tree path must not fall back to parent terminate")

        def kill(self):
            pytest.fail("successful taskkill tree path must not fall back to parent kill")

    monkeypatch.setattr(lifecycle, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        process_control,
        "_taskkill_tree",
        lambda pid, **kwargs: calls.append(("taskkill", pid, kwargs.get("timeout"))) or True,
    )

    lifecycle.terminate_plain(FakeProc(), timeout=2.0, label="Tool")

    assert calls[0] == ("taskkill", 9876, 2.0)
    assert calls[1] == ("wait", 2.0)


def test_safe_subpath_rejects_ownership_root_itself(tmp_path):
    from dragontools.core.path_safety import is_safe_subpath, safe_rmtree

    marker = tmp_path / "keep.txt"
    marker.write_text("important", encoding="utf-8")

    assert is_safe_subpath(tmp_path, tmp_path) is False
    assert safe_rmtree(tmp_path, tmp_path) is False
    assert marker.exists()


def test_taskkill_logging_accepts_single_argument_callback(monkeypatch):
    import dragontools.worker.process_control as module

    class Completed:
        returncode = 1

    monkeypatch.setattr(module.subprocess, "run", lambda *_a, **_k: Completed())
    messages = []

    assert module._taskkill_tree(12345, log=messages.append, label="Tool") is False
    assert messages
    assert "taskkill" in messages[0]


def test_diagnostic_package_rejects_symlink_target(tmp_path, monkeypatch):
    import dragontools.core.diagnostic_package as module

    victim = tmp_path / "victim.txt"
    victim.write_text("do not truncate", encoding="utf-8")
    link = tmp_path / "diag.zip"
    try:
        link.symlink_to(victim)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this host")

    class Settings:
        def allKeys(self):
            return []

        def value(self, _key, default=None, **_kwargs):
            return default

    monkeypatch.setattr(module, "log_base_from_settings", lambda _settings: tmp_path)
    monkeypatch.setattr(module, "verbose_log_dir_from_settings", lambda _settings: tmp_path / "VerboseLog")

    with pytest.raises(ValueError, match="Symlink/Junction"):
        module.create_diagnostic_package(link, settings=Settings(), documents_dir=tmp_path)

    assert victim.read_text(encoding="utf-8") == "do not truncate"


def test_diagnostic_package_does_not_follow_symlinked_logging_root(tmp_path, monkeypatch):
    import dragontools.core.diagnostic_package as module

    base = tmp_path / "base"
    base.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (external / "outside.txt").write_text("password=outside-secret-xyz", encoding="utf-8")
    try:
        (base / "Logging").symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable on this host")

    class Settings:
        def allKeys(self):
            return []

        def value(self, _key, default=None, **_kwargs):
            return default

    monkeypatch.setattr(module, "log_base_from_settings", lambda _settings: base)
    monkeypatch.setattr(module, "verbose_log_dir_from_settings", lambda _settings: base / "VerboseLog")
    monkeypatch.setattr(module, "_tool_diagnostics_text", lambda: "tools ok\n")
    monkeypatch.setattr(module, "_extended_systemtest_text", lambda: "systemtest ok\n")

    target = module.create_diagnostic_package(
        tmp_path / "diag.zip", settings=Settings(), documents_dir=base
    )
    with zipfile.ZipFile(target) as zf:
        combined = "\n".join(
            zf.read(name).decode("utf-8", errors="replace") for name in zf.namelist()
        )

    assert "outside-secret-xyz" not in combined
