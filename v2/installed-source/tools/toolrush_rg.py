"""Native ripgrep transport for ToolRush. No search/regex reimplementation.

Bounded prefix capture replaces `bash ... | head`. Only argv from internal
search builders enters here. No result cache; fresh filesystem reads each call.
"""
from dataclasses import dataclass
import os
import queue
import re
import shlex
import shutil
import subprocess
import threading
import time

from tools import interrupt
from hermes_cli._subprocess_compat import windows_hide_flags

MAX_CAPTURE_BYTES = 8 * 1024 * 1024
CHUNK_BYTES = 16384


@dataclass
class Capture:
    stdout: str
    exit_code: int
    limited: bool = False
    reason: str | None = None


def native_context(ops):
    """Return local cwd/env/rg, or None when shell state cannot be preserved."""
    from tools.environments.local import LocalEnvironment, _IS_WINDOWS, _make_run_env, _msys_to_windows_path
    if not isinstance(ops.env, LocalEnvironment):
        return None
    cwd = ops._local_native_path(getattr(ops.env, 'cwd', None) or ops.cwd)
    if cwd is None or not os.path.isdir(cwd):
        return None
    run_env = _make_run_env(ops.env.env)
    # rg observes these shell exports. Read the atomic snapshot, never source
    # or evaluate shell text in Python. Unrepresentable quoting falls back.
    state = getattr(ops.env, '_snapshot_path', None)
    if state and getattr(ops.env, '_snapshot_ready', False):
        try:
            with open(_msys_to_windows_path(state), encoding='utf-8') as fh:
                snapshot = fh.read(1024 * 1024 + 1)
            if len(snapshot) > 1024 * 1024:
                return None
        except OSError:
            return None
        if re.search(r'(?m)^(?:function\s+)?rg\s*\(\)|^alias rg=', snapshot):
            return None
        relevant = {'RIPGREP_CONFIG_PATH', 'HOME', 'XDG_CONFIG_HOME', 'PATH', 'LANG', 'LC_ALL'}
        for line in snapshot.splitlines():
            if not line.startswith('declare -x '):
                continue
            name = line[11:].split('=', 1)[0]
            if name not in relevant or '=' not in line:
                continue
            raw = line[11:]
            if "$'" in raw or '`' in raw or '$(' in raw:
                return None
            try:
                words = shlex.split(raw, posix=True)
            except ValueError:
                return None
            if len(words) != 1 or '=' not in words[0]:
                return None
            key, value = words[0].split('=', 1)
            if key == 'PATH' and _IS_WINDOWS:
                # Preserve native C:/ paths, but split normal MSYS /c/...:
                # components. Unknown /usr or /bin entries cannot name a
                # native Windows rg; other resolved entries remain usable.
                if ';' in value:
                    parts = value.split(';')
                elif value.startswith('/'):
                    parts = value.split(':')
                else:
                    # Mixed drive-letter POSIX PATH is ambiguous.
                    return None
                value = os.pathsep.join(_msys_to_windows_path(p) for p in parts)
            elif key in ('HOME', 'XDG_CONFIG_HOME', 'RIPGREP_CONFIG_PATH') and _IS_WINDOWS:
                mapped = ops._local_native_path(value) if value else value
                if value and mapped is None:
                    return None
                value = mapped
            # Windows environment keys are case insensitive; avoid two PATHs.
            for previous in list(run_env):
                if previous.upper() == key.upper():
                    run_env.pop(previous)
            run_env[key] = value
    cached = ops._rg_resolution_cache.get('rg')
    executable = _msys_to_windows_path(cached) if cached else None
    if executable and _IS_WINDOWS and not os.path.isfile(executable):
        # command -v rg in Git Bash omits .exe; Windows CreateProcess can
        # infer it but isfile cannot. Validate the actual executable file.
        candidate = executable + '.exe'
        executable = candidate if os.path.isfile(candidate) else None
    if not executable or not os.path.isabs(executable):
        executable = shutil.which('rg', path=run_env.get('PATH'))
    if not executable:
        for candidate in (os.path.join(os.path.expanduser('~'), '.cargo', 'bin', 'rg.exe'),
                          os.path.join(os.environ.get('LOCALAPPDATA',''), 'Microsoft', 'WinGet', 'Links', 'rg.exe')):
            if _IS_WINDOWS and os.path.isfile(candidate):
                executable = candidate
                break
    if not executable or not os.path.isfile(executable):
        return None
    return cwd, run_env, executable


def run_rg(argv, *, cwd, env, max_lines, timeout=60, max_bytes=MAX_CAPTURE_BYTES):
    """Read bounded output and always reap the process, including cancellation."""
    if interrupt.is_interrupted():
        return Capture('', 130, True, 'search_interrupted')
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            creationflags=windows_hide_flags())
    chunks = queue.Queue(maxsize=4)
    stop = threading.Event()

    def pump():
        try:
            while not stop.is_set():
                data = proc.stdout.read1(CHUNK_BYTES)
                if not data:
                    break
                while not stop.is_set():
                    try:
                        chunks.put(data, timeout=0.05)
                        break
                    except queue.Full:
                        pass
        finally:
            while not stop.is_set():
                try:
                    chunks.put(None, timeout=0.05)
                    break
                except queue.Full:
                    pass

    reader = threading.Thread(target=pump, name='toolrush-rg-output', daemon=True)
    reader.start()
    kept = bytearray()
    line_count = 0
    reason = None
    row_bound = False
    reached_eof = False
    deadline = time.monotonic() + timeout
    try:
        while True:
            if interrupt.is_interrupted():
                reason = 'search_interrupted'
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                reason = 'search_timeout'
                break
            try:
                data = chunks.get(timeout=min(remaining, 0.025))
            except queue.Empty:
                continue
            if data is None:
                reached_eof = True
                break
            needed = max_lines - line_count
            pos = -1
            for _ in range(needed):
                pos = data.find(b'\n', pos + 1)
                if pos < 0:
                    break
            if pos >= 0:
                data = data[:pos+1]
                row_bound = True
            room = max_bytes - len(kept)
            if len(data) > room:
                kept.extend(data[:room])
                reason = 'search_output_budget'
                break
            kept.extend(data)
            line_count += data.count(b'\n')
            if row_bound:
                break
    finally:
        stop.set()
        if reached_eof:
            try:
                proc.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                reason = 'search_timeout'
        if proc.poll() is None:
            proc.kill()
        code = proc.wait(timeout=5)
        reader.join(timeout=2)
        proc.stdout.close()
    if reason == 'search_timeout':
        code = 124
    elif reason == 'search_interrupted':
        code = 130
    elif row_bound:
        code = 0  # deliberately bounded prefix, as with head (not full scan)
    text = bytes(kept).decode('utf-8', 'replace').replace('\r\n', '\n')
    return Capture(text, code, bool(reason), reason)
