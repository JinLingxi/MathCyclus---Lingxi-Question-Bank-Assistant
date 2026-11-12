"""Record unfinished source work separately from compilation/browser checks."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
for year in (2017,2016,2015):
    work=ROOT/f'data/imports/codex_{year}_restart'
    payload_path=work/'visual_payloads.json'
    if not payload_path.exists():
        continue
    payloads=json.loads(payload_path.read_text(encoding='utf8'))
    inventory_path=work/'source_inventory.json'
    inventory=json.loads(inventory_path.read_text(encoding='utf8')) if inventory_path.exists() else []
    covered={item['extra']['detected_source'] for item in payloads}
    missing_papers=[entry[0][5:] for entry in inventory if entry[0][5:] not in covered]
    previous_audit_path=work/'source_quality_audit.json'
    previous_audit=json.loads(previous_audit_path.read_text(encoding='utf8')) if previous_audit_path.exists() else {}
    payload_sha=hashlib.sha256(payload_path.read_bytes()).hexdigest()
    if previous_audit.get('status')=='passed' and previous_audit.get('payload_sha256')==payload_sha:
        print(json.dumps(dict(year=year,status='passed',pending_questions=0)))
        continue
    pending=[]
    for item in payloads:
        reasons=[]
        if r'\detokenize' in item['stem_tex'] or 'OCR source' in item['tags']:
            reasons.append('Original-page mathematical TeX transcription incomplete')
        if not item['extra'].get('visual_source_compared'):
            reasons.append('Original-page comparison is not recorded')
        if reasons:
            pending.append(dict(source_item_id=item['source_item_id'],source_label=item['source_label'],reasons=reasons))
    audit=dict(year=year,status='pending' if pending or missing_papers else 'requires_final_visual_audit',
        payload_sha256=payload_sha,
        pending_questions=pending,
        missing_papers=missing_papers,
        note='Compilation and browser text equality do not establish source completeness or crop correctness.')
    (work/'source_quality_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
    report_path=ROOT/f'reports/{year}_retranscription_checks.json'
    if report_path.exists():
        report=json.loads(report_path.read_text(encoding='utf8'))
        report.update(status='pending_source_quality_audit',source_quality_audit=audit,
            browser_checks_current=False)
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(year=year,pending_questions=len(pending))))
