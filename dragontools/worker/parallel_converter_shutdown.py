"""Bounded waiting for physical children and queued coordinator completion."""
import time
from threading import Event


class ParallelConverterShutdownMixin:
    def wait(self, timeout_ms=8000):
        # Never hold the queue lock while waiting: children may need it to emit
        # completion. Qt delivery must happen on the coordinator's own thread.
        from PyQt6.QtCore import QCoreApplication, QThread, QEventLoop
        deadline = time.monotonic() + max(0, int(timeout_ms)) / 1000
        app = QCoreApplication.instance()
        on_owner_thread = QThread.currentThread() == self.thread()
        sleeper = Event()
        while self.isRunning():
            if app is not None and on_owner_thread:
                app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
            if not self.isRunning():
                break
            remaining = int((deadline - time.monotonic()) * 1000)
            if remaining <= 0:
                return False
            children = tuple(self._registry.workers)
            for child in children:
                if child.isRunning():
                    child.wait(min(25, max(0, int((deadline - time.monotonic()) * 1000))))
            sleeper.wait(min(0.001, max(0, deadline - time.monotonic())))
        return True
