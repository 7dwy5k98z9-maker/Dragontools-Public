# -*- coding: utf-8 -*-
from __future__ import annotations

import traceback
from pathlib import Path

from .hdrplus_encode_service import HDRPlusEncodeService
from .hdrplus_mux_service import HDRPlusMuxService


class HDRPlusCompatibilityMixin:
    """Schmale Legacy-/Testwrapper der HDR10+-Fassade.

    Die Methoden enthalten keine Pipeline-Entscheidungen. Sie halten lediglich
    die seit längerem genutzten Helper-Namen stabil und delegieren an Services.
    """

    def _run_hdrplus_tool(
        self,
        cmd: list,
        *,
        label: str,
        tool_name: str,
        accepted_returncodes: tuple[int, ...] = (0,),
    ) -> bool:
        return self._tool_runner.run_hdrplus(
            cmd,
            label=label,
            tool_name=tool_name,
            accepted_returncodes=accepted_returncodes,
        )

    def _run_hdrplus_tool_rc(self, cmd: list, *, allow_error: bool = False) -> int:
        return self._tool_runner.run_hdrplus_rc(cmd, allow_error=allow_error)

    def _verify_final_hdr10plus(self, output_path: str, expected_json: Path) -> bool:
        return self._stream_service.verify_final_hdr10plus(
            output_path,
            expected_json,
            run_tool=self._run_hdrplus_tool,
            run_tool_rc=self._run_hdrplus_tool_rc,
            bitstream_service=self._hdr10plus_service,
        )

    def _extract_hevc_annexb(self, input_path: str, output_hevc: str) -> bool:
        return self._stream_service.extract_hevc_annexb(
            input_path,
            output_hevc,
            run_tool=self._run_hdrplus_tool,
        )

    @staticmethod
    def _has_aux_stream_output(audio_args: list, subtitle_args: list) -> bool:
        return HDRPlusEncodeService.has_aux_stream_output(audio_args, subtitle_args)

    def _encode_hevc_and_stream_donor(
        self,
        *,
        input_path: str,
        encoded_hevc: Path,
        stream_donor: Path,
        vf_args: list,
        audio_args: list,
        audio_input_args: list,
        subtitle_args: list,
        media_info,
    ) -> bool:
        return self._encode_service.encode(
            input_path=input_path,
            encoded_hevc=encoded_hevc,
            stream_donor=stream_donor,
            vf_args=vf_args,
            audio_args=audio_args,
            audio_input_args=audio_input_args,
            subtitle_args=subtitle_args,
            media_info=media_info,
            encoder=self._default_encoder_config(),
        )

    def _run_mux_tool(
        self,
        cmd: list,
        *,
        label: str,
        tool_name: str,
        accepted_returncodes: tuple[int, ...] = (0,),
    ) -> bool:
        return self._tool_runner.run_mux(
            cmd,
            label=label,
            tool_name=tool_name,
            accepted_returncodes=accepted_returncodes,
        )

    def _mux_hdrplus_mkv(self, injected_hevc: str, stream_donor: str, output_path: str) -> bool:
        return self._mux_service.mux_mkv(injected_hevc, stream_donor, output_path)

    def _probe_mp4_audio(self, donor: Path) -> list[dict] | None:
        return self._mux_service.probe_mp4_audio(donor)

    @staticmethod
    def _audio_ext(codec: str) -> str:
        return HDRPlusMuxService.audio_ext(codec)

    def _mux_hdrplus_mp4(
        self,
        injected_hevc: str,
        stream_donor: str,
        output_path: str,
        *,
        tmp_dir: Path,
        subtitle_tracks=(),
    ) -> bool:
        return self._mux_service.mux_mp4(
            injected_hevc,
            stream_donor,
            output_path,
            tmp_dir=tmp_dir,
            subtitle_tracks=subtitle_tracks,
        )

    def _mux_hdrplus_output(
        self,
        injected_hevc: str,
        stream_donor: str,
        output_path: str,
        *,
        container: str,
        tmp_dir: Path | None = None,
        subtitle_tracks=(),
    ) -> bool:
        target = str(container or "mkv").lower()
        if target == "mkv":
            return self._mux_hdrplus_mkv(injected_hevc, stream_donor, output_path)
        if target == "mp4":
            return self._mux_hdrplus_mp4(
                injected_hevc,
                stream_donor,
                output_path,
                tmp_dir=tmp_dir or Path(output_path).parent,
                subtitle_tracks=subtitle_tracks,
            )
        self._log(f"❌ HDR10+: Nicht unterstützter Zielcontainer: {target}", "error")
        return False

    def _cleanup_tmp_sub(self, input_path: str) -> None:
        del input_path  # historischer Parameter; Cleanup hängt ausschließlich am Temp-State.
        tmp_sub = self._temp_state.burn_sub_tmp
        if not tmp_sub:
            return
        try:
            Path(tmp_sub).unlink(missing_ok=True)
        except Exception as exc:
            self._log(
                f"⚠️ Temporäre Datei konnte nicht gelöscht werden: {Path(tmp_sub).name} – {exc}",
                "warn",
            )
            self._log(traceback.format_exc(), "error")
        finally:
            self._temp_state.burn_sub_tmp = None
