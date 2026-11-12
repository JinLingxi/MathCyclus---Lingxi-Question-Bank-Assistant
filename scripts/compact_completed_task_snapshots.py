"""Archive/restore-verify/prune only old, unreferenced completed-task DB copies."""
import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.database_service import DEFAULT_DATABASE_PATH, readonly_database_connection

TASK_DIR = re.compile(r"(?:pep_[ab]_(?:required[1-4]|elective[1-3])|qj_(?:2010_2015|2016_2020|2021_2025)|amc10_12|amc8_2000_2025|codex_20(?:0[0-9]|1[0-9]|2[0-6])_restart)")


def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def checked_path(root, relative):
    root = root.resolve()
    path = root / relative
    resolved = path.resolve()
    allowed = (root/'data/imports', root/'data/backups')
    if path.suffix != '.sqlite3' or not any(resolved.is_relative_to(p.resolve()) for p in allowed):
        raise ValueError('Snapshot outside allowed directories')
    for parent in [path, *path.parents]:
        if parent == root:
            break
        if parent.is_symlink() or parent.is_junction():
            raise ValueError('Link/junction not allowed')
    return resolved


def backup_family(name):
    if name.startswith('before_pep_a_bx1'):
        return 'pep_a_required1'
    match = re.match(r'before_(pep_[ab]_(?:required[1-4]|elective[1-3]))(?:_|$)',name)
    if match:
        return match[1]
    if name.startswith('before_qj'):
        return 'qj'
    if name.startswith('before_amc'):
        return 'amc8' if 'amc8' in name else 'amc10_12'
    match = re.match(r'(?:before_|mathcyclus_schema_migration_apply_)(20(?:0[0-9]|1[0-9]|2[0-6]))_visual',name)
    return 'gaokao_'+match[1] if match else None


def inventory(root):
    groups = defaultdict(list)
    for directory in (root/'data/imports').iterdir():
        if directory.is_dir() and not directory.is_junction() and not directory.is_symlink() and TASK_DIR.fullmatch(directory.name):
            groups['task:'+directory.name].extend(directory.glob('*.sqlite3'))
    for path in (root/'data/backups').glob('*.sqlite3'):
        family = backup_family(path.name)
        if family:
            groups['backup:'+family].append(path)
    candidates, retained = [], []
    for group, paths in groups.items():
        paths.sort(key=lambda p:(p.stat().st_mtime_ns,p.name),reverse=True)
        for index, path in enumerate(paths):
            info = path.stat()
            relative = path.relative_to(root).as_posix()
            reason = None
            if index < 2:
                reason = 'retain_latest_two_per_group'
            elif path.name in {'baseline_before_batch.sqlite3','baseline_before_task.sqlite3'} or path.name.startswith('prepared'):
                reason = 'retain_initial_or_prepared_evidence'
            elif info.st_mtime > time.time()-3600:
                reason = 'recent_file'
            elif info.st_nlink != 1:
                reason = 'shared_hardlink'
            elif any(Path(str(path)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
                reason = 'sqlite_sidecar_present'
            if reason:
                retained.append({'path':relative,'reason':reason})
                continue
            checked_path(root,relative)
            candidates.append({'path':relative,'bytes':info.st_size,'mtime_ns':info.st_mtime_ns,'group':group})
    return candidates, retained


def referenced_candidates(root, candidates):
    names = {Path(c['path']).name.casefold() for c in candidates}
    if not names:
        return {}
    pattern = re.compile('|'.join(re.escape(n) for n in sorted(names,key=len,reverse=True)))
    found = defaultdict(set)
    def scan(value, location):
        if isinstance(value,str) and '.sqlite3' in value.casefold():
            for match in pattern.finditer(value.casefold()):
                found[match.group()].add(location)
    with readonly_database_connection(DEFAULT_DATABASE_PATH) as conn:
        conn.execute('BEGIN')
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            safe=table.replace('"','""')
            for row in conn.execute(f'SELECT * FROM "{safe}"'):
                for value in row:
                    scan(value,'database:'+table)
    # Live task manifests and executable source are protected. Historical
    # reports are retained; their archived snapshot paths can be restored.
    paths = []
    for directory in ('scripts','services','components','docs','.ingestion'):
        base=root/directory
        if base.exists():
            paths.extend(p for p in base.rglob('*') if p.suffix in {'.py','.md','.json','.cjs'} and p.is_file())
    paths.extend(p for p in root.iterdir() if p.is_file() and p.suffix in {'.py','.md','.cjs','.bat','.ps1','.sql','.tex'})
    paths.extend(p for p in (root/'data/imports').rglob('*.json')
                 if any(word in p.name.lower() for word in ('manifest','queue','task_state')))
    for path in paths:
        try:
            overlap=max(len(name) for name in names)+16
            tail=''
            with path.open('r',encoding='utf-8-sig',errors='replace') as source:
                while chunk:=source.read(1024*1024):
                    scan(tail+chunk,path.relative_to(root).as_posix())
                    tail=(tail+chunk)[-overlap:]
        except OSError:
            raise ValueError('Cannot audit reference file: '+str(path))
    return {name:sorted(locations) for name,locations in found.items()}


def prune_verified(root, relative, expected_sha):
    """Acquire exclusive access, rehash, then delete that exact file handle."""
    path = checked_path(root,relative)
    if path.stat().st_nlink != 1 or any(Path(str(path)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
        raise ValueError('Source has links or sidecars; retain')
    if os.name != 'nt':
        raise RuntimeError('Exclusive Windows deletion is required')
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.ReadFile.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p]
    kernel.SetFileInformationByHandle.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateFileW(str(path),0x80000000|0x00010000,0,None,3,0x08000000,None)
    if handle==ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if any(Path(str(path)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
            raise ValueError('Sidecars appeared; retain')
        digest=hashlib.sha256();buffer=ctypes.create_string_buffer(1024*1024);read=wintypes.DWORD()
        while True:
            if not kernel.ReadFile(handle,buffer,len(buffer),ctypes.byref(read),None):
                raise ctypes.WinError(ctypes.get_last_error())
            if not read.value:
                break
            digest.update(buffer.raw[:read.value])
        if digest.hexdigest()!=expected_sha:
            raise ValueError('Source changed; archive retained, source not deleted')
        delete=wintypes.BOOL(True)
        if not kernel.SetFileInformationByHandle(handle,4,ctypes.byref(delete),ctypes.sizeof(delete)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)


def archive_one(root, entry, archive_root, *, prune=False):
    source=checked_path(root,entry['path'])
    info=source.stat()
    if info.st_size!=entry['bytes'] or info.st_mtime_ns!=entry['mtime_ns']:
        raise ValueError('Source changed since inventory')
    if any(Path(str(source)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
        raise ValueError('Source now has SQLite sidecars')
    if shutil.disk_usage(archive_root).free < entry['bytes']*2+128*1024*1024:
        raise ValueError('Insufficient space for archive and isolated restoration')
    archive=archive_root/(hashlib.sha256(entry['path'].encode()).hexdigest()[:24]+'.zip')
    if archive.exists():
        raise FileExistsError(archive)
    digest=hashlib.sha256()
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
        with source.open('rb') as src,z.open('snapshot.sqlite3','w',force_zip64=True) as dst:
            while chunk:=src.read(1024*1024):
                digest.update(chunk);dst.write(chunk)
        z.writestr('_manifest.json',json.dumps({**entry,'sha256':digest.hexdigest()},ensure_ascii=False))
    with archive.open('r+b') as durable:
        durable.flush()
        os.fsync(durable.fileno())
    sha=digest.hexdigest()
    with tempfile.TemporaryDirectory(prefix='.verify-',dir=archive_root) as directory:
        restored=Path(directory)/'snapshot.sqlite3';restored_hash=hashlib.sha256()
        with zipfile.ZipFile(archive) as z,z.open('snapshot.sqlite3') as src,restored.open('xb') as dst:
            while chunk:=src.read(1024*1024):
                restored_hash.update(chunk);dst.write(chunk)
        if restored_hash.hexdigest()!=sha or restored.stat().st_size!=entry['bytes']:
            raise ValueError('Restoration hash/size mismatch')
        with closing(sqlite3.connect(restored.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)) as conn:
            if [r[0] for r in conn.execute('PRAGMA quick_check')]!=['ok']:
                raise ValueError('Restored database quick_check failed')
    result={**entry,'sha256':sha,'archive':archive.relative_to(root).as_posix(),
            'archive_bytes':archive.stat().st_size,'restore_verified':True,'deleted':False}
    if prune:
        prune_verified(root,entry['path'],sha)
        result['deleted']=True
    return result


def restore_archive(root, archive):
    archive=Path(archive).resolve()
    if not archive.is_relative_to((root/'data/backups/cold_archives').resolve()):
        raise ValueError('Archive is outside the cold archive directory')
    with zipfile.ZipFile(archive) as z:
        entry=json.loads(z.read('_manifest.json'))
        target=checked_path(root,entry['path'])
        if target.exists():
            raise FileExistsError(target)
        target.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='.restore-snapshot-',suffix='.tmp',dir=target.parent)
        temporary=Path(name);digest=hashlib.sha256()
        try:
            with os.fdopen(fd,'wb') as dst,z.open('snapshot.sqlite3') as src:
                while chunk:=src.read(1024*1024):
                    digest.update(chunk);dst.write(chunk)
                dst.flush();os.fsync(dst.fileno())
            if digest.hexdigest()!=entry['sha256'] or temporary.stat().st_size!=entry['bytes']:
                raise ValueError('Restore bytes do not match manifest')
            with closing(sqlite3.connect(temporary.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)) as conn:
                if [r[0] for r in conn.execute('PRAGMA quick_check')]!=['ok']:
                    raise ValueError('Restored database is invalid')
            os.utime(temporary,ns=(entry['mtime_ns'],entry['mtime_ns']))
            os.link(temporary,target)  # atomic publication without overwriting
        finally:
            temporary.unlink(missing_ok=True)
    return {'restored':target.relative_to(root).as_posix(),'sha256':entry['sha256'],'bytes':entry['bytes']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--apply',action='store_true')
    mode.add_argument('--restore-archive',type=Path)
    args=parser.parse_args()
    if args.restore_archive:
        print(json.dumps(restore_archive(ROOT,args.restore_archive),ensure_ascii=False))
        return
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    candidates,retained=inventory(ROOT)
    references=referenced_candidates(ROOT,candidates)
    selected=[]
    for entry in candidates:
        evidence=references.get(Path(entry['path']).name.casefold())
        if evidence:
            retained.append({'path':entry['path'],'reason':'referenced','evidence':evidence})
        else:
            selected.append(entry)
    selected.sort(key=lambda e:e['bytes'])
    plan={'created_at':stamp,'mode':'apply' if args.apply else 'dry_run',
          'scope':'old_completed_task_sqlite_copies_only','candidates':selected,'retained':retained,
          'bytes':sum(e['bytes'] for e in selected),'files':len(selected),
          'business_files_deleted':False,'task_records_deleted':False}
    output=ROOT/'reports'/('completed_snapshot_cleanup_'+stamp)
    with Path(str(output)+'.plan.json').open('x',encoding='utf-8') as f:json.dump(plan,f,ensure_ascii=False,indent=2)
    print(json.dumps({'plan':str(output.relative_to(ROOT))+'.plan.json','files':len(selected),
                     'GiB':round(plan['bytes']/1024**3,3),'retained':len(retained)},ensure_ascii=False),flush=True)
    if not args.apply:
        return
    archive_root=ROOT/'data/backups/cold_archives'/('completed_tasks_'+stamp)
    archive_root.mkdir(parents=True,exist_ok=False)
    events=[];freed=0;deleted_bytes=0
    with Path(str(output)+'.journal.jsonl').open('x',encoding='utf-8') as journal:
        for index,entry in enumerate(selected,1):
            try:
                # Archive receipt is durable before deleting its verified source.
                result=archive_one(ROOT,entry,archive_root,prune=False)
                journal.write(json.dumps({'stage':'archive_verified',**result},ensure_ascii=False)+'\n');journal.flush();os.fsync(journal.fileno())
                prune_verified(ROOT,entry['path'],result['sha256'])
                result['deleted']=True
                deleted_bytes+=entry['bytes']
                event={'stage':'deleted',**result}
            except (OSError,ValueError,sqlite3.Error,zipfile.BadZipFile) as exc:
                event={**entry,'stage':'retained_on_error','error':str(exc)}
            freed=deleted_bytes-sum(p.stat().st_size for p in archive_root.glob('*.zip'))
            events.append(event);journal.write(json.dumps(event,ensure_ascii=False)+'\n');journal.flush();os.fsync(journal.fileno())
            print(json.dumps({'processed':index,'total':len(selected),'stage':event['stage'],
                              'net_freed_GiB':round(freed/1024**3,3),'path':entry['path']},ensure_ascii=False),flush=True)
    result={**{k:v for k,v in plan.items() if k!='candidates'},'events':events,'net_freed_bytes':freed,
            'stages':dict(Counter(e['stage'] for e in events)),'archive_root':archive_root.relative_to(ROOT).as_posix()}
    with Path(str(output)+'.result.json').open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'result':str(output.relative_to(ROOT))+'.result.json','net_freed_GiB':round(freed/1024**3,3),'stages':result['stages']},ensure_ascii=False))


if __name__=='__main__':main()
