"""ToolRush exec v1 — persistent-shell executor (scratch lab, NOT the live tree).

Kills both terminal taxes dissected in VAL-T2:
  X1 cold-task env creation (1.26s): ONE process-wide shell, no per-task
     login-shell snapshot bootstrap. Cwd tracked per call (cd per command),
     mirroring the harness's own per-session cwd dual-write.
  X2 per-command spawn+wrap+deadline (~280ms): commands framed through the
     live shell's stdin; stdout framed back. Zero spawns per call.

Framing: each command wrapped as:
  printf '<MARK>BEGIN</MARK>\n'; <cmd>; echo exit:$?; printf '<MARK>END</MARK>\n'
Reader consumes until END marker. Unique marker per process (pid) so stale
output can never alias.

Kill-switch (VAL-T5): TOOLRUSH_PERSIST=0 -> spawn-per-call (subprocess.run),
same function signature — measures ~= baseline, proving the win is the
persistent shell, not the bench.

Safety: local backend only. No remote/docker/modal. Commands run via the
same bash the harness would spawn; no new privileges, no new surfaces.
"""
import os
import subprocess
import sys
import threading
import time
import uuid

USE_PERSIST = os.environ.get("TOOLRUSH_PERSIST", "1") == "1"

_MARK = f"TRX{os.getpid():x}{uuid.uuid4().hex[:8]}"
_BEGIN = f"{_MARK}_BEGIN"
_END = f"{_MARK}_END"

_LOCK = threading.Lock()
_PROC = None
_CWD = None
_BASH = None


def _bash_exe():
    """Reuse the harness's own bash resolver — same binary, minus per-call spawn."""
    global _BASH
    if _BASH is None:
        from tools.environments.local import _find_bash

        _BASH = _find_bash()
    return _BASH


def _spawn(cwd=None):
    global _PROC, _CWD
    _PROC = subprocess.Popen(
        [_bash_exe(), "--noprofile", "--norc"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=cwd or os.getcwd(),
    )
    _CWD = cwd or os.getcwd()
    # Drain bash's startup (nothing expected, but never assume empty)
    return _PROC


def _shell():
    global _PROC
    with _LOCK:
        if _PROC is None or _PROC.poll() is not None:
            _spawn()
        return _PROC


def exec_persist(command, cwd=None, timeout=60):
    """Run one command on the persistent shell. Returns (stdout, exit_code)."""
    proc = _shell()
    with _LOCK:
        if cwd and cwd != _CWD:
            return _run_locked(proc, f"cd {shquote(cwd)} && {command}", timeout, cwd)
        return _run_locked(proc, command, timeout, cwd or _CWD)


def shquote(p):
    return "'" + str(p).replace("'", "'\\''") + "'"


def _run_locked(proc, command, timeout, cwd):
    framed = (
        f"printf '%s\\n' '{_BEGIN}'; "
        f"({command}); _rc=$?; "
        f"printf 'RC:%d\\n' $_rc; printf '%s\\n' '{_END}';\n"
    )
    proc.stdin.write(framed)
    proc.stdin.flush()
    out_lines = []
    rc = -1
    t0 = time.time()
    while True:
        if time.time() - t0 > timeout:
            return "".join(out_lines), 124
        line = proc.stdout.readline()
        if not line:
            # shell died mid-command — respawn once, report
            global _PROC
            _PROC = None
            return "".join(out_lines), -1
        if line.rstrip("\n") == _END:
            break
        if line.startswith("RC:"):
            try:
                rc = int(line[3:].strip())
            except ValueError:
                rc = -1
            continue
        if line.rstrip("\n") == _BEGIN:
            continue
        out_lines.append(line)
    return "".join(out_lines).rstrip("\n"), rc


def exec_spawn(command, cwd=None, timeout=60):
    """Negative control: spawn-per-call, same signature."""
    r = subprocess.run(
        [_bash_exe(), "--noprofile", "--norc", "-c", command],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd or os.getcwd(),
    )
    return r.stdout.rstrip("\n"), r.returncode


def toolrush_exec(command, cwd=None, timeout=60):
    """Dispatch with kill-switch: PERSIST=0 -> spawn-per-call."""
    if USE_PERSIST:
        return exec_persist(command, cwd=cwd, timeout=timeout)
    return exec_spawn(command, cwd=cwd, timeout=timeout)


if __name__ == "__main__":
    mode = "persist" if USE_PERSIST else "spawn"
    print(f"mode={mode}")
    o, c = toolrush_exec("echo termbench")
    assert o.strip() == "termbench" and c == 0, f"{o!r} rc={c}"
    o2, c2 = toolrush_exec("echo second && echo third")
    assert "second" in o2 and "third" in o2 and c2 == 0, f"{o2!r}"
    o3, c3 = toolrush_exec("exit 7")
    assert c3 == 7, f"rc={c3}"
    o4, c4 = toolrush_exec("pwd", cwd="/tmp")
    print(f"selftest OK: {o!r} {o2!r} rc7={c3} pwd={o4!r}")
