# -*- coding: utf-8 -*-
"""
dragontools/worker/process_control.py

Plattformübergreifendes Suspendieren / Fortsetzen eines laufenden
subprocess.Popen-Prozesses.

Windows:  NtSuspendProcess / NtResumeProcess via WinAPI (korrekte Prozess-API).
          OpenThread(pid) wäre falsch – proc.pid ist eine Prozess-ID, kein
          Thread-ID. Der entstehende Handle wäre ungültig; SuspendThread
          haette still versagt.
Linux/macOS: SIGSTOP / SIGCONT.

Oeffentliche API
----------------
suspend_process(proc)   – hängt den Prozess auf und liefert Erfolgsstatus
resume_process(proc)    – setzt ihn fort und liefert Erfolgsstatus
wait_while_paused(worker, lock)
                        – blockiert den aufrufenden Thread solange
                          worker._paused == True; suspendiert dabei den
                          aktuellen Prozess (CPU-schonend).

Benutzung in ConverterThread.wait_if_paused():
    from .process_control import wait_while_paused
    wait_while_paused(self, self._lock)
"""
from __future__ import annotations

import os
import subprocess


TASKKILL_TIMEOUT_SECONDS = 5.0


def _log_process_control(log, message: str, level: str = "warn") -> None:
    if not callable(log):
        return
    try:
        log(message, level)
    except TypeError:
        log(message)


def _windows_process_suspend_resume(pid: int, *, resume: bool) -> int | None:
    """Ruft NtSuspendProcess/NtResumeProcess mit 64-bit-sicheren HANDLE-Typen auf.

    ``None`` bedeutet, dass ``OpenProcess`` keinen Handle liefern konnte.
    Ansonsten wird der NTSTATUS als Integer zurückgegeben (0 = Erfolg).
    """
    import ctypes
    from ctypes import wintypes

    process_suspend_resume = 0x0800
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")

    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    native_call = ntdll.NtResumeProcess if resume else ntdll.NtSuspendProcess
    native_call.argtypes = (wintypes.HANDLE,)
    native_call.restype = ctypes.c_long

    handle = kernel32.OpenProcess(process_suspend_resume, False, int(pid))
    if not handle:
        return None
    try:
        return int(native_call(handle))
    finally:
        kernel32.CloseHandle(handle)


# ---------------------------------------------------------------------------
# Kern-Funktionen
# ---------------------------------------------------------------------------

def suspend_process(
    proc: "subprocess.Popen | None",
    *,
    log=None,
    label: str = "Prozess",
) -> bool:
    """Suspendiert *proc* plattformspezifisch und liefert den Erfolgsstatus.

    Ein fehlender oder bereits beendeter Prozess gilt als erfolgreich: In
    diesem Fall muss nur der Worker-Thread pausiert werden. Betriebssystemfehler
    werden weiterhin fail-soft behandelt, aber nicht mehr still verschluckt.
    """
    if proc is None or proc.poll() is not None:
        return True
    try:
        if os.name == "nt":
            status = _windows_process_suspend_resume(proc.pid, resume=False)
            if status is None:
                _log_process_control(
                    log,
                    f"{label}: Prozess konnte nicht zum Pausieren geöffnet werden (PID {proc.pid}).",
                )
                return False
            if status != 0:
                _log_process_control(
                    log,
                    f"{label}: NtSuspendProcess fehlgeschlagen (Status 0x{status & 0xFFFFFFFF:08X}).",
                )
                return False
        else:
            import signal
            os.kill(proc.pid, signal.SIGSTOP)
        return True
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        _log_process_control(log, f"{label}: Pausieren fehlgeschlagen: {exc}")
        return False


def resume_process(
    proc: "subprocess.Popen | None",
    *,
    log=None,
    label: str = "Prozess",
) -> bool:
    """Setzt einen suspendierten *proc* fort und liefert den Erfolgsstatus."""
    if proc is None or proc.poll() is not None:
        return True
    try:
        if os.name == "nt":
            status = _windows_process_suspend_resume(proc.pid, resume=True)
            if status is None:
                _log_process_control(
                    log,
                    f"{label}: Prozess konnte nicht zum Fortsetzen geöffnet werden (PID {proc.pid}).",
                )
                return False
            if status != 0:
                _log_process_control(
                    log,
                    f"{label}: NtResumeProcess fehlgeschlagen (Status 0x{status & 0xFFFFFFFF:08X}).",
                )
                return False
        else:
            import signal
            os.kill(proc.pid, signal.SIGCONT)
        return True
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        _log_process_control(log, f"{label}: Fortsetzen fehlgeschlagen: {exc}")
        return False


def _taskkill_tree(
    pid: int,
    *,
    log=None,
    label: str = "Prozess",
    timeout: float = TASKKILL_TIMEOUT_SECONDS,
) -> bool:
    """Beendet unter Windows einen Prozess samt aller Kindprozesse.

    ``taskkill`` ist selbst ein externer Prozess und darf den Abbruchpfad nicht
    unbegrenzt blockieren. Nach ``timeout`` Sekunden wird der Aufruf beendet;
    ``terminate_process_tree`` faellt danach auf ``proc.kill()`` zurueck.
    """
    try:
        kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        # CREATE_NO_WINDOW verhindert ein aufpoppendes CMD-Fenster.
        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        if create_no_window:
            kwargs["creationflags"] = create_no_window
        completed = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            timeout=max(0.1, float(timeout)),
            check=False,
            **kwargs,
        )
        if completed.returncode == 0:
            if callable(log):
                log(f"{label}: Prozessbaum per taskkill /T /F beendet (PID {pid}).", "warn")
            return True
        if callable(log):
            log(
                f"{label}: taskkill lieferte Exit-Code {completed.returncode} fuer PID {pid}; "
                "Python-Kill-Fallback bleibt aktiv.",
                "warn",
            )
        return False
    except subprocess.TimeoutExpired:
        if callable(log):
            log(
                f"{label}: taskkill-Timeout nach {max(0.1, float(timeout)):.1f}s fuer PID {pid}; "
                "Python-Kill-Fallback bleibt aktiv.",
                "warn",
            )
        return False
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        if callable(log):
            log(f"{label}: taskkill fehlgeschlagen fuer PID {pid}: {exc}", "warn")
        return False


def terminate_process_tree(
    worker,
    lock,
    *,
    log=None,
    attr_name: str = "_current_process",
    terminate_timeout: float = 3,
    kill_timeout: float = 5,
    label: str = "Prozess",
) -> bool:
    """Beendet den aktuell registrierten Prozess ohne den Worker-Lock zu halten."""
    if hasattr(worker, attr_name):
        with lock:
            proc = getattr(worker, attr_name, None)
    else:
        with lock:
            proc = getattr(worker, "current_process", None)

    if proc is None:
        if callable(log):
            log(f"{label}: kein laufender Prozess für Sofort-Abbruch.", "info")
        return False

    if proc.poll() is not None:
        if callable(log):
            log(f"{label}: Prozess ist bereits beendet.", "info")
        with lock:
            if hasattr(worker, attr_name):
                if getattr(worker, attr_name, None) is proc:
                    setattr(worker, attr_name, None)
            elif getattr(worker, "current_process", None) is proc:
                worker.current_process = None
        return False

    if callable(log):
        log(f"{label}: Sofort-Abbruch - terminate() wird gesendet.", "warn")

    if os.name == "nt":
        # Windows: echte Prozessbaum-Beendigung über taskkill /T /F
        # Damit werden auch alle Kindprozesse (ffmpeg-interne Threads,
        # MP4Box, dovi_tool, mkvmerge) sofort beendet.
        _taskkill_tree(proc.pid, log=log, label=label)
        try:
            proc.wait(timeout=terminate_timeout + kill_timeout)
        except subprocess.TimeoutExpired:
            # Letzter Fallback: direkt per Python-API
            try:
                proc.kill()
            except OSError as exc:
                if callable(log):
                    log(f"{label}: Python-Kill-Fallback fehlgeschlagen: {exc}", "error")
    else:
        # Linux/macOS: Prozesse des gemeinsamen Tool-Runners laufen in einer
        # eigenen Session/Prozessgruppe. Dann beenden wir die komplette
        # Gruppe statt nur den Parent. Für ältere/fremde Popen-Objekte bleibt
        # der bisherige Parent-Fallback erhalten.
        import signal

        use_group = bool(getattr(proc, "_dragontools_process_group", False))

        def _send(sig) -> None:
            if use_group:
                os.killpg(os.getpgid(proc.pid), sig)
            elif sig == signal.SIGTERM:
                proc.terminate()
            else:
                proc.kill()

        try:
            _send(signal.SIGTERM)
            proc.wait(timeout=terminate_timeout)
            if callable(log):
                scope = "Prozessgruppe" if use_group else "Prozess"
                log(f"{label}: {scope} per SIGTERM beendet.", "warn")
        except subprocess.TimeoutExpired:
            if callable(log):
                log(f"{label}: SIGTERM Timeout - SIGKILL wird gesendet.", "warn")
            try:
                _send(signal.SIGKILL)
                proc.wait(timeout=kill_timeout)
                if callable(log):
                    scope = "Prozessgruppe" if use_group else "Prozess"
                    log(f"{label}: {scope} per SIGKILL beendet.", "warn")
            except (OSError, subprocess.SubprocessError) as exc:
                if callable(log):
                    log(f"{label}: Prozess konnte nicht gekillt werden: {exc}", "error")
        except (OSError, subprocess.SubprocessError) as exc:
            if callable(log):
                log(f"{label}: Prozess konnte nicht beendet werden: {exc}", "error")

    with lock:
        if hasattr(worker, attr_name):
            if getattr(worker, attr_name, None) is proc:
                setattr(worker, attr_name, None)
        elif getattr(worker, "current_process", None) is proc:
            worker.current_process = None
    return True


# ---------------------------------------------------------------------------
# High-Level-Helper für Worker-Threads
# ---------------------------------------------------------------------------

def wait_while_paused(worker, lock) -> bool:
    """Haelt den aufrufenden Thread an solange ``worker._paused`` True ist.

    Liest den laufenden Prozess einmalig und suspendiert ihn, damit die CPU
    während der Pause nicht belastet wird.  Nach dem Aufwachen
    (``worker._pause_ev.set()``) wird der Prozess wieder fortgesetzt.

    Parameters
    ----------
    worker:
        ConverterThread-Instanz (oder jeder Worker mit den Attributen
        ``_paused``, ``_pause_ev``, ``current_process``).
    lock:
        ``threading.Lock`` der den Zugriff auf ``current_process`` schuetzt.
    """
    if not getattr(worker, "_paused", False):
        return True

    # ConverterThread.current_process ist selbst gelockt. Deshalb lesen wir
    # _current_process direkt unter Lock und verwenden die Property nur als
    # Fallback für Worker, die kein privates Attribut besitzen.
    if hasattr(worker, "_current_process"):
        with lock:
            proc = getattr(worker, "_current_process", None)
    else:
        proc = getattr(worker, "current_process", None)

    log = getattr(worker, "log", None) or getattr(worker, "_log", None)
    suspended = suspend_process(proc, log=log, label="Worker-Prozess")
    if not suspended:
        # Kein falscher GUI-/Workerzustand: wenn der externe Prozess nicht
        # angehalten werden konnte, wird die Pause verworfen.
        try:
            worker._paused = False
        except (AttributeError, RuntimeError):
            pass
        pause_ev = getattr(worker, "_pause_ev", None)
        if pause_ev is not None:
            pause_ev.set()
        _log_process_control(
            log,
            "Pause konnte nicht sicher aktiviert werden; der Worker läuft weiter.",
            "warn",
        )
        return False

    # Blockieren bis resume() aufgerufen wird
    pause_ev = getattr(worker, "_pause_ev", None)
    if pause_ev is not None:
        pause_ev.wait()

    resumed = resume_process(proc, log=log, label="Worker-Prozess")
    if not resumed:
        _log_process_control(
            log,
            "Der externe Prozess konnte nach der Pause nicht bestätigt fortgesetzt werden.",
            "error",
        )
    return resumed
