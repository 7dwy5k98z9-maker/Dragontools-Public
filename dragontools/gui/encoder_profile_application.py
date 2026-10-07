"""Apply complete profile values while the settings controller holds its load guard."""
from ..core.encoder_profile_override import MODE_TO_SCALE_LABEL
from ..core.type_utils import _safe_bool, _safe_int, _safe_float
from .encoder_profile_options import advanced_profile_options
from .encoder_settings_persistence import _apply_combo_value


def apply_profile_values(controller, profile: dict) -> None:
    widgets = controller._ui.widgets
    opts = profile.get('encoder_options')
    opts = opts if isinstance(opts, dict) else {}
    selected = str(opts.get('encoder', 'cpu')).strip().lower()
    enc_map = {'cpu': 0, 'auto': 1, 'nvenc': 2, 'qsv': 3, 'amf': 4}
    widgets.encoder_combo.setCurrentIndex(enc_map.get(selected, 0))
    controller.refresh_enc_panel()
    enc = controller.active_encoder()
    scale = str(profile.get('scale') or 'original')
    widgets.scale_combo.setCurrentText(MODE_TO_SCALE_LABEL.get(scale, scale))
    crf = profile.get('crf')
    if crf is None:
        crf = opts.get('crf')
    number = _safe_int(crf)
    if number is not None:
        widgets.crf_spin.setValue(number)
        widgets.x265_crf.setValue(number)
    preset = profile.get('preset') or (opts.get('preset') if enc == 'cpu' else None)
    _apply_combo_value(widgets.preset_combo, preset)
    _apply_combo_value(widgets.x265_preset, preset)
    apply_backend_values(controller, enc, opts)
    for key, name in [('preserve_dv', 'preserve_dv_cb'), ('preserve_hdrplus', 'preserve_hdrplus_cb'),
                      ('autocrop_enabled', 'autocrop_cb'), ('imax_auto_detect', 'imax_detect_cb')]:
        if key in opts:
            widget = getattr(widgets, name)
            widget.setChecked(_safe_bool(opts[key], widget.isChecked()))
    controller._state.profile_options = {}
    defaults = controller.collect_enc_opts()
    controller._state.profile_options = advanced_profile_options(opts, defaults)
    # Apply the same typed readers and ranges as global policy before persistence.
    validated = controller.collect_enc_opts()
    controller._state.profile_options = {key: validated[key] for key in controller._state.profile_options}


def apply_backend_values(controller, encoder: str, opts: dict) -> None:
    widgets = controller._ui.widgets
    combo_fields = {
        'nvenc': [('nv_preset', 'preset'), ('nv_bref', 'bref_mode'),
                  ('nv_lookahead_level', 'lookahead_level'), ('nv_multipass', 'multipass')],
        'qsv': [('qsv_preset', 'preset')], 'amf': [('amf_qual', 'quality')],
        'cpu': [('x265_tune', 'tune'), ('x265_aqm', 'aq_mode')],
    }
    int_fields = {
        'nvenc': [('nv_cq', 'cq'), ('nv_bf', 'bf'), ('nv_la', 'rc_lookahead'), ('nv_aq', 'aq_strength')],
        'qsv': [('qsv_q', 'q'), ('qsv_la_depth', 'lookahead_depth')],
        'amf': [('amf_qp', 'qp')], 'cpu': [('x265_bf', 'bf'), ('x265_la', 'rc_lookahead')],
    }
    for name, key in combo_fields.get(encoder, []):
        _apply_combo_value(getattr(widgets, name, None), opts.get(key))
    for name, key in int_fields.get(encoder, []):
        number = _safe_int(opts.get(key))
        if number is not None:
            getattr(widgets, name).setValue(number)
    if encoder == 'cpu':
        for name, key in [('x265_aqs', 'aq_strength'), ('x265_psy', 'psy_rd'), ('x265_psyrdoq', 'psy_rdoq')]:
            if opts.get(key) is not None:
                getattr(widgets, name).setValue(_safe_float(opts[key]))
    elif encoder == 'nvenc':
        for name, key in [('nv_spatial', 'spatial_aq'), ('nv_temporal', 'temporal_aq')]:
            if key in opts:
                getattr(widgets, name).setChecked(_safe_bool(opts[key], True))
