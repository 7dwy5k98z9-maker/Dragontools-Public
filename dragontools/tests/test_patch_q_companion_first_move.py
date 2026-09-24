from __future__ import annotations

from pathlib import Path

from dragontools.core.move_file_service import MoveFileService
from dragontools.core.move_sidecars import MoveSidecarService
from dragontools.worker.move_batch_executor import MoveBatchExecutor


def _sidecar_service(*, filme_path: str = "") -> MoveSidecarService:
    file_service = MoveFileService(
        conflict_mode="overwrite",
        log=lambda *_a: None,
        wait=lambda: None,
        abort_immediately=lambda: False,
        journal=None,
    )
    return MoveSidecarService(
        filme_path=filme_path,
        trickplay_conflict_mode="skip",
        nfo_movie_target_name="movie.nfo",
        move_file=file_service.move,
        overwrite_file=file_service.move,
        log=lambda *_a: None,
        append_report=lambda *_a, **_k: None,
        set_last_result=lambda *_a: None,
    )


def test_companions_are_staged_in_nfo_subtitle_trickplay_order(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    video = source / "Episode.mkv"
    video.write_bytes(b"video")
    nfo = source / "Episode.nfo"
    nfo.write_text("<episodedetails/>", encoding="utf-8")
    subtitle = source / "Episode.de.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHallo\n", encoding="utf-8")
    trickplay = source / "Episode.trickplay"
    trickplay.mkdir()
    (trickplay / "0.jpg").write_bytes(b"jpg")

    service = _sidecar_service()
    result = service.stage_before_video(
        str(video),
        str(target),
        [str(trickplay), str(subtitle), str(nfo)],
        dest_video_path=str(target / video.name),
    )

    assert result["ok"] is True
    assert [row["sidecar_type"] for row in result["results"]] == [
        "nfo",
        "subtitle",
        "trickplay",
    ]
    assert (target / "Episode.nfo").exists()
    assert (target / "Episode.de.srt").exists()
    assert (target / "Episode.trickplay" / "0.jpg").exists()
    # Staging copies; sources are only consumed after a successful video commit.
    assert nfo.exists() and subtitle.exists() and trickplay.exists()


def test_episode_replacement_does_not_remove_staged_new_companions(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "Serie" / "Staffel 01"
    source.mkdir()
    target.mkdir(parents=True)

    new_video = source / "Serie - S01E03 - Neuer Titel.mkv"
    new_video.write_bytes(b"new-video")
    new_nfo = source / "Serie - S01E03 - Neuer Titel.nfo"
    new_nfo.write_text("<episodedetails><title>Neu</title></episodedetails>", encoding="utf-8")
    new_trickplay = source / "Serie - S01E03 - Neuer Titel.trickplay"
    new_trickplay.mkdir()
    (new_trickplay / "0.jpg").write_bytes(b"new-jpg")

    old_video = target / "Serie - S01E03 - Alter Titel.mp4"
    old_video.write_bytes(b"old-video")
    old_nfo = target / "Serie - S01E03 - Alter Titel.nfo"
    old_nfo.write_text("<episodedetails><title>Alt</title></episodedetails>", encoding="utf-8")
    old_trickplay = target / "Serie - S01E03 - Alter Titel.trickplay"
    old_trickplay.mkdir()
    (old_trickplay / "0.jpg").write_bytes(b"old-jpg")

    sidecars = _sidecar_service()
    file_service = MoveFileService(
        conflict_mode="skip",  # SxxExx replacement still intentionally replaces.
        log=lambda *_a: None,
        wait=lambda: None,
        abort_immediately=lambda: False,
        journal=None,
        episode_replacement_mode="auto",
    )
    prepared = file_service.prepare_move(str(new_video), str(target))
    assert prepared["ready"] is True
    assert prepared["episode_replacement_preapproved"] is True

    staged = sidecars.stage_before_video(
        str(new_video),
        str(target),
        [str(new_trickplay), str(new_nfo)],
        dest_video_path=prepared["dest_path"],
    )
    assert staged["ok"] is True

    ok, result = file_service.move(
        str(new_video),
        str(target),
        prepared=prepared,
        protected_paths=staged["protected_paths"],
    )

    assert ok is True
    assert result["episode_identity_replacement"] is True
    assert not old_video.exists()
    assert not old_nfo.exists()
    assert not old_trickplay.exists()
    assert (target / new_video.name).exists()
    assert (target / new_nfo.name).read_text(encoding="utf-8").find("Neu") >= 0
    assert (target / new_trickplay.name / "0.jpg").read_bytes() == b"new-jpg"


class _Journal:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def start_file(self, _path: str) -> None:
        self.events.append("journal:start")

    def set_destination(self, _path: str, **_kwargs) -> None:
        pass

    def finish_file(self, _path: str, **_kwargs) -> None:
        pass


class _Router:
    def __init__(self, target: str) -> None:
        self.target = target

    def route(self, _path: str) -> str:
        return self.target


class _Completion:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def companion_resume_result(self, **_kwargs):
        raise AssertionError("not used")

    def complete(self, **_kwargs):
        self.events.append("complete")

        class Result:
            error = False

        return Result()


def test_batch_orders_companions_before_video_and_completion_after(tmp_path: Path) -> None:
    source = tmp_path / "Episode.mkv"
    source.write_bytes(b"video")
    target = tmp_path / "target"
    target.mkdir()
    events: list[str] = []
    dest = target / source.name
    last_result = {"dest_path": str(dest), "ok": True}

    def prepare(path: str, target_dir: str) -> dict:
        events.append("prepare")
        return {
            "ready": True,
            "dest_path": str(Path(target_dir) / Path(path).name),
            "result": {"dest_path": str(Path(target_dir) / Path(path).name)},
        }

    def stage(*_args) -> dict:
        events.append("companions")
        return {"ok": True, "protected_paths": [str(target / "Episode.trickplay")], "staged_paths": []}

    def move(*_args, **_kwargs) -> bool:
        events.append("video")
        return True

    executor = MoveBatchExecutor(
        files=[(str(source), source.stat().st_size)],
        router=_Router(str(target)),
        journal=_Journal(events),
        completion=_Completion(events),
        companion_resume_sources={},
        wait=lambda: None,
        abort_type=lambda: None,
        prepare_move=prepare,
        stage_sidecars=stage,
        rollback_staged_sidecars=lambda _stage: events.append("rollback"),
        move=move,
        get_last_move_result=lambda: dict(last_result),
        set_last_move_result=lambda result: last_result.update(result),
        append_move_report=lambda _result: None,
        log=lambda *_a: None,
        progress_hook=lambda _n: None,
        file_counted=lambda *_a: None,
    )

    result = executor.run()

    assert result.ok_count == 1
    assert events.index("companions") < events.index("video") < events.index("complete")
    assert "rollback" not in events


def test_staged_sidecar_finalize_does_not_delete_same_source_and_destination(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    video = target / "Episode.mkv"
    video.write_bytes(b"video")
    nfo = target / "Episode.nfo"
    nfo.write_text("<episodedetails/>", encoding="utf-8")

    service = _sidecar_service()
    result = service.move_sidecars(
        str(video),
        str(target),
        [str(nfo)],
        dest_video_path=str(video),
        staged_paths=[str(nfo)],
    )

    assert result["ok"] is True
    assert nfo.exists()


def test_failed_video_move_rolls_back_only_copied_companions(tmp_path: Path) -> None:
    source = tmp_path / "Episode.mkv"
    source.write_bytes(b"video")
    nfo = tmp_path / "Episode.nfo"
    nfo.write_text("<episodedetails/>", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    events: list[str] = []
    stage_state: dict[str, object] = {}
    service = _sidecar_service()

    def stage(path: str, target_dir: str, dest_path: str, _original: str) -> dict:
        staged = service.stage_before_video(
            path,
            target_dir,
            [str(nfo)],
            dest_video_path=dest_path,
        )
        stage_state.update(staged)
        events.append("companions")
        return staged

    def rollback(staged: dict | None) -> None:
        events.append("rollback")
        service.rollback_stage(staged)

    executor = MoveBatchExecutor(
        files=[(str(source), source.stat().st_size)],
        router=_Router(str(target)),
        journal=_Journal(events),
        completion=_Completion(events),
        companion_resume_sources={},
        wait=lambda: None,
        abort_type=lambda: None,
        prepare_move=lambda path, target_dir: {
            "ready": True,
            "dest_path": str(Path(target_dir) / Path(path).name),
            "result": {"dest_path": str(Path(target_dir) / Path(path).name)},
        },
        stage_sidecars=stage,
        rollback_staged_sidecars=rollback,
        move=lambda *_args, **_kwargs: False,
        get_last_move_result=lambda: {"dest_path": str(target / source.name), "ok": False},
        set_last_move_result=lambda _result: None,
        append_move_report=lambda _result: None,
        log=lambda *_a: None,
        progress_hook=lambda _n: None,
        file_counted=lambda *_a: None,
    )

    result = executor.run()

    assert result.error_count == 1
    assert nfo.exists()
    assert not (target / nfo.name).exists()
    assert events.index("companions") < events.index("rollback")
