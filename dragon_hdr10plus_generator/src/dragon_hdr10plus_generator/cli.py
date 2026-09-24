from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .analyzer.decoder import probe_video
from .analyzer.scanner import scan_pq_video
from .metadata.json_writer import write_json_atomic
from .metadata.st2094_40 import build_st2094_40_metadata


def _emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0 if payload.get("success") is True else 2


def _norm(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "").replace("-", "").replace(".", "")


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
    try:
        probe = probe_video(source, ffprobe=args.ffprobe)
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
    if primaries and primaries not in {"bt2020", "rec2020"}:
        return _emit({
            "success": False,
            "error": "SOURCE_NOT_BT2020",
            "message": f"PQ source is not tagged as BT.2020 ({probe.primaries}).",
            "transfer": probe.transfer,
            "primaries": probe.primaries,
        })

    try:
        scan = scan_pq_video(
            source,
            probe,
            ffmpeg=args.ffmpeg,
            analysis_width=max(64, min(1024, int(args.analysis_width))),
        )
        metadata = build_st2094_40_metadata(
            scan.frames,
            scene_threshold=max(0.01, min(1.0, float(args.scene_threshold))),
            min_scene_frames=max(1, int(args.min_scene_frames)),
            tool_version=__version__,
        )
        write_json_atomic(output, metadata)
    except FileNotFoundError as exc:
        output.unlink(missing_ok=True)
        return _emit({"success": False, "error": "TOOL_NOT_FOUND", "message": str(exc)})
    except Exception as exc:
        output.unlink(missing_ok=True)
        return _emit({"success": False, "error": "ANALYSIS_FAILED", "message": str(exc)})

    scenes = len(metadata["SceneInfoSummary"]["SceneFirstFrameIndex"])
    return _emit({
        "success": True,
        "version": __version__,
        "input": str(source),
        "output": str(output),
        "frames": len(scan.frames),
        "scenes": scenes,
        "transfer": probe.transfer,
        "primaries": probe.primaries,
        "analysis_width": scan.width,
        "analysis_height": scan.height,
        "profile": "A",
    })


if __name__ == "__main__":
    raise SystemExit(main())
