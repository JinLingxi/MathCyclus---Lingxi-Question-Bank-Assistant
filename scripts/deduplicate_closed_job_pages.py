"""Share identical immutable page PNGs, preserving every review pathname.

Only the two user-authorized old ingestion roots are eligible. Unique pages,
OCR payloads, crops, source PDFs, SQLite files, archives and live jobs stay put.
"""
import argparse
import ctypes
import hashlib
import json
import os
import sqlite3
import stat
import time
import uuid
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from ctypes import wintypes

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = ('data/imports/pdf_jobs', 'data/imports/codex_2024_restart/jobs')


def checked(path, allowed):
    path = Path(path).absolute()
    if not any(path.is_relative_to(base.resolve()) for base in allowed):
        raise ValueError('Outside authorized page roots')
    if path.parent.name != 'pages' or path.suffix.lower() != '.png':
        raise ValueError('Only generated page PNG files are eligible')
    for parent in (path, *path.parents):
        if parent.is_symlink() or parent.is_junction():
            raise ValueError('Linked path refused')
    return path


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as src:
        while block := src.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def replace_link(temporary, destination):
    """Atomically replace a name while the old inode remains locked/readable.

    POSIX rename semantics allow replacement of an open destination on NTFS;
    existing handles still refer to its old bytes until they are closed.
    """
    class RenameInfo(ctypes.Structure):
        _fields_ = [('flags', wintypes.DWORD), ('root', wintypes.HANDLE),
                    ('length', wintypes.DWORD), ('name', wintypes.WCHAR * 1)]
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                             ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k.CreateFileW.restype = wintypes.HANDLE
    k.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                            ctypes.c_void_p, wintypes.DWORD]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k.CreateFileW(str(temporary), 0x10000, 7, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        name = ('\\\\?\\' + str(destination)).encode('utf-16-le')
        buffer = ctypes.create_string_buffer(RenameInfo.name.offset + len(name) + 2)
        info = RenameInfo.from_buffer(buffer)
        info.flags = 3  # REPLACE_IF_EXISTS | POSIX_SEMANTICS
        info.root = None
        info.length = len(name)
        ctypes.memmove(ctypes.addressof(buffer) + RenameInfo.name.offset, name, len(name))
        if not k.SetFileInformationByHandle(handle, 22, buffer, len(buffer)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        k.CloseHandle(handle)


@contextmanager
def locked(path, share):
    if os.name != 'nt':
        raise RuntimeError('Windows file handles required')
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                             ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k.CreateFileW.restype = wintypes.HANDLE
    k.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                          ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k.CreateFileW(str(path), 0x80000000, share, None, 3, 0x08000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        h = hashlib.sha256()
        buffer = ctypes.create_string_buffer(1024 * 1024)
        size = wintypes.DWORD()
        while True:
            if not k.ReadFile(handle, buffer, len(buffer), ctypes.byref(size), None):
                raise ctypes.WinError(ctypes.get_last_error())
            if not size.value:
                break
            h.update(buffer.raw[:size.value])
        yield h.hexdigest()
    finally:
        k.CloseHandle(handle)


def share_page(canonical, duplicate, expected, allowed, receipt):
    canonical, duplicate = checked(canonical, allowed), checked(duplicate, allowed)
    if os.path.samefile(canonical, duplicate):
        return False
    # Old generated pages are immutable input to review. A shared readonly file
    # prevents an accidental in-place overwrite from changing its other names.
    temporary = duplicate.with_name('.page-link-' + uuid.uuid4().hex + '.tmp')
    try:
        # Canonical: permit readers/renaming links, deny writers. Duplicate: deny
        # readers/writers while allowing our atomic replacement of its name.
        with locked(canonical, 5) as canonical_hash, locked(duplicate, 4) as duplicate_hash:
            if canonical_hash != expected or duplicate_hash != expected:
                raise ValueError('Page bytes changed; retain original')
            if duplicate.stat().st_nlink != 1:
                raise ValueError('Duplicate already has other hard links')
            os.link(canonical, temporary)
            if digest(temporary) != expected or not os.path.samefile(temporary, canonical):
                raise ValueError('New link verification failed')
            receipt({'stage': 'verified_before_replace', 'sha256': expected,
                     'canonical': str(canonical), 'path': str(duplicate),
                     'bytes': duplicate.stat().st_size,
                     'original_mtime_ns': duplicate.stat().st_mtime_ns})
            replace_link(temporary, duplicate)
        if not os.path.samefile(canonical, duplicate) or digest(duplicate) != expected:
            raise RuntimeError('Post-replacement verification failed')
        canonical.chmod(stat.S_IREAD)
        return True
    finally:
        # If replacement fails, the original path still exists. The temporary
        # readonly link is retained for inspection rather than changing shared
        # attributes to delete it.
        if temporary.exists():
            receipt({'stage': 'temporary_link_retained', 'path': str(temporary)})


def plan(root):
    allowed = [root / p for p in ALLOWED]
    connection = sqlite3.connect((root / 'data/mathcyclus.sqlite3').as_uri() + '?mode=ro', uri=True)
    protected_jobs = set()
    for (value,) in connection.execute('SELECT extra_json FROM question_import_draft'):
        try:
            extra = json.loads(value or '{}')
        except (ValueError, TypeError):
            continue
        if isinstance(extra, dict) and extra.get('document_job_id'):
            protected_jobs.add(str(extra['document_job_id']))
    connection.close()
    sizes = defaultdict(list)
    protected = []
    for base in allowed:
        for folder, dirs, names in os.walk(base, followlinks=False):
            dirs[:] = [name for name in dirs if not (Path(folder) / name).is_symlink()
                       and not (Path(folder) / name).is_junction()]
            page_dir = Path(folder)
            if page_dir.name != 'pages':
                continue
            job = page_dir.parent
            if job.name in protected_jobs:
                protected.append(job.relative_to(root).as_posix())
                continue
            manifest_path = job / 'job_manifest.json'
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
                if (not (job / 'source.pdf').is_file()
                        or not isinstance(manifest, dict)
                        or manifest_path.stat().st_mtime > time.time() - 86400):
                    continue
            except (OSError, ValueError):
                continue
            for name in names:
                path = page_dir / name
                if path.suffix.lower() != '.png':
                    continue
                checked(path, allowed)
                st = path.stat()
                if st.st_mtime > time.time() - 86400 or st.st_nlink != 1:
                    continue
                sizes[st.st_size].append(path)
    groups = defaultdict(list)
    for size, paths in sizes.items():
        if len(paths) > 1:
            for path in paths:
                groups[(size, digest(path))].append(path)
    operations = []
    for (size, sha), paths in groups.items():
        paths.sort()
        for duplicate in paths[1:]:
            operations.append({'canonical': paths[0].relative_to(root).as_posix(),
                               'path': duplicate.relative_to(root).as_posix(),
                               'bytes': size, 'sha256': sha})
    return {'operations': operations, 'protected_jobs': protected,
            'potential_saved_bytes': sum(o['bytes'] for o in operations)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    report = plan(ROOT)
    prefix = ROOT / 'reports' / ('closed_job_page_dedup_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    Path(str(prefix) + '.plan.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'plan': str(prefix) + '.plan.json', 'duplicates': len(report['operations']),
                      'potential_GiB': round(report['potential_saved_bytes'] / 1024**3, 3)}, ensure_ascii=False), flush=True)
    if not args.apply:
        return
    events = []
    saved = 0
    with Path(str(prefix) + '.journal.jsonl').open('x', encoding='utf-8') as journal:
        def receipt(event):
            journal.write(json.dumps(event, ensure_ascii=False) + '\n')
            journal.flush()
            os.fsync(journal.fileno())
        for index, operation in enumerate(report['operations'], 1):
            try:
                changed = share_page(ROOT / operation['canonical'], ROOT / operation['path'],
                                     operation['sha256'], [ROOT / p for p in ALLOWED], receipt)
                event = {**operation, 'stage': 'shared' if changed else 'already_shared'}
                if changed:
                    saved += operation['bytes']
            except (OSError, ValueError) as error:
                event = {**operation, 'stage': 'retained', 'reason': str(error)}
            events.append(event)
            receipt(event)
            if index % 500 == 0:
                print(json.dumps({'processed': index, 'total': len(report['operations']),
                                  'saved_GiB': round(saved / 1024**3, 3)}, ensure_ascii=False), flush=True)
    result = {'events': events, 'stages': dict(Counter(e['stage'] for e in events)),
              'saved_unique_file_bytes': saved, 'all_original_paths_preserved': True,
              'archives_deleted': 0, 'database_writes': 0}
    Path(str(prefix) + '.result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'result': str(prefix) + '.result.json', 'stages': result['stages'],
                      'saved_GiB': round(saved / 1024**3, 3)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
