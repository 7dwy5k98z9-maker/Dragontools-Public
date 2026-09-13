from __future__ import annotations

from pathlib import Path

from .trickplay_models import TrickplayFfmpegStrategy, TrickplaySettings


def build_trickplay_ffmpeg_cmd(
    ffmpeg_path: str,
    video: Path,
    output_pattern: Path,
    settings: TrickplaySettings,
    *,
    hwaccel: str,
    force_hwdownload: bool = False,
) -> list[str]:
    cmd = [ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y"]
    mode = normalized_hwaccel(hwaccel)
    if mode != "none":
        cmd.extend(["-hwaccel", mode])
        if force_hwdownload and mode == "cuda":
            cmd.extend(["-hwaccel_output_format", "cuda"])

    cols = max(1, int(settings.tile_columns))
    rows = max(1, int(settings.tile_rows))
    interval = max(1, int(settings.interval_s))
    width = max(16, int(settings.width))
    qscale = max(2, min(31, int(settings.qscale)))
    vf = f"fps=1/{interval},scale={width}:-2,tile={cols}x{rows}"
    if force_hwdownload and mode == "cuda":
        vf = f"hwdownload,format=nv12,{vf}"

    cmd.extend([
        "-noautorotate", "-i", str(video), "-an", "-sn", "-vf", vf,
        "-q:v", str(qscale), "-start_number", "0", "-f", "image2", str(output_pattern),
    ])
    return cmd


def normalized_hwaccel(value: str | None) -> str:
    return str(value or "").strip().lower() or "none"


def trickplay_ffmpeg_strategies(hwaccel: str) -> list[TrickplayFfmpegStrategy]:
    mode = normalized_hwaccel(hwaccel)
    if mode == "none":
        return [TrickplayFfmpegStrategy(
            name="CPU-Pfad",
            hwaccel="none",
            start_message="Trickplay: CPU-Pfad startet.",
            success_message="Trickplay: CPU-Pfad erfolgreich.",
        )]
    if mode == "cuda":
        return _cuda_strategies()
    label = hwaccel_label(mode)
    return [
        TrickplayFfmpegStrategy(
            name=f"{label}-Pfad",
            hwaccel=mode,
            start_message=f"Trickplay: Hardwarepfad {label} startet (GPU-Decoding, kompatible CPU-Filter/Tiling).",
            success_message=f"Trickplay: Hardwarepfad {label} erfolgreich.",
        ),
        TrickplayFfmpegStrategy(
            name="CPU-Fallback",
            hwaccel="none",
            before_message=f"Trickplay: Hardwarepfad {label} fehlgeschlagen; CPU-Fallback startet.",
            start_message="Trickplay: CPU-Fallback startet.",
            success_message="Trickplay: CPU-Fallback erfolgreich.",
        ),
    ]


def _cuda_strategies() -> list[TrickplayFfmpegStrategy]:
    return [
        TrickplayFfmpegStrategy(
            name="CUDA/NVDEC-Pfad",
            hwaccel="cuda",
            start_message="Trickplay: CUDA/NVDEC-Pfad startet (GPU-Decoding, kompatible CPU-Filter/Tiling).",
            success_message="Trickplay: CUDA/NVDEC-Pfad erfolgreich (GPU-Decoding; Filter/Tiling kompatibel ausgeführt).",
        ),
        TrickplayFfmpegStrategy(
            name="CUDA/NVDEC-Kompatibilitätsretry",
            hwaccel="cuda",
            force_hwdownload=True,
            before_message=(
                "Trickplay: CUDA/NVDEC-Pfad fehlgeschlagen; "
                "Kompatibilitätsretry mit explizitem Frame-Download startet."
            ),
            start_message=(
                "Trickplay: CUDA/NVDEC-Kompatibilitätsretry startet "
                "(Frame-Download vor CPU-Filtern)."
            ),
            success_message="Trickplay: CUDA/NVDEC-Kompatibilitätsretry erfolgreich.",
        ),
        TrickplayFfmpegStrategy(
            name="CPU-Fallback",
            hwaccel="none",
            before_message=(
                "Trickplay: CUDA/NVDEC-Kompatibilitätsretry fehlgeschlagen; "
                "CPU-Fallback startet."
            ),
            start_message="Trickplay: CPU-Fallback startet.",
            success_message="Trickplay: CPU-Fallback erfolgreich.",
        ),
    ]


def hwaccel_label(value: str) -> str:
    labels = {
        "cuda": "CUDA/NVDEC",
        "qsv": "Intel QSV",
        "dxva2": "DXVA2",
        "d3d11va": "D3D11VA",
        "none": "CPU",
    }
    return labels.get(value.lower(), value.upper())


def command_hwaccel_label(cmd: list[str]) -> str:
    try:
        idx = cmd.index("-hwaccel")
        label = hwaccel_label(str(cmd[idx + 1]))
        return f"{label} + hwdownload" if "-hwaccel_output_format" in cmd else label
    except (ValueError, IndexError):
        return "CPU"
