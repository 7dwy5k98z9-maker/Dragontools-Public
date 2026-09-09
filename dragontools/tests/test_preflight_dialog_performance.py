from __future__ import annotations

import queue
from types import SimpleNamespace


class _ComboStub:
    def __init__(self, index: int = 0) -> None:
        self.index = index

    def currentIndex(self) -> int:
        return self.index

    def setCurrentIndex(self, index: int) -> None:
        self.index = index


class _LineEditStub:
    def __init__(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = text


class _LabelStub:
    def __init__(self) -> None:
        self.text = ""
        self.visible = False
        self.style = ""

    def setText(self, text: str) -> None:
        self.text = text

    def setVisible(self, visible: bool) -> None:
        self.visible = visible

    def setStyleSheet(self, style: str) -> None:
        self.style = style


def _series_widget_stub(base: str, series_name: str):
    from dragontools.gui.preflight_dialog import SeriesGroupWidget

    widget = SeriesGroupWidget.__new__(SeriesGroupWidget)
    widget._options = [("Anime", base)]
    widget._type_combo = _ComboStub(0)
    widget._series_edit = SimpleNamespace(text=lambda: series_name)
    widget._resolved_series_key = None
    widget._resolved_series_dir = None
    return widget


def _series_widget_stub_with_bases(bases: list[tuple[str, str]], series_name: str, index: int = 0):
    from dragontools.gui.preflight_dialog import SeriesGroupWidget

    widget = SeriesGroupWidget.__new__(SeriesGroupWidget)
    widget._options = bases
    widget._type_combo = _ComboStub(index)
    widget._series_edit = _LineEditStub(series_name)
    widget._resolved_series_key = None
    widget._resolved_series_dir = None
    widget._metadata_hint = _LabelStub()
    widget._update_preview = lambda: None
    return widget


def test_series_preview_path_does_not_scan_existing_folders(monkeypatch):
    from dragontools.tests.test_incremental_move_queue_edit import _install_pyqt_stubs

    _install_pyqt_stubs(monkeypatch)

    from dragontools.rules import move_rules

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Ordnersuche darf die Preflight-Vorschau nicht blockieren")

    monkeypatch.setattr(move_rules, "find_series_dir_candidates", fail_if_called)

    widget = _series_widget_stub(r"D:\Anime", "Stargate Atlantis")

    assert widget._series_root_dir().endswith(r"Anime\Stargate Atlantis")


def test_series_metadata_job_is_payload_for_background_lookup(monkeypatch):
    from dragontools.tests.test_incremental_move_queue_edit import _install_pyqt_stubs

    _install_pyqt_stubs(monkeypatch)

    from dragontools.rules import move_rules

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Bestehende Serienordner werden erst im Hintergrund gesucht")

    monkeypatch.setattr(move_rules, "find_existing_series_dir", fail_if_called)

    widget = _series_widget_stub(r"D:\TV", "Stargate Atlantis")
    kind, _key, payload = widget.metadata_lookup_job()

    assert kind == "series"
    assert payload == {
        "base": r"D:\TV",
        "series_name": "Stargate Atlantis",
        "search_bases": [{"type": "Anime", "base": r"D:\TV"}],
        "year": None,
    }


def test_series_metadata_job_searches_selected_base_before_fallback(monkeypatch):
    from dragontools.tests.test_incremental_move_queue_edit import _install_pyqt_stubs

    _install_pyqt_stubs(monkeypatch)

    widget = _series_widget_stub_with_bases(
        [("TV", r"D:\TV"), ("Anime", r"D:\Anime")],
        "Stargate Atlantis",
        index=1,
    )
    _kind, _key, payload = widget.metadata_lookup_job()

    assert payload["search_bases"] == [
        {"type": "Anime", "base": r"D:\Anime"},
        {"type": "TV", "base": r"D:\TV"},
    ]


def test_existing_series_dir_can_switch_to_fallback_base(monkeypatch):
    from dragontools.tests.test_incremental_move_queue_edit import _install_pyqt_stubs

    _install_pyqt_stubs(monkeypatch)

    widget = _series_widget_stub_with_bases(
        [("TV", r"D:\TV"), ("Anime", r"D:\Anime")],
        "Stargate Atlantis",
        index=1,
    )

    widget.apply_existing_series_dir(
        r"D:\TV\Stargate Atlantis (2004)",
        r"D:\TV",
        "Stargate Atlantis",
        "TV",
    )

    assert widget._type_combo.currentIndex() == 0
    assert widget._resolved_series_dir == r"D:\TV\Stargate Atlantis (2004)"


def test_unusable_library_match_switches_to_database_area_and_applies_year(monkeypatch):
    from dragontools.tests.test_incremental_move_queue_edit import _install_pyqt_stubs

    _install_pyqt_stubs(monkeypatch)

    widget = _series_widget_stub_with_bases(
        [("TV", r"D:\TV"), ("Anime", r"D:\Anime")],
        "Watson",
        index=1,
    )

    widget.apply_unusable_library_series_match(
        message=r"Mediathek-Treffer ist aktuell nicht erreichbar (Bereich TV): D:\TV\Watson (2025)",
        series_name="Watson",
        suggested_series_name="Watson (2025)",
        base=r"D:\TV",
        base_type="TV",
    )

    assert widget._type_combo.currentIndex() == 0
    assert widget._series_edit.text() == "Watson (2025)"
    assert "Bereich TV" in widget._metadata_hint.text


def test_background_lookup_uses_fallback_before_tmdb(monkeypatch):
    from dragontools.tests.test_incremental_move_queue_edit import _install_pyqt_stubs

    _install_pyqt_stubs(monkeypatch)

    from dragontools.core import media_library, online_metadata
    from dragontools.rules import move_rules
    from dragontools.gui.preflight_dialog import PreFlightDialog

    calls: list[str] = []

    def fake_find_candidates(base, series_name, year=None):
        calls.append((base, year))
        if base == r"D:\TV":
            return [r"D:\TV\Stargate Atlantis"]
        return []

    def fail_tmdb(*_args, **_kwargs):
        raise AssertionError("TMDB darf nicht laufen, wenn ein lokaler Ordner gefunden wurde")

    monkeypatch.setattr(move_rules, "find_series_dir_candidates", fake_find_candidates)
    monkeypatch.setattr(media_library, "find_series_dir_from_settings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(online_metadata, "suggest_series_metadata_for_name", fail_tmdb)

    dlg = PreFlightDialog.__new__(PreFlightDialog)
    dlg._metadata_cancelled = False
    result_queue = queue.Queue()
    dlg._run_online_metadata_lookup(
        [(
            "series",
            "job-1",
            {
                "series_name": "Stargate Atlantis",
                "search_bases": [
                    {"type": "Anime", "base": r"D:\Anime"},
                    {"type": "TV", "base": r"D:\TV"},
                ],
            },
        )],
        result_queue,
        online_enabled=True,
    )

    kind, key, result = result_queue.get_nowait()

    assert (kind, key) == ("series", "job-1")
    assert calls == [(r"D:\Anime", None), (r"D:\TV", None)]
    assert result["__existing_series_dir__"] == r"D:\TV\Stargate Atlantis"
    assert result["base"] == r"D:\TV"
    assert result["base_type"] == "TV"


def test_background_lookup_searches_local_folders_without_tmdb(monkeypatch):
    from dragontools.tests.test_incremental_move_queue_edit import _install_pyqt_stubs

    _install_pyqt_stubs(monkeypatch)

    from dragontools.core import media_library, online_metadata
    from dragontools.rules import move_rules
    from dragontools.gui.preflight_dialog import PreFlightDialog

    def no_existing(*_args, **_kwargs):
        return []

    def fail_tmdb(*_args, **_kwargs):
        raise AssertionError("TMDB darf nicht laufen, wenn Online-Metadaten deaktiviert sind")

    monkeypatch.setattr(move_rules, "find_series_dir_candidates", no_existing)
    monkeypatch.setattr(media_library, "find_series_dir_from_settings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(online_metadata, "suggest_series_metadata_for_name", fail_tmdb)

    dlg = PreFlightDialog.__new__(PreFlightDialog)
    dlg._metadata_cancelled = False
    result_queue = queue.Queue()
    dlg._run_online_metadata_lookup(
        [(
            "series",
            "job-1",
            {
                "series_name": "Stargate Atlantis",
                "search_bases": [{"type": "Anime", "base": r"D:\Anime"}],
            },
        )],
        result_queue,
        online_enabled=False,
    )

    kind, key, result = result_queue.get_nowait()

    assert (kind, key) == ("series", "job-1")
    assert result == {"__local_series_missing__": True}

def test_background_library_mapping_notice_is_forwarded_verbatim(monkeypatch):
    from dragontools.tests.test_incremental_move_queue_edit import _install_pyqt_stubs

    _install_pyqt_stubs(monkeypatch)

    from dragontools.core import media_library, online_metadata
    from dragontools.rules import move_rules
    from dragontools.gui.preflight_dialog import PreFlightDialog

    expected_notice = (
        "Alter DB-Speicherpfad wurde über das gespeicherte TV-Pfad-Mapping "
        "auf den aktuell konfigurierten Speicherpfad umgesetzt und geprüft."
    )

    monkeypatch.setattr(
        media_library,
        "find_series_dir_from_settings",
        lambda *_args, **_kwargs: {
            "series_dir": r"D:\TV\American Dad! (2005)",
            "base": r"D:\TV",
            "base_type": "TV",
            "source": "database",
            "mapping_note": "rebased_from_persisted_mapping",
            "mapping_notice": expected_notice,
        },
    )
    monkeypatch.setattr(move_rules, "find_series_dir_candidates", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        online_metadata,
        "suggest_series_metadata_for_name",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Online-Suche darf bei DB-Treffer nicht laufen")
        ),
    )

    dlg = PreFlightDialog.__new__(PreFlightDialog)
    dlg._metadata_cancelled = False
    result_queue = queue.Queue()
    dlg._run_online_metadata_lookup(
        [(
            "series",
            "job-db",
            {
                "series_name": "American Dad!",
                "search_bases": [{"type": "TV", "base": r"D:\TV"}],
            },
        )],
        result_queue,
        online_enabled=True,
    )

    kind, key, result = result_queue.get_nowait()
    assert (kind, key) == ("series", "job-db")
    assert result["notice"] == expected_notice
    assert result["__existing_series_dir__"] == r"D:\TV\American Dad! (2005)"


def test_background_lookup_uses_online_year_to_pick_existing_series_folder(monkeypatch):
    from dragontools.tests.test_incremental_move_queue_edit import _install_pyqt_stubs

    _install_pyqt_stubs(monkeypatch)

    from dragontools.core import media_library, online_metadata
    from dragontools.rules import move_rules
    from dragontools.gui.preflight_dialog import PreFlightDialog

    def fake_candidates(base, series_name, year=None):
        if year == 2024:
            return [r"D:\Anime\Ranma ½ (2024)"]
        return [r"D:\Anime\Ranma ½ (1989)", r"D:\Anime\Ranma ½ (2024)"]

    monkeypatch.setattr(move_rules, "find_series_dir_candidates", fake_candidates)
    monkeypatch.setattr(media_library, "find_series_dir_from_settings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        online_metadata,
        "suggest_series_metadata_for_name",
        lambda *_args, **_kwargs: SimpleNamespace(first_air_year=2024, folder_name="Ranma ½ (2024)"),
    )

    dlg = PreFlightDialog.__new__(PreFlightDialog)
    dlg._metadata_cancelled = False
    result_queue = queue.Queue()
    dlg._run_online_metadata_lookup(
        [("series", "job-ranma", {"series_name": "Ranma 1/2", "search_bases": [{"type": "Anime", "base": r"D:\Anime"}]})],
        result_queue,
        online_enabled=True,
    )

    kind, key, result = result_queue.get_nowait()
    assert (kind, key) == ("series", "job-ranma")
    assert result["__existing_series_dir__"] == r"D:\Anime\Ranma ½ (2024)"


def test_background_lookup_passes_online_year_to_library_search(monkeypatch):
    from dragontools.tests.test_incremental_move_queue_edit import _install_pyqt_stubs

    _install_pyqt_stubs(monkeypatch)

    from dragontools.core import media_library, online_metadata
    from dragontools.rules import move_rules
    from dragontools.gui.preflight_dialog import PreFlightDialog

    years: list[int | None] = []

    monkeypatch.setattr(
        move_rules,
        "find_series_dir_candidates",
        lambda *_args, **_kwargs: [r"D:\Anime\Ranma ½ (1989)", r"D:\Anime\Ranma ½ (2024)"],
    )
    monkeypatch.setattr(
        online_metadata,
        "suggest_series_metadata_for_name",
        lambda *_args, **_kwargs: SimpleNamespace(first_air_year=2024, folder_name="Ranma ½ (2024)"),
    )

    def fake_library(_settings, _series_name, _bases, *, year=None):
        years.append(year)
        return {
            "series_dir": r"D:\Anime\Ranma ½ (2024)",
            "base": r"D:\Anime",
            "base_type": "Anime",
            "source": "database",
        }

    monkeypatch.setattr(media_library, "find_series_dir_from_settings", fake_library)

    dlg = PreFlightDialog.__new__(PreFlightDialog)
    dlg._metadata_cancelled = False
    result_queue = queue.Queue()
    dlg._run_online_metadata_lookup(
        [("series", "job-ranma", {"series_name": "Ranma 1/2", "search_bases": [{"type": "Anime", "base": r"D:\Anime"}]})],
        result_queue,
        online_enabled=True,
    )

    _kind, _key, result = result_queue.get_nowait()
    assert years == [2024]
    assert result["source"] == "database"
    assert result["__existing_series_dir__"] == r"D:\Anime\Ranma ½ (2024)"


def test_background_lookup_returns_folder_choices_when_year_is_unknown(monkeypatch):
    from dragontools.tests.test_incremental_move_queue_edit import _install_pyqt_stubs

    _install_pyqt_stubs(monkeypatch)

    from dragontools.core import media_library, online_metadata
    from dragontools.rules import move_rules
    from dragontools.gui.preflight_dialog import PreFlightDialog

    monkeypatch.setattr(
        move_rules,
        "find_series_dir_candidates",
        lambda *_args, **_kwargs: [r"D:\Anime\Ranma ½ (1989)", r"D:\Anime\Ranma ½ (2024)"],
    )
    monkeypatch.setattr(media_library, "find_series_dir_from_settings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        online_metadata,
        "suggest_series_metadata_for_name",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Online-Suche darf bei deaktivierten Metadaten nicht laufen")
        ),
    )

    dlg = PreFlightDialog.__new__(PreFlightDialog)
    dlg._metadata_cancelled = False
    result_queue = queue.Queue()
    dlg._run_online_metadata_lookup(
        [("series", "job-ranma", {"series_name": "Ranma 1/2", "search_bases": [{"type": "Anime", "base": r"D:\Anime"}]})],
        result_queue,
        online_enabled=False,
    )

    kind, key, result = result_queue.get_nowait()
    assert (kind, key) == ("series", "job-ranma")
    assert "__series_dir_choices__" in result
    assert [choice["path"] for choice in result["__series_dir_choices__"]] == [
        r"D:\Anime\Ranma ½ (1989)",
        r"D:\Anime\Ranma ½ (2024)",
    ]
