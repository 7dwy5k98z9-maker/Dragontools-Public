"""Read ffprobe arrays one record at a time, with bounded record memory."""
import json


class JsonRecordReader:
    def __init__(self, stream, limit=1024 * 1024):
        self.stream = stream
        self.buffer = ''
        self.limit = limit
        self.eof = False
        self.decoder = json.JSONDecoder()

    def fill(self):
        chunk = self.stream.read(65536)
        self.eof = not chunk
        self.buffer += chunk
        if len(self.buffer) > self.limit:
            raise ValueError('ffprobe JSON record exceeds memory limit')

    def peek(self):
        self.buffer = self.buffer.lstrip()
        while not self.buffer and not self.eof:
            self.fill()
            self.buffer = self.buffer.lstrip()
        return self.buffer[:1]

    def expect(self, char):
        if self.peek() != char:
            raise ValueError(f'Invalid ffprobe JSON; expected {char}')
        self.buffer = self.buffer[1:]

    def value(self):
        self.peek()
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer)
            except json.JSONDecodeError:
                if self.eof:
                    raise ValueError('Incomplete ffprobe JSON') from None
                self.fill()
                continue
            if end == len(self.buffer) and not self.eof:
                self.fill()
                continue
            self.buffer = self.buffer[end:]
            return value

    def records(self):
        self.expect('{')
        seen = set()
        while self.peek() != '}':
            key = self.value()
            if not isinstance(key, str) or key in seen:
                raise ValueError('Invalid or duplicate ffprobe section')
            seen.add(key)
            self.expect(':')
            if key in {'packets', 'streams'}:
                self.expect('[')
                while self.peek() != ']':
                    item = self.value()
                    if not isinstance(item, dict):
                        raise ValueError('Invalid ffprobe record')
                    yield key, item
                    if self.peek() == ']':
                        break
                    self.expect(',')
                    if self.peek() == ']':
                        raise ValueError('Trailing comma in ffprobe JSON')
                self.expect(']')
            else:
                self.value()
            if self.peek() == '}':
                break
            self.expect(',')
            if self.peek() == '}':
                raise ValueError('Trailing comma in ffprobe JSON')
        self.expect('}')
        if self.peek() or not {'packets', 'streams'} <= seen:
            raise ValueError('Incomplete or trailing ffprobe JSON')
