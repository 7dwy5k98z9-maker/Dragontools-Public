"""Per-stream packet summaries; no packet/hash lists survive parsing."""
from dataclasses import dataclass, field
import hashlib
import math

from .packet_json_stream import JsonRecordReader


@dataclass(frozen=True, slots=True)
class PacketStreamSnapshot:
    stream_index: int
    codec_type: str
    ordinal: int
    packet_count: int
    hashes: str
    max_pts_s: float | None
    max_dts_s: float | None
    max_duration_s: float | None


@dataclass
class PacketAccumulator:
    count: int = 0
    digest: object = field(default_factory=hashlib.sha256)
    times: dict = field(default_factory=dict)
    missing_hash: bool = False

    def add(self, packet):
        value = packet.get('data_hash')
        if not isinstance(value, str) or not value:
            self.missing_hash = True
            value = ''
        encoded = value.encode('utf-8')
        self.digest.update(len(encoded).to_bytes(8, 'big'))
        self.digest.update(encoded)
        self.count += 1
        for key in ('pts_time', 'dts_time', 'duration_time'):
            raw = packet.get(key)
            if raw in (None, '', 'N/A'):
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                raise ValueError('Invalid packet timing') from None
            if not math.isfinite(value) or (key == 'duration_time' and value < 0):
                raise ValueError('Non-finite or negative packet duration')
            self.times[key] = max(value, self.times.get(key, value))


def stream_index(record, key):
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError('Invalid ffprobe stream index')
    index = int(value)
    if index < 0 or index > 65535:
        raise ValueError('Invalid ffprobe stream index')
    return index


def read_snapshot(stream):
    packets, streams = {}, {}
    for section, record in JsonRecordReader(stream).records():
        index = stream_index(record, 'index' if section == 'streams' else 'stream_index')
        if section == 'streams':
            if index in streams:
                raise ValueError('Duplicate ffprobe stream index')
            streams[index] = record.get('codec_type')
        else:
            if record.get('pts_time') in (None, '', 'N/A'):
                raise ValueError('Packet presentation timestamp is missing')
            if index not in packets:
                packets[index] = PacketAccumulator()
            packets[index].add(record)
        if len(streams) > 4096 or len(packets) > 4096:
            raise ValueError('Too many ffprobe streams')
    if 'video' not in streams.values():
        raise ValueError('ffprobe lieferte keinen Videostream für die Paketprüfung')
    if set(packets) - set(streams):
        raise ValueError('Packets reference undeclared streams')
    ordinals, result = {}, []
    for index, kind in sorted(streams.items()):
        if kind not in {'video', 'audio', 'subtitle'}:
            continue
        data = packets.get(index) or PacketAccumulator()
        if data.missing_hash or (kind != 'subtitle' and not data.count):
            raise ValueError('Paket-/Hashnachweis fehlt')
        ordinal = ordinals.get(kind, 0)
        ordinals[kind] = ordinal + 1
        result.append(PacketStreamSnapshot(index, kind, ordinal, data.count, data.digest.hexdigest(),
                      data.times.get('pts_time'), data.times.get('dts_time'), data.times.get('duration_time')))
    return tuple(result)
