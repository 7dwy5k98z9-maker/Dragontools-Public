# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication, QMessageBox

from .shortcut_dialog import ShortcutDialog
from ..core.paths import BASE, EXE_DIR
from ..core.settings import APP_VERSION
from ..core.update_check import UpdateCheckResult


class MainWindowHelpActionsMixin:
    def _open_help(self):
        from .help_dialog import HelpDialog
        HelpDialog(self).exec()

    def _find_handbook(self) -> Path | None:
        filename = "Handbuch.pdf"
        candidates = [
            BASE / "Handbuch" / filename,
            EXE_DIR / "Handbuch" / filename,
            EXE_DIR / "Daten" / "Handbuch" / filename,
            BASE / filename,
            EXE_DIR / filename,
            EXE_DIR / "Daten" / filename,
            Path(filename).resolve(),
        ]
        for path in candidates:
            if path.exists():
                return path.resolve()
        return None

    def _open_handbook(self):
        handbook_path = self._find_handbook()
        if handbook_path is None:
            QMessageBox.warning(
                self,
                "Handbuch nicht gefunden",
                "Das DragonTools-Handbuch wurde nicht gefunden.\n\n"
                "Erwartet wird Handbuch.pdf im Projektordner unter Handbuch "
                "oder im EXE-Bundle unter Daten\\Handbuch.",
            )
            return

        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(handbook_path))):
            QMessageBox.warning(
                self,
                "Handbuch konnte nicht geöffnet werden",
                f"Die Datei wurde gefunden, konnte aber nicht geöffnet werden:\n{handbook_path}",
            )

    def _open_shortcuts(self):
        ShortcutDialog(self._shortcut_entries(), self).exec()

    def _open_changelog(self):
        from .changelog_dialog import ChangelogDialog
        ChangelogDialog(self).exec()

    def _open_legacy_changelog(self):
        from .changelog_dialog import ChangelogDialog
        ChangelogDialog(self, version_key="v8").exec()

    def _open_url(self, url: str) -> None:
        import webbrowser
        webbrowser.open(url)

    def _check_for_updates(self, _checked: bool = False, *, manual: bool = True) -> None:
        """Prüft asynchron; Fehler beim automatischen Startcheck bleiben still."""
        from .update_checker import GitHubUpdateChecker

        current = getattr(self, "_github_update_checker", None)
        if current is not None and current.running:
            if manual:
                self.statusBar().showMessage("Die Updateprüfung läuft bereits.", 4000)
            return

        checker = GitHubUpdateChecker(self)
        self._github_update_checker = checker
        checker.finished.connect(
            lambda result, requested_manually=manual, owner=checker:
            self._handle_update_result(result, requested_manually, owner)
        )
        if manual:
            self.statusBar().showMessage("Suche nach einer neuen DragonTools-Version …")
        checker.start()

    def _check_for_updates_on_startup(self) -> None:
        # Recovery- und Erinnerungsdialoge haben beim Start Vorrang. Qt-Timer
        # laufen auch innerhalb eines modalen Dialogs weiter, daher verschieben
        # wir die Abfrage, bis kein anderer Dialog mehr geöffnet ist.
        if QApplication.activeModalWidget() is not None:
            QTimer.singleShot(3000, self._check_for_updates_on_startup)
            return
        self._check_for_updates(manual=False)

    def _handle_update_result(
        self,
        result: UpdateCheckResult,
        manual: bool,
        checker,
    ) -> None:
        checker.deleteLater()
        if getattr(self, "_github_update_checker", None) is checker:
            self._github_update_checker = None
        if manual:
            self.statusBar().clearMessage()

        if not result.ok:
            if manual:
                QMessageBox.information(
                    self,
                    "Updateprüfung",
                    "Es konnte momentan nicht nach Updates gesucht werden.\n\n"
                    f"{result.error}",
                )
            return

        release = result.release
        if release is None:
            if manual:
                QMessageBox.information(self, "Updateprüfung", "Es wurden keine Release-Daten gefunden.")
            return

        if not result.update_available:
            if manual:
                QMessageBox.information(
                    self,
                    "DragonTools ist aktuell",
                    f"Installierte Version: {APP_VERSION}\n"
                    f"Neueste Version: {release.version}",
                )
            return

        notes = release.notes.strip()
        if len(notes) > 1200:
            notes = notes[:1197].rstrip() + "…"
        details = f"\n\n{notes}" if notes else ""
        answer = QMessageBox.question(
            self,
            "DragonTools-Update verfügbar",
            f"Eine neue Version ist verfügbar.\n\n"
            f"Installiert: {APP_VERSION}\n"
            f"Verfügbar: {release.version}"
            f"{details}\n\n"
            "Möchtest du die Downloadseite jetzt öffnen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._open_url(release.page_url)

    def _about(self):
        from ..core.project_info import build_about_html

        QMessageBox.about(
            self,
            f"Dragon Tools V{APP_VERSION}",
            build_about_html(),
        )
