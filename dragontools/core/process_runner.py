from __future__ import annotations
"""
Schlanker Subprocess-Helfer für read-only Analyse-Tool-Aufrufe (ffprobe, MediaInfo).

Abgrenzung:
    Dieses Modul ist AUSSCHLIESSLICH für kurze, nicht-interaktive Tool-Abfragen
    gedacht, die einen vollständigen stdout-Output zurückgeben (z.B. JSON).
    Produktive Worker-Pipelines (ffmpeg-Encoding, dovi_tool, MP4Box) steuern
    ihre Prozesse selbst, da sie Fortschritt, Abort und Pause benötigen.

Kein Ersatz für:
    - Encoding-Subprozesse mit Fortschrittsauswertung (ConverterThread)
    - Abort-fähige Langläufer (DVProcessingPipeline, HDRPlusConversionHelper)
    - Interaktive Prozesse (mkvpropedit, dovi_tool editor)
"""

import os
import shutil
import subprocess
from pathlib import Path

from .analysis_process import run_owned_analysis


def tool_available(tool_path: str) -> bool:
    """True, wenn ein Tool eine Datei ist oder über PATH auflösbar ist.

    Ein existierendes Verzeichnis ist kein ausführbares Tool.  Die frühere
    ``Path.exists()``-Prüfung meldete z.B. versehentlich den konfigurierten
    Tool-Ordner als verfügbar und verschob den Fehler bis zum ``Popen``.
    """
    value = str(tool_path or "").strip()
    if not value:
        return False
    try:
        if Path(value).is_file():
            return True
    except OSError:
        pass
    return bool(shutil.which(value))


def subprocess_no_window_kwargs() -> dict:
    """subprocess-Kwargs, damit Windows keine kurzen Konsolenfenster öffnet."""
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0}
    if os.name == "nt":
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
            kwargs["startupinfo"] = startupinfo
        except (AttributeError, OSError):
            pass
    return kwargs


def run_analysis_tool(
    cmd: list[str],
    *,
    allow_error: bool = False,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Führt ein Analyse-Tool aus und gibt das vollständige Ergebnis zurück.

    Parameters
    ----------
    cmd:
        Kommando als String-Liste (erster Eintrag: ausführbare Datei).
    allow_error:
        Wenn True, wird ein Returncode != 0 nicht als Fehler behandelt.
    timeout:
        Maximale Laufzeit in Sekunden. Schutzmaßnahme gegen hängende
        Analyse-Tools (volle Platten, kaputte Mediendateien, Netzwerkpfade).
        Standard: 60 Sekunden – großzügig genug für große Mediendateien.

    Raises
    ------
    RuntimeError:
        Bei Returncode != 0 (sofern allow_error=False), Timeout oder wenn
        das Tool nicht gestartet werden konnte.
    """
    try:
        result = run_owned_analysis(
            cmd,
            no_window_kwargs=subprocess_no_window_kwargs(),
            timeout=timeout,
        )
        if result.returncode != 0 and not allow_error:
            raise RuntimeError(
                f"Fehler bei Kommando:\n{' '.join(cmd)}"
                f"\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
            )
        return result
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"Timeout ({timeout}s) bei Analyse-Tool: {' '.join(cmd)}"
        ) from e
    except RuntimeError:
        raise
    except OSError as e:
        raise RuntimeError(
            f"Analyse-Tool konnte nicht gestartet oder ausgeführt werden: {e}"
        ) from e
