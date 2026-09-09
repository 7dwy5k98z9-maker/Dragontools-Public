from __future__ import annotations

from types import SimpleNamespace


def test_verbose_logger_discard_removes_file(tmp_path):
    from dragontools.core.logger import VerboseLogger

    logger = VerboseLogger(log_dir=tmp_path, enabled=True)
    path = logger.log_file
    assert path is not None and path.exists()

    assert logger.discard() is True

    assert logger.log_file is None
    assert not path.exists()


def test_converter_discards_verbose_after_clean_run(tmp_path):
    from dragontools.core.logger import discard_verbose_after_clean_run

    path = tmp_path / "verbose.txt"
    path.write_text("debug", encoding="utf-8")
    fake_logger = SimpleNamespace(
        log_file=path,
        discarded=False,
        discard=lambda: setattr(fake_logger, "discarded", True) or True,
    )

    discard_verbose_after_clean_run(
        fake_logger,
        abort_requested=False,
        failed_count=0,
        force_keep=False,
    )

    assert fake_logger.discarded is True


def test_converter_keeps_verbose_after_error_or_abort(tmp_path):
    from dragontools.core.logger import discard_verbose_after_clean_run

    calls = []
    fake_logger = SimpleNamespace(discard=lambda: calls.append(True))

    discard_verbose_after_clean_run(
        fake_logger,
        abort_requested=False,
        failed_count=1,
        force_keep=False,
    )
    discard_verbose_after_clean_run(
        fake_logger,
        abort_requested=True,
        failed_count=0,
        force_keep=False,
    )
    discard_verbose_after_clean_run(
        fake_logger,
        abort_requested=False,
        failed_count=0,
        force_keep=True,
    )

    assert calls == []
