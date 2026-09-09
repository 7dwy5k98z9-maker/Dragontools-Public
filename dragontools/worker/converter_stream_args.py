# -*- coding: utf-8 -*-
"""
dragontools/worker/converter_stream_args.py

Ausgelagerte Stream-Argument-Erzeugung für ffmpeg:
    - audio_args              : -map / -c:a / -b:a ...
    - sub_args                : Burn-In-Sub-Entscheidung + Sub-Stream-Copy
    - base_vf_args            : -vf Grundgeruest
    - text_burn_vf_args       : Burn-In via SRT-Extract + subtitles-Filter
    - image_burn_vf_args      : Burn-In via overlay (PGS/DVDSUB)
    - build_vf_args           : Dispatcher für Video-Filter basierend auf burn_sub

Alle Methoden bekommen das ConverterThread als `worker` übergeben.
"""
from __future__ import annotations

import os
import tempfile
import traceback
from pathlib import Path

from ..core.audio_titles import build_audio_title
from .tool_runner import run_tool


class BurnSubtitlePreparationError(RuntimeError):
    """Ein geplanter Subtitle-Burn-In konnte nicht sicher vorbereitet werden."""


def _esc(p: str) -> str:
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


class ConverterStreamArgsHelper:
    """Erzeugt Audio-, Subtitle- und Video-Filter-Argumente für ffmpeg."""

    def __init__(self, worker):
        self.worker = worker

    # ==================================================================
    # Audio
    # ==================================================================
    def audio_args(self, mi, ov, container):
        """Audio-Argumente für ffmpeg - respektiert die Audio-Sprachregeln.

        Die fachliche Entscheidung (welcher Stream, transkodieren ja/nein,
        Ziel-Codec/Channels/Bitrate) kommt aus ``rules.audio_plan`` - dem
        zentralen Entscheidungskern, der auch von Preview und DV-Worker
        genutzt wird. Hier werden nur noch die ffmpeg-Args daraus gebaut.
        """
        from ..rules.audio_plan import compute_audio_track_plan, audio_filter_chain

        worker = self.worker
        plan = compute_audio_track_plan(
            audio_streams=mi.audio_streams,
            file_override=ov,
            container=container,
        )
        if not plan:
            return ["-an"]

        args = []
        for decision in plan:
            chosen = decision.stream
            out_idx = decision.out_idx
            for note in getattr(decision, "processing_notes", ()) or ():
                worker._logger.decision(f"Audio Spur {chosen.index}: {note}")

            if decision.is_extra_stereo:
                # Zusatz-Stereo: gleiche Quellspur nochmal mappen,
                # mit Pan-Filter auf Stereo-Downmix.
                args += ["-map", f"0:{chosen.index}"]
                bk = max(64, int(decision.target_bitrate / 1000) if decision.target_bitrate else 256)
                args += [
                    f"-c:a:{out_idx}", decision.target_codec,
                    f"-ac:a:{out_idx}", "2",
                    f"-b:a:{out_idx}", f"{bk}k",
                ]
                filter_chain = audio_filter_chain(decision)
                if filter_chain:
                    args += [f"-filter:a:{out_idx}", filter_chain]
                lang = getattr(chosen, "language", None) or ""
                worker._logger.audio(
                    chosen.index, chosen.codec, "transcode",
                    decision.target_codec, 2, bk, getattr(chosen, "language", None),
                )
                worker._logger.decision(
                    f"  ↳ Zusatz-Stereo-Downmix ({decision.target_codec.upper()}) aus Spur #{chosen.index}"
                    + (f" ({lang})" if lang else "")
                )
            elif decision.needs_transcode:
                args += ["-map", f"0:{chosen.index}"]
                bk = max(1, int(decision.target_bitrate / 1000) if decision.target_bitrate else 256)
                args += [
                    f"-c:a:{out_idx}", decision.target_codec,
                    f"-ac:a:{out_idx}", str(decision.target_channels),
                    f"-b:a:{out_idx}", f"{bk}k",
                ]
                filter_chain = audio_filter_chain(decision)
                if filter_chain:
                    args += [f"-filter:a:{out_idx}", filter_chain]
                worker._logger.audio(
                    chosen.index, chosen.codec, "transcode",
                    decision.target_codec, decision.target_channels, bk, getattr(chosen, "language", None),
                )
            else:
                args += ["-map", f"0:{chosen.index}"]
                args += [f"-c:a:{out_idx}", "copy"]
                worker._logger.audio(chosen.index, chosen.codec, "copy", language=getattr(chosen, "language", None))

            title_codec = decision.target_codec if decision.needs_transcode else chosen.codec
            title_channels = decision.target_channels if decision.needs_transcode else getattr(chosen, "channels", None)
            title_bitrate = decision.target_bitrate if decision.needs_transcode else getattr(chosen, "bitrate", None)
            title = build_audio_title(
                language=getattr(chosen, "language", None), codec=title_codec,
                channels=title_channels, bitrate_bps=title_bitrate,
            )
            if getattr(chosen, "language", None):
                args += [f"-metadata:s:a:{out_idx}", f"language={chosen.language.lower()}"]
            args += [f"-metadata:s:a:{out_idx}", f"title={title}"]

        return args

    def audio_input_args(self, mi, ov, container):
        """FFmpeg-Eingabeoptionen für Audio-Decoding, z.B. AC3/EAC3-DRC."""
        from ..rules.audio_plan import compute_audio_track_plan, audio_input_args_for_plan

        plan = compute_audio_track_plan(
            audio_streams=mi.audio_streams,
            file_override=ov,
            container=container,
        )
        return audio_input_args_for_plan(plan)

    # ==================================================================
    # Untertitel
    # ==================================================================
    def sub_args(self, input_path, mi, ov, container="mkv"):
        """
        Gibt (video_filter_args, subtitle_args) zurück.
        """
        from ..core.models import normalize_override_dict
        from ..rules.subtitle_rules import (
            build_mp4_subtitle_storage_plan,
            compute_subtitle_plan,
            mp4_sidecars_enabled,
        )

        worker = self.worker
        ov = normalize_override_dict(ov)
        plan = compute_subtitle_plan(
            mi.subtitle_streams,
            audio_streams=mi.audio_streams,
            file_override=ov,
            subtitle_rules=worker.subtitle_rules,
            container_copy_supported=True,
            media_duration_s=getattr(mi, "duration_s", None),
        )

        burn_sub = plan.burn_sub
        keep = list(plan.keep_streams)
        for warning in getattr(plan, "burn_warnings", ()) or ():
            worker.log(f"⚠️ {warning}", "warn")

        # MP4: global wählbar zwischen vollständigem Sidecar-Modus und
        # kompatibilitätsorientiertem internem Text-Mux. Textspuren werden als
        # mov_text transkodiert; PGS/SUP/VobSub bleiben externe Sidecars.
        if str(container or "mkv").lower() == "mp4":
            storage = build_mp4_subtitle_storage_plan(
                plan, subtitle_rules=worker.subtitle_rules
            )
            if burn_sub:
                worker._logger.decision(
                    f"Sub #{burn_sub.index} ({burn_sub.language},forced={burn_sub.forced})→burn-in"
                )

            if mp4_sidecars_enabled(worker.subtitle_rules):
                if storage.external_streams:
                    worker._logger.decision(
                        "MP4-Sidecars aktiv: ausgewählte nicht eingebrannte Untertitel werden extern gespeichert"
                    )
                return (burn_sub if burn_sub else []), ["-sn"]

            sub_map: list[str] = []
            for out_idx, stream in enumerate(storage.internal_streams):
                sub_map += [
                    "-map", f"0:{stream.index}",
                    f"-c:s:{out_idx}", "mov_text",
                ]
                if getattr(stream, "language", None):
                    sub_map += [
                        f"-metadata:s:s:{out_idx}",
                        f"language={str(stream.language).lower()}",
                    ]
                if getattr(stream, "title", None):
                    title = str(stream.title).replace("\n", " ").strip()
                    if title:
                        sub_map += [f"-metadata:s:s:{out_idx}", f"title={title}"]
                sub_map += [
                    f"-disposition:s:{out_idx}",
                    "forced" if bool(getattr(stream, "forced", False)) else "0",
                ]
                worker._logger.decision(
                    f"Sub #{stream.index} ({stream.language}, {stream.codec}, forced={stream.forced})→mov_text intern"
                )

            for stream in storage.external_streams:
                worker._logger.decision(
                    f"Sub #{stream.index} ({stream.language}, {stream.codec})→Sidecar (MP4-Kompatibilität)"
                )

            if not sub_map:
                sub_map = ["-sn"]
            return (burn_sub if burn_sub else []), sub_map

        if burn_sub:
            worker._logger.decision(
                f"Sub #{burn_sub.index} ({burn_sub.language},forced={burn_sub.forced})→burn-in"
            )
            if not keep:
                return burn_sub, ["-sn"]

            sub_map = []
            for stream in keep:
                sub_map += ["-map", f"0:{stream.index}"]
                worker._logger.decision(
                    f"Sub #{stream.index} ({stream.language},forced={stream.forced})→stream copy"
                )
            sub_map += ["-c:s", "copy"]
            return burn_sub, sub_map

        if not keep:
            worker._logger.decision("Keine kompatiblen Untertitel - keine Subs übernommen")
            return [], ["-sn"]

        sub_map = []
        for stream in keep:
            sub_map += ["-map", f"0:{stream.index}"]
            worker._logger.decision(
                f"Sub #{stream.index} ({stream.language},forced={stream.forced})→stream copy"
            )
        sub_map += ["-c:s", "copy"]
        return [], sub_map

    # ==================================================================
    # Video-Filter
    # ==================================================================
    def base_vf_args(self, pre_filters: list[str], post_filters: list[str] | None = None) -> list:
        filters = list(pre_filters) + list(post_filters or [])
        return ["-map", "0:v:0"] + (["-vf", ",".join(filters)] if filters else [])

    def text_burn_vf_args(self, input_path: str, output_path: str, burn_sub,
                          pre_filters: list[str], post_filters: list[str] | None = None) -> list:
        worker = self.worker
        trace_dv = False
        if trace_dv:
            worker.log("[TRACE][DV] before subtitle burn extraction", "info")

        sub_tmp = tempfile.NamedTemporaryFile(
            suffix=".srt",
            delete=False,
            dir=Path(output_path).parent,
        )
        sub_tmp.close()
        sub_tmp_path = sub_tmp.name

        completed = run_tool(
            [
                worker.tools.ffmpeg,
                "-y", "-nostdin", "-loglevel", "error",
                "-i", input_path,
                "-map", f"0:{burn_sub.index}",
                "-c:s", "srt",
                sub_tmp_path,
            ],
            label=f"Burn-In Untertitel #{burn_sub.index}",
            timeout_s=300,
            worker=worker,
            log=worker.log,
        )
        sub_extract_ok = completed.returncode == 0 and not completed.aborted and not completed.timed_out
        extract_error = str(completed.stderr or completed.stdout or "").strip()
        if completed.aborted:
            extract_error = extract_error or "Abgebrochen"
        elif completed.timed_out:
            extract_error = extract_error or "Timeout"

        if sub_extract_ok and Path(sub_tmp_path).exists() and Path(sub_tmp_path).stat().st_size > 0:
            all_filters = pre_filters + [f"subtitles='{_esc(sub_tmp_path)}'"] + list(post_filters or [])
            worker._burn_sub_tmp = sub_tmp_path
            if trace_dv:
                worker.log("[TRACE][DV] after subtitle burn extraction", "info")
            return ["-map", "0:v:0", "-vf", ",".join(all_filters)]

        worker.log(
            "❌ Geplanter Burn-In konnte nicht vorbereitet werden; "
            "die Konvertierung wird nicht ohne den vorgesehenen Untertitel fortgesetzt.",
            "error",
        )
        if trace_dv:
            worker.log("[TRACE][DV] after subtitle burn extraction", "info")
        try:
            os.unlink(sub_tmp_path)
        except FileNotFoundError:
            pass
        except Exception as e:
            worker.log(
                f"⚠️ Temporäre Datei konnte nicht gelöscht werden: "
                f"{Path(sub_tmp_path).name} - {e}",
                "warn",
            )
            worker.log(traceback.format_exc(), "error")
        detail = f" ({extract_error})" if extract_error else ""
        raise BurnSubtitlePreparationError(
            f"Untertitel-Stream #{burn_sub.index} konnte nicht als SRT für den Burn-In vorbereitet werden{detail}."
        )

    def image_burn_vf_args(self, mi, burn_sub, pre_filters: list[str],
                           post_filters: list[str] | None = None) -> list:
        ord_ = next(
            (i for i, s in enumerate(mi.subtitle_streams) if s.index == burn_sub.index),
            0,
        )
        post = ",".join(post_filters or [])

        if pre_filters and post:
            fc = (
                f"[0:v:0]{','.join(pre_filters)}[vpre];"
                f"[vpre][0:s:{ord_}]overlay[vburn];"
                f"[vburn]{post}[vout]"
            )
        elif pre_filters:
            fc = (
                f"[0:v:0]{','.join(pre_filters)}[vpre];"
                f"[vpre][0:s:{ord_}]overlay[vout]"
            )
        elif post:
            fc = f"[0:v:0][0:s:{ord_}]overlay[vburn];[vburn]{post}[vout]"
        else:
            fc = f"[0:v:0][0:s:{ord_}]overlay[vout]"

        return ["-filter_complex", fc, "-map", "[vout]"]

    def build_vf_args(self, input_path: str, output_path: str, mi,
                      burn_sub_or_vf, pre_filters: list[str],
                      post_filters: list[str] | None = None) -> list:
        if not burn_sub_or_vf or isinstance(burn_sub_or_vf, list):
            return self.base_vf_args(pre_filters, post_filters)

        burn_sub = burn_sub_or_vf
        from ..rules.subtitle_rules import TEXT_SUBTITLE_CODECS, IMAGE_SUBTITLE_CODECS

        codec_name = (burn_sub.codec or "").lower()
        if codec_name in TEXT_SUBTITLE_CODECS:
            return self.text_burn_vf_args(input_path, output_path, burn_sub, pre_filters, post_filters)
        if codec_name in IMAGE_SUBTITLE_CODECS:
            return self.image_burn_vf_args(mi, burn_sub, pre_filters, post_filters)

        self.worker.log(
            f"❌ Burn-Sub #{burn_sub.index} hat einen nicht unterstützten Codec: {burn_sub.codec!r}",
            "error",
        )
        raise BurnSubtitlePreparationError(
            f"Geplanter Burn-In verwendet einen nicht unterstützten Codec: {burn_sub.codec!r}."
        )
