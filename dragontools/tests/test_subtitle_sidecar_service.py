# -*- coding: utf-8 -*-
"""Tests fuer SubtitleSidecarService und Hilfsfunktionen."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

class TestSafeLangTag:
    """safe_lang_tag() normalisiert Sprach-Tags fuer Dateinamen."""

    def _fn(self, lang):
        from dragontools.worker.subtitle_sidecar_service import safe_lang_tag
        return safe_lang_tag(lang)

    def test_dreistellig_unveraendert(self):
        assert self._fn("deu") == "deu"
        assert self._fn("eng") == "eng"
        assert self._fn("jpn") == "jpn"

    def test_zweistellig_unveraendert(self):
        assert self._fn("de") == "de"
        assert self._fn("en") == "en"

    def test_grossbuchstaben_klein(self):
        assert self._fn("DEU") == "deu"
        assert self._fn("ZH-Hant") == "zhhant"

    def test_sonderzeichen_entfernt(self):
        assert self._fn("zh-Hant") == "zhhant"
        assert self._fn("pt-BR") == "ptbr"

    def test_none_ergibt_und(self):
        assert self._fn(None) == "und"

    def test_leer_ergibt_und(self):
        assert self._fn("") == "und"

    def test_nur_sonderzeichen_ergibt_und(self):
        assert self._fn("---") == "und"


class TestLangIsoTag:
    """lang_iso_tag() konvertiert ISO-639-2 → ISO-639-1."""

    def _fn(self, code):
        from dragontools.core.lang_codes import lang_iso_tag
        return lang_iso_tag(code)

    def test_deutsch_deu_zu_de(self):
        assert self._fn("deu") == "de"

    def test_deutsch_ger_zu_de(self):
        assert self._fn("ger") == "de"

    def test_englisch_eng_zu_en(self):
        assert self._fn("eng") == "en"

    def test_japanisch_jpn_zu_ja(self):
        assert self._fn("jpn") == "ja"

    def test_franzoesisch_fra_zu_fr(self):
        assert self._fn("fra") == "fr"

    def test_zweistellig_bleibt(self):
        assert self._fn("de") == "de"
        assert self._fn("en") == "en"

    def test_unbekannt_bleibt(self):
        assert self._fn("xyz") == "xyz"

    def test_none_ergibt_und(self):
        assert self._fn(None) == "und"

    def test_leer_ergibt_und(self):
        assert self._fn("") == "und"


class TestSidecarFilename:
    """sidecar_filename() erzeugt Jellyfin/VLC-konforme Pfade."""

    def _fn(self, base, lang, forced, ext, number=None):
        from dragontools.worker.subtitle_sidecar_service import sidecar_filename
        return sidecar_filename(Path(base), lang, forced, ext, number)

    def test_nicht_forced_einzeln(self):
        result = self._fn("/films/Film", "de", False, ".srt")
        assert result == "/films/Film.de.srt"

    def test_forced_einzeln(self):
        result = self._fn("/films/Film", "de", True, ".srt")
        assert result == "/films/Film.de.forced.srt"

    def test_sup_einzeln(self):
        result = self._fn("/films/Film", "ja", False, ".sup")
        assert result == "/films/Film.ja.sup"

    def test_forced_im_namen(self):
        """'forced' muss eindeutig im Dateinamen stehen."""
        result = self._fn("/films/Film", "en", True, ".srt")
        assert "forced" in result

    def test_nummerierung_bei_duplikaten(self):
        """Bei number!=None wird die Nummer in den Namen eingefuegt."""
        result1 = self._fn("/films/Film", "de", False, ".srt", number=1)
        result2 = self._fn("/films/Film", "de", False, ".srt", number=2)
        assert result1 == "/films/Film.de.1.srt"
        assert result2 == "/films/Film.de.2.srt"

    def test_forced_nummerierung(self):
        result = self._fn("/films/Film", "de", True, ".srt", number=1)
        assert result == "/films/Film.de.forced.1.srt"

    def test_output_stem_verwendet(self):
        """Sidecar liegt neben der Output-Datei, nicht der Input-Datei."""
        result = self._fn("/output/Movie_DV", "de", False, ".srt")
        assert result.startswith("/output/Movie_DV")


# ---------------------------------------------------------------------------
# SubtitleSidecarService
# ---------------------------------------------------------------------------

def _make_sub(index, codec, language, forced=False):
    sub = MagicMock()
    sub.index = index
    sub.codec = codec
    sub.language = language
    sub.forced = forced
    return sub


def _make_mi(subs):
    mi = MagicMock()
    mi.subtitle_streams = subs
    mi.audio_streams = []
    return mi


class TestSubtitleSidecarService:
    """Produktive Sidecar-API liefert einen strukturierten Exportstatus."""

    def _svc(self, rules=None):
        from dragontools.worker.subtitle_sidecar_service import SubtitleSidecarService
        log_calls = []
        svc = SubtitleSidecarService(
            ffmpeg_path="/fake/ffmpeg",
            subtitle_rules=rules or {"dv_extract_external_subs": True},
            log=lambda msg, level="info": log_calls.append((level, msg)),
        )
        return svc, log_calls

    def test_keine_streams_gibt_leere_liste(self):
        svc, _ = self._svc()
        mi = _make_mi([])
        result = svc.export_sidecars_result(
            input_path="/src/input.mkv",
            output_base="/dst/Film",
            media_info=mi,
        )
        assert result.exported_paths == ()

    def test_export_disabled_gibt_leere_liste(self):
        svc, _ = self._svc(rules={"dv_extract_external_subs": False})
        mi = _make_mi([_make_sub(3, "subrip", "deu", forced=True)])
        result = svc.export_sidecars_result(
            input_path="/src/input.mkv",
            output_base="/dst/Film",
            media_info=mi,
        )
        assert result.exported_paths == ()

    def test_kein_extern_stream_gibt_leere_liste(self):
        """Wenn compute_subtitle_plan keine external_streams liefert → []."""
        svc, _ = self._svc()
        mi = _make_mi([_make_sub(3, "subrip", "deu")])
        empty_plan = MagicMock()
        empty_plan.external_streams = []
        with patch(
            "dragontools.worker.subtitle_sidecar_service.compute_subtitle_plan",
            return_value=empty_plan,
        ):
            result = svc.export_sidecars_result(
                input_path="/src/input.mkv",
                output_base="/dst/Film",
                media_info=mi,
            )
        assert result.complete is True
        assert result.exported_paths == ()

    def test_erfolgreich_exportierte_subs_in_liste(self):
        """Erfolgreich erzeugte Dateien erscheinen in der Rueckgabe."""
        from dragontools.worker.subtitle_sidecar_service import SubtitleSidecarService

        svc, _ = self._svc()
        sub = _make_sub(3, "subrip", "deu", forced=True)
        mi = _make_mi([sub])

        plan = MagicMock()
        plan.external_streams = [sub]

        fake_path = "/dst/Film_sub_deu_forced_3.srt"

        with (
            patch("dragontools.worker.subtitle_sidecar_service.compute_subtitle_plan", return_value=plan),
            patch("dragontools.worker.subtitle_sidecar_service.run_tool") as mock_run,
            patch("dragontools.worker.subtitle_sidecar_service.Path.exists", side_effect=[False, True]),
            patch("dragontools.worker.subtitle_sidecar_service.Path.is_symlink", return_value=False),
            patch("dragontools.worker.subtitle_sidecar_service.Path.stat") as mock_stat,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            mock_stat.return_value = MagicMock(st_size=1024)
            result = svc.export_sidecars_result(
                input_path="/src/input.mkv",
                output_base="/dst/Film",
                media_info=mi,
            )

        assert result.complete is True
        assert len(result.exported_paths) == 1

    def test_fehlgeschlagener_export_nicht_in_liste(self):
        """Bei rc != 0 darf der Pfad nicht in der Rueckgabe erscheinen."""
        from dragontools.worker.subtitle_sidecar_service import SubtitleSidecarService

        svc, log_calls = self._svc()
        sub = _make_sub(3, "subrip", "deu", forced=False)
        mi = _make_mi([sub])

        plan = MagicMock()
        plan.external_streams = [sub]

        with (
            patch("dragontools.worker.subtitle_sidecar_service.compute_subtitle_plan", return_value=plan),
            patch("dragontools.worker.subtitle_sidecar_service.run_tool") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1)
            result = svc.export_sidecars_result(
                input_path="/src/input.mkv",
                output_base="/dst/Film",
                media_info=mi,
            )

        assert result.complete is False
        assert result.exported_paths == ()
        warn_msgs = [msg for level, msg in log_calls if level == "warn"]
        assert any("fehlgeschlagen" in m for m in warn_msgs)

    def test_abort_check_stoppt_loop(self):
        """abort_check=True stoppt den Export-Loop."""
        from dragontools.worker.subtitle_sidecar_service import SubtitleSidecarService

        svc, _ = self._svc()
        sub1 = _make_sub(3, "subrip", "deu", forced=True)
        sub2 = _make_sub(4, "ass", "eng", forced=False)
        mi = _make_mi([sub1, sub2])

        plan = MagicMock()
        plan.external_streams = [sub1, sub2]

        run_count = [0]

        def fake_run(*args, **kwargs):
            run_count[0] += 1
            return MagicMock(returncode=0)

        with (
            patch("dragontools.worker.subtitle_sidecar_service.compute_subtitle_plan", return_value=plan),
            patch("dragontools.worker.subtitle_sidecar_service.run_tool", side_effect=fake_run),
        ):
            # abort_check gibt sofort True zurueck → kein ffmpeg-Aufruf
            result = svc.export_sidecars_result(
                input_path="/src/input.mkv",
                output_base="/dst/Film",
                media_info=mi,
                abort_check=lambda: True,
            )

        assert result.aborted is True
        assert result.complete is False
        assert result.exported_paths == ()
        assert run_count[0] == 0  # ffmpeg wurde gar nicht aufgerufen

    def test_forced_im_dateinamen(self):
        """Forced-Subs muessen 'forced' im Dateinamen haben."""
        from dragontools.worker.subtitle_sidecar_service import sidecar_filename
        name = sidecar_filename(Path("/films/Film"), "de", True, ".srt")
        assert "forced" in name, f"'forced' fehlt in: {name}"

    def test_output_stem_nicht_input_stem(self):
        """Sidecars verwenden den Output-Stem, nicht den Input-Stem."""
        from dragontools.worker.subtitle_sidecar_service import sidecar_filename
        # Input wäre z.B. "OriginalInput", Output "Film_DV_Remux"
        name = sidecar_filename(Path("/dst/Film_DV_Remux"), "de", False, ".ass")
        assert "Film_DV_Remux" in name
        assert "OriginalInput" not in name



def test_structured_result_marks_partial_export_as_incomplete(tmp_path):
    from dragontools.worker.subtitle_sidecar_service import SubtitleSidecarService

    svc = SubtitleSidecarService(
        ffmpeg_path="ffmpeg",
        subtitle_rules={"dv_extract_external_subs": True},
        log=lambda *_: None,
    )
    sub1 = _make_sub(3, "subrip", "deu")
    sub2 = _make_sub(4, "ass", "eng")
    mi = _make_mi([sub1, sub2])
    plan = MagicMock(external_streams=[sub1, sub2], burn_warnings=())
    calls = 0

    def fake_run(cmd, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            Path(cmd[-1]).write_text("ok", encoding="utf-8")
            return MagicMock(returncode=0, stderr=b"")
        return MagicMock(returncode=1, stderr=b"broken subtitle")

    with (
        patch("dragontools.worker.subtitle_sidecar_service.compute_subtitle_plan", return_value=plan),
        patch("dragontools.worker.subtitle_sidecar_service.run_tool", side_effect=fake_run),
    ):
        result = svc.export_sidecars_result(
            input_path="/src/input.mkv",
            output_base=tmp_path / "Film",
            media_info=mi,
        )

    assert result.expected_count == 2
    assert result.exported_count == 1
    assert result.complete is False
    assert len(result.failures) == 1
    assert result.failures[0].stream_index == 4
    assert "1/2" in result.failure_summary()


def test_sidecar_export_never_overwrites_existing_destination(tmp_path):
    from dragontools.worker.subtitle_sidecar_service import SubtitleSidecarService

    svc = SubtitleSidecarService(
        ffmpeg_path="ffmpeg",
        subtitle_rules={"dv_extract_external_subs": True},
        log=lambda *_: None,
    )
    sub = _make_sub(3, "subrip", "deu")
    mi = _make_mi([sub])
    plan = MagicMock(external_streams=[sub], burn_warnings=())
    existing = tmp_path / "Film.de.srt"
    existing.write_text("USER", encoding="utf-8")

    with (
        patch("dragontools.worker.subtitle_sidecar_service.compute_subtitle_plan", return_value=plan),
        patch("dragontools.worker.subtitle_sidecar_service.run_tool") as mock_run,
    ):
        result = svc.export_sidecars_result(
            input_path="/src/input.mkv",
            output_base=tmp_path / "Film",
            media_info=mi,
        )

    assert result.complete is False
    assert result.exported_paths == ()
    assert existing.read_text(encoding="utf-8") == "USER"
    mock_run.assert_not_called()


def test_abort_happens_before_unsupported_codec_is_reported():
    svc, _logs = TestSubtitleSidecarService()._svc()
    sub = _make_sub(9, "totally_unknown_subtitle_codec", "deu")
    mi = _make_mi([sub])
    plan = MagicMock()
    plan.external_streams = [sub]
    plan.burn_sub = None
    plan.burn_warnings = ()

    with patch("dragontools.worker.subtitle_sidecar_service.compute_subtitle_plan", return_value=plan):
        result = svc.export_sidecars_result(
            input_path="/src/input.mkv",
            output_base="/dst/Film",
            media_info=mi,
            abort_check=lambda: True,
        )

    assert result.aborted is True
    assert result.failures == ()
