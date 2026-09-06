"""Verify the v2 release manifest on Windows and POSIX checkouts."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'MANIFEST.json'
TEXT_SUFFIXES = {'.py', '.json', '.md', '.yaml', '.yml', '.xml'}

def canonical_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        data = data.replace(b'\r\n', b'\n')
    return data

manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
actual = {}
for path in ROOT.rglob('*'):
    if path.is_file() and path.name != 'MANIFEST.json':
        rel = path.relative_to(ROOT).as_posix()
        data = canonical_bytes(path)
        actual[rel] = {
            'sha256': hashlib.sha256(data).hexdigest(),
            'bytes': len(data),
        }
assert set(actual) == set(manifest), {
    'missing': sorted(set(manifest) - set(actual)),
    'extra': sorted(set(actual) - set(manifest)),
}
for name, expected in manifest.items():
    assert actual[name] == expected, (name, expected, actual[name])
print(json.dumps({'verified': True, 'files': len(actual), 'root': str(ROOT)}, indent=2))
