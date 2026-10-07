"""Bounded header/packet diagnostics before any duration-repair mutation."""
from __future__ import annotations

import json
import subprocess

from ..core.media_duration import stream_duration, timestamp_wrap
from ..core.process_runner import subprocess_no_window_kwargs
from .owned_probe import owned_probe_runner
from .log_dispatch import dispatch_log


def wrap_message(expected, actual, *, container: str, stream: str) -> str | None:
    signature = timestamp_wrap(expected, actual)
    if signature is None:
        return None
    count, residual = signature
    return (
        "⚠️ Wahrscheinlicher 2^32-ms Timestamp-Wrap erkannt. "
        f"Soll-Dauer={float(expected):.6f}s; Ist-Dauer={float(actual):.6f}s; "
        f"Differenz={float(actual) - float(expected):.6f}s; Wrap-Anzahl={count}; "
        f"Restabweichung={residual:+.6f}s; Container={container}; betroffener Stream={stream}"
    )


def log_timestamp_diagnostics(*, source_path, output_path, expected_s, actual_s, container, ffprobe_path, log, worker=None):
    """Best effort, failure-only; no frames are decoded or counted.

    At most 16 initial video packets are read. No end seek: seeking using a
    wrapped duration is unreliable and must not trigger an unbounded scan.
    """
    if not log:
        return
    callback = log
    log = lambda message, level='warn': dispatch_log(callback, message, level)
    message = wrap_message(expected_s, actual_s, container=container, stream="Container; Streamzuordnung folgt")
    if message:
        log(message, "warn")
    if not ffprobe_path:
        log("Timestamp-Diagnose: ffprobe nicht konfiguriert.", "warn")
        return
    for label, path in (("Quelle", source_path), ("Ausgabe", output_path)):
        if not path:
            log(f"Timestamp-Diagnose {label}: Pfad nicht verfügbar.", "warn")
            continue
        try:
            payload = _probe(ffprobe_path, path, ["-show_format", "-show_streams"], worker=worker)
            fmt = payload.get("format") or {}
            log(f"Timestamp-Diagnose {label}: Container={fmt.get('format_name', container)}; "
                f"duration={fmt.get('duration', 'N/A')}; start_time={fmt.get('start_time', 'N/A')}", "warn")
            for stream in payload.get("streams") or []:
                kind = stream.get("codec_type", "unknown")
                fields = ("duration", "start_time", "time_base", "avg_frame_rate", "r_frame_rate")
                detail = "; ".join(f"{key}={stream.get(key, 'N/A')}" for key in fields)
                identity = f"{kind} #{stream.get('index', '?')}"
                tag = (stream.get("tags") or {}).get("DURATION", "N/A")
                log(f"   {label} {identity}: {detail}; DURATION-Tag={tag}", "warn")
                if label == "Ausgabe":
                    message = wrap_message(expected_s, stream_duration(stream), container=container, stream=identity)
                    if message:
                        log(message, "warn")
            packets = _probe(ffprobe_path, path, [
                "-select_streams", "v:0", "-read_intervals", "%+#16",
                "-show_packets", "-show_entries", "packet=pts_time,dts_time",
            ], worker=worker).get("packets") or []
            if packets:
                log(f"   {label} Video: erstes Paket PTS/DTS={packets[0]}; "
                    f"letztes Paket der begrenzten Startprobe={packets[-1]} (nicht Dateiende).", "warn")
        except Exception as exc:
            # Diagnostics must never disable the established repair safety net.
            log(f"Timestamp-Diagnose {label} nicht vollständig verfügbar: {exc}", "warn")


def _probe(ffprobe_path, path, args, *, worker=None):
    runner = subprocess.run if worker is None else owned_probe_runner(worker, label='Timestamp-Diagnose')
    result = runner(
        [str(ffprobe_path), "-v", "error", *args, "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, timeout=10, **subprocess_no_window_kwargs(),
    )
    if result.returncode:
        raise RuntimeError(result.stderr or f"ffprobe rc={result.returncode}")
    return json.loads(result.stdout or "{}")
