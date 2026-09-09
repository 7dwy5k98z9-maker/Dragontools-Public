from __future__ import annotations

from ..core.codec_utils import normalize_target_codec
from ..core.models import MediaInfo, Pipeline, TargetCodec, normalize_override_dict
from .pipeline_capabilities import (
    apply_dynamic_hdr_capability_guards,
    classify_source_codec,
    pipeline_capability_error,
    source_dynamic_hdr_flags,
)
from .pipeline_policy import (
    PipelinePolicyState,
    add_pipeline_policy_info,
    apply_av1_priority_policy,
    apply_explicit_pipeline_contract,
    make_initial_policy_state,
    resolve_target_container,
)


class PipelineCapabilityError(ValueError):
    """Raised for an explicit pipeline override that cannot be executed safely."""


class PipelineSelector:
    """Select the conversion pipeline from media flags and effective preserve policy."""

    def select(
        self,
        media_info: MediaInfo,
        *,
        global_preserve_dv: bool = True,
        global_preserve_hdrplus: bool = True,
        per_file_preserve_dv: "bool | None" = None,
        per_file_preserve_hdrplus: "bool | None" = None,
        pipeline_override: str = "auto",
    ) -> Pipeline:
        if pipeline_override and pipeline_override != "auto":
            return _parse_pipeline_override(pipeline_override)

        eff_dv = per_file_preserve_dv if per_file_preserve_dv is not None else global_preserve_dv
        eff_hdp = (
            per_file_preserve_hdrplus
            if per_file_preserve_hdrplus is not None
            else global_preserve_hdrplus
        )
        if media_info.has_dv and eff_dv:
            return Pipeline.DV
        if media_info.has_hdrplus and eff_hdp:
            return Pipeline.HDRPLUS
        return Pipeline.STANDARD


def _parse_pipeline_override(value: str) -> Pipeline:
    try:
        return Pipeline(value)
    except ValueError as exc:
        raise PipelineCapabilityError(f"Unbekanntes Pipeline-Override: {value!r}") from exc


def _requested_preservation(
    override: dict[str, object],
    *,
    global_preserve_dv: bool,
    global_preserve_hdrplus: bool,
) -> tuple[object, object, bool, bool]:
    per_file_dv = override.get("preserve_dv")
    per_file_hdp = override.get("preserve_hdrplus")
    requested_dv = per_file_dv if per_file_dv is not None else global_preserve_dv
    requested_hdp = per_file_hdp if per_file_hdp is not None else global_preserve_hdrplus
    return per_file_dv, per_file_hdp, bool(requested_dv), bool(requested_hdp)


def _resolve_pipeline(
    media_info: MediaInfo,
    *,
    target_codec: str,
    source_codec: str,
    override: str,
    state: PipelinePolicyState,
) -> Pipeline:
    if override != "auto":
        forced = _parse_pipeline_override(override)
        reason = pipeline_capability_error(
            forced,
            source_codec=source_codec,
            target_codec=target_codec,
            media_info=media_info,
        )
        if reason:
            raise PipelineCapabilityError(reason)
        apply_explicit_pipeline_contract(state, pipeline=forced, media_info=media_info)
        return forced

    if target_codec == TargetCodec.AV1.value:
        pipeline = (
            Pipeline.AV1_DV
            if state.effective_dv
            else Pipeline.AV1_HDRPLUS
            if state.effective_hdrplus
            else Pipeline.STANDARD
        )
    else:
        pipeline = PipelineSelector().select(
            media_info,
            global_preserve_dv=state.effective_dv,
            global_preserve_hdrplus=state.effective_hdrplus,
        )

    reason = pipeline_capability_error(
        pipeline,
        source_codec=source_codec,
        target_codec=target_codec,
        media_info=media_info,
    )
    if reason:
        state.capability_warnings.append(reason)
        return Pipeline.STANDARD
    return pipeline


def resolve_pipeline_context(
    media_info: MediaInfo,
    *,
    codec: str,
    file_override: dict | None = None,
    global_preserve_dv: bool = True,
    global_preserve_hdrplus: bool = True,
    job_pipeline: str = "auto",
    standard_container: str = "mkv",
    dv_container: str = "mp4",
) -> dict[str, object]:
    """Resolve effective HDR policy, executable pipeline and target container."""
    target_codec = normalize_target_codec(codec)
    ov = normalize_override_dict(file_override)
    per_file_dv, per_file_hdp, requested_dv, requested_hdp = _requested_preservation(
        ov,
        global_preserve_dv=global_preserve_dv,
        global_preserve_hdrplus=global_preserve_hdrplus,
    )
    source_codec = classify_source_codec(media_info)
    source_has_dv, source_has_hdrplus = source_dynamic_hdr_flags(media_info)
    state = make_initial_policy_state(
        requested_dv=requested_dv,
        requested_hdrplus=requested_hdp,
        source_has_dv=source_has_dv,
        source_has_hdrplus=source_has_hdrplus,
    )
    apply_dynamic_hdr_capability_guards(
        state,
        source_codec=source_codec,
        target_codec=target_codec,
        source_has_dv=source_has_dv,
        source_has_hdrplus=source_has_hdrplus,
        requested_dv=requested_dv,
        requested_hdrplus=requested_hdp,
    )

    override = str(job_pipeline or "auto").strip().lower()
    apply_av1_priority_policy(state, is_auto=override == "auto", target_codec=target_codec)
    pipeline = _resolve_pipeline(
        media_info,
        target_codec=target_codec,
        source_codec=source_codec,
        override=override,
        state=state,
    )
    add_pipeline_policy_info(state, pipeline)
    container = resolve_target_container(
        pipeline,
        standard_container=standard_container,
        dv_container=dv_container,
    )

    return {
        "pipeline": pipeline,
        "container": container,
        "override": ov,
        "per_file_preserve_dv": per_file_dv,
        "per_file_preserve_hdrplus": per_file_hdp,
        "requested_preserve_dv": requested_dv,
        "requested_preserve_hdrplus": requested_hdp,
        "effective_preserve_dv": state.effective_dv,
        "effective_preserve_hdrplus": state.effective_hdrplus,
        "source_codec": source_codec,
        "target_codec": target_codec,
        "should_archive": state.should_archive,
        "archive_reason": state.archive_reason,
        "ignored_hdr": state.ignored_hdr,
        "capability_warnings": state.capability_warnings,
        "policy_infos": state.policy_infos,
    }
