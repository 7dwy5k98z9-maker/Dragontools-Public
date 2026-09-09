# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from .logger_paths import _fd, _fs, _ts
from .move_report import format_move_target_summary_lines
from .settings import APP_VERSION


class DragonLoggerMessageMixin:
    """Domain-specific conversion/move log formatting."""

    def header(
        self,
        gpus: list[str],
        chosen_encoder: str,
        total_files: int,
        codec: str,
        crf: int,
        preset: str,
        *,
        scale_mode: str | None = None,
        overwrite_original: bool | None = None,
        strip_only: bool | None = None,
        encoder_options: dict | None = None,
        manual_override_count: int = 0,
    ) -> None:
        """Schreibt den Konvertierungs-Header (einmal pro Session)."""
        sep = "=" * 90
        self._write(sep)
        self._write(f"🖥️  Konvertierungsbericht – Dragon Tools V{APP_VERSION}")
        if gpus:
            self._write(f"🖥️  erkannte GPUs: {gpus}")
        self._write(f"🎯  gewählter HW-Encoder: {chosen_encoder}")
        self._write(sep)
        self._write(f"Startzeit: {_ts()}")
        self._write(f"Dateien: {total_files}")
        q_label = "CQ" if str(chosen_encoder).lower() == "nvenc" else (
            "QP" if str(chosen_encoder).lower() == "amf" else "CRF"
        )
        quality = f" | {q_label}: {crf}" if crf is not None else ""
        self._write(f"Einstellungen: {str(codec).upper()}{quality} | Preset: {preset}")
        opts = dict(encoder_options or {})
        param_lines: list[str] = []
        if scale_mode is not None:
            param_lines.append(f"Skalierung: {scale_mode or 'original'}")
        if overwrite_original is not None:
            param_lines.append(f"Original ersetzen: {self._fmt_bool(overwrite_original)}")
        if strip_only is not None:
            param_lines.append(f"Strip-Only: {self._fmt_bool(strip_only)}")
        if param_lines or opts:
            self._write("Parameter:")
            if param_lines:
                self._write("  " + " | ".join(param_lines))
            for line in self._format_encoder_details(str(chosen_encoder).lower(), opts):
                self._write(f"  {line}")
            if "preserve_dv" in opts or "preserve_hdrplus" in opts:
                self._write(
                    "  Dolby Vision erhalten: "
                    f"{self._fmt_bool(opts.get('preserve_dv'))} | "
                    "HDR10+ erhalten: "
                    f"{self._fmt_bool(opts.get('preserve_hdrplus'))}"
                )
        if manual_override_count:
            self._write(
                f"Manuelle Datei-Overrides: {manual_override_count} Datei(en) "
                "- Details stehen beim jeweiligen Dateieintrag."
            )
        if self.log_file:
            self._write(f"Log-Datei: {self.log_file}")
        self._write(sep)

    def move_header(self, total_files: int) -> None:
        """Schreibt den Header für einen reinen Verschiebe-Vorgang (ohne Konvertierung)."""
        sep = "=" * 90
        self._write(sep)
        self._write(f"📁  Verschiebebericht – Dragon Tools V{APP_VERSION}")
        self._write(sep)
        self._write(f"Startzeit: {_ts()}")
        if self.log_file:
            self._write(f"Log-Datei: {self.log_file}")
        self._write(f"Dateien:   {total_files}")
        self._write(sep)

    def file_start(self, idx: int, total: int, path: str,
                   codec: str, crf: int | None, preset: str,
                   encoder: str, q_label: str = "CRF",
                   encoder_options: dict | None = None) -> None:
        """
        Datei-Start Block.

        Der eigentliche Dateiname wird bereits vom Worker mit ▶ Datei [...]
        geloggt. Hier bleibt nur die kompakte, pro Datei wirksame Videozeile.
        """
        num  = f"{idx:03d}/{total:03d}"
        now  = datetime.now()
        self._write("")
        self._write(f"▶ Quelle: {Path(path).name}", to_gui=True, to_short=True)
        q_str = str(crf) if crf is not None else "–"
        self._write(
            f"ℹ️  Datei {num} – Start: {now.strftime('%d.%m.%Y %H:%M:%S Uhr')} | "
            f"Video: {str(codec).upper()}/{encoder} {q_label} {q_str} {preset}"
        )

    @staticmethod
    def _fmt_bool(val) -> str:
        return "an" if bool(val) else "aus"

    def _format_encoder_details(self, encoder: str, opts: dict) -> list[str]:
        """Baut die Detail-Zeilen (ohne Prefix) für das Start-Logging."""
        lines: list[str] = []
        enc = (encoder or "").lower()

        if enc == "nvenc":
            bf       = opts.get("bf")
            bref     = opts.get("bref_mode")
            la       = opts.get("rc_lookahead")
            aq       = opts.get("aq_strength")
            sp_aq    = opts.get("spatial_aq")
            tm_aq    = opts.get("temporal_aq")
            if any(v is not None for v in (bf, bref, la)):
                lines.append(
                    f"🎞️  B-Frames: {bf if bf is not None else '–'}  |  "
                    f"B-Ref-Mode: {bref or '–'}  |  "
                    f"Lookahead: {la if la is not None else '–'}"
                )
            if any(v is not None for v in (aq, sp_aq, tm_aq)):
                lines.append(
                    f"🎯 AQ-Stärke: {aq if aq is not None else '–'}  |  "
                    f"Spatial AQ: {self._fmt_bool(sp_aq)}  |  "
                    f"Temporal AQ: {self._fmt_bool(tm_aq)}"
                )

        elif enc == "qsv":
            la_depth = opts.get("lookahead_depth")
            lines.append(
                f"🎞️  Lookahead: an  |  Tiefe: "
                f"{la_depth if la_depth is not None else '–'}"
            )

        elif enc == "amf":
            quality = opts.get("quality")
            qp      = opts.get("qp")
            if quality is not None or qp is not None:
                lines.append(
                    f"🎯 Qualität: {quality or '–'}  |  "
                    f"QP: {qp if qp is not None else '–'}"
                )

        elif enc == "cpu":
            # x265 / Software-Encoder
            bf       = opts.get("bf")
            la       = opts.get("rc_lookahead")
            tune     = opts.get("tune")
            aq_mode  = opts.get("aq_mode")
            aq_str   = opts.get("aq_strength")
            psy_rd   = opts.get("psy_rd")
            psy_rdoq = opts.get("psy_rdoq")
            if any(v is not None for v in (bf, la, tune, aq_mode)):
                lines.append(
                    f"🎞️  B-Frames: {bf if bf is not None else '–'}  |  "
                    f"Lookahead: {la if la is not None else '–'}  |  "
                    f"Tune: {tune or '–'}  |  "
                    f"AQ-Mode: {aq_mode or '–'}"
                )
            if any(v is not None for v in (aq_str, psy_rd, psy_rdoq)):
                lines.append(
                    f"🎯 AQ-Stärke: {aq_str if aq_str is not None else '–'}  |  "
                    f"Psy-RD: {psy_rd if psy_rd is not None else '–'}  |  "
                    f"Psy-RDOQ: {psy_rdoq if psy_rdoq is not None else '–'}"
                )

        # Globale Zusatz-Optionen (encoder-unabhängig)
        autocrop = opts.get("autocrop_enabled")
        imax_auto = opts.get("imax_auto_detect")
        if autocrop is not None or imax_auto is not None:
            lines.append(
                f"🧹 Auto-Crop: {self._fmt_bool(autocrop)}  |  "
                f"IMAX Auto-Erkennung: {self._fmt_bool(imax_auto)}"
            )

        return lines

    def crop(self, w: int, h: int, cw: int, ch: int) -> None:
        if cw == w and ch == h:
            self._write("ℹ️  Keine relevanten schwarzen Balken erkannt – Auto-Crop nicht nötig.")
        else:
            self._write(f"ℹ️  Auto-Crop: {w}x{h} → {cw}x{ch}")

    def scale(self, orig_w: int, orig_h: int, scale_str: str) -> None:
        if scale_str in ("original", "", None):
            self._write(f"ℹ️  Keine Skalierung angewendet (Auflösung: {orig_w}x{orig_h})")
        else:
            self._write(f"ℹ️  Skalierung: {orig_w}x{orig_h} → {scale_str}")

    def audio(self, track_num: int, codec: str, action: str,
              target_codec: str | None = None, channels: int | None = None,
              bitrate_k: int | None = None, language: str | None = None) -> None:
        ch_str  = f" {channels}ch" if channels else ""
        bk_str  = f" {bitrate_k}k" if bitrate_k else ""
        if language:
            try:
                from .lang_codes import lang_display
                language = lang_display(language)
            except Exception:
                pass
        lang = f" [{language}]" if language else ""
        if action == "copy":
            self._write(f"ℹ️  Audio Spur {track_num}{lang} ({codec}) wird kopiert", to_gui=True, to_short=True)
        else:
            tgt = target_codec or "eac3"
            self._write(f"ℹ️  Audio Spur {track_num}{lang} ({codec}) → {tgt}{ch_str}{bk_str}", to_gui=True, to_short=True)

    def subtitle(self, msg: str) -> None:
        self._write(f"ℹ️  {msg}")

    def pipeline(self, name: str, container: str,
                 has_dv: bool, has_hdrplus: bool) -> None:
        flags = []
        if has_dv:     flags.append("Dolby Vision")
        if has_hdrplus: flags.append("HDR10+")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        display_name = {
            "av1_dv": "AV1-DV10 (BETA)",
            "av1_hdrplus": "AV1-HDR10+ (BETA)",
        }.get(str(name or "").lower(), str(name or "").upper())
        self._write(f"ℹ️  Pipeline: {display_name}{flag_str}  →  .{container}", to_gui=True, to_short=True)

    def file_done(self, path: str, new_path: str | None,
                  sz_before: int, sz_after: int,
                  duration_s: float, overwritten: bool,
                  start_ts: float | None = None) -> None:
        name_new = Path(new_path).name if new_path else Path(path).name
        action   = "Original ersetzt" if overwritten else "Konvertiert"
        end_dt   = datetime.now()
        dur_str  = _fd(duration_s)
        self._write(f"✅  {action}: {name_new}", to_gui=True, to_short=True)
        if start_ts:
            start_dt = datetime.fromtimestamp(start_ts)
            self._write(
                f"✅  ⏱ Start: {start_dt.strftime('%H:%M:%S')} Uhr  │  "
                f"Ende: {end_dt.strftime('%H:%M:%S')} Uhr  │  "
                f"Dauer: {dur_str}", to_gui=True, to_short=True
            )
        else:
            self._write(f"✅  Dauer: {dur_str}", to_gui=True, to_short=True)
        if sz_before > 0 and sz_after > 0:
            self._write(
                f"✅  Größe: {_fs(sz_before)} → {_fs(sz_after)}"
                + (f"  (–{_fs(sz_before - sz_after)}, {(sz_before - sz_after) / sz_before * 100:.1f}%)"
                   if sz_after < sz_before else ""), to_gui=True, to_short=True
            )
            self._write("")
            self._write("")

    def move_summary(self, move_log: list | None, move_ok: int, move_errors: int) -> None:
        """Schreibt nur den Verschiebebericht – für Workflows ohne Konvertierungs-Stats (z.B. DV-Remux)."""
        if not move_log and move_ok == 0 and move_errors == 0:
            return
        sep = "=" * 90
        self._write("")
        self._write(sep)
        for line in format_move_target_summary_lines(
            move_log,
            move_ok=move_ok,
            move_errors=move_errors,
        ):
            self._write(line)
        self._write(sep)

    def file_error(self, path: str, reason: str) -> None:
        self._write(f"❌  Fehler bei: {Path(path).name}", to_gui=True, to_short=True)
        self._write(f"❌  {reason}", to_gui=True, to_short=True)

    def file_skipped(self, path: str, reason: str) -> None:
        self._write(f"⏭️  Übersprungen: {Path(path).name}  ({reason})", to_gui=True, to_short=True)

    def summary(self, ok: int, errors: int,
                saved_bytes: int, total_duration_s: float,
                total_before: int = 0, total_after: int = 0,
                move_log: list | None = None,
                start_ts: float | None = None, 
                move_ok: int = 0, move_errors: int = 0,
                archiviert: int = 0) -> None:
        sep = "=" * 90
        end_dt = datetime.now()
        self._write("")
        # Erst Verschiebebericht, falls vorhanden
        if move_log:
            self._write(sep)
            for line in format_move_target_summary_lines(
                move_log,
                move_ok=move_ok,
                move_errors=move_errors,
            ):
                self._write(line)

        # Danach dein Abschlussblock
        self._write("")
        self._write(sep)
        self._write("")
        archiv_suffix = f" / {archiviert} Archivierung{'en' if archiviert != 1 else ''}" if archiviert > 0 else ""
        self._write(f"✅  Konvertiert Gesamt: {ok} OK / {errors} Fehler{archiv_suffix}")
        if not move_log:
            self._write(f"✅  Verschoben Gesamt: {move_ok} OK / {move_errors} Fehler")
        self._write(f"🕐  Gesamtdauer: {_fd(total_duration_s)}")

        if start_ts:
            start_dt = datetime.fromtimestamp(start_ts)
            self._write(
                f"🕐  Konvertiert: {start_dt.strftime('%d.%m.%Y %H:%M')} Uhr"
                f" – {end_dt.strftime('%d.%m.%Y %H:%M')} Uhr"
            )

        if total_before > 0 and total_after > 0:
            pct = saved_bytes / total_before * 100 if total_before > 0 else 0
            if saved_bytes >= 0:
                self._write(
                    f"💾  Einsparung: {_fs(saved_bytes)} ({pct:.1f}%)  │  "
                    f"💾  {_fs(total_before)} → {_fs(total_after)}"
                )
            else:
                self._write(
                    f"⚠️  Größenzunahme: {_fs(abs(saved_bytes))}  │  "
                    f"💾  {_fs(total_before)} → {_fs(total_after)}"
                )

        # Log-Infrastruktur-Fehler am Ende des Runs explizit ausweisen,
        # damit der Nutzer weiß, dass Einträge möglicherweise fehlen.
        failure_msg = self.failure_summary
        if failure_msg:
            print(f"[DragonLogger] {failure_msg}", file=sys.stderr)
            # Direkt in die Datei schreiben (bypass _write um Loop zu vermeiden)
            if self.log_file:
                try:
                    with open(self.log_file, "a", encoding="utf-8") as f:
                        f.write(failure_msg + "\n")
                except Exception:
                    pass
