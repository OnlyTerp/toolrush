"""Negative control: prove the contract tests FAIL when the fast lane is
disconnected (verification-integrity law).

Runs pytest.main in-process with a plugin that kills the fast lane the way
a regression would: config toolrush.fast_search=False AND the bridge
returning None. If the suite still passes, the tests are worthless.
"""
import sys
from pathlib import Path

HERMES = Path(r"C:/dev/AppData/Local/hermes/hermes-agent")
sys.path.insert(0, str(HERMES))
sys.path.insert(0, str(HERMES / "tests"))

import pytest


class KillLane:
    """Simulate lane-disconnected regression: bridge always returns None."""

    @staticmethod
    def pytest_configure(config):
        import tools.file_tools as ft
        ft._toolrush_fast_search = staticmethod(
            lambda *a, **kw: None
        )


def main() -> int:
    rc = pytest.main(
        ["tests/tools/test_toolrush_search.py", "-q", "-p", "no:cacheprovider"],
        plugins=[KillLane()],
    )
    print(f"NEGATIVE-CONTROL-EXIT={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
