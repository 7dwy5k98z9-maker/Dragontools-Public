"""Match generator response counts to its actual per-frame metadata document."""
from ..core.hdr10plus_generation import hdr10plus_summary_frame_count


def validate_generator_frame_contract(result, payload, _failed_from):
    summary_frames = hdr10plus_summary_frame_count(payload)
    if result.frames is None:
        return _failed_from(result, "FRAME_COUNT_MISSING", "Generator meldet keine analysierte Framezahl.")
    if result.frames <= 0:
        return _failed_from(result, "FRAME_COUNT_INVALID", "Generator meldet keine positive analysierte Framezahl.")
    if result.frames != len(payload["SceneInfo"]) or (summary_frames is not None and result.frames != summary_frames):
        return _failed_from(
            result,
            "FRAME_COUNT_MISMATCH",
            f"Generator meldet {result.frames} Frames, die HDR10+-JSON beschreibt aber {summary_frames} Frames.",
        )
    if result.scenes is None:
        return _failed_from(result, "SCENE_COUNT_MISSING", "Generator meldet keine Szenenzahl.")
    if result.scenes <= 0:
        return _failed_from(result, "SCENE_COUNT_INVALID", "Generator meldet keine positive Szenenzahl.")
    summary = payload.get("SceneInfoSummary")
    if isinstance(summary, dict):
        first_frames = summary.get("SceneFirstFrameIndex")
        scene_frames = summary.get("SceneFrameNumbers")
        counts = first_frames if isinstance(first_frames, list) else scene_frames if isinstance(scene_frames, list) else None
        if counts is not None and len(counts) != result.scenes:
            return _failed_from(
                result,
                "SCENE_COUNT_MISMATCH",
                f"Generator meldet {result.scenes} Szenen, die HDR10+-JSON beschreibt aber {len(counts)} Szenen.",
            )

    return None
