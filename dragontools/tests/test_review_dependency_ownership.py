"""Explicit boundaries complement complexity; no line-count limits."""
import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

ROOT = Path(__file__).resolve().parents[1]


def dependencies(module, source):
    result = set()
    package = module.rsplit('.', 1)[0]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = resolve_name('.' * node.level + (node.module or ''), package) if node.level else node.module
            if name:
                result.add(name)
                result.update(name + '.' + alias.name for alias in node.names)
    return result


def forbidden_paths(graph, start, prefixes):
    pending = [(start,)]
    seen = set()
    while pending:
        path = pending.pop()
        module = path[-1]
        if module in seen:
            continue
        seen.add(module)
        if any(module == p or module.startswith(p + '.') for p in prefixes):
            yield path
        pending.extend((*path, target) for target in graph.get(module, ()))


@pytest.fixture(scope='module')
def graph():
    return {'dragontools.' + '.'.join(p.relative_to(ROOT).with_suffix('').parts):
            dependencies('dragontools.' + '.'.join(p.relative_to(ROOT).with_suffix('').parts), p.read_text(encoding='utf-8-sig'))
            for p in ROOT.rglob('*.py') if not {'tests', '__pycache__'} & set(p.relative_to(ROOT).parts)}


@pytest.mark.parametrize('module', ['core.movie_renamer', 'core.renamer_candidate_decision',
    'core.renamer_year_safety', 'worker.packet_snapshot', 'worker.packet_json_stream',
    'gui.conversion_session_state'])
def test_domain_and_state_have_no_transitive_gui_dependency(graph, module):
    forbidden = ['PyQt6.QtWidgets', 'dragontools.gui'] if not module.startswith('gui.') else ['PyQt6']
    assert not list(forbidden_paths(graph, 'dragontools.' + module, forbidden))


def test_dependency_check_detects_hidden_import_and_transitive_violation():
    source = 'def run():\n from ..gui import movie_renamer_widget\n'
    edges = dependencies('dragontools.core.example', source)
    graph = {'entry': {'dragontools.core.example'}, 'dragontools.core.example': edges}
    assert list(forbidden_paths(graph, 'entry', ['dragontools.gui']))


def writes_attribute(source, attribute):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr == attribute and isinstance(node.ctx, ast.Store):
            return True
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if isinstance(node.value, ast.Attribute) and node.value.attr == attribute:
                return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            receiver = node.func.value
            if isinstance(receiver, ast.Attribute) and receiver.attr == attribute:
                if node.func.attr in {'clear', 'pop', 'update', 'setdefault', 'popitem'}:
                    return True
    return False


def test_request_versions_have_one_owner():
    owners = []
    for path in (ROOT / 'gui').glob('movie_renamer*.py'):
        if writes_attribute(path.read_text(encoding='utf-8'), '_request_versions'):
            owners.append(path.name)
    # The coordinator and its search mixin form the single request-state owner.
    assert sorted(owners) == ['movie_renamer_resolve_search.py', 'movie_renamer_resolver.py']


def test_rename_execution_stays_in_action_boundary():
    callers = set()
    for path in (ROOT / 'gui').glob('movie_renamer*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'rename_movie_file'
               for n in ast.walk(tree)):
            callers.add(path.name)
    assert callers == {'movie_renamer_actions.py'}


def test_search_invalidation_has_one_shared_implementation():
    from dragontools.gui.movie_renamer_table_search import MovieRenamerTableSearchMixin
    from dragontools.gui.movie_renamer_table_controller import MovieRenamerTableController
    assert MovieRenamerTableController.invalidate_row_proposal is MovieRenamerTableSearchMixin.invalidate_row_proposal


def test_ownership_check_sees_nested_writes():
    assert writes_attribute('def f(self):\n if True:\n  self._request_versions = {}', '_request_versions')


@pytest.mark.parametrize('statement', ['self._request_versions[key] = 2',
    'del self._request_versions[key]', 'self._request_versions.clear()',
    'self._request_versions.update(other)'])
def test_ownership_check_catches_in_place_mutation(statement):
    assert writes_attribute('def mutate(self):\n ' + statement, '_request_versions')
