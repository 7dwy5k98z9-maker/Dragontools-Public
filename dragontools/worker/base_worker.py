# -*- coding: utf-8 -*-
"""
dragontools/worker/base_worker.py

Konvention für das Worker-Interface zwischen GUI und Worker-Threads.

Keine Vererbung erzwungen - die produktiven Worker sind historisch direkt
von QThread abgeleitet, und ein großflächiger Umbau bringt keinen
Mehrwert. Stattdessen gilt für alle Worker folgendes Namensschema,
damit GUI-Code und gemeinsame Helfer (z.B. converter_progress) nicht mehr
per hasattr/getattr zwei Alt-Namen abfragen muessen:

Abort-Interface (verpflichtend):
    self.abort_requested : bool           # True sobald Abbruch angefordert
    self.abort_type      : str | None     # "sofort" | "nach_datei" | None
    def request_abort(self, mode: str = "sofort") -> None
    def cancel(self) -> None              # Alias für request_abort("sofort")

Pause-Interface (optional, nur wenn der Worker es unterstützt):
    self._paused         : bool
    def pause(self)     -> None
    def resume(self)    -> None

GUI-Code darf sich darauf verlassen:
    - 'abort_requested' existiert immer
    - 'abort_type' existiert immer (ggf. None)
    - Pause-Buttons duerfen nur dann Methoden aufrufen, wenn
      hasattr(worker, 'pause') zutrifft.

Die Qt-unabhängigen Verträge und Prozess-Helfer liegen in
``worker_contracts.py`` bzw. ``core.process_runner``. Dieses Modul enthält
nur noch die tatsächlich genutzte QThread-Basisklasse.
"""
from __future__ import annotations

import logging
from subprocess import Popen
import threading

from PyQt6.QtCore import QThread, pyqtSignal

from .process_control import terminate_process_tree


_LOG = logging.getLogger(__name__)

__all__ = ["BaseWorker"]


class BaseWorker(QThread):
    """Basisklasse für einfache QThread-Worker ohne Lock und ohne abort_type.

    Konsolidiert das identische Boilerplate aus MP4RemuxThread und MergeThread.

    Abort-Interface (bereitgestellt):
        self.abort_requested : bool
        self.current_process : Popen | None
        def request_abort(self, mode: str = "sofort") -> None
        def cancel(self) -> None

    Log-Interface (bereitgestellt, erfordert self._logger im Subklassen-__init__):
        def _log(self, msg: str, level: str = "info") -> None

    Nicht geeignet für:
        ConverterThread  – Lock + abort_type + Mehrfach-Prozesse
        DVRemuxThread    – eigener Lock + abort_type (nutzt aber ansonsten
                           dasselbe Interface inkl. Pause)
        ISOThread        – extra Log-Call in request_abort
        MoveThread       – kein subprocess/current_process
        AudioMuxThread   – gemischte CRLF/LF-Zeilenenden, separater Schritt
        Helper-Klassen   – keine QThread-Subklassen
    """

    abort_requested: bool
    abort_type: str | None

    progress             = pyqtSignal(int)
    log_line             = pyqtSignal(str)
    finished_with_result = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Instanzattribute – explizit pro Instanz, nie als Klassenattribut.
        # Klassenattribute wurden entfernt: bei mehreren gleichzeitigen Worker-
        # Instanzen könnte ein Instanz-Write die Klasse noch nicht schattendes
        # Lesen eines anderen Threads auf den falschen Wert landen lassen.
        self.abort_requested: bool = False
        self.abort_type: str | None = None
        self._current_process: Popen | None = None
        self._process_lock = threading.Lock()

    @property
    def current_process(self) -> Popen | None:
        with self._process_lock:
            return self._current_process

    @current_process.setter
    def current_process(self, proc: Popen | None) -> None:
        with self._process_lock:
            self._current_process = proc

    def request_abort(self, mode: str = "sofort") -> None:
        """Abbruch anfordern und laufenden subprocess beenden.

        Thread-sicher: liest current_process unter Lock, damit kein anderer
        Thread zwischen dem Lesen und dem terminate()-Aufruf den Prozess
        austauschen kann.
        """
        self.abort_requested = True
        self.abort_type = mode
        if mode == "sofort":
            terminate_process_tree(
                self,
                self._process_lock,
                log=getattr(self, "_log", None),
                attr_name="_current_process",
                label=self.__class__.__name__,
            )

    def cancel(self) -> None:
        """Alias für request_abort('sofort')."""
        self.request_abort()

    def _log(self, msg: str, level: str = "info") -> None:
        """Log-Ausgabe via self._logger (DragonLogger).

        Subklassen muessen self._logger im __init__ setzen.
        """
        logger = self._logger  # Absichtlich laut fehlschlagen, wenn Subklassen keinen Logger setzen.
        if level == "error":
            logger.error(msg)
        elif level == "warn":
            logger.warn(msg)
        elif level == "success":
            logger.success(msg)
        else:
            logger.info(msg)

    def _vlog(self, msg: str) -> None:
        """Verbose/Debug-Log – schreibt NUR in den separaten VerboseLog.

        Kein GUI-Output, kein normales Log. Sicher: wirft keine Exception.
        Erfordert self._verbose_logger (VerboseLogger) im Subklassen-__init__,
        fällt aber ohne Fehler zurück wenn nicht gesetzt.
        """
        try:
            vlogger = getattr(self, "_verbose_logger", None)
            if vlogger is not None:
                vlogger.write(msg)
        except Exception:
            pass
