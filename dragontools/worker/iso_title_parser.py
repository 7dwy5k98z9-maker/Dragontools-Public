"""Decode MakeMKV robot title attributes without stripping escaped quotes."""
import json

from .iso_disc_inspector import parse_duration_to_seconds, parse_size_to_bytes


def parse_makemkv_titles(lines):
    titles = {}
    for line in lines:
        if not line.startswith('TINFO:'):
            continue
        fields = line[6:].split(',', 3)
        if len(fields) != 4:
            continue
        try:
            title_id, code, message_code = (int(value) for value in fields[:3])
            raw = json.loads(fields[3])
        except (TypeError, ValueError):
            continue
        # MakeMKV attribute 8 is the chapter count; attribute 9 is duration.
        # A chapter count can look like a valid number of seconds, so using
        # attribute 8 silently rejects complete films during verification.
        if title_id < 0 or code not in {2, 9, 11} or not isinstance(raw, str):
            continue
        entry = titles.setdefault(title_id, dict(id=title_id, duration=0, size=0, name=f'Title {title_id}'))
        if code == 2 and raw:
            entry['name'] = raw
        elif code == 9:
            entry['duration'] = parse_duration_to_seconds(raw)
        elif code == 11:
            entry['size'] = parse_size_to_bytes(raw)
    return [titles[key] for key in sorted(titles)]
