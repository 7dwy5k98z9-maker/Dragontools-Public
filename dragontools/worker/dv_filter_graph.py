"""Edit DV video boundaries while retaining multi-input filter topology."""
from __future__ import annotations

import re


def video_input_label(graph: str, source_stream_index: int | None = None) -> str:
    labels = ([f'[0:{source_stream_index}]'] if source_stream_index is not None else [])
    labels += ['[0:v:0]', '[0:v]', '[1:v:0]']
    matches = [label for label in labels if label in graph]
    if len(matches) != 1 or graph.count(matches[0]) != 1:
        raise ValueError('DV filter graph requires one unambiguous video input')
    return matches[0]


def prepend_video_filter(graph: str, chain: str, *, source_stream_index: int | None = None) -> str:
    label = video_input_label(graph, source_stream_index)
    end = graph.index(label) + len(label)
    if graph[end:].startswith('['):
        intermediate = '[_dv_input_fmt]'
        if intermediate in graph:
            raise ValueError('DV filter input label is already in use')
        return graph[:end] + chain + intermediate + ';' + intermediate + graph[end:]
    return graph[:end] + chain + ',' + graph[end:]


def append_video_filter(graph: str, args: list, chain: str) -> str:
    targets = [str(args[i + 1]) for i, value in enumerate(args[:-1])
               if value == '-map' and str(args[i + 1]).startswith('[')]
    target = targets[0] if len(targets) == 1 else '[vout]'
    intermediate = '[_dv_output_fmt]'
    if intermediate in graph:
        raise ValueError('DV filter output label is already in use')
    # Match a definition at the end of a chain, not reads at its beginning.
    pattern = re.escape(target) + r'(?=\s*(?:;|$))'
    if len(re.findall(pattern, graph)) != 1:
        raise ValueError('DV filter graph requires one mapped video output')
    graph = re.sub(pattern, intermediate, graph, count=1)
    return f'{graph};{intermediate}{chain}{target}'
