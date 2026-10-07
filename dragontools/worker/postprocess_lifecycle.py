"""Own admission, callback registration and the final drain of background jobs."""
from concurrent.futures import wait
import threading


class PostprocessLifecycle:
    def __init__(self):
        self.condition = threading.Condition(threading.RLock())
        self.futures = []
        self.shutdown = False
        self.registering = 0
        self.closed = threading.Event()
        self.shutdown_error = None

    def scheduled(self, future):
        # Called inside condition: drain cannot pass the registration gap.
        self.futures.append(future)
        self.registering += 1

    def registered(self):
        with self.condition:
            self.registering -= 1
            self.condition.notify_all()

    def retire(self, future):
        with self.condition:
            if future in self.futures:
                self.futures.remove(future)
            self.condition.notify_all()

    def drain(self, executor):
        with self.condition:
            owner = not self.shutdown
            self.shutdown = True
        if not owner:
            self.closed.wait()
            if self.shutdown_error is not None:
                raise self.shutdown_error
            return
        try:
            with self.condition:
                self.condition.wait_for(lambda: self.registering == 0)
                futures = list(self.futures)
            wait(futures)
            executor.shutdown(wait=True)
            with self.condition:
                self.condition.wait_for(lambda: not self.futures)
        except BaseException as exc:
            self.shutdown_error = exc
            raise
        finally:
            self.closed.set()
