# -*- coding: utf-8 -*-
"""Table state and proposal presentation for the movie/series renamer."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QTableWidgetItem

from ..core.movie_renamer import (
    MovieRenameProposal,
    RenameProposal,
    SeriesRenameProposal,
    build_series_target_filename,
    build_target_filename,
    parse_movie_release_name,
    parse_series_release_name,
    sanitize_filename_part,
)
from ..core.paths import path_compare_key
from ..rules.renamer_rules import manual_review_below
from .movie_renamer_view import WideCandidateComboBox


class RenamerColumns:
    ACCEPT = 0
    STATUS = 1
    TYPE = 2
    SOURCE = 3
    QUERY = 4
    SERIES = 5
    YEAR = 6
    MATCH = 7
    SCORE = 8
    TARGET = 9
    HINTS = 10


class MovieRenamerTableController:
    def __init__(self, table) -> None:
        self.table = table
        self.columns = RenamerColumns

    def add_row(self, path: Path) -> None:
        movie_parsed = parse_movie_release_name(path)
        series_parsed = parse_series_release_name(path) if movie_parsed.is_probable_series else None
        row = self.table.rowCount()
        self.table.insertRow(row)

        accept = QTableWidgetItem("")
        accept.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        accept.setCheckState(Qt.CheckState.Unchecked)
        accept.setData(Qt.ItemDataRole.UserRole, {"path": str(path), "proposal": None})
        self.table.setItem(row, self.columns.ACCEPT, accept)

        self.set_item(row, self.columns.STATUS, "bereit", editable=False)
        self.set_item(row, self.columns.TYPE, "Serie" if series_parsed is not None else "Film", editable=False)
        self.set_item(row, self.columns.SOURCE, path.name, editable=False, tooltip=str(path))
        self.set_item(
            row,
            self.columns.QUERY,
            f"S{series_parsed.season:02d}E{series_parsed.episode:02d}"
            if series_parsed is not None
            else movie_parsed.query_title,
            editable=False,
        )
        self.set_item(row, self.columns.SERIES, series_parsed.series if series_parsed is not None else "", editable=False)
        self.set_item(row, self.columns.YEAR, str((series_parsed.year if series_parsed else movie_parsed.year) or ""), editable=False)
        self.set_item(row, self.columns.MATCH, "", editable=False)
        self.set_item(row, self.columns.SCORE, "", editable=False)
        self.set_item(row, self.columns.TARGET, "", editable=True)
        warnings = series_parsed.warnings if series_parsed is not None else movie_parsed.warnings
        self.set_item(row, self.columns.HINTS, "; ".join(warnings), editable=False)

    def prepare_manual_series_search(self, row: int, query: str) -> None:
        if row < 0 or row >= self.table.rowCount():
            return
        self.table.removeCellWidget(row, self.columns.MATCH)
        self.set_row_proposal(row, None)
        self.set_item(row, self.columns.SERIES, str(query or "").strip(), editable=False)
        self.set_item(row, self.columns.MATCH, "manuelle Suche …", editable=False)
        self.set_item(row, self.columns.SCORE, "", editable=False)
        self.set_status(row, "🔎 Suche")

    def on_proposal_ready(self, row: int, proposal: RenameProposal) -> None:
        if row < 0 or row >= self.table.rowCount():
            return
        self.set_row_proposal(row, proposal)
        self.set_item(row, self.columns.TYPE, "Serie" if isinstance(proposal, SeriesRenameProposal) else "Film", editable=False)
        self.set_item(row, self.columns.QUERY, self.proposal_query_text(proposal), editable=False)
        self.set_item(row, self.columns.SERIES, self.proposal_series_text(proposal), editable=False)
        self.set_item(row, self.columns.YEAR, str(proposal.parsed.year or ""), editable=False)
        if proposal.candidates:
            self.install_candidate_combo(row, proposal)
            self.apply_candidate(row, self.selected_candidate_index(proposal), update_combo=False)
            return

        self.table.removeCellWidget(row, self.columns.MATCH)
        self.set_item(row, self.columns.MATCH, "kein Treffer", editable=False)
        self.set_item(row, self.columns.SCORE, "", editable=False)
        fallback = proposal.target_name or build_target_filename(
            proposal.parsed.query_title,
            proposal.parsed.year,
            proposal.parsed.suffix,
        )
        self.set_item(row, self.columns.TARGET, fallback, editable=True)
        self.set_item(row, self.columns.HINTS, "; ".join(proposal.warnings), editable=False)
        self.set_status(row, self.status_label(proposal.status))

    def install_candidate_combo(self, row: int, proposal: RenameProposal) -> None:
        combo = WideCandidateComboBox(self.table)
        for idx, candidate in enumerate(proposal.candidates):
            label = getattr(candidate, "choice_label", getattr(candidate, "display_title", f"Treffer {idx + 1}"))
            combo.addItem(label, idx)
        combo.setCurrentIndex(self.selected_candidate_index(proposal))
        combo.currentIndexChanged.connect(lambda _idx, c=combo: self.on_candidate_combo_changed(c))
        self.table.setCellWidget(row, self.columns.MATCH, combo)

    def on_candidate_combo_changed(self, combo: QComboBox) -> None:
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, self.columns.MATCH) is combo:
                idx = combo.currentData()
                self.apply_candidate(row, int(idx if idx is not None else combo.currentIndex()), update_combo=False)
                return

    def apply_candidate(self, row: int, candidate_index: int, *, update_combo: bool = True) -> None:
        proposal = self.row_proposal(row)
        if proposal is None or not proposal.candidates:
            return
        index = max(0, min(int(candidate_index), len(proposal.candidates) - 1))
        selected = proposal.candidates[index]
        source_path = Path(self.row_path(row))

        warnings = list(self.base_candidate_warnings(proposal.warnings))
        if isinstance(proposal, SeriesRenameProposal):
            target_name = build_series_target_filename(
                selected.series,
                selected.season,
                selected.episode,
                selected.episode_title,
                proposal.parsed.suffix,
            )
            # Show what was parsed from the source in the Series column; the
            # online candidate remains visible in the dropdown.
            self.set_item(row, self.columns.SERIES, proposal.parsed.series, editable=False)
            year = selected.year or proposal.parsed.year
        else:
            target_name = build_target_filename(
                selected.title,
                selected.year or proposal.parsed.year,
                proposal.parsed.suffix,
            )
            year = selected.year or proposal.parsed.year

        target_path = source_path.with_name(target_name)
        target_exists = target_path.exists() and path_compare_key(target_path) != path_compare_key(source_path)
        status = "ok"
        if target_exists:
            status = "conflict"
            warnings.append("Zieldatei existiert bereits.")
        elif selected.score < manual_review_below():
            status = "manual_review"
            warnings.append("Treffer ist unsicher und sollte manuell geprüft werden.")

        updated = replace(
            proposal,
            selected=selected,
            target_name=target_name,
            target_path=target_path,
            status=status,
            confidence=selected.score,
            warnings=tuple(warnings),
            target_exists=target_exists,
        )
        self.set_row_proposal(row, updated)
        self.set_item(row, self.columns.YEAR, str(year or ""), editable=False)
        score_text = f"{int(round(selected.score * 100))} %"
        match_reason = str(getattr(selected, "match_reason", "") or "").strip()
        if match_reason:
            score_text += f" · {match_reason}"
        self.set_item(row, self.columns.SCORE, score_text, editable=False)
        self.set_item(row, self.columns.TARGET, target_name, editable=True)
        self.set_item(row, self.columns.HINTS, "; ".join(updated.warnings), editable=False)
        self.set_status(row, self.status_label(updated.status))
        if update_combo:
            combo = self.table.cellWidget(row, self.columns.MATCH)
            if isinstance(combo, QComboBox):
                combo.setCurrentIndex(index)

    @staticmethod
    def base_candidate_warnings(warnings: tuple[str, ...]) -> tuple[str, ...]:
        generated = {
            "Zieldatei existiert bereits.",
            "Treffer ist unsicher und sollte manuell geprüft werden.",
        }
        return tuple(item for item in warnings if item not in generated)

    @staticmethod
    def selected_candidate_index(proposal: RenameProposal) -> int:
        if proposal.selected is None:
            return 0
        for idx, candidate in enumerate(proposal.candidates):
            if candidate == proposal.selected:
                return idx
        return 0

    @staticmethod
    def proposal_query_text(proposal: RenameProposal) -> str:
        if isinstance(proposal, SeriesRenameProposal):
            return f"S{proposal.parsed.season:02d}E{proposal.parsed.episode:02d}"
        return proposal.parsed.query_title

    @staticmethod
    def proposal_series_text(proposal: RenameProposal) -> str:
        if isinstance(proposal, SeriesRenameProposal):
            return proposal.parsed.series
        return ""

    @staticmethod
    def status_label(status: str) -> str:
        return {
            "ok": "✅ Vorschlag",
            "manual_review": "⚠️ prüfen",
            "conflict": "⚠️ Konflikt",
            "no_match": "❌ kein Treffer",
            "not_movie": "🚫 Serie?",
            "not_series": "🚫 keine Serie",
        }.get(status, status)

    def collect_rename_problems(self, rows: list[int]) -> list[str]:
        problems: list[str] = []
        seen_targets: set[str] = set()
        for row in rows:
            source = Path(self.row_path(row))
            target_name = self.target_name(row)
            if not target_name:
                problems.append(f"{source.name}: kein Zielname angegeben.")
                continue
            if not Path(target_name).suffix:
                target_name += source.suffix
            cleaned = sanitize_filename_part(Path(target_name).stem) + Path(target_name).suffix
            target = source.with_name(cleaned)
            key = path_compare_key(target)
            if key in seen_targets:
                problems.append(f"{source.name}: Zielname mehrfach in der Liste.")
            seen_targets.add(key)
            if target.exists() and path_compare_key(target) != path_compare_key(source):
                problems.append(f"{source.name}: Ziel existiert bereits: {target.name}")
        return problems

    def known_path_keys(self) -> set[str]:
        return {
            path_compare_key(self.row_path(row))
            for row in range(self.table.rowCount())
            if self.row_path(row)
        }

    def selected_rows(self) -> list[int]:
        return sorted({index.row() for index in self.table.selectedIndexes()})

    def manual_series_search_selection(self) -> tuple[list[int], int, str]:
        selected = self.selected_rows()
        rows = [row for row in selected if self.row_item(row, self.columns.TYPE).text() == "Serie"]
        values = {self.row_item(row, self.columns.SERIES).text().strip() for row in rows}
        current = next(iter(values)) if len(values) == 1 else ""
        return rows, len(selected) - len(rows), current

    def row_item(self, row: int, col: int) -> QTableWidgetItem:
        item = self.table.item(row, col)
        if item is None:
            item = QTableWidgetItem("")
            self.table.setItem(row, col, item)
        return item

    def set_item(self, row: int, col: int, text: str, *, editable: bool, tooltip: str = "") -> None:
        item = self.row_item(row, col)
        item.setText(text)
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if editable:
            flags |= Qt.ItemFlag.ItemIsEditable
        item.setFlags(flags)
        if tooltip:
            item.setToolTip(tooltip)

    def set_status(self, row: int, text: str) -> None:
        self.set_item(row, self.columns.STATUS, text, editable=False)

    def row_meta(self, row: int) -> dict:
        item = self.row_item(row, self.columns.ACCEPT)
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            data = {"path": "", "proposal": None}
            item.setData(Qt.ItemDataRole.UserRole, data)
        return data

    def row_path(self, row: int) -> str:
        return str(self.row_meta(row).get("path") or "")

    def set_row_path(self, row: int, path: str | Path) -> None:
        meta = self.row_meta(row)
        meta["path"] = str(path)
        self.row_item(row, self.columns.ACCEPT).setData(Qt.ItemDataRole.UserRole, meta)
        self.set_item(row, self.columns.SOURCE, Path(path).name, editable=False, tooltip=str(path))

    def row_proposal(self, row: int) -> RenameProposal | None:
        proposal = self.row_meta(row).get("proposal")
        return proposal if isinstance(proposal, (MovieRenameProposal, SeriesRenameProposal)) else None

    def set_row_proposal(self, row: int, proposal: RenameProposal) -> None:
        meta = self.row_meta(row)
        meta["proposal"] = proposal
        self.row_item(row, self.columns.ACCEPT).setData(Qt.ItemDataRole.UserRole, meta)

    def row_accepted(self, row: int) -> bool:
        return self.row_item(row, self.columns.ACCEPT).checkState() == Qt.CheckState.Checked

    def set_row_accepted(self, row: int, accepted: bool) -> None:
        self.row_item(row, self.columns.ACCEPT).setCheckState(
            Qt.CheckState.Checked if accepted else Qt.CheckState.Unchecked
        )

    def target_name(self, row: int) -> str:
        source = Path(self.row_path(row))
        raw = self.row_item(row, self.columns.TARGET).text().strip()
        if not raw:
            return ""
        target = Path(raw)
        suffix = target.suffix or source.suffix
        return sanitize_filename_part(target.stem) + suffix
