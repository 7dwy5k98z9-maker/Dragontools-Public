"""Local source selection and explicit episode/movie mapping state."""
from dataclasses import replace
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox, QTableWidgetItem
from ..core.path_syntax import path_compare_key, is_video_file
from ..core.renamer_metadata_browser import (ExplicitMovieFileMapping, ExplicitSeriesFileMapping,
    ExplicitFileMapping, MetadataBrowserEpisode, natural_path_key, dedupe_paths)
from .drop_path_files import iter_video_files_in_folder


class RenamerBrowserMappingMixin:
    def _selected_source_paths(self) -> list[str]:
        return [
            str(item.data(Qt.ItemDataRole.UserRole) or "")
            for item in self.source_list.selectedItems()
            if str(item.data(Qt.ItemDataRole.UserRole) or "")
        ]

    def _assign_selected(self) -> None:
        if self._busy:
            self.status.setText("Bitte die laufende Metadaten-Abfrage abwarten.")
            return
        paths = self._selected_source_paths()
        if not paths:
            QMessageBox.information(self, "Zuordnung", "Bitte zuerst lokale Datei(en) markieren.")
            return
        if self._kind() == "movie":
            hit = self._current_movie_hit
            if hit is None or hit.kind != "movie":
                QMessageBox.information(
                    self,
                    "Filmzuordnung",
                    "Bitte zuerst einen Film-Treffer markieren und mit 'Film auswählen' aktivieren.",
                )
                return
            if len(paths) != 1:
                QMessageBox.information(
                    self,
                    "Filmzuordnung",
                    "Bitte genau eine lokale Datei markieren. Ein Film-Treffer darf nicht versehentlich "
                    "mehreren Dateien mit demselben Zielnamen zugeordnet werden.",
                )
                return
            path = paths[0]
            key = path_compare_key(path)
            self._series_mappings.pop(key, None)
            self._movie_mappings[key] = ExplicitMovieFileMapping(Path(path), hit)
            self._refresh_source_labels()
            self._refresh_episode_mapping_column()
            self.status.setText(f"1 Datei → {hit.display_title} zugeordnet.")
            return
        row = self.episode_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Episodenzuordnung", "Bitte eine Ziel-Episode markieren.")
            return
        self._assign_paths_to_episode(paths, row)

    def _drop_assign_to_episode(self, paths: list[str], row: int) -> None:
        # Always expand folders before deciding which paths shall be mapped.
        # This also makes a second drop of an already imported folder useful:
        # add_source_paths() returns no *new* entries in that case, but the
        # contained video files must still be assignable to the target episode.
        expanded: list[str] = []
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                files, _ignored = iter_video_files_in_folder(str(path))
                expanded.extend(files)
            elif is_video_file(path):
                expanded.append(str(path))
        usable = sorted(dedupe_paths(expanded), key=natural_path_key)
        self.add_source_paths(paths)
        if usable:
            self._assign_paths_to_episode(usable, row)

    def _assign_paths_to_episode(self, paths: list[str], start_row: int) -> None:
        if self._busy:
            self.status.setText("Bitte die laufende Metadaten-Abfrage abwarten.")
            return
        if self._current_series_hit is None or not self._episodes:
            QMessageBox.information(self, "Episodenzuordnung", "Bitte zuerst eine Serie und Staffel laden.")
            return
        span = int(self.span_spin.value())
        row = int(start_row)
        assigned = 0
        for path in paths:
            if row < 0 or row >= len(self._episodes):
                break
            end = row + span
            if end > len(self._episodes):
                QMessageBox.warning(self, "Mehrfachfolge", "Die Mehrfachfolge würde über das Staffelende hinausgehen.")
                break
            selected = tuple(self._episodes[row:end])
            if any(item.season != selected[0].season for item in selected):
                QMessageBox.warning(self, "Mehrfachfolge", "Mehrfachfolgen dürfen keine Staffelgrenze überschreiten.")
                break
            conflict = self._mapping_conflict(path, selected)
            if conflict:
                QMessageBox.warning(self, "Episodenzuordnung", conflict)
                break
            key = path_compare_key(path)
            try:
                mapping = ExplicitSeriesFileMapping(
                    source_path=Path(path),
                    hit=self._current_series_hit,
                    season=selected[0].season,
                    episodes=selected,
                    title_mode=str(self.title_mode_combo.currentData() or "all"),
                )
            except ValueError as exc:
                # Providers can occasionally expose gaps/non-standard numbering.
                # Treat that as a user-visible mapping problem, not as an uncaught
                # Qt slot exception.
                QMessageBox.warning(self, "Episodenzuordnung", str(exc))
                break
            # Replace an older assignment only after the new mapping has been
            # validated successfully.  A bad provider span must not destroy a
            # previously valid manual mapping.
            self._movie_mappings.pop(key, None)
            self._series_mappings.pop(key, None)
            self._series_mappings[key] = mapping
            assigned += 1
            row += span
        self._refresh_source_labels()
        self._refresh_episode_mapping_column()
        self.status.setText(f"{assigned} Datei(en) explizit zugeordnet.")

    def _mapping_conflict(self, source_path: str, episodes: tuple[MetadataBrowserEpisode, ...]) -> str:
        target_numbers = {item.episode for item in episodes}
        source_key = path_compare_key(source_path)
        for key, mapping in self._series_mappings.items():
            if key == source_key:
                continue
            if mapping.hit.provider != self._current_series_hit.provider or mapping.hit.provider_id != self._current_series_hit.provider_id:
                continue
            if mapping.season != episodes[0].season:
                continue
            occupied = {item.episode for item in mapping.episodes}
            overlap = sorted(target_numbers & occupied)
            if overlap:
                return (
                    f"E{overlap[0]:02d} ist bereits '{Path(mapping.source_path).name}' zugeordnet. "
                    "Zuordnung zuerst lösen oder auf eine freie Episode verschieben."
                )
        return ""

    def _auto_assign(self) -> None:
        if self._busy:
            self.status.setText("Bitte die laufende Metadaten-Abfrage abwarten.")
            return
        if self._kind() != "series" or not self._episodes:
            return
        row = self.episode_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Automatisch zuordnen", "Bitte die Start-Episode markieren.")
            return
        paths = [
            str(self.source_list.item(i).data(Qt.ItemDataRole.UserRole) or "")
            for i in range(self.source_list.count())
        ]
        unmapped = [
            path
            for path in paths
            if path_compare_key(path) not in self._series_mappings
            and path_compare_key(path) not in self._movie_mappings
        ]
        if not unmapped:
            self.status.setText("Alle lokalen Dateien sind bereits zugeordnet.")
            return
        old_span = self.span_spin.value()
        self.span_spin.setValue(1)
        try:
            self._assign_paths_to_episode(unmapped, row)
        finally:
            self.span_spin.setValue(old_span)

    def _clear_selected_mappings(self) -> None:
        paths = self._selected_source_paths()
        for path in paths:
            key = path_compare_key(path)
            self._series_mappings.pop(key, None)
            self._movie_mappings.pop(key, None)
        self._refresh_source_labels()
        self._refresh_episode_mapping_column()
        self.status.setText(f"{len(paths)} Zuordnung(en) gelöst.")

    def _clear_all_mappings(self) -> None:
        self._series_mappings.clear()
        self._movie_mappings.clear()
        self._refresh_source_labels()
        self._refresh_episode_mapping_column()
        self.status.setText("Alle Zuordnungen gelöscht.")

    def _remove_selected_sources(self) -> None:
        items = list(self.source_list.selectedItems())
        for item in items:
            path = str(item.data(Qt.ItemDataRole.UserRole) or "")
            key = path_compare_key(path)
            self._series_mappings.pop(key, None)
            self._movie_mappings.pop(key, None)
            self.source_list.takeItem(self.source_list.row(item))
        self._refresh_episode_mapping_column()
        self.status.setText(f"{len(items)} lokale Datei(en) entfernt.")

    def _refresh_source_labels(self) -> None:
        title_mode = str(self.title_mode_combo.currentData() or "all")
        for i in range(self.source_list.count()):
            item = self.source_list.item(i)
            path = str(item.data(Qt.ItemDataRole.UserRole) or "")
            key = path_compare_key(path)
            base = Path(path).name
            series_mapping = self._series_mappings.get(key)
            movie_mapping = self._movie_mappings.get(key)
            if series_mapping is not None:
                eps = "".join(f"E{ep.episode:02d}" for ep in series_mapping.episodes)
                item.setText(f"{base}  →  S{series_mapping.season:02d}{eps}")
                if series_mapping.title_mode != title_mode:
                    self._series_mappings[key] = replace(series_mapping, title_mode=title_mode)
            elif movie_mapping is not None:
                item.setText(f"{base}  →  {movie_mapping.hit.display_title}")
            else:
                item.setText(base)

    def _refresh_episode_mapping_column(self) -> None:
        if not self._episodes or self._current_series_hit is None:
            return
        for row, episode in enumerate(self._episodes):
            names: list[str] = []
            for mapping in self._series_mappings.values():
                if mapping.hit.provider != self._current_series_hit.provider or mapping.hit.provider_id != self._current_series_hit.provider_id:
                    continue
                if mapping.season != episode.season:
                    continue
                if episode.episode in {item.episode for item in mapping.episodes}:
                    names.append(Path(mapping.source_path).name)
            item = self.episode_table.item(row, 3) or QTableWidgetItem("")
            item.setText("; ".join(names))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.episode_table.setItem(row, 3, item)

    def _accept_mappings(self) -> None:
        if self._busy:
            self.status.setText("Bitte die laufende Metadaten-Abfrage abwarten.")
            return
        self._refresh_source_labels()
        mappings: list[ExplicitFileMapping] = [*self._series_mappings.values(), *self._movie_mappings.values()]
        if not mappings:
            QMessageBox.information(self, "Metadaten-Browser", "Es sind noch keine Dateien zugeordnet.")
            return
        seen: set[str] = set()
        duplicates: list[str] = []
        for mapping in mappings:
            key = path_compare_key(mapping.source_path)
            if key in seen:
                duplicates.append(Path(mapping.source_path).name)
            seen.add(key)
        if duplicates:
            QMessageBox.warning(
                self,
                "Mehrdeutige Zuordnung",
                "Eine Datei darf nicht gleichzeitig als Film und Serie zugeordnet sein:\n" + "\n".join(duplicates[:10]),
            )
            return
        self._accepted_mappings = sorted(mappings, key=lambda value: natural_path_key(value.source_path))
        self.accept()

