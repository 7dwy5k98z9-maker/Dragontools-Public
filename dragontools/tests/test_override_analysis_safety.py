from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("PyQt6")

from dragontools.gui.convert_widget_override_apply import merge_dialog_override, TRACK_OVERRIDE_KEYS
from dragontools.gui.convert_widget_override_dialog import ConvertWidgetOverrideDialogHelper


class Control:
    def __init__(self, value): self.data = value
    def currentData(self): return self.data
    def value(self): return self.data
    def isChecked(self): return bool(self.data)


def controls(analysis_ok, mode='custom'):
    result = {key: Control(value) for key, value in {
        'processing_combo':'strip_only', 'audio_mode_combo':mode, 'subtitle_mode_combo':mode,
        'drc_mode_combo':'on', 'drc_scale_spin':1.5, 'loudnorm_mode_combo':'off',
        'loudnorm_i_spin':-16, 'imax_cb':True, 'dv_combo':False, 'hdrplus_combo':True,
        'sdr_hdr_combo':True, 'hdrgen_combo':False}.items()}
    result.update(track_analysis_ok=analysis_ok, audio_rows=[], subtitle_rows=[], encoder_override={})
    return result


@pytest.mark.parametrize('mode', ['auto', 'custom', 'legacy', 'unset'])
@pytest.mark.parametrize('analysis_ok', [False, True])
def test_save_preserves_per_file_tracks_after_failed_analysis(monkeypatch, mode, analysis_ok):
    monkeypatch.setattr('dragontools.gui.convert_widget_override_dialog.QMessageBox.warning', Mock())
    old = {
        'auto': {'audio_mode':'auto', 'subtitle_mode':'auto'},
        'custom': {'audio_mode':'custom', 'audio_tracks':[{'index':1,'mode':'drop'}],
                   'subtitle_mode':'custom', 'subtitle_tracks':[{'index':2,'keep':True}]},
        'legacy': {'audio_action':'copy','burn_mode':'selected','burn_stream_index':3},
        'unset': {},
    }[mode]
    values = {name: {**deepcopy(old), 'encoder_profile':name, 'future_flag':True} for name in ['a','b','busy']}
    # Different files must retain their own selections, not the reference file's.
    values['b']['audio_tracks'] = [{'index':8,'mode':'custom','codec':'aac'}]
    state = SimpleNamespace(file_overrides=deepcopy(values),
        preflight_rows_by_path={name: object() for name in values},
        thread=SimpleNamespace(update_override=lambda path, override: path != 'busy'))
    helper = ConvertWidgetOverrideDialogHelper.__new__(ConvertWidgetOverrideDialogHelper)
    helper.owner = SimpleNamespace(update_queue_label=Mock(), log_message=Mock())
    helper._encoder_override = SimpleNamespace(persist_group=lambda ov, ctl: ov.update(encoder_override={'quality':20}))
    helper._persist_override_result(list(values), state, deepcopy(values['a']), controls(analysis_ok))
    assert state.file_overrides['busy'] == values['busy']
    assert 'busy' in state.preflight_rows_by_path
    for name in ['a','b']:
        actual = state.file_overrides[name]
        assert actual['encoder_profile'] == name and actual['future_flag']
        assert actual['processing_mode'] == 'strip_only'
        assert actual['preserve_dv'] is False and actual['preserve_hdrplus'] is True
        assert actual['sdr_hdr'] is True and actual['generate_hdr10plus'] is False
        assert actual['audio_drc'] == {'mode':'on','scale':1.5}
        assert actual['audio_loudnorm'] == {'mode':'off','i':-16.0}
        assert name not in state.preflight_rows_by_path
        if not analysis_ok:
            assert {k:v for k,v in actual.items() if k in TRACK_OVERRIDE_KEYS} == {
                k:v for k,v in values[name].items() if k in TRACK_OVERRIDE_KEYS}
        else:
            assert actual['audio_tracks'] == [] and actual['subtitle_tracks'] == []
            assert 'audio_action' not in actual and 'burn_mode' not in actual


@pytest.mark.parametrize('preserve', [False, True])
def test_merge_has_no_input_side_effects(preserve):
    old = {'audio_tracks':[{'index':1}], 'encoder_profile':'keep'}
    template = {'audio_tracks':[{'index':2}], 'sdr_hdr':True}
    before = deepcopy((old, template))
    result = merge_dialog_override(old, template, preserve_tracks=preserve)
    assert (old, template) == before
    assert result['audio_tracks'][0]['index'] == (1 if preserve else 2)
    assert result['encoder_profile'] == 'keep' and result['sdr_hdr']
