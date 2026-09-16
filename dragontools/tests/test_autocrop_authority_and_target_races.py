from __future__ import annotations

import json
from pathlib import Path

from dragontools.worker.dv_crop_reconcile import reconcile_dv_crop, replace_crop_in_vf_args
from dragontools.worker.move_batch_executor import MoveBatchExecutor


class _Level5Runner:
    def __init__(self, export_path: Path, *, top: int, bottom: int) -> None:
        self.export_path = export_path
        self.top = top
        self.bottom = bottom

    def run(self, _cmd, **_kwargs):
        self.export_path.write_text(
            json.dumps(
                {
                    "active_area": {
                        "presets": [
                            {
                                "id": 0,
                                "left": 0,
                                "right": 0,
                                "top": self.top,
                                "bottom": self.bottom,
                            }
                        ],
                        "edits": {"all": 0},
                    }
                }
            ),
            encoding="utf-8",
        )
        return 0


def test_dv_rpu_metadata_never_overrides_autocrop(tmp_path: Path) -> None:
    """Regression: AutoCrop 1606 must not become RPU 1607/1608."""
    export_path = tmp_path / "level5.json"
    rpu_path = tmp_path / "source.rpu"
    rpu_path.write_bytes(b"rpu")
    logs: list[str] = []

    result = reconcile_dv_crop(
        runner=_Level5Runner(export_path, top=276, bottom=277),
        dovi_tool="dovi_tool",
        rpu_path=rpu_path,
        export_path=export_path,
        source_width=3840,
        source_height=2160,
        autocrop_text="crop=3840:1606:0:278",
        input_path="movie.mkv",
        log=lambda message, _level="info": logs.append(message),
    )

    assert result.success is True
    assert result.source == "autocrop"
    assert result.crop is not None
    assert result.crop.as_filter() == "crop=3840:1606:0:278"
    assert any("RPU-Level5=crop=3840:1607:0:276" in line for line in logs)
    assert any("AutoCrop ist maßgeblich" in line for line in logs)


def test_odd_autocrop_is_normalized_but_rpu_still_cannot_override(tmp_path: Path) -> None:
    export_path = tmp_path / "level5.json"
    rpu_path = tmp_path / "source.rpu"
    rpu_path.write_bytes(b"rpu")

    result = reconcile_dv_crop(
        runner=_Level5Runner(export_path, top=280, bottom=280),
        dovi_tool="dovi_tool",
        rpu_path=rpu_path,
        export_path=export_path,
        source_width=3840,
        source_height=2160,
        autocrop_text="crop=3840:1607:0:276",
        input_path="movie.mkv",
    )

    assert result.crop is not None
    assert result.crop.as_filter() == "crop=3840:1608:0:276"
    assert result.source == "autocrop"


def test_crop_replacement_updates_filter_complex_for_pgs_burnin() -> None:
    graph = "[0:v:0]crop=3840:1607:0:276[vpre];[vpre][0:s:6]overlay[vout]"
    args = ["-filter_complex", graph, "-map", "[vout]"]

    result = replace_crop_in_vf_args(
        args,
        "crop=3840:1607:0:276",
        "crop=3840:1608:0:276",
    )

    assert "crop=3840:1608:0:276" in result[1]
    assert "crop=3840:1607:0:276" not in result[1]
    assert "-vf" not in result


class _Journal:
    def __init__(self) -> None:
        self.status = "queued"
        self.target_updates: list[str] = []
        self.started_before_route = False

    def start_file(self, _path: str, **_kwargs) -> None:
        self.status = "running"
        self.started_before_route = True

    def update_planned_target_if_queued(self, _path: str, target: str) -> bool:
        if self.status != "queued":
            return False
        self.target_updates.append(target)
        return True

    def set_destination(self, _path: str, **_kwargs) -> None:
        pass

    def finish_file(self, _path: str, **_kwargs) -> None:
        self.status = "done"


class _Router:
    def __init__(self, journal: _Journal, target: str) -> None:
        self.journal = journal
        self.target = target
        self.edit_was_accepted: bool | None = None

    def route(self, path: str) -> str:
        # Reproduce the old race at the exact boundary: a target edit arrives
        # after routing begins but before the physical transfer starts.
        self.edit_was_accepted = self.journal.update_planned_target_if_queued(path, "NEW")
        return self.target


class _Completion:
    def companion_resume_result(self, **_kwargs):
        raise AssertionError("not used")

    def complete(self, **_kwargs):
        class Result:
            error = False
        return Result()


def test_move_marks_transaction_running_before_reading_target(tmp_path: Path) -> None:
    source = tmp_path / "episode.mkv"
    source.write_bytes(b"x")
    journal = _Journal()
    router = _Router(journal, str(tmp_path / "target"))

    executor = MoveBatchExecutor(
        files=[(str(source), 1)],
        router=router,
        journal=journal,
        completion=_Completion(),
        companion_resume_sources={},
        wait=lambda: None,
        abort_type=lambda: None,
        move=lambda *_args, **_kwargs: True,
        get_last_move_result=lambda: {"dest_path": str(tmp_path / "target" / source.name)},
        set_last_move_result=lambda _result: None,
        append_move_report=lambda _result: None,
        log=lambda *_args: None,
        progress_hook=lambda _n: None,
        file_counted=lambda *_args: None,
    )

    result = executor.run()

    assert journal.started_before_route is True
    assert router.edit_was_accepted is False
    assert result.ok_count == 1


def test_target_dialog_commit_reresolves_storage_key_from_source_text() -> None:
    """Architecture regression without importing PyQt on headless CI."""
    source_path = Path(__file__).resolve().parents[1] / "gui" / "convert_widget_queue_target_actions.py"
    source = source_path.read_text(encoding="utf-8")
    assert "rejected = self._apply_replacement_targets(input_paths, replacements)" in source
    apply_body = source.split("def _apply_replacement_targets", 1)[1].split("def _change_planned_target", 1)[0]
    assert "key = self._planned_target_storage_key(input_path)" in apply_body
    assert "replacements.get(input_path)" in apply_body
