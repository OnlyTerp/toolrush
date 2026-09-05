"""Real-entry-point proof: acceleration must retain ripgrep semantics."""
import json
import uuid
from unittest.mock import patch

import pytest
from tools import file_tools as ft
from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations


@pytest.fixture
def local_search(tmp_path, monkeypatch):
    root = tmp_path / 'corpus'
    root.mkdir()
    # A neighboring run_agent test reloads this module. Keep the real
    # backend identity current, never weaken the production local-only gate.
    from tools.environments.local import LocalEnvironment
    env = LocalEnvironment(cwd=str(root))
    ops = ShellFileOperations(env)
    monkeypatch.setattr(ft, '_get_file_ops', lambda task_id='default': ops)
    yield root, ops
    env.cleanup()


def search(root, monkeypatch, lane='1', **kwargs):
    monkeypatch.setenv('TOOLRUSH_SEARCH', lane)
    raw = ft.search_tool(path=str(root), task_id='rg-'+uuid.uuid4().hex, **kwargs)
    return json.JSONDecoder().raw_decode(raw)[0]


def test_ignore_file_semantics_preserved(local_search, monkeypatch):
    root, ops = local_search
    (root/'.ignore').write_text('ignored.txt\n')
    (root/'ignored.txt').write_text('needle SHOULD_NOT_BE_RETURNED\n')
    (root/'visible.txt').write_text('needle visible\n')
    baseline = search(root, monkeypatch, '0', pattern='needle')
    fast = search(root, monkeypatch, '1', pattern='needle')
    assert fast == baseline
    assert 'SHOULD_NOT_BE_RETURNED' not in json.dumps(fast)


def test_real_search_runs_rg_without_shell(local_search, monkeypatch):
    root, ops = local_search
    (root/'visible.txt').write_text('needle visible\n')
    monkeypatch.setenv('TOOLRUSH_SEARCH', '1')
    # A new ops instance also proves executable discovery does not spawn bash.
    with patch.object(ops, '_exec', side_effect=AssertionError('shell search invoked')):
        result = search(root, monkeypatch, '1', pattern='needle')
    assert 'error' not in result, result
    assert result['total_count'] == 1


@pytest.mark.parametrize('kwargs', [
    {'pattern': 'needle'},
    {'pattern': 'needle', 'context': 1},
    {'pattern': 'needle', 'output_mode': 'files_only'},
    {'pattern': 'needle', 'output_mode': 'count'},
    {'pattern': 'needle', 'limit': 2, 'offset': 1},
    {'pattern': 'needle', 'file_glob': '*.txt'},
    {'pattern': '(?<=needle) visible'},
    {'pattern': '(needle)\\1'},
    {'pattern': 'NO_MATCH_SENTINEL'},
    {'pattern': 'needle\\nnext'},
    {'pattern': '*.txt', 'target': 'files'},
    {'pattern': '*.txt', 'target': 'files', 'order': 'modified'},
    {'pattern': '--needle'},
    {'pattern': '[]'},
])
def test_engine_envelope_differential(local_search, monkeypatch, kwargs):
    root, ops = local_search
    (root/'visible.txt').write_bytes(b'needle visible\r\nnext\r\nneedle\r\n--needle\r\nneedle\r\n')
    (root/'ignored.txt').write_text('not a matching record\n')
    (root/'.ignore').write_text('ignored.txt\n')
    slow = search(root, monkeypatch, '0', **kwargs)
    fast = search(root, monkeypatch, '1', **kwargs)
    if kwargs.get('target') == 'files' and kwargs.get('order') != 'modified':
        # File discovery is explicitly unordered; both preserve the same
        # set, whereas content offset pagination is path-stable.
        slow['files'] = sorted(slow.get('files', []))
        fast['files'] = sorted(fast.get('files', []))
    assert fast == slow


def test_files_no_shell(local_search, monkeypatch):
    root, ops = local_search
    (root/'visible.txt').write_text('visible\n')
    with patch.object(ops, '_exec', side_effect=AssertionError('shell search invoked')):
        result = search(root, monkeypatch, '1', target='files', pattern='*.txt')
    assert 'error' not in result, result
    assert result['total_count'] == 1


def test_truncated_search_is_strict_json(local_search, monkeypatch):
    root, ops = local_search
    (root/'many.txt').write_text('needle\n' * 12)
    monkeypatch.setenv('TOOLRUSH_SEARCH', '1')
    raw = ft.search_tool('needle', path=root.as_posix(), limit=1, context=1, task_id=uuid.uuid4().hex)
    result = json.loads(raw)
    assert result['truncated'] is True
    assert 'offset=1' in result['_hint']


@pytest.mark.parametrize('mode', ['content','files_only','count'])
def test_page_bound_reports_more(local_search, monkeypatch, mode):
    root, ops = local_search
    for n in range(4):
        (root/f'{n}.txt').write_text('needle\n')
    result = search(root, monkeypatch, '1', pattern='needle', limit=2, output_mode=mode)
    assert result['truncated'] is True
    assert result['total_count_is_lower_bound'] is True
    page = result.get('matches', result.get('files', result.get('counts')))
    assert len(page) == 2


def test_shell_cached_executable_still_allows_native_search(local_search, monkeypatch):
    root, ops = local_search
    (root/'x.txt').write_text('needle\n')
    # Real shell discovery reports /c/.../rg (no .exe). Reusing the ops must
    # not silently disable acceleration after one stock/backend call.
    assert search(root, monkeypatch, '0', pattern='needle')['total_count'] == 1
    with patch.object(ops, '_exec', side_effect=AssertionError('fell back after cache')):
        result = search(root, monkeypatch, '1', pattern='needle')
    assert 'error' not in result, result
