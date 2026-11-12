from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from services import question_match_cache as cache
from services.import_service import find_question_content_matches
from services.question_similarity_service import extract_similarity_payload


class MatchCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / 'source.sqlite3')
        self.sidecar = Path(self.tmp.name) / 'cache.sqlite3'
        self.stub = patch.object(cache, '_cache_path', return_value=self.sidecar)
        self.stub.start()
        self.addCleanup(self.stub.stop)
        self.stem = r'已知函数 $f(x)=x^2+2x$，求其最小值。'
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('CREATE TABLE question(question_id TEXT PRIMARY KEY, stem_tex TEXT, choices_json TEXT, question_type_id INTEGER)')
            c.execute('CREATE TABLE unrelated(value TEXT)')
            c.execute('INSERT INTO question VALUES (?,?,?,?)', ('Q1', self.stem, '[]', 3))

    def matches(self, **kwargs):
        return find_question_content_matches(self.db, self.stem, question_type_id=3, **kwargs)

    def test_disk_reuse_and_unrelated_write(self):
        expected = self.matches()
        self.assertEqual(expected[0]['kind'], 'exact')
        cache._snapshot.cache_clear()  # New process/snapshot still uses disk results.
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('INSERT INTO unrelated VALUES (?)', ('draft-only edit',))
        with patch('services.import_service.score_question_pair', side_effect=AssertionError('recomputed')):
            self.assertEqual(self.matches(), expected)

    def test_formal_insert_edit_and_delete_invalidate(self):
        self.matches()
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('INSERT INTO question VALUES (?,?,?,?)', ('Q2', self.stem, '[]', 3))
        self.assertEqual([m['question_id'] for m in self.matches()], ['Q1', 'Q2'])
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("UPDATE question SET stem_tex='completely unrelated' WHERE question_id='Q1'")
        self.assertEqual([m['question_id'] for m in self.matches()], ['Q2'])
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("DELETE FROM question WHERE question_id='Q2'")
        self.assertEqual(self.matches(), [])

    def test_options_type_threshold_and_rule_version_are_keys(self):
        original = self.matches()
        self.assertEqual(original[0]['kind'], 'exact')
        self.assertEqual(self.matches(choices=['1', '2'])[0]['kind'], 'similar')
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("UPDATE question SET choices_json='[\"A\"]', question_type_id=1")
        self.assertEqual(self.matches()[0]['kind'], 'similar')
        keys = [cache.match_cache_key('corpus', 'stem', [], 3, score, limit)
                for score, limit in [(0.88, 3), (0.4, 3), (0.88, 5)]]
        self.assertEqual(len(set(keys)), 3)
        with patch.object(cache, '_scorer_version', return_value='changed-rules'):
            self.assertNotEqual(cache.match_cache_key('corpus', 'stem', [], 3, 0.88, 3), keys[0])

    def test_unavailable_or_corrupt_cache_falls_back(self):
        self.sidecar.write_text('invalid sqlite', encoding='utf8')
        self.assertEqual(self.matches()[0]['kind'], 'exact')

    def test_wal_changes_invalidate_before_checkpoint(self):
        with closing(sqlite3.connect(self.db)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            self.assertEqual(self.matches()[0]['kind'], 'exact')
            writer.execute("UPDATE question SET question_type_id=1")
            writer.commit()
            self.assertEqual(self.matches()[0]['kind'], 'similar')
            writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            self.assertEqual(self.matches()[0]['kind'], 'similar')

    def test_prepared_choices_are_not_shared_with_callers(self):
        first = extract_similarity_payload(self.stem, ['1', '2'], 1)
        first['choices'].append('bad edit')
        self.assertEqual(extract_similarity_payload(self.stem, ['1', '2'], 1)['choices'], ['1', '2'])


if __name__ == '__main__':
    unittest.main()
