# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QInputDialog, QMessageBox

from ..core.encoder_profile_override import profile_to_override
from ..core.models import normalize_override_dict


class ConvertWidgetQueueOverrideActionsMixin:

    def _encoder_profile_choices(self) -> list[tuple[str, dict]]:
        choices: list[tuple[str, dict]] = []
        for key, profile in sorted(self.profile_manager.data.items()):
            override = profile_to_override(
                key,
                profile,
                default_codec=self.default_codec,
            )
            if override:
                try:
                    label = self.profile_manager.profile_display_name(key, profile)
                except Exception:
                    label = f"{key}  -  {override.get('label', key)}"
                choices.append((label, override))
        return choices

    def _assign_encoder_profile(self, path: str) -> None:
        if not self._guard_queue_edit_allowed("Encoder-Profil aendern"):
            return

        choices = self._encoder_profile_choices()
        if not choices:
            QMessageBox.information(
                self,
                "Keine Profile",
                "Für diesen Codec sind keine passenden Encoder-Profile vorhanden.",
            )
            return

        reset_label = "Globales Profil verwenden"
        labels = [reset_label] + [label for label, _override in choices]
        current_profile = normalize_override_dict(
            self._state.file_overrides.get(path, {})
        ).get("encoder_profile")
        current_key = (
            current_profile.get("key")
            if isinstance(current_profile, dict)
            else ""
        )
        current_index = 0
        if current_key:
            for idx, (_label, override) in enumerate(choices, start=1):
                if override.get("key") == current_key:
                    current_index = idx
                    break

        item, ok = QInputDialog.getItem(
            self,
            "Encoder-Profil für Datei",
            Path(path).name,
            labels,
            current=current_index,
            editable=False,
        )
        if not ok:
            return

        ov = dict(self._state.file_overrides.get(path) or {})
        selected_label = ""
        if item == reset_label:
            ov.pop("encoder_profile", None)
        else:
            selected = choices[labels.index(item) - 1][1]
            ov["encoder_profile"] = dict(selected)
            selected_label = selected.get("label") or selected.get("key") or ""

        if self._state.thread and hasattr(self._state.thread, "update_override"):
            accepted = self._state.thread.update_override(path, ov)
            if not accepted:
                QMessageBox.warning(
                    self,
                    "Profil abgelehnt",
                    f"'{Path(path).name}' wird gerade verarbeitet\n"
                    "oder ist bereits abgeschlossen.\n\n"
                    "Das Profil kann nur für noch nicht gestartete Dateien gesetzt werden.",
                )
                return

        self._state.file_overrides[path] = ov
        self.update_queue_label(path)
        if selected_label:
            self._log(f"Encoder-Profil für Datei gesetzt: {Path(path).name} -> {selected_label}", "info")
        else:
            self._log(f"Encoder-Profil für Datei entfernt: {Path(path).name}", "info")

    def _toggle_strip_only(self, paths: str | tuple[str, ...] | list[str]) -> None:
        if not self._guard_queue_edit_allowed("Strip-Only-Override aendern"):
            return
        raw_paths = [paths] if isinstance(paths, str) else list(paths or ())
        selected = list(dict.fromkeys(str(path) for path in raw_paths if path))
        if not selected:
            return

        # Gemischte Auswahl -> alles aktivieren. Nur wenn bereits alle markierten
        # Dateien Strip-Only sind, schaltet die Aktion die gesamte Auswahl aus.
        all_enabled = all(
            normalize_override_dict(self._state.file_overrides.get(path, {})).get("processing_mode") == "strip_only"
            for path in selected
        )
        enable = not all_enabled
        rejected: list[str] = []
        applied: list[str] = []

        for path in selected:
            ov = dict(self._state.file_overrides.get(path) or {})
            if enable:
                ov["processing_mode"] = "strip_only"
            else:
                ov.pop("processing_mode", None)

            if self._state.thread and hasattr(self._state.thread, "update_override"):
                if not self._state.thread.update_override(path, ov):
                    rejected.append(path)
                    continue

            self._state.file_overrides[path] = ov
            getattr(self._state, "preflight_rows_by_path", {}).pop(path, None)
            self.update_queue_label(path)
            applied.append(path)

        if applied:
            state_text = "aktiviert" if enable else "deaktiviert"
            if len(applied) == 1:
                detail = Path(applied[0]).name
            else:
                detail = f"{len(applied)} markierte Dateien"
            self._log(f"Strip-Only {state_text}: {detail}", "info")

        if rejected:
            preview = "\n".join(f"• {Path(path).name}" for path in rejected[:8])
            more = f"\n… und {len(rejected) - 8} weitere" if len(rejected) > 8 else ""
            QMessageBox.warning(
                self,
                "Override teilweise abgelehnt",
                "Strip-Only kann nur für noch nicht gestartete Dateien gesetzt werden.\n\n"
                f"Nicht geändert:\n{preview}{more}",
            )

    def _toggle_imax(self, path: str) -> None:
        if not self._guard_queue_edit_allowed("IMAX-Override aendern"):
            return
        ov = dict(self._state.file_overrides.get(path) or {})
        ov["imax"] = not ov.get("imax", False)
        if self._state.thread and hasattr(self._state.thread, "update_override"):
            ok = self._state.thread.update_override(path, ov)
            if not ok:
                QMessageBox.warning(
                    self,
                    "Override abgelehnt",
                    f"'{Path(path).name}' wird gerade verarbeitet\n"
                    "oder ist bereits abgeschlossen.\n\n"
                    "IMAX-Override kann nur f\u00fcr noch nicht gestartete Dateien gesetzt werden.",
                )
                return
        self._state.file_overrides[path] = ov
        self.update_queue_label(path)

    def _edit_override(self, paths) -> None:
        if not self._guard_queue_edit_allowed("Datei-Einstellungen aendern"):
            return
        self._override_dialog.edit_override(paths)
