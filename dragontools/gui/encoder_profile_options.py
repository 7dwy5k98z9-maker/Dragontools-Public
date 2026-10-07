"""Read codec-owned profile options through the existing global settings policy."""
from copy import deepcopy
import json

from ..core import settings_conversion as keys


_UI_OPTIONS = frozenset({
    'encoder', 'crf', 'preset', 'tune', 'aq_mode', 'aq_strength', 'psy_rd', 'psy_rdoq',
    'bf', 'rc_lookahead', 'cq', 'bref_mode', 'lookahead_level', 'multipass',
    'spatial_aq', 'temporal_aq', 'q', 'lookahead_depth', 'quality', 'qp',
    'preserve_dv', 'preserve_hdrplus', 'autocrop_enabled', 'imax_auto_detect',
})

_POLICY_KEYS = {
    keys.SET_KEY_AUTOCROP_MODE: 'autocrop_mode',
    keys.SET_KEY_AUTOCROP_PROBE_START: 'autocrop_probe_start_s',
    keys.SET_KEY_AUTOCROP_PROBE_DURATION: 'autocrop_probe_duration_s',
    keys.SET_KEY_AUTOCROP_PROBE_INTERVAL: 'autocrop_probe_interval_s',
    keys.SET_KEY_IMAX_PROBE_INTERVAL: 'imax_probe_interval_s',
    keys.SET_KEY_IMAX_PROBE_DURATION: 'imax_probe_duration_s',
    keys.SET_KEY_IMAX_MIN_VARIANCE_PERCENT: 'imax_min_variance_percent',
    keys.SET_KEY_IMAX_MIN_HITS: 'imax_min_hits',
    keys.SET_KEY_QUALITY_TARGET_ENABLED: 'quality_target_enabled',
    keys.SET_KEY_QUALITY_TARGET_VMAF: 'quality_target_vmaf',
    keys.SET_KEY_QUALITY_TARGET_SAMPLES: 'quality_target_samples',
    keys.SET_KEY_QUALITY_TARGET_SAMPLE_DURATION: 'quality_target_sample_duration_s',
    keys.SET_KEY_QUALITY_TARGET_MIN: 'quality_target_min',
    keys.SET_KEY_QUALITY_TARGET_MAX: 'quality_target_max',
    keys.SET_KEY_SDR_HDR_ENABLED: 'sdr_hdr_enabled',
    keys.SET_KEY_SDR_HDR_CONTRAST_RECOVERY: 'sdr_hdr_contrast_recovery',
    keys.SET_KEY_SDR_HDR_BACKEND: 'sdr_hdr_backend',
    keys.SET_KEY_HDR10PLUS_GENERATOR_ENABLED: 'hdr10plus_generator_enabled',
    keys.SET_KEY_COMFYUI_BASE_URL: 'comfyui_base_url',
    keys.SET_KEY_COMFYUI_WORKFLOW_PATH: 'comfyui_workflow_path',
    keys.SET_KEY_COMFYUI_MODEL_PROFILE: 'comfyui_model_profile',
    keys.SET_KEY_COMFYUI_MODEL_ROOT: 'comfyui_model_root',
    keys.SET_KEY_COMFYUI_CHECKPOINT: 'comfyui_checkpoint',
    keys.SET_KEY_COMFYUI_AUTO_START: 'comfyui_auto_start',
    keys.SET_KEY_COMFYUI_START_FILE: 'comfyui_start_file',
    keys.SET_KEY_COMFYUI_START_WAIT_SECONDS: 'comfyui_start_wait_seconds',
}


class ProfilePolicySettings:
    """Read-only overlay; existing typed readers retain all bounds and choices."""
    def __init__(self, settings, options):
        self.settings = settings
        self.options = options if isinstance(options, dict) else {}

    def value(self, key, default=None, **kwargs):
        option = _POLICY_KEYS.get(key)
        if option in self.options:
            return deepcopy(self.options[option])
        try:
            return self.settings.value(key, default, **kwargs)
        except TypeError:
            return self.settings.value(key, default)


def profile_policy_settings(controller):
    return ProfilePolicySettings(controller._settings, getattr(controller._state, 'profile_options', {}))


def advanced_profile_options(options: dict, defaults: dict) -> dict:
    """Accept known policy fields, excluding UI values and runtime capabilities."""
    return {key: deepcopy(value) for key, value in options.items()
            if key in defaults and key not in _UI_OPTIONS and not key.startswith('_')}


def save_profile_options(controller) -> None:
    controller._settings.setValue(f'encoder/{controller._default_codec}/profile_options',
        json.dumps(getattr(controller._state, 'profile_options', {}), ensure_ascii=False))


def load_profile_options(controller) -> None:
    raw = controller._settings.value(f'encoder/{controller._default_codec}/profile_options', '{}')
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        value = {}
    controller._state.profile_options = deepcopy(value) if isinstance(value, dict) else {}
