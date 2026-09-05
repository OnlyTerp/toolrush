"""VAL-SAFE-05 / reviewer B1: snapshot exclusion-refresh must fail CLOSED.

Regression coverage for the fail-open defect in
``BaseEnvironment._snapshot_excluded_passthrough_names``: the exclusion set
was computed inside ``try:`` and ANY failure (``is_multiplex_active()`` raising,
``tools.env_passthrough`` import/call failure) was swallowed to
``logger.debug``, returning whatever had accumulated — empty on the first
dump. The dump then ran unfiltered: ``export -p`` wrote the full child env,
including profile-scoped passthrough names (``BUZZ_*`` and configured
passthrough), into ``hermes-snap-<id>.sh``. A later command from a different
profile sharing the collapsed LocalEnvironment ``source``s that snapshot — a
cross-profile secret persist (see the BUZZ_* documentation in
``tools/environments/local.py``).

The monotonic exclusion design only protects when the refresh succeeds at
least once; fail-open on the first dump defeats it. Required behavior:

- a failed refresh latches a monotonic fail-closed marker on the environment
  while still returning the best-known (previously accumulated) set;
- while the marker is latched, ``init_session`` and the per-command re-dump
  SKIP generating ``export -p`` entirely, leaving the previous (already
  filtered) snapshot in place — a stale-but-filtered snapshot is safe, an
  unfiltered one is not;
- the dump helper belt-unsets known secret prefixes (``BUZZ_*``) even when
  the caller passes an empty exclusion set.
"""

import os
import shlex
import shutil
import subprocess
import sys

import pytest

from tools.environments.base import BaseEnvironment, _export_dump_excluding_session_vars

SNAP_SEED_VAR = "HERMES_SNAPSEED_TOKEN"
SNAP_SEED_VALUE = "seed1"
PROBE_SECRET = "nsec1fastrabbit-not-a-real-key"


def _boom(*args, **kwargs):
    raise RuntimeError("injected exclusion-refresh failure")


def _to_msys_path(path: str) -> str:
    """Native Windows path → git-bash ``/c/...`` form (no-op on POSIX)."""
    p = path.replace("\\", "/")
    if len(p) > 2 and p[1] == ":":
        p = f"/{p[0].lower()}{p[2:]}"
    return p


def _bash_exe() -> str:
    """Resolve git-bash exactly like LocalEnvironment does.

    ``shutil.which("bash")`` alone resolves the WSL stub on Windows hosts
    with WSL installed, which fails with a cryptic exit 1 — production code
    uses ``_find_bash`` for the same reason.
    """
    from tools.environments.local import _find_bash

    return _find_bash()


class _StubBashEnv(BaseEnvironment):
    """Minimal concrete BaseEnvironment that really runs bash.

    Keeps BaseEnvironment's own snapshot machinery (init_session bootstrap,
    _wrap_command re-dump) under test against a REAL bash and a real snapshot
    file in tmp_path. ``__new__(...)`` instances skip ``__init__`` so the
    exclusion-set unit tests need no backend plumbing at all.
    """

    is_local = False
    _profile_scoped_passthrough = True
    _additional_names: tuple = ()

    def _additional_profile_scoped_passthrough_names(self):
        return tuple(self._additional_names)

    def _quote_shell_path(self, path: str) -> str:
        # Mirror LocalEnvironment's native→MSYS rewrite; base's plain
        # shlex.quote would feed git-bash an unusable native path.
        return shlex.quote(_to_msys_path(path))

    def _run_bash(self, cmd_string, *, login=False, timeout=120, stdin_data=None):
        # Deliberately ignore login: the stub exercises the snapshot *script*
        # machinery, not login-shell profile loading.
        popen_kwargs = {}
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        else:
            popen_kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        return subprocess.Popen(
            [_bash_exe(), "-c", cmd_string],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=os.environ.copy(),
            cwd=os.getcwd(),
            **popen_kwargs,
        )

    def cleanup(self):
        return None


def _new_stub(additional_names=()):
    env = _StubBashEnv.__new__(_StubBashEnv)
    env._additional_names = tuple(additional_names)
    env._snapshot_passthrough_names = set()
    return env


def _seed_snapshot(env):
    """Write a known-good (filtered) snapshot file containing a marker var."""
    seeded = f"export {SNAP_SEED_VAR}={SNAP_SEED_VALUE}\n"
    with open(env._snapshot_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(seeded)
    return seeded


def _snap_text(env):
    with open(env._snapshot_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Exclusion-refresh failure must latch the fail-closed marker, not fail open.
# ---------------------------------------------------------------------------


class TestExclusionRefreshFailClosed:
    def test_refresh_error_keeps_previous_set_and_latches_broken(self):
        """A mid-refresh failure must not return an empty set: the monotonic
        set accumulated so far is still the best-known exclusion set, and the
        environment must be marked so dump sites skip unfiltered dumps."""
        from agent import secret_scope as ss

        env = _new_stub(("BUZZ_PREVIOUS_PROFILE",))
        env._snapshot_passthrough_names.add("BUZZ_PREVIOUS_PROFILE")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ss, "is_multiplex_active", _boom)
            excluded = env._snapshot_excluded_passthrough_names()

        # Fail closed: previously accumulated names still reported...
        assert excluded == ("BUZZ_PREVIOUS_PROFILE",)
        # ...and the environment is latched so dump sites skip the dump.
        assert getattr(env, "_snapshot_exclusion_broken", False) is True

    def test_passthrough_call_failure_also_latches_broken(self):
        """tools.env_passthrough get_all_passthrough() failure is the same
        fail-open edge (B1 named the import/call failure explicitly) and must
        must latch the marker too."""
        import tools.env_passthrough as ep
        from agent import secret_scope as ss

        env = _new_stub(("BUZZ_PREVIOUS_PROFILE",))
        env._snapshot_passthrough_names.add("BUZZ_PREVIOUS_PROFILE")

        ss.set_multiplex_active(True)
        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(ep, "get_all_passthrough", _boom)
                excluded = env._snapshot_excluded_passthrough_names()
        finally:
            ss.set_multiplex_active(False)

        assert excluded == ("BUZZ_PREVIOUS_PROFILE",)
        assert getattr(env, "_snapshot_exclusion_broken", False) is True

    def test_first_dump_failure_latches_broken(self):
        """The B1 edge itself: failure on the FIRST dump (empty accumulated
        set) must latch the marker — returning () is only safe because the
        dump sites now refuse to dump while latched."""
        from agent import secret_scope as ss

        env = _new_stub(("BUZZ_MANAGED_AGENT",))

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ss, "is_multiplex_active", _boom)
            excluded = env._snapshot_excluded_passthrough_names()

        assert excluded == ()
        assert getattr(env, "_snapshot_exclusion_broken", False) is True

    def test_healthy_refresh_does_not_latch_broken(self, monkeypatch):
        from agent import secret_scope as ss

        monkeypatch.setenv("BUZZ_MANAGED_AGENT", "1")
        env = _new_stub(("BUZZ_MANAGED_AGENT",))

        ss.set_multiplex_active(True)
        try:
            excluded = env._snapshot_excluded_passthrough_names()
        finally:
            ss.set_multiplex_active(False)

        assert "BUZZ_MANAGED_AGENT" in excluded
        assert getattr(env, "_snapshot_exclusion_broken", False) is False

    def test_broken_marker_is_monotonic_after_recovery(self):
        """Once latched, a later healthy refresh must NOT unlatch: the dump
        sites keep refusing until the environment is recycled. (A marker a
        flapping refresh could clear would re-open the B1 window.)"""
        from agent import secret_scope as ss

        env = _new_stub(("BUZZ_MANAGED_AGENT",))

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ss, "is_multiplex_active", _boom)
            env._snapshot_excluded_passthrough_names()
        assert getattr(env, "_snapshot_exclusion_broken", False) is True

        ss.set_multiplex_active(True)
        try:
            env._snapshot_excluded_passthrough_names()
        finally:
            ss.set_multiplex_active(False)

        assert getattr(env, "_snapshot_exclusion_broken", False) is True


# ---------------------------------------------------------------------------
# While latched, dump sites must SKIP generating export -p (fail closed).
# ---------------------------------------------------------------------------


class TestSnapshotDumpFailClosed:
    def test_init_session_skips_dump_when_exclusion_refresh_broken(
        self, tmp_path
    ):
        """Bootstrap with a latched refresh must NOT overwrite the previous
        good snapshot with an unfiltered env dump (BUZZ_* from the child env
        would persist cross-profile)."""
        from agent import secret_scope as ss

        env = _StubBashEnv.__new__(_StubBashEnv)
        env._additional_names = ("BUZZ_PROBE_TOKEN",)
        env._snapshot_passthrough_names = set()
        env._profile_scoped_passthrough = True
        BaseEnvironment.__init__(
            env, cwd="~", timeout=30, env={}
        )
        env._snapshot_path = str(tmp_path / "hermes-snap-test.sh")
        seeded = _seed_snapshot(env)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ss, "is_multiplex_active", _boom)
            env.init_session()

        text = _snap_text(env)
        # The previously filtered snapshot is left in place...
        assert seeded in text
        # ...and no unfiltered dump (which would carry the probe secret)
        # replaced it.
        assert "BUZZ_PROBE_TOKEN" not in text

    def test_init_session_dumps_when_refresh_healthy(self, tmp_path):
        """Control: with a healthy refresh the bootstrap dumps normally (the
        seeded marker is gone because the dump re-captured the live env)."""
        env = _StubBashEnv.__new__(_StubBashEnv)
        env._additional_names = ()
        env._snapshot_passthrough_names = set()
        env._profile_scoped_passthrough = True
        BaseEnvironment.__init__(env, cwd="~", timeout=30, env={})
        env._snapshot_path = str(tmp_path / "hermes-snap-test.sh")
        _seed_snapshot(env)

        env.init_session()

        text = _snap_text(env)
        assert SNAP_SEED_VAR not in text

    def test_wrap_command_skips_redump_when_exclusion_refresh_broken(
        self, tmp_path
    ):
        """Per-command re-dump with a latched refresh must not emit the
        mktemp/export-p/mv sequence that would overwrite the snapshot with
        the (unfiltered) child env."""
        from agent import secret_scope as ss

        env = _new_stub(("BUZZ_PREVIOUS_PROFILE",))
        env._snapshot_ready = True
        env._session_id = "testsnapfail"
        env._cwd_marker = "__HERMES_CWD_testsnapfail__"
        env._snapshot_path = str(tmp_path / "hermes-snap-test.sh")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ss, "is_multiplex_active", _boom)
            wrapped = env._wrap_command("true", "/tmp")

        assert "export -p" not in wrapped
        assert "mktemp" not in wrapped

    def test_wrap_command_keeps_redump_when_healthy(self, tmp_path):
        """Control: the re-dump sequence must survive for healthy refreshes
        (session-continuity of env vars is a feature; only the broken case
        skips it)."""
        env = _new_stub(())
        env._snapshot_ready = True
        env._session_id = "testsnapok"
        env._cwd_marker = "__HERMES_CWD_testsnapok__"
        env._snapshot_path = str(tmp_path / "hermes-snap-test.sh")

        wrapped = env._wrap_command("true", "/tmp")

        assert "export -p" in wrapped
        assert "mktemp" in wrapped


# ---------------------------------------------------------------------------
# Belt: the dump unsets known secret prefixes even with an empty set.
# ---------------------------------------------------------------------------


class TestSnapshotBeltUnset:
    def test_belt_unsets_known_secret_prefixes_even_with_empty_set(
        self, monkeypatch, tmp_path
    ):
        """If a caller forgets the exclusion set, the dump must still refuse
        to persist BUZZ_* names — a cheap second line of defense behind the
        fail-closed latch."""
        monkeypatch.setenv("BUZZ_TEST_TOKEN", PROBE_SECRET)
        monkeypatch.setenv("HAPPY_UNRELATED", "fine-to-persist")

        out_path = tmp_path / "belt-snap.sh"
        dump = _export_dump_excluding_session_vars(
            shlex.quote(_to_msys_path(str(out_path))), ()
        )
        subprocess.run(
            [_bash_exe(), "-c", dump],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

        with open(out_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        assert "BUZZ_TEST_TOKEN" not in text
        assert PROBE_SECRET not in text
        # Ordinary session-continuity vars still persist by design.
        assert "HAPPY_UNRELATED" in text


# ---------------------------------------------------------------------------
# End-to-end: real bash snapshot file, injected refresh failure, two profiles.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="Windows git-bash lane")
class TestEndToEndFailClosed:
    def test_cross_profile_secret_never_persists_fail_closed(
        self, monkeypatch, tmp_path
    ):
        """Profile A (env carries BUZZ_TEST_TOKEN) runs the bootstrap AND a
        per-command re-dump while the exclusion refresh is latched broken:
        the snapshot file must never contain profile A's secret, i.e. profile
        B sharing this environment could never source it."""
        from agent import secret_scope as ss

        monkeypatch.setenv("BUZZ_TEST_TOKEN", PROBE_SECRET)
        env = _StubBashEnv.__new__(_StubBashEnv)
        env._additional_names = ("BUZZ_TEST_TOKEN",)
        env._snapshot_passthrough_names = set()
        env._profile_scoped_passthrough = True
        BaseEnvironment.__init__(env, cwd="~", timeout=30, env={})
        env._snapshot_path = str(tmp_path / "hermes-snap-test.sh")
        seeded = _seed_snapshot(env)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ss, "is_multiplex_active", _boom)
            env.init_session()
            # Simulate an environment whose snapshot was already created by a
            # healthy refresh earlier in its lifetime and whose refresh has
            # only NOW broken: the per-command re-dump must also skip.
            env._snapshot_ready = True
            wrapped = env._wrap_command("true", _to_msys_path(str(tmp_path)))
            subprocess.run(
                [_bash_exe(), "-c", wrapped],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
                env=os.environ.copy(),
                cwd=str(tmp_path),
            )

        text = _snap_text(env)
        assert seeded in text
        assert "BUZZ_TEST_TOKEN" not in text
        assert PROBE_SECRET not in text
