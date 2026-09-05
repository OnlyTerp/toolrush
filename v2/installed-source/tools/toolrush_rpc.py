"""ToolRush explicit read batches. Transport speed, never extra authority.

The operator's goal: 'bottleneck goes back to a models tokens per second and
not stupid tool calls, file lookups etc'. One authenticated RPC carries a
bounded batch; every member still uses the standard tool handler.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor

from agent.thread_scoped_output import thread_scoped_silence
from tools.thread_context import propagate_context_to_thread

READ_TOOLS = frozenset({'read_file', 'search_files', 'web_search', 'web_extract'})
MAX_BATCH = 16
MAX_WORKERS = 4


def _error(message):
    return json.dumps({'error': message})


def execute_read_batch(args, *, allowed_tools, counter, budget, log, dispatch, stop_event):
    """Called on the single serving thread: validation/reservation are atomic."""
    from tools.toolrush_runtime import enabled
    if not enabled('parallel_reads', 'TOOLRUSH_PARALLEL'):
        return _error('ToolRush parallel reads are disabled')
    calls = args.get('calls') if isinstance(args, dict) else None
    if not isinstance(calls, list) or not 1 <= len(calls) <= MAX_BATCH:
        return _error(f'parallel requires 1..{MAX_BATCH} read calls')
    for call in calls:
        if not isinstance(call, dict):
            return _error('Each parallel call must be a tool/args object')
        name = call.get('tool')
        if not isinstance(name, str) or name not in READ_TOOLS or name not in allowed_tools:
            return _error(f'Tool {name!r} is not an enabled parallel read tool')
        if not isinstance(call.get('args'), dict):
            return _error('Each parallel call requires an args object')
    if counter[0] + len(calls) > budget:
        return _error(f'Tool call limit reached ({budget}); entire batch refused')
    if stop_event.is_set():
        return _error('Tool batch interrupted before dispatch')
    # Bind a session kernel's cell once, before any worker can outlive it.
    # Its dispatch checks retirement for each member, including queued reads.
    if hasattr(dispatch, 'for_batch'):
        dispatch = dispatch.for_batch()
    counter[0] += len(calls)

    def invoke(call):
        start = time.monotonic()
        if stop_event.is_set():
            raw = _error('Tool batch interrupted')
        else:
            try:
                with thread_scoped_silence():
                    raw = dispatch(call['tool'], dict(call['args']))
            except Exception as exc:
                raw = _error(str(exc))
        try:
            result = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            result = raw
        # Match ordinary client decoding for double-encoded JSON results.
        if isinstance(result, str):
            try: result = json.loads(result)
            except (ValueError, TypeError): pass
        record = {'tool':call['tool'], 'args_preview':str(call['args'])[:80],
                  'duration':round(time.monotonic()-start, 3), 'batch':True}
        return result,record

    if len(calls) == 1:
        completed = [invoke(calls[0])]
    else:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS,len(calls)),
                                thread_name_prefix='toolrush-read') as pool:
            jobs = [pool.submit(propagate_context_to_thread(invoke),call) for call in calls]
            completed = [job.result() for job in jobs]
    # Counters and log are written only by the serving thread, input order.
    log.extend(record for result,record in completed)
    return json.dumps([result for result,record in completed], ensure_ascii=False)
