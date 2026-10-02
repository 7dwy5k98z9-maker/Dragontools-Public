import ast
import json
from pathlib import Path

import pytest

from dragontools.tests.responsibility_checks import structural_risks

ROOT = Path(__file__).resolve().parents[1]
DEBT = json.loads((Path(__file__).with_name('architecture_debt.json')).read_text(encoding='utf-8'))
MODULES = sorted(p for p in ROOT.rglob('*.py') if not {'tests', '__pycache__'} & set(p.relative_to(ROOT).parts))


@pytest.mark.parametrize('path', MODULES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_new_structural_responsibility_hotspots(path):
    """Known debt is explicit; new/worsening hotspots fail, independent of LOC."""
    risks = structural_risks(path.read_text(encoding='utf-8-sig'))
    allowed = DEBT.get(path.relative_to(ROOT).as_posix(), {})
    assert all(value <= allowed.get(key, 0) for key,value in risks.items()), (
        f'{path.name}: responsibility review required: {risks}; known debt: {allowed}')


@pytest.mark.parametrize('relative,forbidden', [
    ('worker/duration_packet_integrity.py', {'PyQt6', 'subprocess', 'os', 'shutil'}),
    ('worker/duration_timestamp_candidate_validation.py', {'PyQt6', 'subprocess', 'os', 'shutil'}),
    ('gui/convert_widget_override_apply.py', {'PyQt6', 'subprocess', 'os', 'shutil'}),
    ('gui/convert_widget_override_dialog.py', {'subprocess', 'shutil'}),
])
def test_safety_modules_keep_their_io_and_ui_boundaries(relative, forbidden):
    tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): imports.update(a.name.split('.')[0] for a in node.names)
        if isinstance(node, ast.ImportFrom): imports.add((node.module or '').split('.')[0])
    assert not imports & forbidden


def test_long_cohesive_module_and_data_tables_are_allowed():
    source = '"""Single responsibility with detailed documentation."""\n' + '# explanation\n' * 400
    source += 'TABLE = ' + repr(list(range(1000))) + '\ndef lookup(index):\n    return TABLE[index]\n'
    assert not structural_risks(source)


def test_branch_heavy_function_is_rejected_even_on_few_lines():
    source = 'def overloaded(x):\n' + ''.join(f'    if x == {i}: return {i}\n' for i in range(30))
    assert structural_risks(source)['function:overloaded'] > 25


def test_class_accumulating_many_behaviors_is_flagged():
    source = 'class Overloaded:\n'
    for i in range(10):
        source += f'    def task_{i}(self, x):\n' + ''.join(f'        if x == {j}: return {j}\n' for j in range(6))
    assert structural_risks(source)['class-behaviors:Overloaded'] == 10


def test_large_data_class_is_not_a_god_class():
    assert not structural_risks('class Model:\n' + ''.join(f'    field_{i}: str\n' for i in range(400)))


def test_nested_callback_complexity_belongs_to_callback_not_parent():
    source = 'def outer():\n    def callback(x):\n' + ''.join(f'        if x == {j}: return {j}\n' for j in range(30))
    assert set(structural_risks(source)) == {'function:outer.callback'}
