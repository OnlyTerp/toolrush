"""Installed ToolRush plugin integration tests; no plugin-free speed claims."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest

PLUGIN=Path(__file__).resolve().parents[3]/'plugins/toolrush/__init__.py'

@pytest.fixture
def plugin(monkeypatch):
    import tools.environments.local as local
    import tools.file_operations as fo
    # Restore class monkeypatches after each test; load the actual user plugin.
    for cls,name in [(local.LocalEnvironment,'_run_bash'),(local.LocalEnvironment,'cleanup'),
                     (local.LocalEnvironment,'_kill_process'),
                     (fo.ShellFileOperations,'read_file'),(fo.ShellFileOperations,'_native_read_enabled')]:
        monkeypatch.setattr(cls,name,getattr(cls,name))
    spec=importlib.util.spec_from_file_location('toolrush_test_plugin',PLUGIN)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.register(None)
    yield module


def test_plugin_does_not_replace_core_read_gates(plugin,monkeypatch):
    from tools.environments.local import LocalEnvironment
    from tools.file_operations import ShellFileOperations
    from tools import toolrush_runtime
    monkeypatch.setattr(toolrush_runtime,'enabled',lambda *args:False)
    env=LocalEnvironment(cwd=os.getcwd())
    try:
        assert ShellFileOperations(env)._native_read_enabled() is False
    finally:
        env.cleanup()


def test_bridge_filter_errors_never_fall_back_to_raw_environment(plugin):
    def broken(*args): raise RuntimeError('filter failed')
    local=SimpleNamespace(_make_run_env=broken)
    with pytest.raises(RuntimeError,match='filter failed'):
        plugin._bridge_prefix(SimpleNamespace(env={}),local)


def test_no_asynchronous_snapshot_state(plugin):
    import tools.environments.local as local
    env=local.LocalEnvironment(cwd=os.getcwd())
    try:
        body=env._wrap_command('export TOOLRUSH_PROOF=done',env.cwd)
        built=plugin._build_frame(env,local,body,5)
        frame=built[0].decode()
        assert ' ; } &' not in frame
        assert '(set -C;' not in frame, 'temporary reservation must not fork bash'
        assert '{ ( unset ${!HERMES_SESSION_' not in frame, 'frame already isolates the post-command dump'
    finally: env.cleanup()


def test_loaded_plugin_exports_exitcodes_and_output(plugin,monkeypatch,tmp_path):
    from tools.environments.local import LocalEnvironment
    monkeypatch.setenv('TOOLRUSH_PERSIST','1')
    env=LocalEnvironment(cwd=str(tmp_path))
    try:
        for n in range(5):
            r=env.execute(f'export TOOLRUSH_PROOF=value{n}')
            assert r['returncode']==0,r
            r=env.execute('printf "%s" "$TOOLRUSH_PROOF"')
            assert r['returncode']==0 and r['output']==f'value{n}',r
        r=env.execute('printf fail; false')
        assert r['returncode']==1 and r['output']=='fail',r
    finally: env.cleanup()


def test_warm_streams_before_completion(plugin,monkeypatch,tmp_path):
    import threading,time
    from tools.environments.local import LocalEnvironment
    monkeypatch.setenv('TOOLRUSH_PERSIST','1')
    env=LocalEnvironment(cwd=str(tmp_path))
    handle=None
    try:
        handle=env._run_bash("printf 'early-output'; /usr/bin/sleep 1; printf 'finished'")
        from tools.toolrush_shell import WarmHandle
        assert isinstance(handle,WarmHandle)
        result=[]; arrived=threading.Event()
        def read():
            result.append(os.read(handle.stdout.fileno(),3)); arrived.set()
            while os.read(handle.stdout.fileno(),4096): pass
        worker=threading.Thread(target=read,daemon=True); worker.start()
        assert arrived.wait(.7), 'output held until command finished'
        assert result[0]==b'ear'
        assert handle.wait(4)==0
        worker.join(2)
    finally:
        if handle and handle.poll() is None: handle.kill()
        env.cleanup()


def test_warm_output_has_no_hidden_cap(plugin,monkeypatch,tmp_path):
    from tools.environments.local import LocalEnvironment
    monkeypatch.setenv('TOOLRUSH_PERSIST','1')
    env=LocalEnvironment(cwd=str(tmp_path))
    try:
        command="python -c \"import sys;sys.stdout.write('x'*5000000)\""
        result=env.execute(command,timeout=15)
        assert result['returncode']==0,result
        assert len(result['output'])==5000000
    finally: env.cleanup()


def test_direct_warm_handle_preserves_coreutils_path(plugin,monkeypatch,tmp_path):
    from tools.environments.local import LocalEnvironment
    monkeypatch.setenv('TOOLRUSH_PERSIST','1')
    env=LocalEnvironment(cwd=str(tmp_path))
    try:
        handle=env._run_bash('command -v sleep; command -v mktemp')
        output=handle.stdout.read().decode()
        assert handle.wait(3)==0,output
        assert '/sleep' in output and '/mktemp' in output,output
    finally: env.cleanup()


def test_warm_snapshot_commit_is_native_and_synchronous(plugin,monkeypatch,tmp_path):
    from tools.environments.local import LocalEnvironment
    import tools.toolrush_shell as transport
    monkeypatch.setenv('TOOLRUSH_PERSIST','1')
    env=LocalEnvironment(cwd=str(tmp_path))
    calls=[];real=transport.os.replace
    def track(src,dst):
        calls.append((src,dst)); return real(src,dst)
    monkeypatch.setattr(transport.os,'replace',track)
    try:
        assert env.execute('export TOOLRUSH_NATIVE_COMMIT=latest')['returncode']==0
        assert calls, 'snapshot commit must not fork mv.exe per command'
        assert env.execute('printf %s "$TOOLRUSH_NATIVE_COMMIT"')['output']=='latest'
    finally:env.cleanup()


def test_warm_does_not_retain_revoked_parent_environment(plugin,monkeypatch,tmp_path):
    from tools.environments.local import LocalEnvironment
    monkeypatch.setenv('TOOLRUSH_PERSIST','1')
    env=LocalEnvironment(cwd=str(tmp_path))
    try:
        monkeypatch.setenv('TR_REVOCABLE_PROOF','first')
        handle=env._run_bash('printf %s "$TR_REVOCABLE_PROOF"')
        assert handle.stdout.read()==b'first' and handle.wait(2)==0
        monkeypatch.delenv('TR_REVOCABLE_PROOF')
        handle=env._run_bash('printf %s "${TR_REVOCABLE_PROOF-absent}"')
        assert handle.stdout.read()==b'absent' and handle.wait(2)==0
    finally:env.cleanup()


def test_compound_background_commands_do_not_use_shared_broker(plugin,monkeypatch,tmp_path):
    from tools.environments.local import LocalEnvironment
    from tools.toolrush_shell import WarmHandle
    monkeypatch.setenv('TOOLRUSH_PERSIST','1')
    env=LocalEnvironment(cwd=str(tmp_path))
    try:
        command="printf first\n( /usr/bin/sleep .1; printf child ) &\nprintf end"
        handle=env._run_bash(env._wrap_command(command,env.cwd))
        assert not isinstance(handle,WarmHandle)
        handle.stdout.read();handle.wait(5)
    finally:env.cleanup()


def test_warm_timeout_reaps_and_recovers(plugin,monkeypatch,tmp_path):
    import time
    from tools.environments.local import LocalEnvironment
    monkeypatch.setenv('TOOLRUSH_PERSIST','1')
    env=LocalEnvironment(cwd=str(tmp_path))
    try:
        start=time.monotonic()
        result=env.execute('sleep 20',timeout=.2)
        assert result['returncode']!=0
        assert time.monotonic()-start<6
        result=env.execute('printf recovered',timeout=5)
        assert result['output']=='recovered' and result['returncode']==0,result
    finally: env.cleanup()
