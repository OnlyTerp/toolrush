"""VAL-D3: full model-call path (handle_function_call) vs raw dispatch."""
import json
import statistics
import sys
import time

sys.path.insert(0, "C:/dev/AppData/Local/hermes/hermes-agent")
from tools.registry import registry, ToolEntry  # noqa: E402

FIXED = "toolrush-noop-ok"


def _noop(args, **kw):
    return FIXED


registry._tools["toolrush_noop"] = ToolEntry(
    name="toolrush_noop", toolset="toolrush",
    schema={"name": "toolrush_noop", "description": "noop", "parameters": {}},
    handler=_noop, check_fn=None, requires_env=[], is_async=False,
    description="noop", emoji="⚡",
)
from model_tools import handle_function_call  # noqa: E402

r = handle_function_call(
    function_name="toolrush_noop", function_args={},
    task_id="d3-warm", tool_call_id="d3-w", session_id="d3-s",
)
assert FIXED in str(r), f"full path wrong: {str(r)[:200]}"
print("full path OK", flush=True)

N = 15


def med(fn):
    ts = sorted(
        (lambda t0: (fn(), (time.perf_counter() - t0) * 1000)[1])(time.perf_counter())
        for _ in range(N)
    )
    return round(statistics.median(ts), 3), round(ts[int(len(ts) * 0.9)], 3)


disp_m, disp_p90 = med(lambda: registry.dispatch("toolrush_noop", {}, task_id="d3-x"))
full_m, full_p90 = med(lambda: handle_function_call(
    function_name="toolrush_noop", function_args={},
    task_id="d3-x", tool_call_id="d3-c", session_id="d3-s",
))
out = {
    "dispatch_ms": {"median": disp_m, "p90": disp_p90},
    "full_path_ms": {"median": full_m, "p90": full_p90},
    "pipeline_tax_ms": round(full_m - disp_m, 3),
}
print(json.dumps(out, indent=2))
open("C:/dev/toolrush/dispatch_full.json", "w").write(json.dumps(out, indent=2))
print("DISPATCH-D3-OK")
