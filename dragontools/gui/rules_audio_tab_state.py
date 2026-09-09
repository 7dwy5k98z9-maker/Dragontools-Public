# -*- coding: utf-8 -*-
from __future__ import annotations

class AudioTabStateMixin:
    def _preview(self):
        """Simuliert die Entscheidung mit den aktuell eingestellten Regeln."""
        from ..core.models import AudioStream
        rules = self.get_data()
        codec = self.p_codec.text().strip() or "aac"
        ch    = self.p_ch.value()
        br_k  = self.p_br.value()
        br    = br_k * 1000 if br_k > 0 else 0

        stream = AudioStream(index=0, language="de", forced=False, title=None,
                             codec=codec, channels=ch, bitrate=br)
        from ..rules.audio_plan import audio_filter_chain, compute_audio_track_plan
        plan = compute_audio_track_plan(
            audio_streams=[stream],
            file_override=None,
            container="mkv",
            rules=rules,
            apply_language_rules=False,
        )
        if not plan:
            self.prev_res.setText("⚠️  Keine Audiospur würde übernommen.")
            return
        decision = plan[0]

        if decision.needs_transcode:
            bk = max(1, int(decision.target_bitrate or 0) // 1000)
            msg = (f"⚠️  Transkodierung nötig\n"
                   f"   Eingang:  {codec.upper()}  {ch}ch  "
                   f"{br_k if br_k else '?'} kbps\n"
                   f"   Ausgang:  {decision.target_codec.upper()}  "
                   f"{decision.target_channels}ch  {bk} kbps")
        else:
            msg = (f"✅  Kopieren (passthrough)\n"
                   f"   {codec.upper()}  {ch}ch  "
                   f"{br_k if br_k else '?'} kbps  → direkt übernommen")

        filter_chain = audio_filter_chain(decision)
        notes = list(getattr(decision, "processing_notes", ()) or ())
        if filter_chain:
            notes.append(f"Filter: {filter_chain}")
        if decision.drc_scale is not None:
            notes.append(f"FFmpeg-Eingabeoption: -drc_scale {decision.drc_scale:.1f}")
        if notes:
            msg += "\n\n🔊  Audio-Dynamik / Lautheit:\n   " + "\n   ".join(notes)

        effective_channels = int(decision.target_channels if decision.needs_transcode else ch)
        if rules.get("extra_stereo") and effective_channels > 2:
            stereo_bk = rules.get("extra_stereo_bitrate_k", 256)
            stereo_codec = str(rules.get("extra_stereo_codec", "aac")).upper()
            msg += (f"\n\n🎧  Zusatz-Stereo-Spur:\n"
                    f"   {stereo_codec}  2ch  {stereo_bk} kbps  (Downmix aus obiger Spur)")
        self.prev_res.setText(msg)

    def get_data(self) -> dict:
        trans = {}
        for codec, cb in self._trans_checks.items():
            if cb.isChecked():
                trans[codec] = {"target_codec": self._trans_codecs[codec].currentText()}

        language_data = self.language_editor.data()
        language_priority = language_data["language_priority"]

        return {
            **language_data,
            "preferred_languages": language_priority[:1] or ["de"],
            "fallback_languages":  language_priority[1:] or ["en"],
            "max_tracks":          language_data["max_languages"],
            "ignore_commentary_tracks": self.ignore_commentary_cb.isChecked(),
            "ignore_descriptive_audio": self.ignore_descriptive_cb.isChecked(),
            "passthrough_codecs":  [l.strip() for l in self.pass_edit.text().split(",") if l.strip()],
            "extra_stereo":           self.extra_stereo_cb.isChecked(),
            "extra_stereo_codec":     self.extra_stereo_codec.currentText(),
            "extra_stereo_bitrate_k": self.extra_stereo_br.value(),
            "audio_processing": {
                "drc_enabled": self.drc_cb.isChecked(),
                "drc_scale": round(float(self.drc_scale.value()), 1),
                "loudnorm_enabled": self.loudnorm_cb.isChecked(),
                "loudnorm_i": round(float(self.loudnorm_i.value()), 1),
                "loudnorm_lra": float(self._audio_processing_lra),
                "loudnorm_tp": float(self._audio_processing_tp),
            },
            "channel_rules": {
                "mono":        {"max_channels": 1,                    "target_codec": self.s10_codec.currentText(), "max_bitrate_k": self.s10_br.value()},
                "stereo": {
                    "max_channels": 2,
                    "target_codec": self.s20_codec.currentText(),
                    "max_bitrate_k": self.s20_br.value(),
                    "copy_min_bitrate_k": self.s20_copy_min_br.value(),
                    "copy_max_bitrate_k": max(self.s20_copy_min_br.value(), self.s20_copy_max_br.value()),
                },
                "surround_51": {
                    "max_channels": 6,
                    "target_channels": 2 if self.s51_downmix_mode.currentData() == "always" else 6,
                    "target_codec": self.s51_codec.currentText(),
                    "max_bitrate_k": self.s51_br.value(),
                    "copy_min_bitrate_k": self.s51_copy_min_br.value(),
                    "copy_max_bitrate_k": max(self.s51_copy_min_br.value(), self.s51_copy_max_br.value()),
                    "downmix_mode": str(self.s51_downmix_mode.currentData() or "never"),
                    "downmix_bitrate_k": self.s51_downmix_br.value(),
                },
                "surround_71": {
                    "max_channels": 8,
                    "target_channels": 2 if self.s71_downmix_target.currentData() == "stereo" else 6,
                    "target_codec": self.s71_codec.currentText(),
                    "max_bitrate_k": self.s71_br.value(),
                    "copy_min_bitrate_k": self.s71_copy_min_br.value(),
                    "copy_max_bitrate_k": max(self.s71_copy_min_br.value(), self.s71_copy_max_br.value()),
                    "downmix_mode": str(self.s71_downmix_mode.currentData() or "never"),
                    "downmix_target": str(self.s71_downmix_target.currentData() or "surround_51"),
                    "downmix_bitrate_k": self.s71_downmix_br.value(),
                },
            },
            "transcode_rules": trans,
        }
