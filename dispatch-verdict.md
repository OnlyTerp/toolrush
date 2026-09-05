# VAL-D4 verdict: dispatch pipeline — measured, STOP here (no theater)

## Numbers (all REAL paths, trivial noop handler, N=15-25)

| layer | median | notes |
|---|---|---|
| raw handler call | 0.000ms | direct `_noop()` |
| registry.dispatch | 0.005ms | entry lookup + handler + normalize |
| full model-call path (`handle_function_call`) | 4.444ms | pre-hooks + edit approval + middleware + dispatch + post-hooks |
| **pipeline tax** | **4.44ms** | full minus dispatch |

## Why STOP is the honest verdict

1. Absolute scale: 4.44ms against post-toolrush handlers (read 1.18ms,
   terminal 12.1ms, search 42ms) and model round-trips (seconds). A
   heroic 3x pipeline win would save ~3ms/call — unmeasurable in any
   real session. Optimizing it is theater by our own contract's definition.
2. What the 4.44ms BUYS (profiled): plugin pre/post hooks, ACP edit
   approval, tool request+execution middleware, observability context,
   read-loop tracker notify. This is the SAFETY machinery — approval
   gates and audit hooks. Trimming it trades safety for single-digit ms.
3. The registry itself (0.005ms) is already three orders below the
   fastest handler. There is nothing left to kill here.

## What this means for the standing goal

Per-handler waves (1-3) removed 99%+ of tool-call latency. The remaining
dispatch pipeline is 4.44ms of load-bearing safety rails. The bottleneck
for local tool work is now: model TPS >> 4ms pipeline >> 1-42ms handlers.
Tool-call latency as a class is DONE for local backends. What remains is
porting the three lab prototypes into the live tree behind kill-switches —
Operator's call, not more lab work.

VAL-D4: DONE (documented stop with numbers).
