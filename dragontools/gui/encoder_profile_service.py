# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.audit_log import append_audit_event


class EncoderProfileService:
    def __init__(self, *, profile_manager, parent_widget, log) -> None:
        self._profile_manager = profile_manager
        self._parent_widget = parent_widget
        self._log = log

    def save_profile_dialog(self, payload: dict) -> None:
        from PyQt6.QtWidgets import QInputDialog, QMessageBox

        display_choices = self._profile_manager.user_display_choices()
        display_to_key = {display: key for display, key in display_choices}
        item, ok = QInputDialog.getItem(
            self._parent_widget,
            "Profil speichern",
            "Profilname (eigener Name):",
            list(display_to_key.keys()),
            editable=True,
        )
        if not ok or not str(item).strip():
            return
        payload = dict(payload or {})
        item = str(item).strip()
        if item in display_to_key:
            key = display_to_key[item]
            label = self._profile_manager.profile_label(key)
        else:
            label = item
            payload["label"] = label
            key = self._profile_manager.key_for_user_label(label, payload)
        if self._profile_manager.is_builtin(key):
            QMessageBox.warning(
                self._parent_widget,
                "Nicht erlaubt",
                "Standard-Profile können nicht überschrieben werden.\nBitte einen anderen Namen wählen.",
            )
            return
        payload["label"] = label
        self._profile_manager.set(key, payload)
        display = self._profile_manager.profile_display_name(key, payload)
        self._log("💾 Profil '" + display + "' gespeichert.")
        append_audit_event("Profil gespeichert", f"{display} | Schlüssel: {key}")

    def load_profile_dialog(self) -> dict | None:
        from PyQt6.QtWidgets import QMessageBox, QInputDialog

        display_choices = self._profile_manager.user_display_choices()
        display_to_key = {display: key for display, key in display_choices}
        if not display_to_key:
            QMessageBox.information(
                self._parent_widget,
                "Eigene Profile",
                "Noch keine eigenen Profile gespeichert.\n\nKlicke auf 'Profil speichern' um die aktuellen\nEinstellungen als Profil zu sichern.",
            )
            return None
        item, ok = QInputDialog.getItem(
            self._parent_widget,
            "Profil laden",
            "Eigenes Profil:",
            list(display_to_key.keys()),
            editable=False,
        )
        if not ok:
            return None
        key = display_to_key.get(item)
        if not key:
            return None
        profile = self._profile_manager.get(key)
        if profile:
            display = self._profile_manager.profile_display_name(key, profile)
            self._log(f"📂 Profil '{display}' geladen.")
            append_audit_event("Profil geladen", f"{display} | Schlüssel: {key}")
        return profile

    def assistant_profile_dialog(self, codec: str) -> dict | None:
        import copy

        from PyQt6.QtWidgets import QInputDialog, QMessageBox

        from ..core.codec_profile_assistant import assistant_profiles_for_codec

        choices = assistant_profiles_for_codec(codec)
        if not choices:
            QMessageBox.information(
                self._parent_widget,
                "Profil-Assistent",
                "Für diesen Codec sind keine Assistenten-Profile hinterlegt.",
            )
            return None

        display_map = {
            f"{choice.label}  -  {choice.description}": choice
            for choice in choices
        }
        item, ok = QInputDialog.getItem(
            self._parent_widget,
            "Profil-Assistent",
            "Empfohlenes Startprofil:",
            list(display_map.keys()),
            editable=False,
        )
        if not ok:
            return None
        choice = display_map.get(item)
        if choice is None:
            return None
        profile = copy.deepcopy(choice.profile)
        profile["_assistant_key"] = choice.key
        self._log(f"🧭 Profil-Assistent: '{choice.label}' angewendet.")
        append_audit_event("Profil-Assistent angewendet", f"{choice.label} | Schlüssel: {choice.key}")
        return profile
