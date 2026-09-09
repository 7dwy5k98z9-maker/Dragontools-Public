# -*- coding: utf-8 -*-
"""Tests für rules/pipeline_selector.py und core/paths.py (Singleton)"""
import threading

from dragontools.rules.pipeline_selector import PipelineSelector
from dragontools.core.models import MediaInfo, VideoStream


def _make_media_info(hdr_format: str | None = None) -> MediaInfo:
    vs = VideoStream(
        index=0, codec="hevc", width=3840, height=2160, hdr_format=hdr_format
    )
    return MediaInfo(
        path="/fake/film.mkv",
        audio_streams=[],
        subtitle_streams=[],
        video_streams=[vs],
    )


class TestPipelineSelector:
    def test_standard_ohne_hdr(self):
        mi = _make_media_info(hdr_format=None)
        sel = PipelineSelector()
        assert sel.select(mi) == "standard"

    def test_dv_pipeline_wenn_dv_erkannt(self):
        mi = _make_media_info(hdr_format="dolby_vision")
        sel = PipelineSelector()
        assert sel.select(mi, global_preserve_dv=True) == "dv"

    def test_standard_wenn_dv_deaktiviert(self):
        mi = _make_media_info(hdr_format="dolby_vision")
        sel = PipelineSelector()
        assert sel.select(mi, global_preserve_dv=False) == "standard"

    def test_hdrplus_pipeline_wenn_hdrplus_erkannt(self):
        mi = _make_media_info(hdr_format="hdr10plus")
        sel = PipelineSelector()
        assert sel.select(mi, global_preserve_hdrplus=True) == "hdrplus"

    def test_expliziter_override_schlaegt_erkennung(self):
        mi = _make_media_info(hdr_format="dolby_vision")
        sel = PipelineSelector()
        # Explizit "standard" erzwingen, obwohl DV erkannt
        assert sel.select(mi, pipeline_override="standard") == "standard"

    def test_per_datei_override_schlaegt_global(self):
        mi = _make_media_info(hdr_format="dolby_vision")
        sel = PipelineSelector()
        # Global deaktiviert, per-Datei aktiviert
        result = sel.select(
            mi,
            global_preserve_dv=False,
            per_file_preserve_dv=True,
        )
        assert result == "dv"


class TestToolPathsSingleton:
    def test_singleton_gibt_gleiche_instanz_zurück(self):
        from dragontools.core.paths import get_tool_paths, invalidate_tool_paths
        invalidate_tool_paths()
        a = get_tool_paths()
        b = get_tool_paths()
        assert a is b

    def test_singleton_ist_thread_sicher(self):
        from dragontools.core.paths import get_tool_paths, invalidate_tool_paths
        invalidate_tool_paths()
        instances: list = []
        errors: list = []

        def worker():
            try:
                instances.append(get_tool_paths())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # Alle Threads müssen dieselbe Instanz erhalten haben
        assert len(set(id(i) for i in instances)) == 1

    def test_invalidate_erzeugt_neue_instanz(self):
        from dragontools.core.paths import get_tool_paths, invalidate_tool_paths
        invalidate_tool_paths()
        a = get_tool_paths()
        invalidate_tool_paths()
        b = get_tool_paths()
        assert a is not b
