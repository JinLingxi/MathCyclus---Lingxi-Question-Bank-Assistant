"""Read-only source verification and warming of disposable review match caches."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contextlib import ExitStack
import json
from time import perf_counter
from unittest.mock import patch

from services import question_similarity_service as scorer
from services import question_match_cache as cache
from services.import_service import find_question_content_matches

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'data/imports/qj_2021_2025'
DB = str(ROOT / 'data/mathcyclus.sqlite3')


def run(items):
    start = perf_counter()
    results = [find_question_content_matches(DB, p['stem_tex'], choices=p['choices'],
               question_type_id=p['question_type_id'], max_results=3) for p in items]
    return round(perf_counter() - start, 4), results


def main():
    sys.stdout.reconfigure(encoding='utf8')
    items = json.loads((WORK / 'visual_payloads.json').read_text(encoding='utf8'))
    expected = json.loads((WORK / 'duplicate_checks.json').read_text(encoding='utf8'))
    first = items[:7]
    # Reproduce the old full-scan path without changing rules or the database.
    with ExitStack() as stack:
        stack.enter_context(patch.object(cache, 'load_matches', return_value=None))
        stack.enter_context(patch.object(cache, 'store_matches'))
        for name in ['_prepared_payload', '_bigrams', '_exact_text_signature']:
            function = getattr(scorer, name)
            stack.enter_context(patch.object(scorer, name, function.__wrapped__))
        baseline, reference = run(first)
    print(json.dumps({'baseline_7_questions_seconds': baseline}), flush=True)
    cold, actual = run(first)
    assert actual == reference
    warm, repeated = run(first)
    assert repeated == reference
    print(json.dumps({'optimized_first_pass_seconds': cold, 'optimized_cached_seconds': warm}), flush=True)
    start = perf_counter()
    for i, item in enumerate(items, 1):
        _, result = run([item])
        assert result[0] == expected[item['source_item_id']]['similarity_candidates'][:3], item['source_item_id']
        if i % 25 == 0 or i == len(items):
            print(json.dumps({'verified_and_cached': i, 'total': len(items)}), flush=True)
    report = dict(status='ok',baseline_7_questions_seconds=baseline,
                  optimized_first_pass_seconds=cold,optimized_cached_seconds=warm,
                  results_identical_to_previous_checks=len(items),
                  cache_warm_seconds=round(perf_counter()-start, 3),
                  corpus_sha256=cache.corpus_snapshot(DB)[1])
    (WORK / 'review_performance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
