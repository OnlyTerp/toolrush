"""Real TCP, generated client, installed dispatch: ToolRush RPC acceptance."""
import contextvars
import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from tools import code_execution_tool as cet


@pytest.fixture
def rpc(monkeypatch):
    server=socket.socket(); server.bind(('127.0.0.1',0)); server.listen()
    endpoint='tcp://127.0.0.1:'+str(server.getsockname()[1])
    stop=threading.Event(); log=[]; counter=[0]
    monkeypatch.setenv('HERMES_RPC_SOCKET',endpoint)
    monkeypatch.setenv('HERMES_RPC_TOKEN','test-token')
    monkeypatch.delenv('HERMES_RPC_PERSISTENT',raising=False)
    clients=[]; threads=[]
    def start(dispatch=None,budget=50,allowed=None):
        th=threading.Thread(target=cet._rpc_server_loop,args=(server,'toolrush-rpc-test',log,counter,budget,
            frozenset(allowed or cet.SANDBOX_ALLOWED_TOOLS),stop,'test-token'),kwargs={'dispatch':dispatch},daemon=True)
        th.start(); threads.append(th)
        module={}; exec(cet.generate_hermes_tools_module(list(cet.SANDBOX_ALLOWED_TOOLS)),module)
        clients.append(module)
        return module,log,counter
    yield start
    stop.set()
    for m in clients:
        if m.get('_sock'): m['_sock'].close()
    server.close()
    for th in threads: th.join(3)


def test_parallel_client_real_socket_overlaps_and_keeps_order(rpc):
    gate=threading.Barrier(4); active=0; peak=0; lock=threading.Lock()
    def dispatch(name,args):
        nonlocal active,peak
        with lock: active+=1; peak=max(peak,active)
        gate.wait(2)
        with lock: active-=1
        return json.dumps({'value':args['path']})
    module,log,count=rpc(dispatch)
    result=module['parallel']([{'tool':'read_file','args':{'path':str(i)}} for i in range(4)])
    assert result==[{'value':str(i)} for i in range(4)]
    assert peak==4 and count[0]==4 and len(log)==4


def test_parallel_drives_real_tools_and_fresh_files(rpc,tmp_path):
    paths=[tmp_path/f'proof{i}.txt' for i in range(3)]
    for p in paths: p.write_text('ToolRush RPC live proof\n')
    module,log,count=rpc()
    calls=[{'tool':'read_file','args':{'path':str(p)}} for p in paths]
    result=module['parallel'](calls)
    assert all('ToolRush RPC live proof' in r.get('content','') for r in result),result
    for p in paths: p.write_text('Changed on disk\n')
    result=module['parallel'](calls)
    assert all('Changed on disk' in r.get('content','') for r in result),result
    assert count[0]==6


@pytest.mark.parametrize('calls',[
    [{'tool':'read_file','args':{}},{'tool':'write_file','args':{'path':'denied','content':'x'}}],
    [{'tool':'terminal','args':{'command':'pwd'}}],
    [{'tool':'read_file','args':[]}],
    [{"tool": [], "args": {}}],
    [{"tool": {"unexpected": "mapping"}, "args": {}}],
    [{'tool':'read_file','args':{}}]*17,
])
def test_invalid_batch_has_zero_side_effects(rpc,calls):
    invoked=[]
    module,log,count=rpc(lambda n,a:invoked.append(n) or '{}')
    result=module['parallel'](calls)
    assert 'error' in result
    assert not invoked and not log and count[0]==0


def test_parallel_budget_reserved_atomically(rpc):
    invoked=[]
    module,log,count=rpc(lambda n,a:invoked.append(n) or '{}',budget=2)
    result=module['parallel']([{'tool':'read_file','args':{}}]*3)
    assert 'error' in result and not invoked and count[0]==0
    assert module['parallel']([{'tool':'read_file','args':{}}]*2)==[{},{}]
    assert count[0]==2 and len(invoked)==2
    assert 'error' in module['read_file']('anything')


def test_parallel_allowlist_and_auth_remain_enforced(rpc,monkeypatch):
    invoked=[]
    module,log,count=rpc(lambda n,a:invoked.append(n) or '{}',allowed={'read_file'})
    result=module['parallel']([{'tool':'web_search','args':{'query':'no'}}])
    assert 'error' in result and not invoked
    monkeypatch.setenv('HERMES_RPC_TOKEN','wrong')
    result=module['parallel']([{'tool':'read_file','args':{}}])
    assert 'error' in result and not invoked and count[0]==0


def test_parallel_failure_is_per_item(rpc):
    def dispatch(n,a):
        if a['path']=='bad': raise RuntimeError('test failure')
        return json.dumps({'path':a['path']})
    module,log,count=rpc(dispatch)
    result=module['parallel']([{'tool':'read_file','args':{'path':p}} for p in ['ok','bad','end']])
    assert result[0]=={'path':'ok'} and 'error' in result[1] and result[2]=={'path':'end'}
    assert count[0]==3


def test_batch_binds_authority_once_and_never_uses_next_cell():
    from tools.toolrush_rpc import execute_read_batch
    stop=threading.Event(); seen=[]; bound=[]
    def dispatch(n,a): raise AssertionError('dynamic authority used')
    def bind():
        bound.append('old-cell')
        return lambda n,a: seen.append('old-cell') or '{}'
    dispatch.for_batch=bind
    result=json.loads(execute_read_batch({'calls':[{'tool':'read_file','args':{}}]*8},
        allowed_tools={'read_file'},counter=[0],budget=50,log=[],dispatch=dispatch,stop_event=stop))
    assert result==[{}]*8 and seen==['old-cell']*8 and bound==['old-cell']


def test_stopped_batch_runs_nothing():
    from tools.toolrush_rpc import execute_read_batch
    stop=threading.Event();stop.set();calls=[]
    result=json.loads(execute_read_batch({'calls':[{'tool':'read_file','args':{}}]*8},
        allowed_tools={'read_file'},counter=[0],budget=50,log=[],
        dispatch=lambda n,a:calls.append(n) or '{}',stop_event=stop))
    assert not calls and isinstance(result,dict) and 'error' in result


def test_parallel_kill_switch_refuses_batch_without_dispatch(rpc,monkeypatch):
    monkeypatch.setenv('TOOLRUSH_PARALLEL','0')
    active=0;peak=0;lock=threading.Lock()
    def dispatch(n,a):
        nonlocal active,peak
        with lock:active+=1;peak=max(peak,active)
        time.sleep(.01)
        with lock:active-=1
        return json.dumps(a)
    module,log,count=rpc(dispatch)
    result=module['parallel']([{'tool':'read_file','args':{'path':str(i)}} for i in range(8)])
    assert isinstance(result,dict) and 'disabled' in result['error'] and peak==0


def test_session_authority_supports_concurrent_calls_and_retirement(monkeypatch):
    from tools.code_kernel import CellAuthority
    import model_tools
    identity=contextvars.ContextVar('toolrush_identity',default='missing')
    identity.set('cell-one'); authority=CellAuthority('task-one')
    gate=threading.Barrier(3)
    def handle(name,args,**kw):
        gate.wait(2)
        return identity.get(),kw['task_id']
    monkeypatch.setattr(model_tools,'handle_function_call',handle)
    with ThreadPoolExecutor(3) as pool:
        results=list(pool.map(lambda _:authority.dispatch('read_file',{}),range(3)))
    assert results==[('cell-one','task-one')]*3
    authority.retire()
    assert 'error' in json.loads(authority.dispatch('read_file',{}))
