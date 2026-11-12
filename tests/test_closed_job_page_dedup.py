import os
import stat
import tempfile
import unittest
from pathlib import Path

from scripts.deduplicate_closed_job_pages import checked, digest, locked, share_page


@unittest.skipUnless(os.name == 'nt', 'Windows file-sharing behavior')
class ClosedPageDedupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pages = self.root / 'job/pages'
        self.pages.mkdir(parents=True)
        self.first = self.pages / 'a.png'
        self.second = self.pages / 'b.png'
        self.first.write_bytes(b'preserved image bytes')
        self.second.write_bytes(self.first.read_bytes())
        self.receipts = []

    def tearDown(self):
        for path in self.root.rglob('*'):
            if path.is_file():
                path.chmod(stat.S_IWRITE | stat.S_IREAD)
        self.temp.cleanup()

    def test_identical_pages_keep_paths_and_bytes(self):
        expected = digest(self.first)
        self.assertTrue(share_page(self.first, self.second, expected, [self.root], self.receipts.append))
        self.assertTrue(os.path.samefile(self.first, self.second))
        self.assertEqual(digest(self.second), expected)
        self.assertEqual(self.receipts[0]['stage'], 'verified_before_replace')
        self.assertFalse(self.second.stat().st_mode & stat.S_IWRITE)
        third = self.pages / 'c.png'
        third.write_bytes(b'preserved image bytes')
        self.assertTrue(share_page(self.first, third, expected, [self.root], self.receipts.append))
        self.assertTrue(os.path.samefile(third, self.first))

    def test_changed_duplicate_is_not_replaced(self):
        self.second.write_bytes(b'different image')
        with self.assertRaises(ValueError):
            share_page(self.first, self.second, digest(self.first), [self.root], self.receipts.append)
        self.assertEqual(self.second.read_bytes(), b'different image')
        self.assertFalse(os.path.samefile(self.first, self.second))

    def test_active_handle_and_outside_path_are_refused(self):
        with locked(self.second, 0):
            with self.assertRaises(OSError):
                share_page(self.first, self.second, digest(self.first), [self.root], self.receipts.append)
        self.assertEqual(digest(self.second), digest(self.first))
        with self.assertRaises(ValueError):
            checked(self.root / 'not-pages/a.png', [self.root])
        with self.assertRaises(ValueError):
            checked(self.second, [self.root / 'other'])


if __name__ == '__main__':
    unittest.main()
