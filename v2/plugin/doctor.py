"""Read-only ToolRush installed integrity and compatibility check. No models."""
import argparse
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys

P = Path(__file__).parent
parser = argparse.ArgumentParser()
parser.add_argument('--smoke', action='store_true')
parser.add_argument('--hermes-root', type=Path, default=None,
                    help='Hermes source/install root; auto-detected when omitted')
args = parser.parse_args()


def resolve_hermes_root() -> Path:
    candidates = []
    if args.hermes_root is not None:
        candidates.append(args.hermes_root)
    env_root = os.environ.get('HERMES_AGENT_ROOT')
    if env_root:
        candidates.append(Path(env_root))
    candidates.append(P.parent.parent / 'hermes-agent')
    try:
        spec = importlib.util.find_spec('hermes_cli')
    except (ImportError, ModuleNotFoundError):
        spec = None
    if spec is not None and spec.origin:
        candidates.append(Path(spec.origin).resolve().parents[1])
    for candidate in candidates:
        candidate = candidate.expanduser().resolve()
        if (candidate / 'hermes_cli').exists() or (candidate / 'tools').exists():
            return candidate
    raise SystemExit(
        'Hermes root not found; pass --hermes-root or set HERMES_AGENT_ROOT'
    )


R = resolve_hermes_root()
sys.path.insert(0, str(R))
s = importlib.util.spec_from_file_location(
    'toolrush_doctor_compat', P / 'compat.py'
)
c = importlib.util.module_from_spec(s)
s.loader.exec_module(c)
payload = json.loads((P / 'payload.json').read_text(encoding='utf-8'))
result = {
    'hermes_root': str(R),
    'payload': {},
    'lanes': {},
    'restart_note': 'This fresh-process check does not activate already-running gateways.',
}
try:
    for name, row in payload['helpers'].items():
        c.verify_blob((P / row['file']).read_bytes(), row['sha256'])
        result['payload'][name] = 'verified'
    for lane, rows in payload['lanes'].items():
        try:
            result['lanes'][lane] = {
                'status': 'compatible',
                'pending_function_patches': len(c.prepare_rows(rows)),
            }
        except Exception as exc:
            result['lanes'][lane] = {'status': 'degraded', 'reason': str(exc)}
    if args.smoke:
        from hermes_cli.plugins import PluginManager, PluginManifest
        manager = PluginManager()
        manager._load_plugin(PluginManifest(
            name='toolrush', version='2.0.0', source='user',
            path=str(P), key='toolrush'
        ))
        loaded = manager._plugins['toolrush']
        assert loaded.enabled and not loaded.error, loaded.error
        status = loaded.module._COMPAT_STATUS
        result['boot'] = status
        if status.get('rpc', {}).get('status') == 'ready':
            from tools.code_execution_tool import execute_code
            from tools.code_kernel import shutdown_all_kernels
            code = (
                'from hermes_tools import parallel\n'
                'r = parallel('
                + repr([{
                    'tool': 'read_file',
                    'args': {'path': str(R / f), 'limit': 4},
                } for f in ['tools/file_tools.py', 'tools/file_operations.py']])
                + ')\nassert len(r) == 2 and all("content" in x for x in r), r\n'
                  'print("TOOLRUSH-DOCTOR-OK")'
            )
            try:
                output = json.loads(execute_code(
                    code, task_id='toolrush-doctor', enabled_tools=['read_file']
                ))
                result['smoke'] = {
                    'exit_code': output.get('exit_code'),
                    'output': output.get('output'),
                    'tool_calls': output.get('tool_calls_made'),
                }
                assert output.get('exit_code') == 0 and output.get('tool_calls_made') == 2, output
            finally:
                shutdown_all_kernels()
        else:
            result['smoke'] = {'status': 'skipped', 'reason': 'rpc lane is not compatible'}
    result['ok'] = all(
        value['status'] == 'compatible' for value in result['lanes'].values()
    )
except Exception as exc:
    result['ok'] = False
    result['error'] = str(exc)
print(json.dumps(result, indent=2))
sys.exit(0 if result['ok'] else 2)
