# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Callable


class DVRpuService:
    def __init__(self, *, dovi_tool_path: str, log: Callable[[str, str], None]) -> None:
        self._dovi_tool_path = dovi_tool_path
        self._log = log

    def extract_rpu(self, run_cmd, *, input_hevc: Path, output_rpu: Path) -> bool:
        self._log("DV: Extrahiere RPU …", "info")
        return (
            run_cmd(
                [
                    self._dovi_tool_path,
                    "extract-rpu",
                    "-i",
                    str(input_hevc),
                    "-o",
                    str(output_rpu),
                ]
            )
            == 0
        )

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
