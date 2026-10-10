"""Completeness query workers and ownership across dialog close/start."""
from PyQt6.QtCore import QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication, QMessageBox

from ..core.online_metadata_config import config_from_settings
from ..core.renamer_completeness import recognized_series, completeness_targets, CompletenessResult
from ..core.renamer_completeness_provider import RenamerCompletenessService, CompletenessCancelled
from .qt_receiver_state import receiver_is_alive


class CompletenessThread(QThread):
    progress = pyqtSignal(str)

    def __init__(self, targets, config):
        super().__init__(QApplication.instance())
        self.setObjectName("Serien-Vollständigkeit prüfen")
        self.targets = tuple(targets)
        self.config = config
        self.results = []

    def run(self):
        service = RenamerCompletenessService(self.config)
        for target in self.targets:
            if self.isInterruptionRequested():
                break
            self.progress.emit(target.label)
            try:
                results = service.check(target, cancelled=self.isInterruptionRequested)
            except CompletenessCancelled:
                break
            except Exception as exc:
                results = (CompletenessResult(target.series.hit, target.season, "Nicht prüfbar", note=str(exc)),)
            self.results.extend(results)


class CompletenessDialogRuntimeMixin:
    def start_check(self):
        if self.worker is not None or self.closed:
            return
        targets = self.selected_targets()
        if not targets:
            self.status.setText("Bitte mindestens eine Serie oder Staffel auswählen.")
            return
        self.report = ()
        self.results_table.setRowCount(0)
        self.set_busy(True)
        self.status.setText("Metadatenquelle wird aktuell abgefragt …")
        worker = CompletenessThread(targets, self.config)
        self.worker = worker
        worker.progress.connect(self.on_progress)
        worker.finished.connect(self.on_finished)
        try:
            if self.closed:
                raise RuntimeError("Prüfung wurde vor dem Start abgebrochen.")
            worker.start()
        except Exception as exc:
            if not worker.isRunning():
                self.worker = None
                worker.deleteLater()
                self.set_busy(False)
            self.status.setText(f"Prüfung konnte nicht starten: {exc}")

    @pyqtSlot(str)
    def on_progress(self, label):
        if not self.closed:
            self.status.setText(f"Prüfe {label} …")

    @pyqtSlot()
    def on_finished(self):
        worker = self.worker
        if worker is None:
            return
        if worker.isRunning():
            QTimer.singleShot(10, self.on_finished)
            return
        self.worker = None
        worker.deleteLater()
        if self.closed:
            return
        self.report = tuple(worker.results)
        self.set_busy(False)
        self.present_report()
        complete = sum(row.status == "Vollständig" for row in self.report)
        unknown = sum(row.status == "Nicht prüfbar" for row in self.report)
        self.status.setText(f"{len(self.report)} Ergebnis(se): {complete} vollständig, "
                            f"{len(self.report) - complete - unknown} unvollständig/fehlend, {unknown} nicht prüfbar.")

    def iter_shutdown_workers(self):
        return (self.worker,) if self.worker is not None else ()

    def done(self, result):
        self.closed = True
        if self.worker is not None:
            self.worker.requestInterruption()
        super().done(result)

    def closeEvent(self, event):
        self.closed = True
        if self.worker is not None:
            self.worker.requestInterruption()
        super().closeEvent(event)


class MovieRenamerCompletenessController:
    def __init__(self, owner, table_controller):
        self.owner = owner
        self.table_controller = table_controller
        self.dialogs = []

    def open(self, *, whole_series=False):
        from .movie_renamer_completeness_dialog import MovieRenamerCompletenessDialog

        retained = []
        for dialog in self.dialogs:
            if not receiver_is_alive(dialog):
                continue
            if dialog.closed and dialog.worker is None:
                dialog.deleteLater()
            else:
                retained.append(dialog)
        self.dialogs = retained
        for dialog in self.dialogs:
            if not dialog.closed:
                dialog.raise_()
                dialog.activateWindow()
                return dialog
        proposals = (self.table_controller.row_proposal(row)
                     for row in range(self.table_controller.table.rowCount()))
        series = recognized_series(proposals)
        targets = completeness_targets(series, whole_series=whole_series)
        if not targets:
            QMessageBox.information(self.owner, "Vollständigkeit prüfen",
                "Keine erkannte Serie mit TMDB-/TheTVDB-Zuordnung vorhanden. "
                "Bitte zuerst Metadaten-Vorschläge laden und den passenden Treffer auswählen.")
            return None
        config = config_from_settings(self.owner.settings, require_enabled=False)
        dialog = MovieRenamerCompletenessDialog(targets, config, self.owner, whole_series=whole_series)
        self.dialogs.append(dialog)
        dialog.show()
        return dialog

    def iter_shutdown_workers(self):
        return tuple(worker for dialog in self.dialogs if receiver_is_alive(dialog)
                     for worker in dialog.iter_shutdown_workers())

    def shutdown(self):
        workers = self.iter_shutdown_workers()
        for worker in workers:
            worker.requestInterruption()
        return not any(worker.isRunning() for worker in workers)
