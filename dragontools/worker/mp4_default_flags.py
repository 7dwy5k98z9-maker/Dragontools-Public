"""Finalize planned MP4 track enable flags on owned candidates before probing.

FFmpeg enables the first track when every default disposition is false. Editing
only tkhd's three flag bytes avoids remuxing media or introducing a new tool.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import struct


@dataclass(frozen=True)
class _Box:
    kind: bytes
    body: int
    end: int


def _boxes(stream, start, end):
    result = []
    while start < end:
        if end-start < 8 or len(result) >= 4096:
            raise ValueError('Ungültige oder zu umfangreiche MP4-Boxstruktur.')
        stream.seek(start)
        header = stream.read(8)
        if len(header)!=8:
            raise ValueError('MP4-Boxheader ist abgeschnitten.')
        size, kind = struct.unpack('>I4s', header)
        width = 8
        if size == 1:
            extended = stream.read(8)
            if len(extended)!=8: raise ValueError('MP4-Langheader ist abgeschnitten.')
            size = struct.unpack('>Q', extended)[0]
            width = 16
        elif size == 0:
            size = end-start
        if size < width or start+size > end:
            raise ValueError('MP4-Boxgröße überschreitet ihre bestätigte Grenze.')
        result.append(_Box(kind, start+width, start+size))
        start += size
    return result


def _one(boxes, kind):
    matches = [box for box in boxes if box.kind==kind]
    if len(matches)!=1: raise ValueError(f'MP4 benötigt genau eine {kind!r}-Box.')
    return matches[0]


def _track_flags(stream, moov):
    tracks = {'audio':[], 'subtitle':[]}
    for trak in _boxes(stream, moov.body, moov.end):
        if trak.kind!=b'trak': continue
        children = _boxes(stream, trak.body, trak.end)
        mdia = _one(children, b'mdia')
        hdlr = _one(_boxes(stream, mdia.body, mdia.end), b'hdlr')
        if hdlr.end-hdlr.body < 12: raise ValueError('MP4-Spurtyp ist abgeschnitten.')
        stream.seek(hdlr.body+8)
        handler = stream.read(4)
        category = 'audio' if handler==b'soun' else (
            'subtitle' if handler in {b'text',b'sbtl',b'subt',b'clcp'} else None)
        if category is None: continue
        tkhd = _one(children, b'tkhd')
        if tkhd.end-tkhd.body < 24: raise ValueError('MP4-Spurheader ist abgeschnitten.')
        stream.seek(tkhd.body)
        full_header = stream.read(4)
        if full_header[0] not in {0,1}: raise ValueError('Unbekannte MP4-Spurheader-Version.')
        tracks[category].append((tkhd.body+1, full_header[1:]))
    return tracks


def _updates(tracks, contract):
    updates = []
    for category, expected in [('audio',contract.audio_tracks),('subtitle',contract.subtitle_tracks)]:
        if len(tracks[category])!=len(expected):
            raise ValueError(f'MP4-{category}-Anzahl passt nicht zum geplanten Vertrag.')
        for (position, previous), planned in zip(tracks[category], expected):
            if planned.default is None: continue
            flags = int.from_bytes(previous, 'big')
            updated = ((flags|1) if planned.default else (flags&~1)).to_bytes(3,'big')
            if updated!=previous: updates.append((position,previous,updated))
    return updates


def finalize_mp4_defaults(output_path, contract, *, input_path=None, abort_check=None):
    """Validate all tracks first; modify only a distinct job output's tkhd flags."""
    if contract is None or str(contract.container).lower()!='mp4': return 0
    expected = (*contract.audio_tracks, *contract.subtitle_tracks)
    if not expected or all(track.default is None for track in expected): return 0
    output = Path(output_path)
    if input_path and os.path.samefile(output, input_path):
        raise ValueError('MP4-Spurflags dürfen nicht an der Originalquelle geändert werden.')
    with output.open('r+b') as stream:
        top = _boxes(stream, 0, os.fstat(stream.fileno()).st_size)
        _one(top, b'ftyp')
        updates = _updates(_track_flags(stream, _one(top,b'moov')), contract)
        if callable(abort_check) and abort_check():
            raise RuntimeError('MP4-Metadatenabschluss wurde abgebrochen.')
        for position, previous, updated in updates:
            stream.seek(position)
            if stream.read(3)!=previous: raise ValueError('MP4-Spurheader wurde zwischenzeitlich verändert.')
        for position, previous, updated in updates:
            stream.seek(position)
            stream.write(updated)
        if updates:
            stream.flush()
            os.fsync(stream.fileno())
    return len(updates)
