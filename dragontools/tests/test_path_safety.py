# -*- coding: utf-8 -*-
"""Tests für core/path_safety.py"""
from pathlib import Path

import pytest

from dragontools.core.path_safety import is_safe_subpath, safe_unlink, safe_rmtree


@pytest.fixture()
def tmp(tmp_path):
    return tmp_path


class TestIsSafeSubpath:
    def test_direktes_kind_ist_sicher(self, tmp):
        child = tmp / "datei.mkv"
        child.touch()
        assert is_safe_subpath(tmp, child) is True

    def test_tiefes_kind_ist_sicher(self, tmp):
        deep = tmp / "a" / "b" / "c.mkv"
        deep.parent.mkdir(parents=True)
        deep.touch()
        assert is_safe_subpath(tmp, deep) is True

    def test_elternverzeichnis_ist_unsicher(self, tmp):
        assert is_safe_subpath(tmp, tmp.parent) is False

    def test_geschwister_ist_unsicher(self, tmp_path):
        base = tmp_path / "base"
        base.mkdir()
        other = tmp_path / "other"
        other.mkdir()
        assert is_safe_subpath(base, other) is False

    def test_pfad_traversal_mit_dotdot(self, tmp):
        traversal = tmp / ".." / "irgendwas"
        assert is_safe_subpath(tmp, traversal) is False

    def test_root_als_basis_ist_immer_unsicher(self, tmp):
        root = Path(tmp.anchor)
        assert is_safe_subpath(root, tmp) is False

    def test_nicht_existierende_basis_ist_unsicher(self, tmp):
        ghost_base = tmp / "ghost_dir_existiert_nicht"
        child = ghost_base / "datei.mkv"
        assert is_safe_subpath(ghost_base, child) is False


class TestSafeUnlink:
    def test_loescht_datei_im_basisverzeichnis(self, tmp):
        f = tmp / "test.mkv"
        f.write_text("daten")
        assert safe_unlink(tmp, f) is True
        assert not f.exists()

    def test_loescht_keine_datei_ausserhalb(self, tmp_path):
        base = tmp_path / "base"
        base.mkdir()
        outside = tmp_path / "geheim.mkv"
        outside.write_text("sensitiv")
        assert safe_unlink(base, outside) is False
        assert outside.exists()

    def test_verzeichnis_wird_nicht_geloescht(self, tmp):
        d = tmp / "unterverzeichnis"
        d.mkdir()
        assert safe_unlink(tmp, d) is False
        assert d.exists()

    def test_nicht_vorhandene_datei_gibt_true(self, tmp):
        # safe_unlink verwendet missing_ok=True - eine bereits nicht-vorhandene
        # Datei gilt als erfolgreich entfernt (idempotentes Löschen).
        missing = tmp / "existiert_nicht.mkv"
        assert safe_unlink(tmp, missing) is True


class TestSafeRmtree:
    def test_loescht_unterverzeichnis(self, tmp):
        d = tmp / "temp_dir"
        d.mkdir()
        (d / "datei.txt").write_text("x")
        assert safe_rmtree(tmp, d) is True
        assert not d.exists()

    def test_loescht_nichts_ausserhalb(self, tmp_path):
        base = tmp_path / "base"
        base.mkdir()
        outside = tmp_path / "wichtig"
        outside.mkdir()
        assert safe_rmtree(base, outside) is False
        assert outside.exists()

    def test_datei_statt_verzeichnis_gibt_false(self, tmp):
        f = tmp / "datei.txt"
        f.write_text("x")
        assert safe_rmtree(tmp, f) is False
