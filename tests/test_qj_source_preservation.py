"""Local source-integrity regression checks for this ingestion task."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

WORK=Path(__file__).resolve().parents[1]/'data/imports/qj_2021_2025'


@unittest.skipUnless((WORK/'correction_support.py').exists(),'local ingestion source not present')
class SourcePreservationTests(unittest.TestCase):
    def test_all_original_question_fields_are_restored(self):
        original={p['source_item_id']:p for p in json.loads((WORK/'source_payload_before_corrections.json').read_text(encoding='utf8'))}
        current=json.loads((WORK/'visual_payloads.json').read_text(encoding='utf8'))
        self.assertEqual(len(current),416)
        for row in current:
            for field in ['stem_tex','choices','question_type_id']:
                self.assertEqual(row[field],original[row['source_item_id']][field],(row['source_item_id'],field))

    def test_active_corrections_allow_only_answers_and_analysis(self):
        sys.path.insert(0,str(WORK))
        self.addCleanup(lambda:sys.path.remove(str(WORK)))
        spec=importlib.util.spec_from_file_location('qj_source_guard',WORK/'correction_support.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        entries=module.load_corrections()
        self.assertEqual(len(entries),92)
        for key,value in entries.items():
            fields=value['fields']
            self.assertTrue(set(fields)<={'answer_tex','solution_tex','append_solution','prepend_solution','replacements'},key)
            self.assertTrue(all(r[0] in {'answer_tex','solution_tex'} for r in fields.get('replacements',[])),key)


if __name__=='__main__':unittest.main()
