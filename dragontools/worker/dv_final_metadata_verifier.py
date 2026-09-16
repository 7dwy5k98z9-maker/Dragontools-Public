from __future__ import annotations

from pathlib import Path

from .dv_crop_reconcile import read_level5_offsets
from .dv_pipeline_timeouts import timeout_hevc_extract as _TIMEOUT_HEVC_EXTRACT, timeout_rpu_extract as _TIMEOUT_RPU_EXTRACT


class DVFinalMetadataVerifier:
    def __init__(self, *, tools, temp_state, rpu_service, hdr10plus_service, log, verbose_log, assert_nonempty_file) -> None:
        self._tools = tools
        self._temp_state = temp_state
        self._rpu_service = rpu_service
        self._hdr10plus_service = hdr10plus_service
        self._log = log
        self._vlog = verbose_log
        self._assert_nonempty_file = assert_nonempty_file

    def verify(self, state, runner, *, inspect_dynamic_hdr, verify_fallback) -> bool:
        req = state.request
        self._vlog("[DV][VERIFY] Finale Datei mit MediaInfo prüfen")
        inspection = inspect_dynamic_hdr(req.output_path, self._tools)
        require_hdr10plus = bool(req.preserve_dv_hdr10plus_combo)
        strict_crop = bool(getattr(state, "effective_crop", None))
        missing_dv, missing_hdr = True, require_hdr10plus
        if inspection.conclusive:
            dv_label = self._dv_label(inspection)
            hdr_label = "JA" if inspection.hdr10plus else "NEIN"
            self._vlog(f"[DV][VERIFY] MediaInfo: Dolby Vision={dv_label}; HDR10+={hdr_label}")
            missing_dv = not inspection.dolby_vision
            missing_hdr = bool(require_hdr10plus and not inspection.hdr10plus)
            state.verified_dolby_vision = state.verified_dolby_vision or not missing_dv
            state.verified_hdr10plus = state.verified_hdr10plus or (require_hdr10plus and not missing_hdr)
            if not missing_dv and not missing_hdr:
                container = str(getattr(req, "container", "mp4") or "mp4").upper()
                if not strict_crop:
                    self._log(f"✅ [DV][VERIFY] Finales {container}: Dolby Vision {dv_label} | HDR10+ {hdr_label}", "info")
                    return True
                self._log(f"ℹ️  [DV][VERIFY] Physischer Crop aktiv – finale RPU wird im {container} zusätzlich bytegenau gegen die verifizierte Crop-RPU geprüft.", "info")
                return verify_fallback(state, runner, verify_dv=True, verify_hdr10plus=False)
            missing = [name for name, flag in (("Dolby Vision", missing_dv), ("HDR10+", missing_hdr)) if flag]
            self._log("⚠️  [DV][VERIFY] MediaInfo bestätigt " + " / ".join(missing) + " nicht. Starte Bitstream-Fallbackprüfung.", "warn")
        else:
            detail = next((w for w in inspection.warnings if w), "keine Videospur erkannt")
            self._log(f"⚠️  [DV][VERIFY] MediaInfo-Ergebnis unklar ({detail}). Starte Bitstream-Fallbackprüfung.", "warn")
        ok = verify_fallback(
            state, runner, verify_dv=bool(missing_dv or strict_crop), verify_hdr10plus=missing_hdr
        )
        return ok

    @staticmethod
    def _dv_label(inspection) -> str:
        if not inspection.dolby_vision:
            return "NEIN"
        profile = inspection.dolby_vision_profile
        return f"JA – Profil {profile}" if profile and profile != "Ja" else "JA"

    def verify_fallback(self, state, runner, *, verify_dv: bool, verify_hdr10plus: bool, sha256_file) -> bool:
        if not verify_dv and not verify_hdr10plus:
            return True
        req, files = state.request, state.files
        final_hevc = files.root / "final_mux_verify.hevc"
        final_rpu = files.root / "final_mux_verify.rpu"
        final_hdr_json = files.root / "final_mux_hdr10plus_verify.json"
        for path in (final_hevc, final_rpu, final_hdr_json):
            path.unlink(missing_ok=True)
        container = str(getattr(req, "container", "mp4") or "mp4")
        self._log(f"ℹ️  [DV][FALLBACK] Finalen {container.upper()}-Bitstream prüfen", "info")
        if not self._extract_final_hevc(req.output_path, container, final_hevc, runner):
            return False
        if verify_dv and not self._verify_dv(state, final_hevc, final_rpu, runner, sha256_file, container):
            return False
        if verify_hdr10plus and not self._verify_hdr10plus(state, final_hevc, final_hdr_json, runner, container):
            return False
        if verify_dv and not state.final_rpu_present:
            self._log("⚠️ [DV][FALLBACK] Finaler RPU-Nachweis fehlgeschlagen; Kandidat wird zur Diagnose erhalten, Original-Replace bleibt gesperrt.", "warn")
        else:
            self._log("✅ [DV][FALLBACK] Offene dynamische Metadaten bestätigt.", "info")
        return True

    def _extract_final_hevc(self, output_path: str, container: str, final_hevc, runner) -> bool:
        cmd = [self._tools.ffmpeg, "-y", "-loglevel", "error", "-i", output_path, "-map", "0:v:0", "-c:v", "copy"]
        if container.lower() == "mp4":
            cmd += ["-bsf:v", "hevc_mp4toannexb"]
        cmd += ["-an", "-sn", "-dn", "-f", "hevc", str(final_hevc)]
        rc = runner.run(cmd, timeout=_TIMEOUT_HEVC_EXTRACT(), label="STEP 7/7 Post-Mux HEVC-Fallbackprüfung")
        return rc == 0 and self._assert_nonempty_file(final_hevc, "STEP 7 Post-Mux HEVC-Fallbackprüfung")

    def _verify_dv(self, state, final_hevc, final_rpu, runner, sha256_file, container: str) -> bool:
        """Verify final RPU without ever treating a mismatch as disposable output.

        A post-mux RPU mismatch is a metadata/geometry review condition. The final
        video remains valuable and must reach the workflow verifier so it can be
        archived with diagnostics instead of being deleted by generic failure cleanup.
        """
        state.final_rpu_checked = True
        state.final_rpu_present = False
        state.verified_dolby_vision = False
        state.verified_dv_crop_alignment = False
        state.final_rpu_matches_injected = None
        state.final_rpu_expected_sha256 = ""
        state.final_rpu_actual_sha256 = ""
        state.final_rpu_level5_offsets = ()
        state.final_rpu_level5_dynamic = False
        state.final_rpu_message = ""

        run_rpu = runner.adapter(timeout=_TIMEOUT_RPU_EXTRACT(), label="STEP 7/7 Post-Mux RPU-Fallbackprüfung")
        if not self._rpu_service.extract_rpu(run_rpu, input_hevc=final_hevc, output_rpu=final_rpu):
            state.final_rpu_message = (
                f"Dolby-Vision-RPU konnte aus dem finalen {container.upper()} nicht extrahiert werden. "
                "Der fertige Video-Kandidat muss erhalten und manuell geprüft werden."
            )
            self._log(f"⚠️ [DV][FALLBACK] {state.final_rpu_message}", "warn")
            return True
        if not self._assert_nonempty_file(final_rpu, "STEP 7 Post-Mux RPU-Fallbackprüfung"):
            state.final_rpu_message = (
                f"Extrahierte Dolby-Vision-RPU aus dem finalen {container.upper()} ist leer/ungueltig. "
                "Der fertige Video-Kandidat muss erhalten und manuell geprüft werden."
            )
            self._log(f"⚠️ [DV][FALLBACK] {state.final_rpu_message}", "warn")
            return True

        state.final_rpu_present = True
        state.verified_dolby_vision = True
        try:
            state.final_rpu_actual_sha256 = sha256_file(final_rpu)
        except Exception:
            state.final_rpu_actual_sha256 = ""
        if state.rpu_to_use is not None:
            try:
                state.final_rpu_expected_sha256 = sha256_file(state.rpu_to_use)
            except Exception:
                state.final_rpu_expected_sha256 = ""

        self._capture_final_level5(state, final_rpu, runner)

        expected_hash = state.final_rpu_expected_sha256
        actual_hash = state.final_rpu_actual_sha256
        matches = bool(expected_hash and actual_hash and expected_hash == actual_hash)
        state.final_rpu_matches_injected = matches
        state.verified_dv_crop_alignment = matches
        if matches:
            state.final_rpu_message = (
                "Finale Dolby-Vision-RPU ist byteidentisch zur injizierten RPU. "
                "RPU/Video-Ausrichtung ist bestätigt."
            )
            self._log("✅ [DV][FALLBACK] Dolby Vision im finalen Bitstream bestätigt; RPU byteidentisch.", "info")
            return True

        state.final_rpu_message = (
            f"Dolby-Vision-RPU im finalen {container.upper()} ist nicht byteidentisch zur injizierten RPU. "
            "Das ist fuer sich allein kein Fehler. Nur wenn die finale Video-Geometrie vom "
            "normalisierten Soll abweicht, wird Level 5 gegen Soll- und Ist-Geometrie bewertet."
        )
        self._log(f"ℹ️ [DV][FALLBACK] {state.final_rpu_message}", "info")
        return True

    def _capture_final_level5(self, state, final_rpu: Path, runner) -> None:
        """Best-effort Level-5 snapshot for the later archive CSV."""
        export_json = state.files.root / "final_mux_verify_level5.json"
        export_json.unlink(missing_ok=True)
        dovi_tool = str(getattr(self._tools, "dovi_tool", "") or "")
        if not dovi_tool:
            return
        commands = (
            [dovi_tool, "export", "-i", str(final_rpu), "-d", f"level5={export_json}"],
            [dovi_tool, "export", "-i", str(final_rpu), "--data", f"level5={export_json}"],
        )
        for index, command in enumerate(commands, start=1):
            export_json.unlink(missing_ok=True)
            try:
                rc = runner.run(
                    command,
                    timeout=_TIMEOUT_RPU_EXTRACT(),
                    label=f"STEP 7/7 Finale RPU Level-5-Diagnose ({index}/{len(commands)})",
                    allow_error=True,
                )
            except Exception:
                rc = -1
            if rc == 0 and export_json.exists() and export_json.stat().st_size > 0:
                try:
                    offsets = read_level5_offsets(export_json)
                except Exception as exc:
                    self._vlog(f"[DV][FALLBACK] Finale Level-5-Diagnose konnte nicht gelesen werden: {exc}")
                    return
                state.final_rpu_level5_offsets = offsets
                state.final_rpu_level5_dynamic = len(offsets) > 1
                return

    def _verify_hdr10plus(self, state, final_hevc, final_hdr_json, runner, container: str) -> bool:
        run_hdr = runner.adapter(timeout=_TIMEOUT_HEVC_EXTRACT(), label="STEP 7/7 Post-Mux HDR10+-Fallbackprüfung")
        if not self._hdr10plus_service.verify_metadata(run_hdr, source_stream=final_hevc, scratch_json=final_hdr_json, expected_json=state.files.hdr10plus_json):
            reason = f"HDR10+-Metadaten sind nach dem {container.upper()}-Mux nicht identisch nachweisbar."
            self._temp_state.record_failure(reason=reason, stage="STEP 7/7 Post-Mux Metadaten-Fallbackprüfung")
            self._log("❌ [DV+HDR10+][FALLBACK] HDR10+-Nachprüfung fehlgeschlagen.", "error")
            return False
        state.verified_hdr10plus = True
        self._log("✅ [DV+HDR10+][FALLBACK] HDR10+ im finalen Bitstream bestätigt.", "info")
        return True
