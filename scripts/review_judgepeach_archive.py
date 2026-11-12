"""Offline, non-DB smoke review of the supplied third-party source snapshot."""
from pathlib import Path
import ast
from dataclasses import asdict
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import warnings

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'reports/external_review/judgepeach/math-question-bank-main'
sys.dont_write_bytecode = True
sys.path.insert(0, str(VENDOR))
checks = []

def record(name, action):
    try:
        detail = action()
        checks.append(dict(name=name, status='passed', detail=detail))
    except Exception as exc:
        checks.append(dict(name=name, status='failed', error=f'{type(exc).__name__}: {exc}'))

def python_syntax():
    files = sorted(VENDOR.rglob('*.py'))
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', SyntaxWarning)
        for path in files:
            ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    return {'files': len(files), 'execution': False}

def javascript_syntax():
    node = shutil.which('node')
    assert node, 'Node executable unavailable'
    files = sorted((VENDOR/'static/js').glob('*.js'))
    for path in files:
        result = subprocess.run([node, '--check', str(path)], capture_output=True,
                                text=True, encoding='utf8', timeout=30)
        assert result.returncode == 0, f'{path.name}: {result.stderr[:500]}'
    return {'files': len(files), 'browser_execution': False}

record('python_syntax', python_syntax)
record('javascript_syntax', javascript_syntax)

from mathbank.question_duplicates import compare_questions
from mathbank.source_review_results import parse_review_response
from mathbank.import_review import make_source_review_advisory
from mathbank.task_manager import TaskManager

def duplicate_case(left, right, expected, reason=None):
    result = compare_questions({'content': left}, {'content': right})
    assert result.classification == expected, result
    assert result.auto_merge_allowed is False
    if reason:
        assert reason in result.reasons, result
    return asdict(result)

record('duplicate_identical_text', lambda: duplicate_case('已知 $x=1$，求值。', '已知 $x=1$，求值。', 'exact'))
record('duplicate_fraction_presentation', lambda: duplicate_case(r'求 $\dfrac{1}{2}$。', r'求 $\frac{1}{2}$。', 'exact'))
base = r'对任意 $x\in[0,1)$，都有 $x<2$。'
for name, value, reason in [
    ('number', r'对任意 $x\in[0,1)$，都有 $x<3$。', 'NUMBER_CHANGED'),
    ('variable', r'对任意 $y\in[0,1)$，都有 $y<2$。', 'VARIABLE_CHANGED'),
    ('relation', r'对任意 $x\in[0,1)$，都有 $x\le2$。', 'RELATION_CHANGED'),
    ('quantifier', r'存在 $x\in[0,1)$，都有 $x<2$。', 'QUANTIFIER_CHANGED'),
    ('interval', r'对任意 $x\in(0,1)$，都有 $x<2$。', 'MATH_STRUCTURE_CHANGED'),
]:
    record('duplicate_changed_'+name, lambda value=value, reason=reason: duplicate_case(base, value, 'possible_variant', reason))

def visual_missing():
    result = compare_questions({'content': '如图求值。\n![](a.png)'},
                               {'content': '如图求值。\n![](b.png)'})
    assert result.classification == 'probable' and result.needs_visual_review
    return asdict(result)
record('duplicate_without_pixel_evidence', visual_missing)

def json_valid():
    assert parse_review_response('```json\n{"items":[]}\n```') == {'items': []}
    return 'complete JSON fence accepted'
record('visual_evidence_valid_json', json_valid)

def json_reject(raw):
    try:
        parse_review_response(raw)
    except ValueError:
        return 'rejected as expected'
    raise AssertionError('Invalid evidence accepted')
for name, raw in [('truncated','{"items":['), ('duplicate_keys','{"items":[],"items":[1]}'),
                  ('nan','{"value":NaN}'), ('prefixed','explanation {"items":[]}')]:
    record('visual_evidence_rejects_'+name, lambda raw=raw: json_reject(raw))

def advisory_policy():
    questions = [{'source_review': {'required': True, 'blocking': True}}]
    diagnostics = {}
    make_source_review_advisory(questions, diagnostics)
    assert questions[0]['source_review']['required'] is True
    assert questions[0]['source_review']['blocking'] is False
    assert diagnostics['source_review_blocking_count'] == 0
    return {'questions': questions, 'diagnostics': diagnostics}
record('source_review_is_advisory_not_import_gate', advisory_policy)

def task_terminal_state():
    manager = TaskManager(max_workers=1, max_queue=0)
    try:
        manager.create('review-smoke')
        manager.cancel('review-smoke')
        assert manager.complete('review-smoke', data='late result') is False
        assert manager.snapshot('review-smoke')['status'] == 'cancelled'
        return 'cancelled task cannot be overwritten by late completion'
    finally:
        manager.shutdown(wait=True)
record('cancelled_task_stays_cancelled', task_terminal_state)

result = {
    'scope': 'Supplied ZIP snapshot only; no network, model calls, installation, server startup or application database access.',
    'snapshot_version': '3.0.2',
    'snapshot_readme_sha256': hashlib.sha256((VENDOR/'README.md').read_bytes()).hexdigest(),
    'source_counts': {'backend_modules': len(list((VENDOR/'mathbank').glob('*.py'))),
                      'test_modules': len(list((VENDOR/'tests').glob('test_*.py')))},
    'checks': checks,
    'passed': sum(c['status']=='passed' for c in checks),
    'failed': sum(c['status']=='failed' for c in checks),
    'not_verified': ['Full pytest suite: pytest, FastAPI, SQLAlchemy and other runtime dependencies absent in current venv.',
                     'Live browser layout, full server API flows, native Word/PDF exports and paid OCR/model quality.',
                     'Remote GitHub branch, commit, release status and current dependency/model availability.'],
}
out = ROOT/'reports/external_review/judgepeach_review_checks.json'
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
print(json.dumps(result, ensure_ascii=True, indent=2))
raise SystemExit(bool(result['failed']))
