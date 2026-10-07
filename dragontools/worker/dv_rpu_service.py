# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Callable
from ..core.strict_numbers import positive_integer


class DVRpuService:
    def __init__(self, *, dovi_tool_path: str, log: Callable[[str, str], None]) -> None:
        self._dovi_tool_path = dovi_tool_path
        self._log = log

    def extract_rpu(
        self,
        run_cmd,
        *,
        output_rpu: Path,
        input_hevc: Path | None = None,
        input_path: Path | str | None = None,
        mode: str | int | None = None,
        track_number: int | None = None,
    ) -> bool:
        """Extract a Dolby-Vision RPU from HEVC *or directly from Matroska*.

        ``dovi_tool`` applies the global conversion mode while extracting the
        RPU as well.  This lets the normal encoder path avoid a large
        ``source.hevc -> p8.hevc`` intermediate: P5 uses mode 3 and P7/P8 use
        mode 2, so the RPU is normalized to P8.1 directly from the source MKV
        while the picture encode reads the MKV independently.

        ``input_hevc`` is retained for compatibility with the post-injection
        verification paths, which still operate on raw HEVC.
        """
        source = input_path if input_path is not None else input_hevc
        if source is None:
            raise ValueError("extract_rpu requires input_path or input_hevc")

        cmd = [self._dovi_tool_path]
        if mode not in (None, ""):
            cmd += ["-m", str(mode)]
        cmd += ["extract-rpu", "-i", str(source)]
        if track_number is not None:
            cmd += ["-t", str(positive_integer(track_number))]
        cmd += ["-o", str(output_rpu)]

        self._log("DV: Extrahiere RPU …", "info")
        return run_cmd(cmd) == 0

    def inject_rpu(
        self,
        run_cmd,
        *,
        input_hevc: Path,
        input_rpu: Path,
        output_hevc: Path,
    ) -> bool:
        self._log("DV: Injiziere RPU …", "info")
        return (
            run_cmd(
                [
                    self._dovi_tool_path,
                    "inject-rpu",
                    "-i",
                    str(input_hevc),
                    "--rpu-in",
                    str(input_rpu),
                    "-o",
                    str(output_hevc),
                ]
            )
            == 0
        )
