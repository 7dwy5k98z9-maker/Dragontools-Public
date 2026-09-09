from __future__ import annotations

from types import SimpleNamespace

from dragontools.gui.convert_widget_paths import ConvertWidgetTargetPathService
from dragontools.gui.convert_widget_recovery import ConvertWidgetRecoveryService


class _Settings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def value(self, key, default="", type=None):
        value = self.values.get(key, default)
        return type(value) if type is not None else value


class _FileList:
    def __init__(self):
        self.paths: list[str] = []

    def add_path(self, path: str) -> bool:
        if path in self.paths:
            return False
        self.paths.append(path)
        return True

    def count(self) -> int:
        return len(self.paths)


def test_target_path_service_uses_codec_specific_keys(monkeypatch):
    service = ConvertWidgetTargetPathService(default_codec="h265", settings=_Settings())
    keys = service.key_map()
    assert keys["tv"].endswith("h265/tv") or "h265" in keys["tv"].lower()
    assert keys["anime"].endswith("h265/anime") or "h265" in keys["anime"].lower()
    assert keys["film"].endswith("h265/filme") or "h265" in keys["film"].lower()


def test_restore_job_files_preserves_move_context(tmp_path):
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"video")
    state = SimpleNamespace(
        planned_targets={},
        sidecar_outputs_by_video={},
        restored_move_context={},
        preflight_rows_by_path={},
        file_overrides={},
        total_files=0,
    )
    file_list = _FileList()
    logs = []
    refreshes = []
    service = ConvertWidgetRecoveryService(
        state=state,
        file_list=file_list,
        log=lambda msg, level="info": logs.append((msg, level)),
        active_worker=lambda: None,
        refresh_queue=lambda: refreshes.append(True),
        update_label=lambda _path: None,
        default_codec="h265",
        get_subtitle_rules=lambda: {},
        overwrite_original=lambda: False,
        get_tools=lambda: None,
    )

    result = service.restore_job_files(
        [str(video)],
        context="move",
        planned_targets={str(video): str(tmp_path / "target.mkv")},
        sidecar_outputs_by_video={str(video): [str(tmp_path / "episode.de.srt")]},
        target_paths={"tv": str(tmp_path / "TV")},
        conflict_mode="overwrite",
        journal_path=str(tmp_path / "move.json"),
    )

    assert result == {"added": 1, "missing": 0, "duplicate": 0, "invalid": 0}
    assert state.total_files == 1
    assert state.planned_targets[str(video)].endswith("target.mkv")
    assert state.sidecar_outputs_by_video[str(video)][0].endswith("episode.de.srt")
    assert state.restored_move_context["conflict_mode"] == "overwrite"
    assert refreshes == [True]


def test_restore_job_files_rejects_missing_and_non_video(tmp_path):
    state = SimpleNamespace(
        planned_targets={},
        sidecar_outputs_by_video={},
        restored_move_context={},
        preflight_rows_by_path={},
        file_overrides={},
        total_files=0,
    )
    service = ConvertWidgetRecoveryService(
        state=state,
        file_list=_FileList(),
        log=lambda *_args, **_kwargs: None,
        active_worker=lambda: None,
        refresh_queue=lambda: None,
        update_label=lambda _path: None,
        default_codec="h265",
        get_subtitle_rules=lambda: {},
        overwrite_original=lambda: False,
        get_tools=lambda: None,
    )
    missing = tmp_path / "missing.mkv"
    text = tmp_path / "notes.txt"
    text.write_text("x", encoding="utf-8")

    result = service.restore_job_files([str(missing), str(text), ""])
    assert result == {"added": 0, "missing": 1, "duplicate": 0, "invalid": 2}


def test_preflight_badge_refresh_failure_is_logged(monkeypatch, tmp_path):
    import dragontools.gui.convert_widget_recovery as module

    video = tmp_path / "episode.mkv"
    video.write_bytes(b"video")
    state = SimpleNamespace(
        planned_targets={},
        sidecar_outputs_by_video={},
        restored_move_context={},
        preflight_rows_by_path={},
        file_overrides={},
        total_files=0,
    )
    logs = []
    monkeypatch.setattr(
        module,
        "build_batch_preflight_rows",
        lambda *_args, **_kwargs: [{"path": str(video), "status": "ok"}],
    )
    service = ConvertWidgetRecoveryService(
        state=state,
        file_list=_FileList(),
        log=lambda msg, level="info": logs.append((level, msg)),
        active_worker=lambda: None,
        refresh_queue=lambda: None,
        update_label=lambda _path: (_ for _ in ()).throw(RuntimeError("badge kaputt")),
        default_codec="h265",
        get_subtitle_rules=lambda: {},
        overwrite_original=lambda: False,
        get_tools=lambda: None,
    )

    rows = service.build_preflight_report_rows([str(video)], {})

    assert rows[0]["path"] == str(video)
    assert any(level == "warn" and "badge kaputt" in msg for level, msg in logs)
