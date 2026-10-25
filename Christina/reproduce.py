"""Build a narrow demonstration from a pinned ComfyUI checkout and measure it.

Usage: python reproduce.py --source /path/to/ComfyUI
Dependencies: requirements.txt. No model downloads or inference are performed.
"""
import argparse
import ast
import difflib
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import textwrap
from datetime import datetime, timezone

from radon.complexity import cc_visit
from radon.metrics import mi_visit
from radon.raw import analyze

BASE = 'c194dd00cd42aa18d9dbf27d977bf6b85d9ea565'
ROOT = Path(__file__).resolve().parent


def build(source):
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'detect_unet_config')
    branches = [(n, name) for n in function.body if isinstance(n, ast.If)
                for signature, name in [
                    ('joint_blocks.0.context_block.attn.qkv.weight', '_detect_mmdit_config'),
                    ('clf.1.weight', '_detect_cascade_config')]
                if signature in ast.unparse(n.test)]
    assert len(branches) == 2
    helpers = []
    for node, name in branches:
        body = ''.join(lines[node.body[0].lineno - 1:node.end_lineno])
        helpers.append('def ' + name + '(state_dict, key_prefix, state_dict_keys):\n'
                       + textwrap.indent(textwrap.dedent(body), '    ') + '\n')
    for node, name in reversed(branches):
        lines[node.body[0].lineno - 1:node.end_lineno] = [
            '        return ' + name + '(state_dict, key_prefix, state_dict_keys)\n']
    result = ''.join(lines)
    result = result.replace('def detect_unet_config(', ''.join(helpers) + 'def detect_unet_config(', 1)
    assert result.count('suffix_list=[]') == 1
    return result.replace('suffix_list=[]', 'suffix_list=()', 1)


def measure(path):
    source = path.read_text(encoding='utf-8')
    blocks = cc_visit(source)
    names = ['detect_unet_config', '_detect_mmdit_config', '_detect_cascade_config', 'any_suffix_in']
    result = {b.name: b.complexity for b in blocks if b.name in names}
    lint = subprocess.run([sys.executable, '-m', 'ruff', 'check', str(path),
                           '--isolated', '--select', 'B006', '--output-format', 'json'],
                          capture_output=True, text=True)
    if lint.returncode not in (0, 1):
        raise RuntimeError(lint.stderr)
    return {'cc': result, 'module_mi': mi_visit(source, multi=True),
            'module_sloc': analyze(source).sloc, 'B006': len(json.loads(lint.stdout)),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    args = parser.parse_args()
    checkout = Path(args.source).resolve()
    revision = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != BASE:
        raise SystemExit('Checkout must be at ' + BASE)
    raw = subprocess.check_output(['git', '-C', str(checkout), 'show', BASE + ':comfy/model_detection.py'])
    source = raw.decode('utf-8')
    after = build(source)
    for name, content in [('before', source), ('after', after)]:
        destination = ROOT / name / 'comfy' / 'model_detection.py'
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content.encode('utf-8'))
    patch = ''.join(difflib.unified_diff(source.splitlines(True), after.splitlines(True),
                    fromfile='a/comfy/model_detection.py', tofile='b/comfy/model_detection.py'))
    (ROOT / 'improvement.patch').write_bytes(patch.encode('utf-8'))
    tests = subprocess.run([sys.executable, '-m', 'unittest', '-v', 'test_quality_demo'],
                           cwd=ROOT, capture_output=True, text=True)
    (ROOT / 'test_results.txt').write_text(tests.stdout + tests.stderr, encoding='utf-8')
    if tests.returncode:
        raise SystemExit(tests.stderr)
    result = {'baseline_commit': BASE, 'measurement_utc': datetime.now(timezone.utc).isoformat(),
              'python': platform.python_version(), 'platform': platform.platform(),
              'tools': {x: importlib.metadata.version(x) for x in ['radon', 'ruff']},
              'scope': 'complete comfy/model_detection.py; extracted-function tests only',
              'before': measure(ROOT / 'before/comfy/model_detection.py'),
              'after': measure(ROOT / 'after/comfy/model_detection.py')}
    (ROOT / 'measurement.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
