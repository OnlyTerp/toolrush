"""Streaming warm-shell substrate for ToolRush on Windows.

One reusable broker per LocalEnvironment. Each command runs in an isolated
subshell; the caller's existing wrapper remains authoritative for state,
exit status, cwd, and secret exclusions. No asynchronous snapshot commit.
"""
import os
import re
import shlex
import subprocess
import threading
import uuid

from hermes_cli._subprocess_compat import windows_hide_flags


class WarmShell:
    def __init__(self, local, owner):
        sanitized = local._make_run_env(owner.env)  # NEVER raw-env fallback
        # Broker carries no profile/provider/session credentials. Every frame
        # receives its own sanitized environment inside the subshell.
        keep = {'SYSTEMROOT','WINDIR','SYSTEMDRIVE','COMSPEC','PATH','PATHEXT',
                'TEMP','TMP','HOME','MSYS_NO_PATHCONV','MSYS2_ARG_CONV_EXCL'}
        broker_env = {k:v for k,v in sanitized.items() if k.upper() in keep}
        cwd = local._resolve_safe_cwd(owner.cwd)
        self.proc = subprocess.Popen([local._find_bash(), '--noprofile','--norc','-s'],
            cwd=cwd, env=broker_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, creationflags=windows_hide_flags(), bufsize=0)
        self.lock = threading.Lock()
        self.dead = False

    def close(self):
        self.dead = True
        if self.proc.poll() is None:
            try:
                from agent.deadline import kill_process_tree
                kill_process_tree(self.proc.pid)
            finally:
                if self.proc.poll() is None:
                    self.proc.kill()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        for pipe in (self.proc.stdin, self.proc.stdout):
            try: pipe.close()
            except (OSError, ValueError): pass


def build_frame(owner, local, command):
    uid = uuid.uuid4().hex
    env = local._make_run_env(owner.env)
    # No heuristic extraction of actual user code: wrapper is unchanged.
    # Only replace its one internal mktemp allocation with an unguessable
    # unique per-frame path. Creation uses noclobber and existing umask 077.
    lines = command.split('\n')
    prefix = '__hermes_snap_tmp=$(mktemp '
    allocations = [i for i,line in enumerate(lines) if line.startswith(prefix)]
    commit = None
    if len(allocations) == 1:
        i=allocations[0]
        line=lines[i]
        boundary=line.find(') && ')
        # Change only the exact internal atomic-move clause emitted by core.
        # No shell parsing/rewrite of the user command or exclusion program.
        move='&& mv -f "$__hermes_snap_tmp" '+owner._quote_shell_path(owner._snapshot_path)+';'
        if boundary > len(prefix) and move in line:
            temporary=owner._snapshot_path+'.tmp.'+uid
            ready=temporary+'.ready'
            unique=owner._quote_shell_path(temporary)
            lines[i]=f'__hermes_snap_tmp={unique}; '+line[boundary+5:]
            lines[i]=lines[i].replace(move,'&& : > '+owner._quote_shell_path(ready)+';',1)
            from tools.environments.base import _export_dump_excluding_session_vars
            exclusions=owner._snapshot_excluded_passthrough_names()
            dump=_export_dump_excluding_session_vars('"$__hermes_snap_tmp"',exclusions)
            if dump in lines[i] and dump.startswith('{ ( ') and ') || true; }' in dump:
                # User code has finished and the entire frame is already a
                # subshell. Dropping only this redundant dump subshell cannot
                # leak unsets into the broker or change user exit/cwd state.
                flattened=dump.replace('{ ( ','{ ',1).replace(') || true; }','true; }',1)
                lines[i]=lines[i].replace(dump,flattened,1)
            commit=(local._msys_to_windows_path(temporary),
                    local._msys_to_windows_path(owner._snapshot_path),
                    local._msys_to_windows_path(ready))
    exports=[]
    for key,value in env.items():
        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',key) and isinstance(value,str):
            if key.upper() == 'PATH':
                # Popen normally lets MSYS convert the Windows PATH at startup.
                # Exporting its semicolon form inside an existing bash skips
                # that conversion and loses all native/coreutils commands.
                if ';' in value:
                    value=':'.join(local._windows_to_msys_path(p) for p in value.split(';'))
                key='PATH'
            exports.append(f'export {key}={shlex.quote(value)}')
    begin=('__TRB_'+uid+'__\n').encode()
    end=('\n__TRE_'+uid+':').encode()
    body='\n'.join(lines)
    frame=(f"printf '%s\\n' '__TRB_{uid}__'\n(\n"+'\n'.join(exports)+'\n'+body+
           f"\n) </dev/null\n__tr_rc=$?\nprintf '\\n__TRE_{uid}:%s\\n' \"$__tr_rc\"\n")
    return frame.encode('utf-8'),begin,end,commit


class WarmHandle:
    """Real streaming ProcessHandle: fixed-size parser + OS pipe backpressure."""
    def __init__(self, shell, frame, begin, end, commit=None):
        self.shell=shell
        self.commit=commit
        if commit:
            # Native exclusive reservation is the mktemp security property,
            # without a second MSYS fork. The shell opens this same private
            # inode under umask 077; commit remains synchronous and atomic.
            fd=os.open(commit[0],os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            os.close(fd)
        self._done=threading.Event()
        self._returncode=None
        read_fd,self._write_fd=os.pipe()
        self.stdout=os.fdopen(read_fd,'rb',buffering=0)
        threading.Thread(target=self._run,args=(frame,begin,end),daemon=True,
                         name='toolrush-warm-frame').start()

    @property
    def pid(self): return self.shell.proc.pid
    @property
    def returncode(self): return self._returncode
    def poll(self): return self._returncode if self._done.is_set() else None
    def wait(self,timeout=None):
        if not self._done.wait(timeout):
            raise subprocess.TimeoutExpired('toolrush-frame',timeout)
        return self._returncode
    def kill(self): self.shell.close()

    def _emit(self,data):
        view=memoryview(data)
        while view:
            written=os.write(self._write_fd,view)
            view=view[written:]

    def _run(self,frame,begin,end):
        proc=self.shell.proc
        buf=bytearray(); started=False
        try:
            # Unbuffered FileIO can write a prefix; finish every byte before
            # reading. Large frames are bounded by caller command limits.
            view=memoryview(frame)
            while view:
                n=proc.stdin.write(view); view=view[n:]
            while True:
                chunk=os.read(proc.stdout.fileno(),65536)
                if not chunk:
                    self._returncode=1
                    self.shell.dead=True
                    break
                buf.extend(chunk)
                if not started:
                    pos=buf.find(begin)
                    if pos<0:
                        if len(buf)>len(begin): del buf[:-len(begin)]
                        continue
                    del buf[:pos+len(begin)]; started=True
                pos=buf.find(end)
                if pos>=0:
                    eol=buf.find(b'\n',pos+len(end))
                    if eol>=0:
                        self._emit(buf[:pos])
                        try: self._returncode=int(buf[pos+len(end):eol].strip())
                        except ValueError: self._returncode=1; self.shell.dead=True
                        if self.commit:
                            temporary,target,ready=self.commit
                            if os.path.isfile(ready):
                                # Completion is not visible until the filtered
                                # snapshot is atomically committed. Never async.
                                try: os.replace(temporary,target)
                                except OSError:
                                    self._returncode=1; self.shell.dead=True
                                    self._emit(b'\n[ToolRush snapshot commit failed]')
                        break
                # Emit all bytes except an actual delimiter prefix. Holding
                # a fixed tail hides short progress messages until completion.
                if pos >= 0:
                    if pos:
                        self._emit(buf[:pos]); del buf[:pos]
                else:
                    keep=min(len(end)-1,len(buf))
                    while keep and not buf.endswith(end[:keep]):
                        keep-=1
                    amount=len(buf)-keep
                    if amount:
                        self._emit(buf[:amount]); del buf[:amount]
        except (OSError,ValueError,RuntimeError):
            self._returncode=1
            self.shell.dead=True
        finally:
            if self.commit:
                for path in (self.commit[0],self.commit[2]):
                    try: os.unlink(path)
                    except OSError: pass
            if self._returncode is None: self._returncode=1
            try: os.close(self._write_fd)
            except OSError: pass
            self._done.set()
            self.shell.lock.release()
