"""ToolRush v2 — thin Windows warm-shell integration.

Core Hermes owns native file reads/search and safe scheduling. This plugin
only installs the streaming persistent-shell transport. It never races a
snapshot commit, bypasses core read gates, or falls back to raw secrets.
Reload requires a fresh host process; do not hot-patch live turns.
"""
import os
import re
import shlex
import threading

_SPAWN_LOCK=threading.Lock()
_WARM_ATTR='_toolrush_warm_v2'


def _bridge_prefix(owner,local):
    # Kept as a diagnostic hook. Filtering failures propagate; callers may
    # use the ordinary backend, which applies the same filter itself.
    env=local._make_run_env(owner.env)
    return '\n'.join(f'export {k}={shlex.quote(v)}' for k,v in env.items()
                     if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',k) and isinstance(v,str))+'\n'


def _build_frame(owner,local,command,timeout=None):
    from tools.toolrush_shell import build_frame
    return build_frame(owner,local,command)


def _apply_terminal_lane():
    from tools.environments import local
    from tools.toolrush_shell import WarmShell,WarmHandle
    from tools.toolrush_runtime import enabled
    cls=local.LocalEnvironment
    original=cls._run_bash
    cleanup=cls.cleanup
    kill_process=cls._kill_process
    if getattr(original,'_toolrush_v2',False): return

    def run(owner,command,*,login=False,timeout=120,stdin_data=None):
        if (login or stdin_data is not None or not local._IS_WINDOWS
                or not enabled('warm_shell','TOOLRUSH_PERSIST')):
            return original(owner,command,login=login,timeout=timeout,stdin_data=stdin_data)
        # Background children can retain the broker stdout after a frame.
        # Keep such commands on the existing disposable-process path.
        for line in command.splitlines():
            if line.startswith('eval '):
                try: user_code=shlex.split(line)[1]
                except (ValueError,IndexError): user_code='&'
                if re.search(r'(?<!&)&(?!&)',user_code):
                    return original(owner,command,login=login,timeout=timeout,stdin_data=stdin_data)
        shell=None; acquired=False
        try:
            with _SPAWN_LOCK:
                shell=getattr(owner,_WARM_ATTR,None)
                if shell is None or shell.dead or shell.proc.poll() is not None:
                    if shell is not None: shell.close()
                    shell=WarmShell(local,owner)
                    setattr(owner,_WARM_ATTR,shell)
            acquired=shell.lock.acquire(blocking=False)
            if not acquired:
                # Never queue independent work behind one busy warm shell.
                return original(owner,command,login=login,timeout=timeout,stdin_data=stdin_data)
            frame,begin,end,commit=_build_frame(owner,local,command,timeout)
            return WarmHandle(shell,frame,begin,end,commit)
        except Exception:
            if acquired: shell.lock.release()
            # Frame submission happens only in WarmHandle's worker. No failed
            # submitted command is retried, avoiding duplicated side effects.
            return original(owner,command,login=login,timeout=timeout,stdin_data=stdin_data)

    def clean(owner):
        shell=getattr(owner,_WARM_ATTR,None)
        if shell is not None:
            shell.close(); setattr(owner,_WARM_ATTR,None)
        return cleanup(owner)

    def kill(owner,proc):
        if isinstance(proc,WarmHandle):
            # LocalEnvironment's Windows PID terminator only kills the broker
            # on this build. The handle owns the full frame tree and its pipe.
            proc.kill()
            return
        return kill_process(owner,proc)

    run._toolrush_v2=True
    run._toolrush_original=original
    clean._toolrush_v2=True
    run.__name__='_run_bash'
    cls._run_bash=run
    cls._kill_process=kill
    cls.cleanup=clean


_COMPAT_STATUS=None

def register(ctx=None):
    global _COMPAT_STATUS
    import importlib.util
    import logging
    from pathlib import Path
    if _COMPAT_STATUS is None:
        try:
            spec=importlib.util.spec_from_file_location('_toolrush_compat_v2',Path(__file__).with_name('compat.py'))
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            _COMPAT_STATUS=module.install()
        except Exception as exc:
            _COMPAT_STATUS={'bootstrap':{'status':'degraded','reason':str(exc)}}
            logging.getLogger(__name__).warning('ToolRush compatibility bootstrap disabled: %s',exc)
            return
    if any(_COMPAT_STATUS.get(name,{}).get('status')=='ready'
           for name in ('snapshot','rpc')):
        _apply_terminal_lane()
    return _COMPAT_STATUS
