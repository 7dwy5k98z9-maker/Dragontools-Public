# -*- coding: utf-8 -*-
"""
dragontools/worker/converter_strip.py

Ausgelagerte Strip-Only-Funktion des ConverterThread.
Video wird immer per Stream-Copy übernommen (kein Re-Encode).

Audio- und Subtitle-Auswahl laufen über die zentralen Planfunktionen
(compute_audio_track_plan / compute_subtitle_plan) und respektieren
File-Overrides vollständig.

Audio: Video-Copy, aber Audio folgt den Regeln.
  - needs_transcode=False → Stream-Copy
  - needs_transcode=True  → Transcode gemaess Plan (Codec/Channels/Bitrate)

Subtitles: Stream-Copy oder Drop; Burn-In technisch nicht möglich.
  Ein geplantes burn_sub wird als Stream-Copy behandelt, damit forced/
  relevante Untertitel nicht verloren gehen.
"""
from __future__ import annotations


class ConverterStripHelper:
    """Kapselt den Strip-Only-Modus (copy-only, kein Re-Encode)."""

    def __init__(self, worker):
        self.worker = worker
        self.last_sidecar_paths: list[str] = []

    def strip_only(
        self,
        inp: str,
        out: str,
        mi,
        ov: dict | None = None,
        container: str = "mkv",
    ) -> bool:
        from ..rules.audio_plan import (
            audio_filter_chain,
            audio_input_args_for_plan,
            compute_audio_track_plan,
        )
        from ..rules.subtitle_rules import build_mp4_subtitle_storage_plan, compute_subtitle_plan

        worker = self.worker
        try:
            worker.log(
                "ℹ️ Strip-Only: Video-Copy. "
                "Audio- und Subtitle-Auswahl nach konfigurierten Regeln und Overrides "
                "(Audio wird ggf. transcodiert wenn Regeln es erfordern).",
                "info",
            )
        except Exception:
            pass

        # ── Audio ─────────────────────────────────────────────────────────
        # Auswahl via zentralem Audio-Plan; pro Spur entscheidet der Plan
        # ob Stream-Copy oder Transcode nötig ist.
        # Referenz-Implementierung: converter_stream_args.audio_args()
        audio_plan = compute_audio_track_plan(
            audio_streams=mi.audio_streams,
            file_override=ov,
            container=container,
        )
        cmd = [
            worker.tools.ffmpeg,
            "-y",
            "-loglevel", "error",
            *audio_input_args_for_plan(audio_plan),
            "-i", inp,
        ]
        if audio_plan:
            for decision in audio_plan:
                cmd += ["-map", f"0:{decision.stream.index}"]
                if decision.needs_transcode:
                    bk = max(
                        1,
                        int(decision.target_bitrate / 1000)
                        if decision.target_bitrate else 256,
                    )
                    cmd += [
                        f"-c:a:{decision.out_idx}", decision.target_codec,
                        f"-ac:a:{decision.out_idx}", str(decision.target_channels),
                        f"-b:a:{decision.out_idx}", f"{bk}k",
                    ]
                    filter_chain = audio_filter_chain(decision)
                    if filter_chain:
                        cmd += [f"-filter:a:{decision.out_idx}", filter_chain]
                else:
                    cmd += [f"-c:a:{decision.out_idx}", "copy"]
        else:
            cmd += ["-an"]

        # ── Untertitel ────────────────────────────────────────────────────
        # Auswahl via zentralem Subtitle-Plan. Burn-In ist in Strip-Only
        # nicht möglich; ein geplantes burn_sub wird als Stream-Copy
        # behandelt.
        sub_plan = compute_subtitle_plan(
            mi.subtitle_streams,
            audio_streams=mi.audio_streams,
            file_override=ov,
            subtitle_rules=worker.subtitle_rules,
            container_copy_supported=True,
            media_duration_s=getattr(mi, "duration_s", None),
        )
        for warning in getattr(sub_plan, "burn_warnings", ()) or ():
            worker.log(f"⚠️ {warning}", "warn")
        target_container = str(container or "mkv").lower()
        if target_container == "mp4":
            storage = build_mp4_subtitle_storage_plan(
                sub_plan,
                subtitle_rules=worker.subtitle_rules,
                preserve_burn_candidate=True,
            )
            if storage.internal_streams:
                for out_idx, stream in enumerate(storage.internal_streams):
                    cmd += [
                        "-map", f"0:{stream.index}",
                        f"-c:s:{out_idx}", "mov_text",
                    ]
                    if getattr(stream, "language", None):
                        cmd += [
                            f"-metadata:s:s:{out_idx}",
                            f"language={str(stream.language).lower()}",
                        ]
                    if getattr(stream, "title", None):
                        title = str(stream.title).replace("\n", " ").strip()
                        if title:
                            cmd += [f"-metadata:s:s:{out_idx}", f"title={title}"]
                    cmd += [
                        f"-disposition:s:{out_idx}",
                        "forced" if bool(getattr(stream, "forced", False)) else "0",
                    ]
            else:
                cmd += ["-sn"]
        else:
            streams_to_copy: list = []
            if sub_plan.burn_sub:
                streams_to_copy.append(sub_plan.burn_sub)
            streams_to_copy.extend(sub_plan.keep_streams)
            # Deduplizierung nach Stream-Index
            seen: set = set()
            deduped: list = []
            for stream in streams_to_copy:
                if stream.index not in seen:
                    seen.add(stream.index)
                    deduped.append(stream)

            if deduped:
                for stream in deduped:
                    cmd += ["-map", f"0:{stream.index}"]
                cmd += ["-c:s", "copy"]
            else:
                cmd += ["-sn"]

        if str(container or "mkv").lower() == "mp4":
            cmd += ["-movflags", "+faststart"]
        cmd += ["-map", "0:v:0", "-c:v", "copy", out]
        ok = worker._progress.run(cmd) == 0
        self.last_sidecar_paths = []
        if ok:
            from pathlib import Path
            from ..rules.subtitle_rules import any_sidecar_export_enabled
            from .subtitle_sidecar_service import SubtitleSidecarService
            target_container = str(container or "mkv").lower()
            if any_sidecar_export_enabled(worker.subtitle_rules, container=target_container):
                service = SubtitleSidecarService(
                    ffmpeg_path=worker.tools.ffmpeg,
                    subtitle_rules=worker.subtitle_rules,
                    log=worker.log,
                    worker=worker,
                )
                export = service.export_sidecars_result(
                    input_path=inp,
                    output_base=Path(out).with_suffix(""),
                    media_info=mi,
                    file_override=ov,
                    preserve_burn_candidate=True,
                    container=target_container,
                )
                self.last_sidecar_paths = list(export.exported_paths)
                if not export.complete:
                    worker.log(f"❌ Strip-Only Untertitel-Export: {export.failure_summary()}", "error")
                    return False
        return ok
