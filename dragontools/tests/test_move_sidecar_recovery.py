from __future__ import annotations


def _service(tmp_path, *, move_file=None):
    from dragontools.core.move_sidecars import MoveSidecarService

    reports = []
    return MoveSidecarService(
        filme_path="",
        trickplay_conflict_mode="skip",
        nfo_movie_target_name="movie.nfo",
        move_file=move_file or (lambda *_args, **_kwargs: (False, {})),
        log=lambda *_args: None,
        append_report=lambda result, *_args: reports.append(result),
        set_last_result=lambda _result: None,
    ), reports


def test_missing_source_sidecar_is_success_when_expected_target_exists(tmp_path):
    source = tmp_path / "work" / "episode.de.srt"
    target = tmp_path / "TV" / "Serie"
    target.mkdir(parents=True)
    (target / source.name).write_text("already moved", encoding="utf-8")
    service, reports = _service(tmp_path)

    result = service.move_sidecars("episode.mkv", str(target), [str(source)])

    assert result["ok"] is True
    assert result["already_present"] == 1
    assert result["failed"] == 0
    assert reports[0]["already_present"] is True


def test_missing_source_sidecar_remains_retryable_when_target_is_missing(tmp_path):
    source = tmp_path / "work" / "episode.de.srt"
    target = tmp_path / "TV" / "Serie"
    target.mkdir(parents=True)
    service, _reports = _service(tmp_path)

    result = service.move_sidecars("episode.mkv", str(target), [str(source)])

    assert result["ok"] is False
    assert result["failed"] == 1
