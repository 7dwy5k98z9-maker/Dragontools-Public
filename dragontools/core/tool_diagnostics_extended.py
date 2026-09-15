from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .process_runner import subprocess_no_window_kwargs

CommandRunner = Callable[[list[str], int], tuple[int, str]]

def _exists_or_which(path: str) -> bool:
    value = str(path or "").strip()
    return bool(value) and (Path(value).exists() or bool(shutil.which(value)))

def _run_command(cmd: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, **subprocess_no_window_kwargs())
        return int(result.returncode), "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    except Exception as exc:
        return 1, str(exc)

def _first_useful_line(text: str) -> str:
    return next((line.strip() for line in (text or "").splitlines() if line.strip()), "")

def _path_for(tool_paths: dict[str, str], key: str, path_exists=None) -> str:
    value = str(tool_paths.get(key) or "").strip()
    checker = path_exists or _exists_or_which
    return value if value and checker(value) else ""

def _mini_row(name: str, ok: bool, detail: str, *, skipped: bool = False) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "skipped": bool(skipped), "detail": detail}

def _file_ok(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 0
    except OSError:
        return False

def _duration_ok(text: str) -> bool:
    try:
        return float(str(text).splitlines()[0].strip()) > 0
    except (IndexError, TypeError, ValueError):
        return False

def run_extended_system_test(
    tool_paths: dict[str, str],
    *,
    runner: CommandRunner | None = None,
    path_exists=None,
) -> list[dict[str, Any]]:
    """Praktischer Mini-Systemtest mit temporären Testdateien.

    Der Test führt keine produktive Konvertierung aus. Er erzeugt eine
    1-Sekunden-Testdatei und nutzt sie für einfache ffprobe/mkvmerge/MP4Box-
    Durchläufe. DV- und HDR10+-Tools werden bewusst nur auf CLI-Reaktion
    geprüft, weil echte Metadaten-Testdaten dafür nötig wären.
    """
    run = runner or _run_command
    rows: list[dict[str, Any]] = []

    ffmpeg = _path_for(tool_paths, "ffmpeg", path_exists)
    ffprobe = _path_for(tool_paths, "ffprobe", path_exists)
    mediainfo = _path_for(tool_paths, "mediainfo", path_exists)
    mkvmerge = _path_for(tool_paths, "mkvmerge", path_exists)
    mp4box = _path_for(tool_paths, "mp4box", path_exists)
    dovi_tool = _path_for(tool_paths, "dovi_tool", path_exists)
    hdr10plus_tool = _path_for(tool_paths, "hdr10plus_tool", path_exists)

    with tempfile.TemporaryDirectory(prefix="dragontools_systemtest_") as tmp:
        tmp_dir = Path(tmp)
        sample_avi = tmp_dir / "mini_video.avi"
        sample_mkv = tmp_dir / "mini_video.mkv"
        sample_mp4 = tmp_dir / "mini_video.mp4"

        sample_ready = False
        if not ffmpeg:
            rows.append(_mini_row("ffmpeg Mini-Encoding", False, "ffmpeg nicht gefunden", skipped=True))
        else:
            cmd = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=64x64:rate=1:duration=1",
                "-c:v",
                "mpeg4",
                "-t",
                "1",
                str(sample_avi),
            ]
            rc, text = run(cmd, 20)
            sample_ready = rc == 0 and _file_ok(sample_avi)
            rows.append(
                _mini_row(
                    "ffmpeg Mini-Encoding",
                    sample_ready,
                    "1-Sekunden-Testvideo erzeugt"
                    if sample_ready
                    else f"Testvideo konnte nicht erzeugt werden: {_first_useful_line(text) or 'unbekannter Fehler'}",
                )
            )

        if not ffprobe:
            rows.append(_mini_row("ffprobe Mini-Analyse", False, "ffprobe nicht gefunden", skipped=True))
        elif not sample_ready:
            rows.append(_mini_row("ffprobe Mini-Analyse", False, "kein Testvideo vorhanden", skipped=True))
        else:
            rc, text = run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(sample_avi),
                ],
                10,
            )
            ok = rc == 0 and _duration_ok(text)
            detail = f"Dauer erkannt: {text.splitlines()[0].strip()}s" if ok else (
                f"ffprobe konnte die Dauer nicht lesen: {_first_useful_line(text) or 'unbekannter Fehler'}"
            )
            rows.append(_mini_row("ffprobe Mini-Analyse", ok, detail))

        if not mediainfo:
            rows.append(_mini_row("MediaInfo Mini-Analyse", False, "MediaInfo nicht gefunden", skipped=True))
        elif not sample_ready:
            rows.append(_mini_row("MediaInfo Mini-Analyse", False, "kein Testvideo vorhanden", skipped=True))
        else:
            rc, text = run([mediainfo, "--Output=JSON", str(sample_avi)], 10)
            ok = rc == 0 and "track" in text.lower()
            rows.append(
                _mini_row(
                    "MediaInfo Mini-Analyse",
                    ok,
                    "MediaInfo-JSON gelesen"
                    if ok
                    else f"MediaInfo konnte die Testdatei nicht lesen: {_first_useful_line(text) or 'unbekannter Fehler'}",
                )
            )

        mkv_ready = False
        if not mkvmerge:
            rows.append(_mini_row("mkvmerge Mini-Remux", False, "mkvmerge nicht gefunden", skipped=True))
        elif not sample_ready:
            rows.append(_mini_row("mkvmerge Mini-Remux", False, "kein Testvideo vorhanden", skipped=True))
        else:
            rc, text = run([mkvmerge, "-q", "-o", str(sample_mkv), str(sample_avi)], 20)
            mkv_ready = rc == 0 and _file_ok(sample_mkv)
            rows.append(
                _mini_row(
                    "mkvmerge Mini-Remux",
                    mkv_ready,
                    "MKV-Remux erfolgreich"
                    if mkv_ready
                    else f"MKV-Remux fehlgeschlagen: {_first_useful_line(text) or 'unbekannter Fehler'}",
                )
            )

        if not mp4box:
            rows.append(_mini_row("MP4Box Mini-Mux", False, "MP4Box nicht gefunden", skipped=True))
        elif not sample_ready:
            rows.append(_mini_row("MP4Box Mini-Mux", False, "kein Testvideo vorhanden", skipped=True))
        else:
            rc, text = run([mp4box, "-quiet", "-add", str(sample_avi), str(sample_mp4)], 20)
            ok = rc == 0 and _file_ok(sample_mp4)
            rows.append(
                _mini_row(
                    "MP4Box Mini-Mux",
                    ok,
                    "MP4-Mux erfolgreich"
                    if ok
                    else f"MP4-Mux nicht erfolgreich: {_first_useful_line(text) or 'Codec/Container nicht akzeptiert'}",
                )
            )

        for key, label in (
            ("dovi_tool", "dovi_tool CLI-Test"),
            ("hdr10plus_tool", "hdr10plus_tool CLI-Test"),
        ):
            tool = dovi_tool if key == "dovi_tool" else hdr10plus_tool
            if not tool:
                rows.append(_mini_row(label, False, f"{key} nicht gefunden", skipped=True))
                continue
            rc, text = run([tool, "--version"], 10)
            ok = rc == 0 or bool(text.strip())
            rows.append(
                _mini_row(
                    label,
                    ok,
                    "CLI reagiert; echte Metadatenprüfung benötigt DV/HDR10+-Quelldaten"
                    if ok
                    else f"CLI-Test fehlgeschlagen: {_first_useful_line(text) or 'unbekannter Fehler'}",
                )
            )

    return rows


