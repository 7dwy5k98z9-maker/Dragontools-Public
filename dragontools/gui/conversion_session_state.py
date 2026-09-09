# -*- coding: utf-8 -*-
"""
dragontools/gui/conversion_session_state.py

Zentraler Laufzeitzustand einer Konvertierungs-Session.
Alle transienten Zustandsfelder, die früher direkt auf ConvertWidget lagen,
sind hier gebündelt. Keine PyQt6-Abhängigkeiten.
"""
from __future__ import annotations


class ConversionSessionState:
    """
    Kapselt den gesamten veränderlichen Zustand eines Konvertierungs-Laufs.

    Instanz wird einmalig in ConvertWidget erzeugt und per Dependency
    Injection an alle Controller weitergereicht.  Controller lesen und
    schreiben den State ausschließlich über diese Klasse – kein Zugriff
    über »owner«.
    """

    def __init__(self) -> None:
        # ── Per-Datei-Metadaten ─────────────────────────────────────
        self.file_overrides: dict[str, dict] = {}
        """Override-Einstellungen pro Eingabepfad  (path → override_dict)."""

        self.planned_targets: dict[str, object] = {}
        """Geplante Zielverzeichnisse für Verschieben  (path → target)."""

        self.restored_move_context: dict[str, object] = {}
        """Aus Move-Journal wiederhergestellter Kontext bis zum nächsten Move-Only-Lauf."""

        # ── Run-weite Zähler / Flags ────────────────────────────────
        self.fertig: set[str] = set()
        """Ausgabepfade erfolgreich abgeschlossener Dateien."""

        self.sidecar_outputs_by_video: dict[str, list[str]] = {}
        """Externe Begleitdateien (Subs) pro Videodatei  (output_path → [sidecar, …]).
        Wird von conversion_result_service befüllt, sobald ein Worker ✅ meldet.
        Leere Liste = Datei fertig, aber keine externen Subs erzeugt.
        """

        self.postprocess_outputs_by_input: dict[str, list[dict]] = {}
        """NFO-/Trickplay-Statusdaten pro Eingabedatei (input_path -> Details)."""

        self.pending_postprocess_inputs: set[str] = set()
        """Eingabepfade, deren NFO-/Trickplay-Nacharbeit noch nicht terminal gemeldet wurde."""

        self.finish_waiting_for_postprocess: bool = False
        """True, wenn der Worker fertig ist, die GUI aber noch Postprocessing-Ergebnisse abwartet."""

        self.preflight_rows_by_path: dict[str, dict] = {}
        """Zuletzt bekannte Preflight-/Regelvorschau pro Eingabepfad."""

        self.completed_inputs: set[str] = set()
        """Eingabepfade, die der Worker abgearbeitet hat (OK + Fehler)."""

        self.run_results: dict[str, dict] = {}
        """Terminale Ergebniszeilen des aktuellen Laufs (input_path -> Ergebnisdaten)."""

        self.move_report_log: list = []
        """Kumulierter Verschiebebericht für Zwischenverschiebungen."""

        self.move_ok_count: int = 0
        """Kumulierte Anzahl erfolgreich verschobener Videodateien."""

        self.move_error_count: int = 0
        """Kumulierte Anzahl fehlgeschlagener Verschiebeversuche."""

        self.pending_remove_paths: set[str] = set()
        """Pfade, die nach Worker-Abschluss aus der Liste entfernt werden."""

        self.total_files: int = 0
        """Gesamtzahl Dateien im aktuellen Run."""

        self.last_total_pct: int = 0
        """Letzter Gesamt-Prozentwert (verhindert Rücksprünge)."""

        self.active_file_progress: dict[str, int] = {}
        """Aktuelle Datei-Fortschritte im Parallelbetrieb  (input_path -> Prozent)."""

        self.active_file_eta: dict[str, object] = {}
        """Aktuelle ETA-Werte im Parallelbetrieb  (input_path -> Sekunden/None)."""

        self.progress_focus_path: str | None = None
        """Optional fokussierte Datei für die Fortschrittsanzeige; None = aktive gesamt."""

        self.current_log_path: str | None = None
        """Pfad zur aktiven Log-Datei des laufenden Workers."""

        self.job_journal = None
        """Aktives Job-Journal des aktuellen Laufs (oder None)."""

        self.job_journal_current_path: str | None = None
        """Zuletzt im Journal als laufend markierte Datei."""

        self.job_journal_current_paths: set[str] = set()
        """Alle im Journal aktuell als laufend markierten Dateien."""

        self.summary_written: bool = False
        """Schutz-Flag – verhindert doppeltes Schreiben der Run-Zusammenfassung."""

        # ── Worker-Referenzen ───────────────────────────────────────
        self.thread = None
        """Aktiver ConverterThread oder DVRemuxThread (oder None)."""

        self.move_thread = None
        """Aktiver MoveThread (oder None)."""

        self.retired_move_threads: list = []
        """Fertig gelaufene MoveThreads, die noch kurz referenziert bleiben."""

        self.incremental_move_active: bool = False
        """True während 'Fertige verschieben' parallel zu einem laufenden Encode."""

    # ── Lifecycle ───────────────────────────────────────────────────

    def reset_for_run(self, file_count: int) -> None:
        """Setzt den Laufzeitzustand für einen neuen Conversion-Run zurück."""
        self.fertig.clear()
        self.sidecar_outputs_by_video.clear()
        self.completed_inputs.clear()
        self.run_results.clear()
        self.move_report_log.clear()
        self.postprocess_outputs_by_input.clear()
        self.pending_postprocess_inputs.clear()
        self.finish_waiting_for_postprocess = False
        self.preflight_rows_by_path.clear()
        self.move_ok_count = 0
        self.move_error_count = 0
        self.pending_remove_paths.clear()
        self.current_log_path = None
        self.job_journal = None
        self.job_journal_current_path = None
        self.job_journal_current_paths.clear()
        self.total_files = file_count
        self.summary_written = False
        self.last_total_pct = 0
        self.incremental_move_active = False
        self.retired_move_threads.clear()
        self.active_file_progress.clear()
        self.active_file_eta.clear()
        self.progress_focus_path = None

    def clear_all(self) -> None:
        """Vollständiges Reset – inkl. Overrides, Targets und Run-Zustand."""
        self.file_overrides.clear()
        self.planned_targets.clear()
        self.restored_move_context.clear()
        self.fertig.clear()
        self.sidecar_outputs_by_video.clear()
        self.completed_inputs.clear()
        self.run_results.clear()
        self.move_report_log.clear()
        self.postprocess_outputs_by_input.clear()
        self.pending_postprocess_inputs.clear()
        self.finish_waiting_for_postprocess = False
        self.move_ok_count = 0
        self.move_error_count = 0
        self.pending_remove_paths.clear()
        self.total_files = 0
        self.last_total_pct = 0
        self.active_file_progress.clear()
        self.active_file_eta.clear()
        self.progress_focus_path = None
        self.current_log_path = None
        self.job_journal = None
        self.job_journal_current_path = None
        self.job_journal_current_paths.clear()
        self.summary_written = False
        self.thread = None
        self.move_thread = None
        self.retired_move_threads.clear()
        self.incremental_move_active = False
