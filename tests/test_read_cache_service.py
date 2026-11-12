from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from services.database_service import database_change_token
from services.read_cache_service import cached_database_read
from services.question_text_format_service import question_display_note


class ReadCacheTests(unittest.TestCase):
    def test_read_reuse_wal_invalidation_and_independent_results(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / 'test.sqlite3')
            with closing(sqlite3.connect(db)) as c:
                c.execute('PRAGMA journal_mode=WAL')
                c.execute('CREATE TABLE sample(value TEXT)')
                c.execute("INSERT INTO sample VALUES ('first')")
                c.commit()
                calls = []

                @cached_database_read(maxsize=4)
                def read(path):
                    calls.append(path)
                    with closing(sqlite3.connect(path)) as reader:
                        return {'rows': [list(r) for r in reader.execute('SELECT value FROM sample')]}

                self.assertEqual(read(db)['rows'], [['first']])
                read(db)['rows'][0][0] = 'local edit'
                self.assertEqual(read(db)['rows'], [['first']])
                self.assertEqual(len(calls), 1)
                before = database_change_token(db)
                c.execute("UPDATE sample SET value='updated'")
                c.commit()
                self.assertNotEqual(database_change_token(db), before)
                self.assertEqual(read(db)['rows'], [['updated']])
                self.assertEqual(len(calls), 2)
                c.execute('DELETE FROM sample')
                c.commit()
                self.assertEqual(read(db)['rows'], [])

    def test_boilerplate_hidden_but_source_warning_retained(self):
        boilerplate = '对照原书扫描页转写，保留原书答案及解法。'
        self.assertEqual(question_display_note(boilerplate), '')
        self.assertEqual(question_display_note(boilerplate + ' 来源疑点：需复核'), '来源疑点：需复核')
        self.assertEqual(question_display_note('教师备注：第二种解法'), '教师备注：第二种解法')


if __name__ == '__main__':
    unittest.main()
