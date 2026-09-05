"""Safety/bounds tests drive the real ToolRush subprocess transport."""
import os
import sys
import threading
import time

import pytest
from tools import toolrush_rg as tr


def run(script, **kw):
    return tr.run_rg([sys.executable, '-c', script], cwd=os.getcwd(),
                     env=os.environ.copy(), max_lines=kw.pop('max_lines', 500), **kw)


def test_real_exit_code_not_inferred_from_silence():
    r = run('import sys; sys.exit(2)')
    assert r.exit_code == 2
    assert r.stdout == ''
    assert not r.limited


def test_no_match_exit_one_preserved():
    assert run('import sys; sys.exit(1)').exit_code == 1


def test_output_budget_bounds_giant_unterminated_line():
    r = run("import sys; sys.stdout.write('x'*1000000)", max_bytes=4096)
    assert len(r.stdout) <= 4096
    assert r.limited and r.reason == 'search_output_budget'


def test_line_budget():
    r = run("import sys; sys.stdout.write('x\\n'*10000)", max_lines=3)
    assert r.stdout == 'x\nx\nx\n'


def test_timeout_reaps_process():
    r = run('import time; time.sleep(20)', timeout=0.08)
    assert r.exit_code == 124
    assert r.reason == 'search_timeout'
    assert not any(t.name == 'toolrush-rg-output' for t in threading.enumerate())


def test_cancel_before_spawn(monkeypatch):
    monkeypatch.setattr(tr.interrupt, 'is_interrupted', lambda: True)
    monkeypatch.setattr(tr.subprocess, 'Popen', lambda *a, **kw: pytest.fail('spawned after cancel'))
    assert run('raise SystemExit(0)').exit_code == 130


def test_cancel_inflight_reaps(monkeypatch):
    start = time.monotonic()
    monkeypatch.setattr(tr.interrupt, 'is_interrupted', lambda: time.monotonic() - start > .1)
    r = run('import time; time.sleep(20)')
    assert r.exit_code == 130
    assert not any(t.name == 'toolrush-rg-output' for t in threading.enumerate())


def test_metacharacters_never_enter_shell(tmp_path):
    marker = tmp_path/'must-not-exist'
    # This argument is an inert Python value, not a shell redirection.
    r = tr.run_rg([sys.executable, '-c', 'import sys; print(sys.argv[1])',
                   f'; > {marker}'], cwd=str(tmp_path), env=os.environ.copy(), max_lines=5)
    assert r.exit_code == 0
    assert not marker.exists()
    assert '; >' in r.stdout
