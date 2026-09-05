"""ToolRush — kill the Windows tool-call spawn tax. Hermes user plugin.

Problem (measured 2026-09-03 on this host): every foreground terminal call and
every shell-based file op cold-spawns ``bash -c`` (~287ms for ``echo``; a
single read_file cost ~1460ms across 3-5 spawn round-trips), because
``LocalEnvironment`` ignores ``persistent_shell`` (SSH-only upstream) and
``ShellFileOperations`` routes Windows reads through shell probes even though
a byte-parity native path exists.

Both lanes patch at CLASS level (so live env instances benefit) and live in
this user plugin, outside the hermes-agent package — update-safe.

LANE 1 — read_file fast lane (TOOLRUSH_FASTLANE, default on)
  Flips ``ShellFileOperations._native_read_enabled`` to allow the harness's
  OWN ``_read_file_native`` (byte-parity, chunked, binary-sniffing, sed/cut
  clamping semantics) on Windows local environments, and pre-translates
  MSYS-style paths (``/c/Users/...``) to native form first so a bash-flavored
  path still resolves instead of reporting not-found. Any OS surprise inside
  ``_read_file_native`` falls back to the shell path by design (its own
  except-OSError branches). ``HERMES_NATIVE_FILE_READ=0`` (upstream switch)
  and ``TOOLRUSH_FASTLANE=0`` both restore stock behavior.

LANE 2 — terminal warm shell (TOOLRUSH_PERSIST, default on)
  Patches ``LocalEnvironment._run_bash`` (class attr). When the call is a
  plain foreground script (no login bootstrap, no stdin pipe, Windows local
  env, lane enabled, warm shell not busy), the EXACT wrapped script that
  ``execute()`` built (``_wrap_command``: snapshot source, cd, CWD marker,
  env re-dump) is executed inside a subshell on a warm
  ``bash --noprofile --norc -s`` owned by that env instance, framed by
  unguessable BEGIN/END markers with the exit code echoed inside the frame.

  The subshell gets ``< /dev/null`` so commands reading stdin see EOF exactly
  like the cold path's DEVNULL. Per-frame prefix unsets+re-exports the
  gateway session-bridged vars (HERMES_SESSION_*, HERMES_UI_SESSION_ID,
  HERMES_CRON_*, HERMES_BROWSER_CONTROL_*) and PATH from a fresh
  ``_make_run_env`` — the only env facts a cold Popen would have delivered
  that a long-lived shell would otherwise miss.

  The return value is a ``_ThreadedProcessHandle`` subclass (the harness's
  own in-memory adapter) whose pipe replays the frame's collected output.
  ``_wait_for_process`` therefore keeps ALL of its semantics: adaptive poll,
  activity heartbeats, bounded capture + spill files, interrupt (/stop),
  timeout, run_bounded_sync backstop. ``handle.pid`` is the warm bash pid so
  ``_kill_process``/``kill_process_tree`` really kill the tree on timeout.

  If the warm shell is busy (a concurrent session is mid-frame on the shared
  default env), the call waits briefly then falls back to a cold spawn —
  preserving the stock path's parallelism instead of serializing sessions.

  ``cleanup()`` is wrapped to kill the env's warm shell first.

No config-schema additions, no new privileges, no model-visible surface.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import threading
import time
import uuid

_WARM_ATTR = "_toolrush_warm"
_SPAWN_LOCK = threading.Lock()
_CAP_BYTES = 64 * 1024 * 1024  # hard in-memory cap for one frame's output
_BUSY_FALLBACK_S = 0.5         # wait this long for a busy shell, then cold-spawn


def _flag(name: str) -> bool:
    return os.environ.get(name, "1") == "1"


# ─────────────────────────────────────────────────────────────────────────────
# LANE 1: read_file fast lane
# ─────────────────────────────────────────────────────────────────────────────

def _apply_read_lane() -> None:
    import tools.file_operations as fo

    # 1a. Flip the native-read gate for Windows local envs.
    orig_enabled = fo.ShellFileOperations._native_read_enabled
    if not getattr(orig_enabled, "_toolrush", False):

        def _native_read_enabled_patched(self):  # noqa: N805
            if not _flag("TOOLRUSH_FASTLANE"):
                return orig_enabled(self)
            # Honor the upstream kill-switch too.
            flag = os.environ.get("HERMES_NATIVE_FILE_READ", "1").strip().lower()
            if flag in ("0", "false", "no", "off"):
                return False
            try:
                return self._lsp_local_only()
            except Exception:
                return orig_enabled(self)

        _native_read_enabled_patched._toolrush = True
        _native_read_enabled_patched.__name__ = "_native_read_enabled"
        fo.ShellFileOperations._native_read_enabled = _native_read_enabled_patched

    # 1b. Translate MSYS-style paths before the native path stats them.
    orig_read = fo.ShellFileOperations.read_file
    if not getattr(orig_read, "_toolrush", False):

        def _read_file_patched(self, path, offset=1, limit=2000):  # noqa: N805
            if _flag("TOOLRUSH_FASTLANE") and isinstance(path, str):
                try:
                    from tools.environments.local import _msys_to_windows_path

                    native = _msys_to_windows_path(path)
                    if native != path and os.path.isfile(native):
                        path = native
                except Exception:
                    pass
            return orig_read(self, path, offset, limit)

        _read_file_patched._toolrush = True
        _read_file_patched.__name__ = "read_file"
        fo.ShellFileOperations.read_file = _read_file_patched


# ─────────────────────────────────────────────────────────────────────────────
# LANE 2: terminal warm shell
# ─────────────────────────────────────────────────────────────────────────────

class _ShellDead(Exception):
    pass  # retained for potential external probes; lanes no longer raise it


def _bridge_prefix(self, local_mod) -> str:
    """Per-frame export prefix: session-bridged vars + PATH, fresh each call."""
    lines = [
        "for __trk in ${!HERMES_SESSION_*} ${!HERMES_CRON_AUTO_DELIVER_*} "
        "${!HERMES_CRON_SESSION*} ${!HERMES_BROWSER_CONTROL_*}; do "
        'unset "$__trk"; done 2>/dev/null',
    ]
    try:
        run_env = local_mod._make_run_env(self.env)
    except Exception:
        run_env = dict(os.environ)
    prefixes = (
        "HERMES_SESSION_", "HERMES_CRON_", "HERMES_BROWSER_CONTROL_",
    )
    wanted = {"HERMES_UI_SESSION_ID", "PATH"}
    exports = {}
    for k, v in run_env.items():
        if k in wanted or any(k.startswith(p) for p in prefixes):
            if isinstance(v, str):
                exports[k] = v
    for k in sorted(exports):
        lines.append(f"export {k}={shlex.quote(exports[k])}")
    return "\n".join(lines) + "\n"


def _ensure_warm(self, local_mod) -> dict:
    warm = getattr(self, _WARM_ATTR, None)
    if warm and not warm["dead"] and warm["proc"].poll() is None:
        return warm
    with _SPAWN_LOCK:
        warm = getattr(self, _WARM_ATTR, None)
        if warm and not warm["dead"] and warm["proc"].poll() is None:
            return warm
        from hermes_cli._subprocess_compat import windows_hide_flags

        try:
            cwd = local_mod._resolve_safe_cwd(self.cwd)
        except Exception:
            cwd = self.cwd
        if not os.path.isdir(cwd):
            cwd = os.getcwd()
        try:
            env = local_mod._make_run_env(self.env)
        except Exception:
            env = dict(os.environ)
        proc = subprocess.Popen(
            [local_mod._find_bash(), "--noprofile", "--norc", "-s"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            env=env,
            creationflags=windows_hide_flags(),
        )
        warm = {"proc": proc, "lock": threading.Lock(), "dead": False}
        try:
            setattr(self, _WARM_ATTR, warm)
        except Exception:
            pass
        return warm


def _abort(warm: dict) -> None:
    warm["dead"] = True
    proc = warm["proc"]
    try:
        proc.kill()
    except Exception:
        pass
    try:
        from agent.deadline import kill_process_tree

        kill_process_tree(int(proc.pid))
    except Exception:
        pass


def _build_frame(self, local_mod, cmd_string: str, timeout) -> tuple:
    """Build the full frame ON THE DISPATCH THREAD.

    ``_bridge_prefix`` calls ``_make_run_env`` → ``_inject_session_context_env``,
    which reads the CALLING thread's session context; the handle's worker
    thread must never build it. Returns the exact bytes to write to the shell.

    Snapshot-dump surgery: the harness's wrapped script re-dumps the env
    snapshot (mktemp + export dump + fn dump + mv ≈ 5 MSYS forks, ~150ms)
    BEFORE the CWD marker, i.e. in the blocking path. We rewrite that one
    line into an async background job ``{ ... ; } &`` inside the frame's
    subshell: the dump still runs with the subshell's evolved environment
    (so exports persist to the snapshot file exactly like the cold path)
    and stays atomic (mktemp+mv), but the response returns at the END
    marker without waiting for it. An orphaned dump never writes to
    stdout, and a next-frame ``source`` racing an unfinished dump reads
    the previous complete file and self-heals one frame later.
    """
    uid = uuid.uuid4().hex[:12]
    body = cmd_string
    lines = cmd_string.split("\n")
    dump_idxs = [i for i, l in enumerate(lines)
                 if l.startswith("__hermes_snap_tmp=$(mktemp")]
    if len(dump_idxs) == 1:
        i = dump_idxs[0]
        # Wrap the harness's own dump line verbatim in a background group.
        # The line ends with "|| true", so "; } &" keeps it valid bash.
        lines[i] = "{ " + lines[i] + " ; } &"
        body = "\n".join(lines)
    # else: unfamiliar wrapped-script shape → run it verbatim (slower, still
    # semantically identical because the whole script executes in the frame).
    frame = (
        _bridge_prefix(self, local_mod)
        + "printf '%s\\n' '__TRB_" + uid + "__'\n"
        + "( " + body + " ) </dev/null\n"
        + "__tr_rc=$?\n"
        + "printf '\\n__TRE_" + uid + ":%s\\n' \"$__tr_rc\"\n"
    )
    return frame.encode("utf-8"), ("__TRB_" + uid + "__\n").encode(), ("__TRE_" + uid + ":").encode()


def _run_frame(warm: dict, frame: bytes, begin_line: bytes, end_prefix: bytes,
               timeout) -> tuple:
    """Write one prebuilt frame to the warm shell; return (output, rc).

    Runs on the handle's worker thread. Caller must hold warm["lock"] and
    must release it when this returns (done by the exec_fn wrapper).
    Never raises — a dead shell yields ("", 1).
    """
    proc = warm["proc"]
    try:
        proc.stdin.write(frame)
        proc.stdin.flush()
    except (BrokenPipeError, OSError):
        _abort(warm)
        return "", 1

    try:
        deadline = time.monotonic() + max(float(timeout or 120), 1.0) + 30.0
    except (TypeError, ValueError):
        deadline = time.monotonic() + 150.0

    out = bytearray()
    skipping = True  # discard stale grandchild noise before BEGIN
    while True:
        if time.monotonic() > deadline:
            # Backstop: the harness's own timeout normally fires first and
            # kills the tree via handle.pid; this guards a wedged reader.
            _abort(warm)
            return out[:_CAP_BYTES].decode("utf-8", errors="replace"), 124
        line = proc.stdout.readline()
        if not line:
            _abort(warm)
            return out[:_CAP_BYTES].decode("utf-8", errors="replace"), 1
        if skipping:
            if line == begin_line or line.rstrip(b"\r\n") + b"\n" == begin_line:
                skipping = False
            continue
        if line.startswith(end_prefix):
            try:
                rc = int(line[len(end_prefix):].strip())
            except ValueError:
                rc = 1
            # Drop the single "\n" our END printf injected.
            if out.endswith(b"\n"):
                del out[-1:]
            return out[:_CAP_BYTES].decode("utf-8", errors="replace"), rc
        if len(out) < _CAP_BYTES:
            out += line
        # past cap: keep consuming (avoids pipe deadlock) but stop storing


def _apply_terminal_lane() -> None:
    import tools.environments.local as local_mod
    from tools.environments.base import _ThreadedProcessHandle

    LocalEnv = local_mod.LocalEnvironment
    orig_run_bash = LocalEnv._run_bash
    if getattr(orig_run_bash, "_toolrush", False):
        return
    orig_cleanup = LocalEnv.cleanup

    class _WarmHandle(_ThreadedProcessHandle):
        """In-memory handle whose pid is the warm bash (tree-killable)."""

        def __init__(self, warm, exec_fn, cancel_fn):
            self._warm = warm
            super().__init__(exec_fn=exec_fn, cancel_fn=cancel_fn)

        @property
        def pid(self):
            try:
                return self._warm["proc"].pid
            except Exception:
                return None

    def _run_bash_patched(self, cmd_string, *, login=False, timeout=120,
                          stdin_data=None):  # noqa: N805
        if (
            not _flag("TOOLRUSH_PERSIST")
            or login
            or stdin_data is not None
            or not getattr(local_mod, "_IS_WINDOWS", False)
        ):
            return orig_run_bash(self, cmd_string, login=login,
                                 timeout=timeout, stdin_data=stdin_data)
        try:
            warm = _ensure_warm(self, local_mod)
        except Exception:
            return orig_run_bash(self, cmd_string, login=login,
                                 timeout=timeout, stdin_data=stdin_data)

        lock = warm["lock"]
        if not lock.acquire(blocking=False):
            # A concurrent session holds the shell. Wait briefly, then
            # cold-spawn rather than serializing sessions.
            if not lock.acquire(timeout=_BUSY_FALLBACK_S):
                return orig_run_bash(self, cmd_string, login=login,
                                     timeout=timeout, stdin_data=stdin_data)
        try:
            # Re-check liveness under the lock; respawn if needed.
            if warm["dead"] or warm["proc"].poll() is not None:
                warm["dead"] = True
                warm = _ensure_warm(self, local_mod)
                if warm["lock"] is not lock and not warm["lock"].acquire(blocking=False):
                    return orig_run_bash(
                        self, cmd_string, login=login, timeout=timeout,
                        stdin_data=stdin_data)

            # Build the frame HERE (session ContextVars live on this thread).
            frame, begin_line, end_prefix = _build_frame(
                self, local_mod, cmd_string, timeout)
            shell_lock = warm["lock"]

            def _exec():
                try:
                    return _run_frame(warm, frame, begin_line, end_prefix,
                                      timeout)
                finally:
                    # Hold the shell until the frame completes so a second
                    # frame can never interleave writes on the same stdin.
                    try:
                        shell_lock.release()
                    except RuntimeError:
                        pass

            return _WarmHandle(warm, exec_fn=_exec,
                               cancel_fn=lambda: _abort(warm))
        except Exception:
            try:
                warm["lock"].release()
            except RuntimeError:
                pass
            return orig_run_bash(self, cmd_string, login=login,
                                 timeout=timeout, stdin_data=stdin_data)

    def _cleanup_patched(self):  # noqa: N805
        warm = getattr(self, _WARM_ATTR, None)
        if warm:
            _abort(warm)
            try:
                setattr(self, _WARM_ATTR, None)
            except Exception:
                pass
        return orig_cleanup(self)

    _run_bash_patched._toolrush = True
    _run_bash_patched.__name__ = "_run_bash"
    _cleanup_patched._toolrush = True
    _cleanup_patched.__name__ = "cleanup"
    LocalEnv._run_bash = _run_bash_patched
    LocalEnv.cleanup = _cleanup_patched


# ─────────────────────────────────────────────────────────────────────────────
# Plugin entry points
# ─────────────────────────────────────────────────────────────────────────────

def register(ctx=None) -> None:  # noqa: ARG001
    for apply in (_apply_read_lane, _apply_terminal_lane):
        try:
            apply()
        except Exception:
            # Never break the host process at load time.
            import traceback

            traceback.print_exc()


def on_load(ctx=None) -> None:  # noqa: ARG001
    register(ctx)


# Import-time self-application: the patch is live the moment we're imported,
# regardless of how the loader invokes us.
try:
    register()
except Exception:
    pass
