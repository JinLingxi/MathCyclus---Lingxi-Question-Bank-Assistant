"""User-authorized cold archival of closed SQLite/WAL/SHM snapshot bundles."""
import argparse
import ctypes
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path
from ctypes import wintypes

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.compact_completed_task_snapshots import checked_path, referenced_candidates, digest_file
from services.database_service import DEFAULT_DATABASE_PATH, readonly_database_connection


class LockedBundle:
    def __init__(self,root,relative):
        self.base=checked_path(root,relative)
        self.paths=[self.base]+[Path(str(self.base)+s) for s in ('-wal','-shm','-journal') if Path(str(self.base)+s).exists()]
        self.handles=[]
        if os.name!='nt':
            raise RuntimeError('Windows exclusive file handles required')
        self.k=ctypes.WinDLL('kernel32',use_last_error=True)
        self.k.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        self.k.CreateFileW.restype=wintypes.HANDLE
        self.k.ReadFile.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p]
        self.k.SetFileInformationByHandle.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
        self.k.CloseHandle.argtypes=[wintypes.HANDLE]
    def __enter__(self):
        try:
            for p in self.paths:
                if p.is_symlink() or p.stat().st_nlink!=1:
                    raise ValueError('Linked bundle member; retain')
                handle=self.k.CreateFileW(str(p),0x80000000|0x00010000,0,None,3,0x08000000,None)
                if handle==ctypes.c_void_p(-1).value:
                    raise ctypes.WinError(ctypes.get_last_error())
                self.handles.append(handle)
            return self
        except BaseException:
            self.__exit__(None,None,None)
            raise
    def chunks(self,index):
        buffer=ctypes.create_string_buffer(1024*1024);size=wintypes.DWORD()
        while True:
            if not self.k.ReadFile(self.handles[index],buffer,len(buffer),ctypes.byref(size),None):
                raise ctypes.WinError(ctypes.get_last_error())
            if not size.value:
                break
            yield buffer.raw[:size.value]
    def mark_delete(self):
        marked=[]
        try:
            for handle in self.handles:
                flag=wintypes.BOOL(True)
                if not self.k.SetFileInformationByHandle(handle,4,ctypes.byref(flag),ctypes.sizeof(flag)):
                    raise ctypes.WinError(ctypes.get_last_error())
                marked.append(handle)
        except BaseException:
            for handle in marked:
                flag=wintypes.BOOL(False)
                if not self.k.SetFileInformationByHandle(handle,4,ctypes.byref(flag),ctypes.sizeof(flag)):
                    raise RuntimeError('Delete rollback failed; restore from durable archive receipt')
            raise
    def __exit__(self,*args):
        for handle in reversed(self.handles):
            self.k.CloseHandle(handle)
        self.handles=[]


def verify_zip(archive,folder):
    folder=Path(folder).resolve()
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('_manifest.json'))
        base=Path(manifest['base']).name
        for member in manifest['members']:
            name=Path(member['path']).name
            if name not in {base,base+'-wal',base+'-shm',base+'-journal'}:
                raise ValueError('Invalid bundle member')
            out=folder/name
            if not out.resolve().is_relative_to(folder):
                raise ValueError('Invalid restore path')
            digest=hashlib.sha256()
            with z.open(member['entry']) as src,out.open('xb') as dst:
                while chunk:=src.read(1024*1024):
                    dst.write(chunk);digest.update(chunk)
            if digest.hexdigest()!=member['sha256'] or out.stat().st_size!=member['bytes']:
                raise ValueError('Bundle restoration bytes differ')
    with closing(sqlite3.connect((folder/base).as_uri()+'?mode=ro',uri=True)) as conn:
        if [r[0] for r in conn.execute('PRAGMA quick_check')]!=['ok']:
            raise ValueError('Restored SQLite/WAL state failed quick_check')
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts={t:conn.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('question','question_import_draft') if t in tables}
    return manifest,counts


def archive_bundle(root,relative,archive_dir,journal):
    base=checked_path(root,relative)
    paths=[base]+[Path(str(base)+s) for s in ('-wal','-shm','-journal') if Path(str(base)+s).exists()]
    if any(p.stat().st_mtime>time.time()-3600 for p in paths):
        raise ValueError('Recently modified bundle')
    sizes=sum(p.stat().st_size for p in paths)
    if shutil.disk_usage(archive_dir).free<sizes*2+128*1024*1024:
        raise ValueError('Not enough space for full restore verification')
    archive=archive_dir/(hashlib.sha256(relative.encode()).hexdigest()[:24]+'.zip')
    with LockedBundle(root,relative) as locked:
        manifest={'base':relative,'version':1,'members':[]}
        with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
            for index,path in enumerate(locked.paths):
                digest=hashlib.sha256();size=0
                name='snapshot'+path.name[len(base.name):]+'.bin'
                with z.open(name,'w',force_zip64=True) as out:
                    for chunk in locked.chunks(index):
                        digest.update(chunk);size+=len(chunk);out.write(chunk)
                manifest['members'].append({'path':path.relative_to(root).as_posix(),'entry':name,'bytes':size,'sha256':digest.hexdigest()})
            z.writestr('_manifest.json',json.dumps(manifest,ensure_ascii=False))
        with archive.open('r+b') as f:f.flush();os.fsync(f.fileno())
        with tempfile.TemporaryDirectory(prefix='.verify-bundle-',dir=archive_dir) as temp:
            if not Path(temp).resolve().is_relative_to(archive_dir.resolve()):
                raise ValueError('Restore temporary directory escaped archive root')
            _,counts=verify_zip(archive,temp)
        receipt={**manifest,'archive':archive.relative_to(root).as_posix(),'archive_bytes':archive.stat().st_size,
                 'bytes':sum(m['bytes'] for m in manifest['members']),'restore_verified':True,'counts':counts}
        journal.write(json.dumps({'stage':'verified',**receipt},ensure_ascii=False)+'\n');journal.flush();os.fsync(journal.fileno())
        locked.mark_delete()
    return {'stage':'deleted',**receipt}


def restore_bundle(root,archive):
    archive=Path(archive).resolve()
    if not archive.is_relative_to((root/'data/backups/cold_archives').resolve()):
        raise ValueError('Archive outside allowed root')
    with tempfile.TemporaryDirectory(prefix='.restore-test-',dir=archive.parent) as temp:
        verify_zip(archive,temp)
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('_manifest.json'))
        base=checked_path(root,manifest['base']);restored=[]
        for member in manifest['members']:
            path=root/member['path']
            if path not in [base,*(Path(str(base)+s) for s in ('-wal','-shm','-journal'))]:
                raise ValueError('Member path does not belong to bundle')
            if path.is_symlink():
                raise ValueError('Linked restore path')
            if path.exists() and digest_file(path)!=member['sha256']:
                raise FileExistsError('Existing member differs; refuse overwrite: '+str(path))
        for member in manifest['members']:
            path=root/member['path']
            if path.exists():
                continue
            path.parent.mkdir(parents=True,exist_ok=True)
            fd,name=tempfile.mkstemp(prefix='.bundle-',suffix='.tmp',dir=path.parent)
            temporary=Path(name)
            try:
                with os.fdopen(fd,'wb') as dst,z.open(member['entry']) as src:
                    shutil.copyfileobj(src,dst,1024*1024);dst.flush();os.fsync(dst.fileno())
                if digest_file(temporary)!=member['sha256']:
                    raise ValueError('Restoration hash mismatch')
                os.link(temporary,path);restored.append(member['path'])
            finally:
                temporary.unlink(missing_ok=True)
    return {'restored':restored}


def make_plan():
    previous=json.loads((ROOT/'reports/completed_snapshot_cleanup_20261108_222128.plan.json').read_text(encoding='utf-8'))
    candidates=[e['path'] for e in previous['retained'] if e['reason']=='sqlite_sidecar_present' and (ROOT/e['path']).exists()]
    # Shanghai: retain the latest final staging DB and all task-finish backups;
    # cold-store the now-obsolete pre-task/pre-stage copies.
    for folder in (ROOT/'data/imports').glob('shanghai_*'):
        if folder.is_dir() and not folder.is_symlink() and not folder.is_junction():
            candidates += [p.relative_to(ROOT).as_posix() for p in folder.glob('*.sqlite3')
                           if p.name=='baseline_before_batch.sqlite3' or p.name.startswith('stage_baseline_')]
    entries=[{'path':p} for p in sorted(set(candidates))]
    references=referenced_candidates(ROOT,entries)
    selected=[];retained=[]
    for entry in entries:
        active=[v for v in references.get(Path(entry['path']).name.casefold(),[])
                if v.startswith(('database:','services/','components/','.ingestion/','data/imports/','question_bank_app.py'))]
        if active:
            retained.append({**entry,'reason':'live_reference','evidence':active})
        else:
            checked_path(ROOT,entry['path']);selected.append(entry)
    return selected,retained


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--apply',action='store_true')
    modes.add_argument('--restore-archive',type=Path)
    args=parser.parse_args()
    if args.restore_archive:
        print(json.dumps(restore_bundle(ROOT,args.restore_archive),ensure_ascii=False));return
    with readonly_database_connection(DEFAULT_DATABASE_PATH) as c:
        root_count=c.execute("SELECT count(*) FROM import_batch WHERE subset_key LIKE 'shanghai-%' AND import_type='codex_task'").fetchone()[0]
        rows=c.execute("""WITH RECURSIVE tree(id) AS (
            SELECT batch_id FROM import_batch WHERE subset_key LIKE 'shanghai-%' AND import_type='codex_task'
            UNION SELECT b.batch_id FROM import_batch b JOIN tree t ON b.parent_batch_id=t.id)
            SELECT review_status,count(*) FROM question_import_draft WHERE batch_id IN (SELECT id FROM tree) GROUP BY review_status""").fetchall()
        if root_count!=7 or not rows or any(r[0]!='committed' for r in rows):
            raise ValueError('Shanghai still has uncommitted drafts')
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    selected,retained=make_plan()
    plan={'mode':'apply' if args.apply else 'dry_run','selected':selected,'retained':retained,
          'files':len(selected),'GiB':round(sum((ROOT/e['path']).stat().st_size for e in selected)/1024**3,3)}
    prefix=ROOT/'reports'/('snapshot_bundle_cleanup_'+stamp)
    with Path(str(prefix)+'.plan.json').open('x',encoding='utf-8') as f:json.dump(plan,f,ensure_ascii=False,indent=2)
    print(json.dumps({'plan':str(prefix.relative_to(ROOT))+'.plan.json','bundles':len(selected),'GiB':plan['GiB'],'protected':len(retained)},ensure_ascii=False),flush=True)
    if not args.apply:return
    backup=ROOT/'data/backups'/('after_shanghai_completed_before_bundle_cleanup_'+stamp+'.sqlite3')
    with readonly_database_connection(DEFAULT_DATABASE_PATH) as source,closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    with closing(sqlite3.connect(backup.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)) as c:
        if [r[0] for r in c.execute('PRAGMA quick_check')]!=['ok']:
            raise ValueError('Final protection backup did not verify')
    protection_bytes=backup.stat().st_size
    archive_dir=ROOT/'data/backups/cold_archives'/('snapshot_bundles_'+stamp)
    archive_dir.mkdir(parents=True,exist_ok=False)
    events=[];deleted=0
    with Path(str(prefix)+'.journal.jsonl').open('x',encoding='utf-8') as journal:
        for index,e in enumerate(selected,1):
            try:
                result=archive_bundle(ROOT,e['path'],archive_dir,journal);deleted+=result['bytes']
            except (OSError,ValueError,sqlite3.Error,zipfile.BadZipFile) as error:
                result={'stage':'retained','base':e['path'],'reason':str(error)}
            events.append(result);journal.write(json.dumps(result,ensure_ascii=False)+'\n');journal.flush();os.fsync(journal.fileno())
            saved=deleted-sum(p.stat().st_size for p in archive_dir.glob('*.zip'))-protection_bytes
            print(json.dumps({'processed':index,'total':len(selected),'stage':result['stage'],'net_freed_GiB':round(saved/1024**3,3)},ensure_ascii=False),flush=True)
    outcome={'events':events,'stages':dict(Counter(e['stage'] for e in events)),'net_freed_bytes':saved,
             'archive_root':archive_dir.relative_to(ROOT).as_posix(),'retained':retained,
             'protection_backup':backup.relative_to(ROOT).as_posix(),'protection_backup_bytes':protection_bytes}
    with Path(str(prefix)+'.result.json').open('x',encoding='utf-8') as f:json.dump(outcome,f,ensure_ascii=False,indent=2)
    print(json.dumps({'result':str(prefix.relative_to(ROOT))+'.result.json','stages':outcome['stages'],'net_freed_GiB':round(saved/1024**3,3)},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
