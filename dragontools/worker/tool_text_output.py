"""Bounded text drains and callback delivery for tool stdout/stderr."""
from __future__ import annotations
import codecs
import io
import queue
import threading
import time
from typing import Callable
from ..core.callback_dispatch import invoke_callback, is_callback_like
from .log_dispatch import dispatch_log
LogFn = Callable[[str, str], None]
LineFn = Callable[[str], None]

def _dispatch_callbacks(
    callback_queue: "queue.SimpleQueue[tuple[LineFn, str]]",
    *,
    label: str,
    log: LogFn | None,
) -> None:
    deadline = time.monotonic() + 0.02
    for _ in range(32):
        if time.monotonic() >= deadline:
            return
        try:
            callback, text = callback_queue.get_nowait()
        except queue.Empty:
            return
        try:
            invoke_callback(callback, text)
        except Exception as exc:
            dispatch_log(log, f"{label}: Ausgabe-Callback fehlgeschlagen: {exc}", "warn")


def _text_chunks(stream):
    raw = getattr(stream, "buffer", None)
    if raw is None or not hasattr(raw, "read1"):
        yield from iter(lambda: stream.readline(65536), "")
        return
    decoder = io.IncrementalNewlineDecoder(codecs.getincrementaldecoder("utf-8")("replace"), True)
    for chunk in iter(lambda: raw.read1(65536), b""):
        yield decoder.decode(chunk)
    tail = decoder.decode(b"", final=True)
    if tail:
        yield tail


def _queue_line(callback_queue, callback, text, stop):
    while not stop.is_set():
        try:
            callback_queue.put((callback, text.rstrip()), timeout=0.1)
            return
        except queue.Full:
            continue


def _start_text_drain(stream, target, callback, callback_queue, lifecycle, stop):
    def _drain():
        if stream is None:
            return
        pending = ""
        try:
            for text in _text_chunks(stream):
                if stop.is_set():
                    return
                lifecycle.note_activity()
                target.append(text)
                if not is_callback_like(callback):
                    continue
                pending += text
                while "\n" in pending or len(pending) >= 65536:
                    newline = pending.find("\n")
                    end = newline + 1 if 0 <= newline < 65536 else 65536
                    _queue_line(callback_queue, callback, pending[:end], stop)
                    pending = pending[end:]
            if pending:
                _queue_line(callback_queue, callback, pending, stop)
        except (OSError, ValueError) as exc:
            if not stop.is_set():
                target.mark_read_failure(exc)
            return
    thread = threading.Thread(target=_drain, daemon=True)
    thread.start()
    return thread


def _join_threads(*threads: threading.Thread | None, timeout: float) -> None:
    for thread in threads:
        if thread is not None:
            thread.join(timeout=timeout)


def _finish_text_drains(threads, callback_queue, *, label, log, timeout=5.0):
    deadline = time.monotonic() + timeout
    while any(thread is not None and thread.is_alive() for thread in threads) or not callback_queue.empty():
        _dispatch_callbacks(callback_queue, label=label, log=log)
        if time.monotonic() >= deadline:
            return False
        _join_threads(*threads, timeout=0.01)
    _dispatch_callbacks(callback_queue, label=label, log=log)
    return True


