"""Lightweight validation for a manually transcribed paper source module."""
from __future__ import annotations
import argparse, importlib.util, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('module'); ap.add_argument('--expected', type=int, required=True)
    args = ap.parse_args(); path = Path(args.module)
    spec = importlib.util.spec_from_file_location('paper_source', path); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    rows = list(mod.ROWS); errors=[]; figures=0
    if [r['number'] for r in rows] != list(range(1,args.expected+1)): errors.append('question_number_coverage')
    for row in rows:
        if row['question_type_id'] in (1,2) and len(row['choices']) != 4: errors.append(f"q{row['number']}:choice_count")
        for text in [row['stem_tex'], *row['choices']]:
            if text.count('$') % 2: errors.append(f"q{row['number']}:odd_dollar")
            if re.search(r'(?<!\\)\b(sin|cos|tan|log|ln)\b', text): errors.append(f"q{row['number']}:plain_function")
        figures += len(row.get('figures', ()))
    result={'status':'ok' if not errors else 'blocked','paper':mod.PAPER,'questions':len(rows),'figures':figures,'errors':sorted(set(errors))}
    print(json.dumps(result,ensure_ascii=False)); return 0 if not errors else 1
if __name__=='__main__': raise SystemExit(main())
