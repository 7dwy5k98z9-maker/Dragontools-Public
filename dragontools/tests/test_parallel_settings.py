from __future__ import annotations


class DummySettings:
    def __init__(self, values: dict[str, object]):
        self.values = values

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        if type is not None:
            return type(value)
        return value


class MutableSettings(DummySettings):
    def contains(self, key):
        return key in self.values

    def setValue(self, key, value):
        self.values[key] = value


def test_parallel_jobs_use_new_safe_defaults_when_not_configured():
    from dragontools.core.parallel_settings import parallel_jobs_for_encoder

    settings = DummySettings({})

    assert parallel_jobs_for_encoder(settings, "cpu", file_count=10) == 1
    assert parallel_jobs_for_encoder(settings, "nvenc", file_count=10) == 2
    assert parallel_jobs_for_encoder(settings, "qsv", file_count=10) == 2
    assert parallel_jobs_for_encoder(settings, "amf", file_count=10) == 2


def test_parallel_defaults_migration_updates_old_saved_defaults():
    from dragontools.core.parallel_settings import migrate_parallel_defaults
    from dragontools.core.settings import (
        SET_KEY_PARALLEL_CPU_JOBS,
        SET_KEY_PARALLEL_DEFAULTS_MIGRATED,
        SET_KEY_PARALLEL_GPU_JOBS,
    )

    settings = MutableSettings({
        SET_KEY_PARALLEL_CPU_JOBS: 2,
        SET_KEY_PARALLEL_GPU_JOBS: 4,
    })

    migrate_parallel_defaults(settings)

    assert settings.values[SET_KEY_PARALLEL_CPU_JOBS] == 1
    assert settings.values[SET_KEY_PARALLEL_GPU_JOBS] == 2
    assert settings.values[SET_KEY_PARALLEL_DEFAULTS_MIGRATED] is True


def test_parallel_defaults_migration_keeps_custom_values():
    from dragontools.core.parallel_settings import migrate_parallel_defaults
    from dragontools.core.settings import SET_KEY_PARALLEL_CPU_JOBS, SET_KEY_PARALLEL_GPU_JOBS

    settings = MutableSettings({
        SET_KEY_PARALLEL_CPU_JOBS: 3,
        SET_KEY_PARALLEL_GPU_JOBS: 5,
    })

    migrate_parallel_defaults(settings)

    assert settings.values[SET_KEY_PARALLEL_CPU_JOBS] == 3
    assert settings.values[SET_KEY_PARALLEL_GPU_JOBS] == 5


def test_parallel_jobs_use_cpu_and_gpu_limits():
    from dragontools.core.parallel_settings import parallel_jobs_for_encoder
    from dragontools.core.settings import SET_KEY_PARALLEL_CPU_JOBS, SET_KEY_PARALLEL_GPU_JOBS

    settings = DummySettings({
        SET_KEY_PARALLEL_CPU_JOBS: 2,
        SET_KEY_PARALLEL_GPU_JOBS: 4,
    })

    assert parallel_jobs_for_encoder(settings, "cpu", file_count=10) == 2
    assert parallel_jobs_for_encoder(settings, "nvenc", file_count=10) == 4
    assert parallel_jobs_for_encoder(settings, "qsv", file_count=10) == 4
    assert parallel_jobs_for_encoder(settings, "amf", file_count=10) == 4


def test_parallel_jobs_are_limited_by_file_count_and_maximum():
    from dragontools.core.parallel_settings import parallel_jobs_for_encoder
    from dragontools.core.settings import SET_KEY_PARALLEL_GPU_JOBS

    settings = DummySettings({SET_KEY_PARALLEL_GPU_JOBS: 99})

    assert parallel_jobs_for_encoder(settings, "nvenc", file_count=3) == 3


def test_split_files_for_parallel_workers_uses_round_robin_order():
    from dragontools.core.parallel_settings import split_files_for_parallel_workers

    chunks = split_files_for_parallel_workers(["a.mkv", "b.mkv", "c.mkv", "d.mkv", "e.mkv"], 2)

    assert chunks == [["a.mkv", "c.mkv", "e.mkv"], ["b.mkv", "d.mkv"]]


def test_parallel_jobs_accept_legacy_float_string_values():
    from dragontools.core.parallel_settings import clamp_parallel_jobs

    assert clamp_parallel_jobs("2.0", 1) == 2
