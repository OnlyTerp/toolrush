"""Contract tests: read-only terminal parallel admission + wire parallel_tool_calls (VAL-PT-1).

Drives the REAL planner (`_plan_tool_batch_segments`) and the REAL wire-param
resolution. RED state: written BEFORE the patch — classifier + wire param do not
exist yet, so every "new behavior" assertion must fail and every NEG-CTL
(pinning today's behavior) must pass.
"""

import uuid
from types import SimpleNamespace

import pytest

from agent.tool_dispatch_helpers import _plan_tool_batch_segments


def _tc(name="terminal", arguments="{}", call_id=None):
    return SimpleNamespace(
        id=call_id or f"call_{uuid.uuid4().hex[:8]}",
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _term(cmd, call_id=None):
    return _tc("terminal", '{"command": %s}' % _json_str(cmd), call_id=call_id)


def _json_str(s):
    import json
    return json.dumps(s)


def _kinds(segments):
    return [kind for kind, _ in segments]


def _ids(segments):
    return [tc.id for _, calls in segments for tc in calls]


# ---------------------------------------------------------------------------
# VAL-PT-1 — the classifier
# ---------------------------------------------------------------------------

class TestReadonlyClassifier:
    def _f(self):
        # imported lazily so the module-level import above doesn't hide a missing symbol
        from agent.tool_dispatch_helpers import _is_readonly_terminal_command
        return _is_readonly_terminal_command

    def test_grep_true(self):
        assert self._f()("grep -n foo C:/x/config.yaml")

    def test_ls_grep_chain_true(self):
        assert self._f()('ls -la ~/.operator/claude-shim/ && grep -n "model" file')

    def test_git_status_true(self):
        assert self._f()("git status --short | head -20")

    def test_curl_healthz_true(self):
        assert self._f()("curl -s -m 5 http://127.0.0.1:18778/healthz")

    def test_sed_print_true(self):
        assert self._f()("sed -n '970,1010p' file")

    def test_redirect_overwrite_false(self):
        assert not self._f()("echo hi > file.txt")

    def test_sed_inplace_false(self):
        assert not self._f()("sed -i s/a/b/ file")

    def test_npm_install_false(self):
        assert not self._f()("npm install")

    def test_git_checkout_false(self):
        assert not self._f()("git checkout -- x")

    def test_rm_false(self):
        assert not self._f()("rm x")

    def test_pip_install_false(self):
        assert not self._f()("pip install y")

    def test_empty_false(self):
        assert not self._f()("")

    def test_mixed_chain_one_write_segment_false(self):
        assert not self._f()("echo ok; rm -rf x")

    def test_cd_chain_is_state_barrier(self):
        # Hermes saves cwd after terminal calls; concurrent cd is not a
        # read even when its subprocess uses an isolated shell.
        assert not self._f()("cd ~/.operator/claude-shim && ls -la *.bak")

    def test_dollar_expansion_rejected(self):
        # $-opacity is a SAFETY feature — can't see through variable expansion
        assert not self._f()("for f in *.bak; do sha256sum $f; done")


# ---------------------------------------------------------------------------
# VAL-PT-2 — planner admits read-only terminal into parallel runs
# ---------------------------------------------------------------------------

class TestPlannerReadonlyTerminal:
    def test_readonly_terminal_batch_all_parallel(self):
        calls = [
            _term("rg -n foo C:/x/config.yaml", "t1"),
            _tc("web_search", "{}", "w1"),
            _term("ls -la ~/.operator/claude-shim/", "t2"),
            _term("curl -s -m 5 http://127.0.0.1:18778/healthz", "t3"),
        ]
        segments = _plan_tool_batch_segments(calls)
        assert _kinds(segments) == ["parallel"]
        assert _ids(segments) == ["t1", "w1", "t2", "t3"]

    def test_write_terminal_is_barrier_after_readers(self):
        calls = [
            _term("rg -n foo file", "r1"),
            _term("ls -la dir", "r2"),
            _term("echo hi > out.txt", "w1"),
        ]
        segments = _plan_tool_batch_segments(calls)
        assert _kinds(segments) == ["parallel", "sequential"]
        assert [tc.id for tc in segments[0][1]] == ["r1", "r2"]
        assert [tc.id for tc in segments[1][1]] == ["w1"]

    def test_write_first_orders_reads_after(self):
        calls = [
            _term("echo hi > out.txt", "w1"),
            _term("rg -n foo out.txt", "r1"),
            _term("ls -la .", "r2"),
        ]
        segments = _plan_tool_batch_segments(calls)
        assert _kinds(segments) == ["sequential", "parallel"]
        assert _ids(segments) == ["w1", "r1", "r2"]

    def test_unknown_command_stays_barrier(self):
        calls = [
            _term("python mystery.py", "b1"),
            _tc("web_search", "{}", "w1"),
        ]
        segments = _plan_tool_batch_segments(calls)
        # barrier first → then parallel run of remaining is < 2 calls → sequential merge
        assert "parallel" not in _kinds(segments)
        assert _ids(segments) == ["b1", "w1"]

    def test_mixed_write_in_middle_splits(self):
        calls = [
            _term("rg -n a file", "r1"),
            _term("sed -i s/a/b/ file", "w1"),
            _term("rg -n b file", "r2"),
        ]
        segments = _plan_tool_batch_segments(calls)
        assert _ids(segments) == ["r1", "w1", "r2"]
        # r1 parallel-safe alone? single-call run demoted to sequential;
        # w1 barrier; r2 single run demoted. Never crosses the barrier.
        for k, calls_seg in segments:
            assert all(
                tc.id in {"r1", "w1", "r2"} for tc in calls_seg
            )


# ---------------------------------------------------------------------------
# VAL-PT-3 — wire parallel_tool_calls
# ---------------------------------------------------------------------------

class TestWireParallelToolCalls:
    def _resolve(self, provider, model):
        from agent.transports.chat_completions import _parallel_tool_calls_for
        return _parallel_tool_calls_for(provider=provider, model=model)

    def test_inco_safe(self):
        assert self._resolve("custom:inco", "glm-5.3-flash:fast") is True

    def test_unknown_provider_absent(self):
        assert self._resolve(None, None) is None
        assert self._resolve("mystery", "mystery") is None

    def test_denylisted_provider_absent(self):
        assert self._resolve("anthropic", "claude-x") is None


# ---------------------------------------------------------------------------
# VAL-PT-4 — LocalEnvironment cwd snapshot under concurrency (source pin)
# ---------------------------------------------------------------------------

class TestLocalEnvCwdSnapshot:
    def test_run_bash_reads_cwd_before_popen(self, tmp_path):
        """The Popen call must capture cwd at call time (arg, not attribute read)."""
        import inspect
        import importlib
        from tools.environments import local as local_mod
        # Fresh reload: earlier tests monkey-patch _run_bash on the class without
        # restoring; inspect.getsource must see the REAL implementation.
        local_mod = importlib.reload(local_mod)
        src = inspect.getsource(local_mod.LocalEnvironment._run_bash)
        assert "self.cwd" in src  # reads it into safe_cwd/_popen_cwd local before Popen
        # the Popen call must use the local snapshot, not re-read self.cwd
        popen_call = src[src.find("proc = subprocess.Popen"):]
        assert "_popen_cwd" in popen_call[:400], popen_call[:200]
