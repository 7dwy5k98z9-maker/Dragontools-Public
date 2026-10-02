from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import __version__
from .analyzer.decoder import ProbeTimeoutError, ProbeToolNotFoundError, probe_video
from .analyzer.scanner import FFmpegInactivityTimeoutError, scan_pq_video
from .metadata.json_writer import write_json_atomic
from .metadata.st2094_40 import build_st2094_40_metadata


def _emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0 if payload.get("success") is True else 2


def _norm(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "").replace("-", "").replace(".", "")



def _infer_bit_depth(pixel_format: str, profile: str = "") -> int | None:
    """Infer only when the format/profile is explicit enough to be fail-closed."""
    fmt = str(pixel_format or "").strip().lower()
    prof = str(profile or "").strip().lower()
    match = re.search(r"(?:p|gbrp|gray|yuva\d*p)(10|12|14|16)(?:le|be)?$", fmt)
    if match:
        return int(match.group(1))
    match = re.search(r"p0(10|12)(?:le|be)?$", fmt)
    if match:
        return int(match.group(1))
    if fmt in {
        "yuv420p", "yuv422p", "yuv444p", "yuva420p", "yuva422p", "yuva444p",
        "nv12", "nv21", "gbrp", "gray", "gray8", "rgb24", "bgr24",
    }:
        return 8
    if "main 10" in prof or "main10" in prof:
        return 10
    if prof == "main" and str(pixel_format or "").strip():
        # HEVC Main together with a known, non-high-bit-depth pixel format is 8-bit.
        if not re.search(r"(?:10|12|14|16)", fmt):
            return 8
    return None

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="HDRPlusGenerator")
    parser.add_argument("--version", action="store_true", dest="show_version")
    sub = parser.add_subparsers(dest="command")
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--input", required=True)
    analyze.add_argument("--output", required=True)
    analyze.add_argument("--ffprobe", default="ffprobe")
    analyze.add_argument("--ffmpeg", default="ffmpeg")
    analyze.add_argument("--analysis-width", type=int, default=256)
    analyze.add_argument("--scene-threshold", type=float, default=0.32)
    analyze.add_argument("--min-scene-frames", type=int, default=6)
    analyze.add_argument("--probe-timeout", type=float, default=30.0)
    analyze.add_argument("--ffmpeg-inactivity-timeout", type=float, default=300.0)
    analyze.add_argument("--progress-interval", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.show_version:
        return _emit({"success": True, "version": __version__})
    if args.command != "analyze":
        return _emit({"success": False, "error": "INVALID_COMMAND", "message": "Use analyze or --version."})

    source = Path(args.input)
    output = Path(args.output)
    output.unlink(missing_ok=True)
    if not source.is_file():
        return _emit({"success": False, "error": "INPUT_NOT_FOUND", "message": f"Input not found: {source}"})
    print("HDR10+ phase: Vorprüfung", file=sys.stderr, flush=True)
    try:
        probe = probe_video(
            source,
            ffprobe=args.ffprobe,
            timeout_s=max(0.1, float(args.probe_timeout)),
        )
    except ProbeToolNotFoundError as exc:
        return _emit({"success": False, "error": "TOOL_NOT_FOUND", "message": str(exc)})
    except ProbeTimeoutError as exc:
        return _emit({"success": False, "error": "PROBE_TIMEOUT", "message": str(exc)})
    except FileNotFoundError as exc:
        return _emit({"success": False, "error": "INPUT_NOT_FOUND", "message": str(exc)})
    except Exception as exc:
        return _emit({"success": False, "error": "PROBE_FAILED", "message": str(exc)})

    transfer = _norm(probe.transfer)
    if transfer not in {"pq", "st2084", "smpte2084", "smpte2084pq"}:
        return _emit({
            "success": False,
            "error": "SOURCE_NOT_PQ",
            "message": "Source does not use PQ/ST2084 transfer characteristics.",
            "transfer": probe.transfer,
        })

    primaries = _norm(probe.primaries)
    if primaries not in {"bt2020", "rec2020"}:
        return _emit({
            "success": False,
            "error": "SOURCE_NOT_BT2020",
            "message": f"PQ source is not tagged as BT.2020 ({probe.primaries}).",
            "transfer": probe.transfer,
            "primaries": probe.primaries,
        })

    matrix = _norm(probe.color_space)
    if matrix and matrix not in {"bt2020", "bt2020nc", "bt2020ncl"}:
        return _emit({
            "success": False,
            "error": "SOURCE_MATRIX_UNEXPECTED",
            "message": f"PQ/BT.2020 source has an unexpected matrix ({probe.color_space}).",
            "matrix": probe.color_space,
        })

    effective_bit_depth = probe.bit_depth or _infer_bit_depth(probe.pixel_format, probe.profile)
    if effective_bit_depth is not None and effective_bit_depth < 10:
        return _emit({
            "success": False,
            "error": "SOURCE_BIT_DEPTH_UNEXPECTED",
            "message": (
                f"PQ/BT.2020 source resolves to only {effective_bit_depth}-bit video "
                f"(pix_fmt={probe.pixel_format or 'unknown'}, profile={probe.profile or 'unknown'})."
            ),
            "bit_depth": effective_bit_depth,
            "pixel_format": probe.pixel_format,
            "profile": probe.profile,
        })

    if probe.width is None or probe.height is None or probe.width <= 0 or probe.height <= 0:
        return _emit({
            "success": False,
            "error": "PROBE_INCOMPLETE",
            "message": "ffprobe did not provide a valid video width and height.",
            "width": probe.width,
            "height": probe.height,
        })

    print("HDR10+ phase: Bildanalyse", file=sys.stderr, flush=True)
    try:
        scan = scan_pq_video(
            source,
            probe,
            ffmpeg=args.ffmpeg,
            analysis_width=max(64, min(1024, int(args.analysis_width))),
            inactivity_timeout_s=max(0.1, float(args.ffmpeg_inactivity_timeout)),
            progress_interval_s=max(0.5, float(args.progress_interval)),
        )
        frame_count = len(scan.frames)
        analysis_width = scan.width
        analysis_height = scan.height
        metadata = build_st2094_40_metadata(
            scan.frames,
            scene_threshold=max(0.01, min(1.0, float(args.scene_threshold))),
            min_scene_frames=max(1, int(args.min_scene_frames)),
            tool_version=__version__,
        )
        del scan
        scenes = len(metadata["SceneInfoSummary"]["SceneFirstFrameIndex"])
        print("HDR10+ phase: Metadaten schreiben", file=sys.stderr, flush=True)
        write_json_atomic(output, metadata)
        del metadata
    except FileNotFoundError as exc:
        output.unlink(missing_ok=True)
        return _emit({"success": False, "error": "TOOL_NOT_FOUND", "message": str(exc)})
    except FFmpegInactivityTimeoutError as exc:
        output.unlink(missing_ok=True)
        return _emit({"success": False, "error": "ANALYSIS_TIMEOUT", "message": str(exc)})
    except Exception as exc:
        output.unlink(missing_ok=True)
        return _emit({"success": False, "error": "ANALYSIS_FAILED", "message": str(exc)})

    return _emit({
        "success": True,
        "version": __version__,
        "input": str(source),
        "output": str(output),
        "frames": frame_count,
        "frame_count_source": "analysis_actual",
        "frame_count_reliability": "reliable",
        "progress_total_frames": probe.frames,
        "progress_total_source": probe.frame_count_source,
        "progress_total_reliability": probe.frame_count_reliability,
        "estimated_total_frames": probe.frames if probe.frame_count_reliability == "estimated" else None,
        "estimated_total_source": probe.frame_count_source if probe.frame_count_reliability == "estimated" else "",
        "scenes": scenes,
        "transfer": probe.transfer,
        "primaries": probe.primaries,
        "analysis_width": analysis_width,
        "analysis_height": analysis_height,
        "profile": "A",
    })


if __name__ == "__main__":
    raise SystemExit(main())
