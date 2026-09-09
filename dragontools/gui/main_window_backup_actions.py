# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import QInputDialog, QLineEdit, QMessageBox


class MainWindowBackupActionsMixin:
    def _export_backup(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        from ..core.settings_backup import (
            SECRET_MODE_ENCRYPTED,
            SECRET_MODE_EXCLUDED,
            default_backup_path,
            export_backup,
        )

        choice = QMessageBox(self)
        choice.setIcon(QMessageBox.Icon.Question)
        choice.setWindowTitle("DragonTools-Backup")
        choice.setText("Wie sollen sensible Zugangsdaten behandelt werden?")
        choice.setInformativeText(
            "Ohne Keys ist die empfohlene Standardoption. "
            "Verschlüsselt speichert API-Keys, Tokens und PIN geschützt mit einem Passwort."
        )
        without_btn = choice.addButton("Ohne Keys (empfohlen)", QMessageBox.ButtonRole.AcceptRole)
        encrypted_btn = choice.addButton("Verschlüsselt inkl. Keys", QMessageBox.ButtonRole.ActionRole)
        choice.addButton(QMessageBox.StandardButton.Cancel)
        choice.exec()

        clicked = choice.clickedButton()
        if clicked is not without_btn and clicked is not encrypted_btn:
            return

        secret_mode = SECRET_MODE_EXCLUDED
        password = None
        if clicked is encrypted_btn:
            password, ok = QInputDialog.getText(
                self,
                "Backup-Passwort",
                "Passwort für das verschlüsselte Backup (mindestens 8 Zeichen):",
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                return
            if len(password) < 8:
                QMessageBox.warning(self, "Backup-Passwort", "Das Passwort muss mindestens 8 Zeichen lang sein.")
                return
            confirm, ok = QInputDialog.getText(
                self,
                "Backup-Passwort bestätigen",
                "Passwort erneut eingeben:",
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                return
            if confirm != password:
                QMessageBox.warning(self, "Backup-Passwort", "Die Passwörter stimmen nicht überein.")
                return
            secret_mode = SECRET_MODE_ENCRYPTED

        suggested = str(default_backup_path())
        path, _ = QFileDialog.getSaveFileName(
            self,
            "DragonTools-Backup exportieren",
            suggested,
            "DragonTools Backup (*.zip);;Alle Dateien (*)",
        )
        if not path:
            return
        try:
            backup_path = export_backup(
                path,
                settings=self._settings,
                secret_mode=secret_mode,
                password=password,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Backup fehlgeschlagen", str(exc))
            return

        protection = (
            "verschlüsselt inklusive API-Keys/Tokens/PIN"
            if secret_mode == SECRET_MODE_ENCRYPTED
            else "ohne API-Keys/Tokens/PIN"
        )
        QMessageBox.information(
            self,
            "Backup erstellt",
            f"Backup wurde erstellt ({protection}):\n{backup_path}",
        )

    def _restore_backup(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        from ..core.paths import invalidate_tool_paths
        from ..core.settings_backup import (
            InvalidBackupPassword,
            SECRET_MODE_ENCRYPTED,
            SECRET_MODE_LEGACY_PLAINTEXT,
            default_backup_path,
            export_backup,
            inspect_backup,
            restore_backup,
        )

        path, _ = QFileDialog.getOpenFileName(
            self,
            "DragonTools-Backup wiederherstellen",
            str(default_backup_path().parent),
            "DragonTools Backup (*.zip);;Alle Dateien (*)",
        )
        if not path:
            return

        try:
            backup_info = inspect_backup(path)
        except Exception as exc:
            QMessageBox.critical(self, "Backup ungültig", str(exc))
            return

        password = None
        restore_legacy_plaintext_secrets = True
        if backup_info.get("requires_password"):
            password, ok = QInputDialog.getText(
                self,
                "Verschlüsseltes Backup",
                "Passwort für die im Backup enthaltenen Zugangsdaten:",
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                return
        elif backup_info.get("secret_mode") == SECRET_MODE_LEGACY_PLAINTEXT:
            legacy_choice = QMessageBox(self)
            legacy_choice.setIcon(QMessageBox.Icon.Warning)
            legacy_choice.setWindowTitle("Legacy-Backup mit Klartext-Zugangsdaten")
            legacy_choice.setText(
                "Dieses alte Backup kann API-Keys, Tokens oder PINs im Klartext enthalten."
            )
            legacy_choice.setInformativeText(
                "Sollen diese alten Zugangsdaten übernommen werden, oder sollen die lokal "
                "aktuell gespeicherten Zugangsdaten behalten werden?"
            )
            keep_btn = legacy_choice.addButton(
                "Lokale Zugangsdaten behalten",
                QMessageBox.ButtonRole.AcceptRole,
            )
            import_btn = legacy_choice.addButton(
                "Alte Zugangsdaten übernehmen",
                QMessageBox.ButtonRole.ActionRole,
            )
            legacy_choice.addButton(QMessageBox.StandardButton.Cancel)
            legacy_choice.exec()
            clicked = legacy_choice.clickedButton()
            if clicked is keep_btn:
                restore_legacy_plaintext_secrets = False
            elif clicked is import_btn:
                restore_legacy_plaintext_secrets = True
            else:
                return

        if backup_info.get("secret_mode") == SECRET_MODE_ENCRYPTED:
            secret_hint = "\nDas Backup enthält verschlüsselte API-Keys/Tokens/PINs."
        elif backup_info.get("secret_mode") == SECRET_MODE_LEGACY_PLAINTEXT:
            secret_hint = (
                "\nLegacy-Backup: alte Klartext-Zugangsdaten werden übernommen."
                if restore_legacy_plaintext_secrets
                else "\nLegacy-Backup: lokale API-Keys/Tokens/PINs bleiben erhalten."
            )
        else:
            secret_hint = "\nNicht im Backup enthaltene API-Keys/Tokens/PINs bleiben lokal unverändert."
        res = QMessageBox.question(
            self,
            "Backup wiederherstellen",
            "Aktuelle Einstellungen, Regeln und Profile werden durch das Backup ersetzt.\n"
            f"{secret_hint}\n\n"
            "Vorher wird automatisch ein Sicherheitsbackup ohne Keys erstellt.\n\n"
            "Fortfahren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        try:
            safety_path = export_backup(
                default_backup_path(prefix="DragonTools_vor_Restore"),
                settings=self._settings,
            )
            result = restore_backup(
                path,
                settings=self._settings,
                clear_settings=True,
                password=password,
                restore_legacy_plaintext_secrets=restore_legacy_plaintext_secrets,
            )
            invalidate_tool_paths()
            self._reload_all_paths()
        except InvalidBackupPassword as exc:
            QMessageBox.critical(self, "Restore fehlgeschlagen", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Restore fehlgeschlagen", str(exc))
            return

        restored_count = len(result.get("restored_files") or [])
        QMessageBox.information(
            self,
            "Backup wiederhergestellt",
            "Backup wurde wiederhergestellt.\n\n"
            f"Wiederhergestellte Dateien: {restored_count}\n"
            f"Sicherheitsbackup vorher: {safety_path}\n\n"
            "Ein Neustart von Dragon Tools ist nach einem Restore sinnvoll.",
        )

    def _create_diagnostic_package(self):
        from PyQt6.QtWidgets import QFileDialog
        from ..core.diagnostic_package import (
            create_diagnostic_package,
            default_diagnostic_package_path,
        )

        suggested = str(default_diagnostic_package_path())
        path, _ = QFileDialog.getSaveFileName(
            self,
            "DragonTools-Diagnosepaket erstellen",
            suggested,
            "DragonTools Diagnosepaket (*.zip);;Alle Dateien (*)",
        )
        if not path:
            return
        try:
            package_path = create_diagnostic_package(path, settings=self._settings)
        except Exception as exc:
            QMessageBox.critical(self, "Diagnosepaket fehlgeschlagen", str(exc))
            return
        QMessageBox.information(
            self,
            "Diagnosepaket erstellt",
            "Diagnosepaket wurde erstellt:\n"
            f"{package_path}\n\n"
            "Hinweis: Das Paket enthält lokale Pfade und Dateinamen aus Logs.",
        )
