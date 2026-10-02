"""Year editing for film releases and series starts."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QInputDialog, QMessageBox

from ..core.movie_renamer import parse_movie_release_name
from ..core.movie_renamer_year_override import normalize_year_override


class MovieRenamerYearStateMixin:
    def row_year_override(self, row: int) -> int | None:
        return normalize_year_override(self.row_meta(row).get("year_override"))

    def set_row_year_override(self, row: int, value) -> None:
        year = normalize_year_override(value)
        meta = self.row_meta(row)
        meta["year_override"] = year
        self.row_item(row, self.columns.ACCEPT).setData(Qt.ItemDataRole.UserRole, meta)
        self.invalidate_row_proposal(row)
        parsed = parse_movie_release_name(self.row_path(row))
        effective_year = year if year is not None else parsed.year
        self.set_item(row, self.columns.YEAR, str(effective_year or ""), editable=False)
        self.set_item(row, self.columns.HINTS,
                      f"Suchjahr {year} manuell gesetzt." if year is not None else "Jahr aus Dateinamen verwenden.",
                      editable=False)
        self.set_status(row, "bereit")


class MovieRenamerYearPromptMixin:
    def edit_selected_year(self) -> None:
        rows = self.table_controller.selected_rows()
        if not rows:
            QMessageBox.information(self.owner, "Jahr ändern", "Bitte zuerst Film- oder Serien-Zeilen markieren.")
            return
        years = {
            str(self.table_controller.row_year_override(row) or
                self.table_controller.row_item(row, self.table_controller.columns.YEAR).text())
            for row in rows
        }
        value, ok = QInputDialog.getText(
            self.owner, "Jahr ändern",
            f"Jahr für {len(rows)} ausgewählte Datei(en):\n"
            "Film: Erscheinungsjahr · Serie: Startjahr der Serie\n"
            "Leer lassen: Jahr wieder aus dem Dateinamen übernehmen.",
            text=next(iter(years)) if len(years) == 1 else "",
        )
        if not ok:
            return
        try:
            year = normalize_year_override(value)
        except ValueError as exc:
            QMessageBox.warning(self.owner, "Ungültiges Jahr", str(exc))
            return
        for row in rows:
            self.table_controller.set_row_year_override(row, year)
        self.view.status_lbl.setText(
            f"Jahr für {len(rows)} Datei(en) angepasst; Metadaten werden neu gesucht."
        )
        self.resolver.rerun_rows(rows)
