from __future__ import annotations

from pathlib import Path

from ..rules.subtitle_rules import any_sidecar_export_enabled
from .converter_strip_runtime import subtitle_rules, tools
from .subtitle_sidecar_service import SubtitleSidecarService


def export_strip_sidecars(worker, *, input_path: str, output_path: str, media_info, file_override, container: str) -> tuple[bool, list[str]]:
    rules = subtitle_rules(worker)
    target_container = str(container or "mkv").lower()
    if not any_sidecar_export_enabled(rules, container=target_container):
        return True, []
    service = SubtitleSidecarService(
        ffmpeg_path=tools(worker).ffmpeg,
        subtitle_rules=rules,
        log=worker.log,
        worker=worker,
    )
    export = service.export_sidecars_result(
        input_path=input_path,
        output_base=Path(output_path).with_suffix(""),
        media_info=media_info,
        file_override=file_override,
        preserve_burn_candidate=True,
        container=target_container,
    )
    if not export.complete:
        worker.log(f"❌ Strip-Only Untertitel-Export: {export.failure_summary()}", "error")
        return False, list(export.exported_paths)
    return True, list(export.exported_paths)
