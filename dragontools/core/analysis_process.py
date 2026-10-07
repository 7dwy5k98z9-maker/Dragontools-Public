"""Owned analysis subprocesses with bounded, complete file-backed output."""
from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time

from .owned_process import close_owned_job, spawn_owned_process, terminate_owned_job

MAX_ANALYSIS_OUTPUT_BYTES = 64 * 1024 * 1024


def _stop_analysis_process(proc, no_window_kwargs):
    if terminate_owned_job(proc):
        proc.wait(timeout=5)
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=5, check=False, **no_window_kwargs)
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=5)


def _read_output(stream, *, text=True):
    stream.seek(0)
    data = stream.read(MAX_ANALYSIS_OUTPUT_BYTES + 1)
    if len(data) > MAX_ANALYSIS_OUTPUT_BYTES:
        raise RuntimeError("Analyse-Tool-Ausgabe überschreitet die Speichergrenze; Ergebnis ist unvollständig.")
    if not text:
        return data
    return data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def _wait_analysis(proc, streams, timeout):
    started = time.monotonic()
    while True:
        if any(os.fstat(stream.fileno()).st_size > MAX_ANALYSIS_OUTPUT_BYTES for stream in streams):
            raise RuntimeError("Analyse-Tool-Ausgabe überschreitet die Speichergrenze; Ergebnis ist unvollständig.")
        remaining = None if timeout is None else float(timeout) - (time.monotonic() - started)
        if remaining is not None and remaining <= 0:
            raise subprocess.TimeoutExpired(proc.args, timeout)
        try:
            return proc.wait(timeout=.1 if remaining is None else min(.1, remaining))
        except subprocess.TimeoutExpired:
            continue


def run_owned_analysis(cmd, *, timeout, no_window_kwargs, text=True):
    # Spool both streams independently so neither pipe backpressure nor a
    # surviving child's inherited pipe can block timeout handling.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        proc = spawn_owned_process(cmd, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL,
                                **no_window_kwargs,
                                **({"start_new_session": True} if os.name != "nt" else {}))
        try:
            _wait_analysis(proc, (stdout, stderr), timeout)
            close_owned_job(proc)
            return subprocess.CompletedProcess(cmd, proc.returncode, _read_output(stdout, text=text), _read_output(stderr, text=text))
        finally:
            try:
                if proc.poll() is None:
                    _stop_analysis_process(proc, no_window_kwargs)
            finally:
                close_owned_job(proc)
