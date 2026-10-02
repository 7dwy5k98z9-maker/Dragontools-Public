"""Bounded diagnostic storage, explicitly detached when a tool run ends."""
from collections import deque
from threading import Lock


class ToolOutputBuffer:
    def __init__(self, limit=8 * 1024 * 1024):
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError('Output limit must be a positive integer')
        self.limit = limit
        self.lines = deque()
        self.size = 0
        self.truncated = False
        self.released = False
        self.lock = Lock()

    def append(self, text):
        with self.lock:
            if self.released or not text:
                return
            if len(text) > self.limit:
                self.truncated = True
                text = text[-self.limit:]
            self.lines.append(text)
            self.size += len(text)
            while self.size > self.limit:
                self.truncated = True
                self.size -= len(self.lines.popleft())

    def text(self):
        with self.lock:
            return ''.join(self.lines).rstrip('\r\n')

    def release(self):
        with self.lock:
            self.released = True
            self.lines.clear()
            self.size = 0
