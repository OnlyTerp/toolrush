"""ToolRush v2 native-reader contract: real handler, no shell bytes path."""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from tools import file_tools as ft
from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations


@pytest.fixture
def local_ops(tmp_path, monkeypatch):
    # Construct the actual backend. Only dependency selection is injected;
    # read_file_tool, path guards and ShellFileOperations all run unchanged.
    # run_agent tests reload the backend module; construct its CURRENT class
    # so the production isinstance backend-isolation check stays meaningful.
    from tools.environments.local import LocalEnvironment
    env = LocalEnvironment(cwd=str(tmp_path))
    ops = ShellFileOperations(env)
    monkeypatch.setattr(ft, '_get_file_ops', lambda task_id='default': ops)
    monkeypatch.setenv('HERMES_NATIVE_FILE_READ', '1')
    monkeypatch.setenv('TOOLRUSH_FASTLANE', '1')
    yield ops
    env.cleanup()


def decode(value):
    return json.JSONDecoder().raw_decode(value)[0]


def test_windows_read_handler_uses_native_bytes(local_ops, tmp_path):
    target = tmp_path / 'utf8 sample.txt'
    target.write_bytes('alpha\r\nβeta\r\nlast'.encode('utf-8'))
    with patch.object(local_ops, '_exec', side_effect=AssertionError('shell spawned for native read')):
        result = decode(ft.read_file_tool(str(target), offset=2, limit=2, task_id='native-read-proof'))
    assert 'error' not in result, result
    assert result['total_lines'] == 3
    assert '2|βeta' in result['content']
    assert '3|last' in result['content']


@pytest.mark.parametrize('content', [b'', b'only', b'first\nlast', b'first\r\nlast\r\n',
                                         b'\xef\xbb\xbfbom\nend', 'emoji 🍀\n𝔸\n'.encode(),
                                         b'x'*3000+b'\nend\n'])
@pytest.mark.parametrize('offset,limit', [(1,2),(2,1),(50,2)])
def test_read_differential(local_ops, tmp_path, monkeypatch, content, offset, limit):
    import uuid
    target = tmp_path / 'sample.txt'
    target.write_bytes(content)
    monkeypatch.setenv('TOOLRUSH_FASTLANE','0')
    slow = decode(ft.read_file_tool(str(target), offset=offset, limit=limit, task_id=uuid.uuid4().hex))
    monkeypatch.setenv('TOOLRUSH_FASTLANE','1')
    fast = decode(ft.read_file_tool(str(target), offset=offset, limit=limit, task_id=uuid.uuid4().hex))
    assert fast == slow


def test_no_stale_contents_after_same_mtime_edit(local_ops, tmp_path):
    import uuid
    target = tmp_path/'fresh.txt'
    target.write_bytes(b'BEFORE\n')
    before = target.stat()
    first = decode(ft.read_file_tool(str(target), task_id=uuid.uuid4().hex))
    target.write_bytes(b'AFTER!\n')
    os.utime(target, ns=(before.st_atime_ns,before.st_mtime_ns))
    second = decode(ft.read_file_tool(str(target), task_id=uuid.uuid4().hex))
    assert 'BEFORE' in first['content']
    assert 'AFTER!' in second['content']


@pytest.mark.parametrize('path', ['/tmp/x', '/dev/null', 'C:relative', '\\\\?\\C:\\x'])
def test_ambiguous_windows_namespace_falls_back(local_ops, path):
    import sys
    if sys.platform != 'win32':
        return
    assert local_ops._local_native_path(path) is None


def test_nonlocal_backend_never_native():
    class Remote:
        cwd='/work'
    remote = ShellFileOperations(Remote())
    assert not remote._native_read_enabled()
    assert remote._local_native_path('C:/host/file') is None


def test_native_read_kill_switch(local_ops, monkeypatch):
    monkeypatch.setenv('TOOLRUSH_FASTLANE', '0')
    assert not local_ops._native_read_enabled()
    monkeypatch.setenv('TOOLRUSH_FASTLANE', '1')
    monkeypatch.setenv('HERMES_NATIVE_FILE_READ', '0')
    assert not local_ops._native_read_enabled()
