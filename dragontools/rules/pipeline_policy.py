from __future__ import annotations

from dataclasses import dataclass, field

from ..core.models import MediaInfo, Pipeline


@dataclass(slots=True)
class PipelinePolicyState:
    """Mutable policy state while resolving dynamic-HDR preservation."""

    effective_dv: bool
    effective_hdrplus: bool
    should_archive: bool = False
    archive_reason: str | None = None
    ignored_hdr: list[str] = field(default_factory=list)
    capability_warnings: list[str] = field(default_factory=list)
    policy_infos: list[str] = field(default_factory=list)

    def disable(self, flag: str, reason: str, *, archive: bool) -> None:
        if flag == "dv":
            self.effective_dv = False
        elif flag == "hdr10plus":
            self.effective_hdrplus = False
        else:
            raise ValueError(f"Unbekannte HDR-Policy: {flag!r}")

        if flag not in self.ignored_hdr:
            self.ignored_hdr.append(flag)
        self.capability_warnings.append(reason)
        if archive and self.archive_reason is None:
            self.should_archive = True
            self.archive_reason = reason


def make_initial_policy_state(
    *,
    requested_dv: bool,
    requested_hdrplus: bool,
    source_has_dv: bool,
    source_has_hdrplus: bool,
) -> PipelinePolicyState:
    """Only source metadata that actually exists can become an effective contract."""
    return PipelinePolicyState(
        effective_dv=bool(requested_dv and source_has_dv),
        effective_hdrplus=bool(requested_hdrplus and source_has_hdrplus),
    )


def apply_av1_priority_policy(
    state: PipelinePolicyState,
    *,
    is_auto: bool,
    target_codec: str,
) -> None:
    """AV1 has no combined DV+HDR10+ path; automatic selection prefers DV."""
    if not (is_auto and target_codec == "av1" and state.effective_dv and state.effective_hdrplus):
        return

    state.effective_hdrplus = False
    state.policy_infos.append(
        "AV1: Quelle enthält Dolby Vision und HDR10+; Dolby Vision hat Priorität. "
        "HDR10+ wird bewusst nicht erhalten."
    )


def apply_explicit_pipeline_contract(
    state: PipelinePolicyState,
    *,
    pipeline: Pipeline,
    media_info: MediaInfo,
) -> None:
    """An explicit pipeline command also defines the effective metadata contract."""
    if pipeline == Pipeline.STANDARD:
        state.effective_dv = False
        state.effective_hdrplus = False
    elif pipeline in {Pipeline.HDRPLUS, Pipeline.AV1_HDRPLUS}:
        state.effective_dv = False
        state.effective_hdrplus = True
    elif pipeline == Pipeline.DV:
        state.effective_dv = True
        state.effective_hdrplus = bool(state.effective_hdrplus and media_info.has_hdrplus)
    elif pipeline == Pipeline.AV1_DV:
        state.effective_dv = True
        state.effective_hdrplus = False


def add_pipeline_policy_info(state: PipelinePolicyState, pipeline: Pipeline) -> None:
    if pipeline == Pipeline.AV1_HDRPLUS:
        state.policy_infos.append(
            "AV1 HDR10+ verwendet CPU/libaom-av1 und ist deutlich langsamer als der normale SVT-AV1-Pfad."
        )


def resolve_target_container(
    pipeline: Pipeline,
    *,
    standard_container: str,
    dv_container: str,
) -> str:
    std_container = str(standard_container or "mkv").strip().lower()
    dv_target_container = str(dv_container or "mp4").strip().lower()
    if std_container not in {"mkv", "mp4"}:
        std_container = "mkv"
    if dv_target_container not in {"mkv", "mp4"}:
        dv_target_container = "mp4"
    return dv_target_container if pipeline in {Pipeline.DV, Pipeline.AV1_DV} else std_container
