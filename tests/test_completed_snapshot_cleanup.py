import hashlib
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from scripts.compact_completed_task_snapshots import archive_one, checked_path, inventory, prune_verified, restore_archive


@unittest.skipUnless(os.name=='nt','Windows exclusive deletion')
class SnapshotCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.folder=self.root/'data/imports/pep_a_required1'
        self.folder.mkdir(parents=True)
        self.archives=self.root/'data/backups/cold_archives/test'
        self.archives.mkdir(parents=True)
        self.source=self.folder/'staged_old.sqlite3'
        conn=sqlite3.connect(self.source)
        conn.execute('CREATE TABLE proof(value TEXT)')
        conn.execute("INSERT INTO proof VALUES('original bytes')")
        conn.commit();conn.close()
        st=self.source.stat()
        self.entry={'path':self.source.relative_to(self.root).as_posix(),'bytes':st.st_size,'mtime_ns':st.st_mtime_ns,'group':'test'}

    def tearDown(self):
        self.temp.cleanup()

    def test_verified_archive_deletion_and_exact_restore(self):
        digest=hashlib.sha256(self.source.read_bytes()).hexdigest()
        result=archive_one(self.root,self.entry,self.archives,prune=True)
        self.assertFalse(self.source.exists())
        restore_archive(self.root,self.root/result['archive'])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),digest)
        with self.assertRaises(FileExistsError):
            restore_archive(self.root,self.root/result['archive'])

    def test_wrong_hash_and_sidecars_keep_source(self):
        with self.assertRaises(ValueError):
            prune_verified(self.root,self.entry['path'],'0'*64)
        self.assertTrue(self.source.exists())
        Path(str(self.source)+'-wal').write_bytes(b'protect')
        with self.assertRaises(ValueError):
            prune_verified(self.root,self.entry['path'],hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertTrue(self.source.exists())

    def test_main_database_and_outside_paths_are_rejected(self):
        for name in ['data/mathcyclus.sqlite3','outside.sqlite3','data/imports/../../../outside.sqlite3']:
            with self.assertRaises(ValueError):
                checked_path(self.root,name)

    def test_open_database_is_not_deleted(self):
        conn=sqlite3.connect(self.source)
        conn.execute('SELECT * FROM proof').fetchall()
        try:
            with self.assertRaises(OSError):
                prune_verified(self.root,self.entry['path'],hashlib.sha256(self.source.read_bytes()).hexdigest())
        finally:
            conn.close()
        self.assertTrue(self.source.exists())

    def test_latest_two_are_retained(self):
        for index in range(3):
            p=self.folder/f'staged_{index}.sqlite3'
            p.write_bytes(self.source.read_bytes())
            os.utime(p,(time.time()-10000+index,time.time()-10000+index))
        os.utime(self.source,(time.time()-20000,time.time()-20000))
        candidates,retained=inventory(self.root)
        selected={Path(e['path']).name for e in candidates}
        self.assertIn('staged_old.sqlite3',selected)
        self.assertNotIn('staged_2.sqlite3',selected)
        self.assertNotIn('staged_1.sqlite3',selected)


if __name__=='__main__':
    unittest.main()
