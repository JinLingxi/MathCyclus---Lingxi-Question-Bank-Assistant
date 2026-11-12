import sqlite3,unittest
from scripts.pep_a_required1_pipeline import append_preserving_current

class TextbookAppendConcurrencyTests(unittest.TestCase):
    def test_user_changes_between_stage_and_apply_are_preserved(self):
        db=sqlite3.connect(':memory:')
        db.executescript('''CREATE TABLE question(question_id TEXT PRIMARY KEY,stem TEXT);
          CREATE TABLE import_batch(batch_id TEXT PRIMARY KEY);
          CREATE TABLE question_import_draft(draft_id TEXT PRIMARY KEY,source_item_id TEXT,review_status TEXT);
          INSERT INTO question VALUES('old','before');''')
        # Simulate independent UI activity after the import plan was prepared.
        db.execute("UPDATE question SET stem='user edit' WHERE question_id='old'")
        db.execute("INSERT INTO question VALUES('user-added','approved elsewhere')");db.commit()
        additions=dict(question_import_draft=[dict(draft_id='new',source_item_id='pep-a-bx1-section_07-q001',review_status='needs_review')])
        report=append_preserving_current(db,additions)
        self.assertEqual(report['formal_count_before'],2)
        self.assertEqual(report['formal_count_after'],2)
        self.assertEqual(db.execute("SELECT stem FROM question WHERE question_id='old'").fetchone()[0],'user edit')
        self.assertEqual(db.execute("SELECT stem FROM question WHERE question_id='user-added'").fetchone()[0],'approved elsewhere')
        self.assertEqual(db.execute('SELECT COUNT(*) FROM question_import_draft').fetchone()[0],1)
        with self.assertRaises(AssertionError):append_preserving_current(db,additions)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM question_import_draft').fetchone()[0],1)
        db.close()

    def test_formal_mutation_plan_is_rejected(self):
        db=sqlite3.connect(':memory:');db.execute('CREATE TABLE question(question_id TEXT PRIMARY KEY)');db.commit()
        with self.assertRaises(AssertionError):append_preserving_current(db,dict(question=[dict(question_id='bad')]))
        self.assertEqual(db.execute('SELECT COUNT(*) FROM question').fetchone()[0],0);db.close()

if __name__=='__main__':unittest.main()
