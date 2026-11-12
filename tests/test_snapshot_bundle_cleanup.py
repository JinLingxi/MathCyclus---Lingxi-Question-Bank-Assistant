import ctypes
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from ctypes import wintypes
from pathlib import Path
from scripts.compact_snapshot_bundles import LockedBundle,archive_bundle,restore_bundle,verify_zip


@unittest.skipUnless(os.name=='nt','Windows exclusive bundle handling')
class BundleCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.base=self.root/'data/imports/shanghai_required1/stage_baseline_test.sqlite3'
        self.base.parent.mkdir(parents=True)
        live=self.root/'live.sqlite3'
        conn=sqlite3.connect(live)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE proof(value)')
        conn.execute('INSERT INTO proof VALUES(42)')
        conn.commit()
        for suffix in ('','-wal','-shm'):
            shutil.copy2(Path(str(live)+suffix),Path(str(self.base)+suffix))
        conn.close()
        for suffix in ('','-wal','-shm'):
            os.utime(Path(str(self.base)+suffix),(time.time()-7200,time.time()-7200))
        self.archives=self.root/'data/backups/cold_archives/bundles'
        self.archives.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_nonempty_wal_roundtrip(self):
        self.assertGreater(Path(str(self.base)+'-wal').stat().st_size,0)
        with (self.root/'journal.jsonl').open('w',encoding='utf-8') as journal:
            receipt=archive_bundle(self.root,self.base.relative_to(self.root).as_posix(),self.archives,journal)
        self.assertFalse(self.base.exists())
        self.assertTrue(all(not (self.root/m['path']).exists() for m in receipt['members']))
        restore_bundle(self.root,self.root/receipt['archive'])
        conn=sqlite3.connect(self.base)
        try:self.assertEqual(conn.execute('SELECT value FROM proof').fetchone()[0],42)
        finally:conn.close()

    def test_active_bundle_is_preserved(self):
        conn=sqlite3.connect(self.base)
        conn.execute('SELECT * FROM proof').fetchall()
        try:
            with self.assertRaises(OSError):
                with LockedBundle(self.root,self.base.relative_to(self.root).as_posix()):
                    pass
        finally:conn.close()
        self.assertTrue(self.base.exists())

    def test_failed_delete_cancels_earlier_delete_marks(self):
        originals={s:Path(str(self.base)+s).read_bytes() for s in ('','-wal','-shm')}
        with LockedBundle(self.root,self.base.relative_to(self.root).as_posix()) as locked:
            real=locked.k.SetFileInformationByHandle;calls=0
            def fail_second(handle,kind,pointer,size):
                nonlocal calls
                if ctypes.cast(pointer,ctypes.POINTER(wintypes.BOOL)).contents.value:
                    calls+=1
                    if calls==2:
                        ctypes.set_last_error(5)
                        return 0
                return real(handle,kind,pointer,size)
            locked.k.SetFileInformationByHandle=fail_second
            with self.assertRaises(OSError):
                locked.mark_delete()
        for suffix,content in originals.items():
            self.assertEqual(Path(str(self.base)+suffix).read_bytes(),content)


if __name__=='__main__':unittest.main()
