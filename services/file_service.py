import csv
import datetime
import os
import shutil
import tempfile
import time


def _same_filesystem_temp_path(target_path: str) -> str:
    target_dir = os.path.dirname(os.path.abspath(target_path)) or "."
    os.makedirs(target_dir, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".write", dir=target_dir)
    os.close(fd)
    return temp_path


def backup_existing_file(path: str, backup_root: str = ".backups") -> str:
    """Copy the existing file to a timestamped backup path and return it."""
    if not path or not os.path.isfile(path):
        return ""

    abs_path = os.path.abspath(path)
    root_dir = os.getcwd()
    try:
        rel_path = os.path.relpath(abs_path, root_dir)
        if rel_path.startswith(".."):
            rel_path = os.path.basename(abs_path)
    except ValueError:
        rel_path = os.path.basename(abs_path)

    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    rel_dir = os.path.dirname(rel_path)
    stem, ext = os.path.splitext(os.path.basename(rel_path))
    backup_dir = os.path.join(root_dir, backup_root, rel_dir)
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, f"{stem}.{timestamp}{ext or '.bak'}")
    shutil.copy2(abs_path, backup_path)
    return backup_path


def file_change_token(path: str):
    """Return a cache token that changes when file content changes."""
    if not path or not os.path.exists(path):
        return (0, 0)
    stat = os.stat(path)
    return (getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)), stat.st_size)


def _replace_with_retry(temp_path: str, target_path: str, attempts: int = 8, delay: float = 0.25) -> None:
    last_error = None
    for attempt in range(attempts):
        try:
            os.replace(temp_path, target_path)
            return
        except OSError as e:
            last_error = e
            if getattr(e, "winerror", None) not in (5, 32) or attempt == attempts - 1:
                break
            time.sleep(delay)

    raise PermissionError(
        f"无法写入文件：{target_path}。该文件可能正被 Excel/WPS、编辑器、杀毒软件或另一个程序占用；"
        "请关闭占用后重试。"
    ) from last_error


def atomic_write_text(path: str, content: str, encoding: str = "utf-8", backup: bool = False) -> None:
    """Write text by replacing the target only after the temp file is complete."""
    if backup:
        backup_existing_file(path)
    temp_path = _same_filesystem_temp_path(path)
    try:
        with open(temp_path, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def atomic_write_csv_rows(path: str, fieldnames, rows, encoding: str = "utf-8-sig", backup: bool = False) -> None:
    if backup:
        backup_existing_file(path)
    temp_path = _same_filesystem_temp_path(path)
    try:
        with open(temp_path, "w", encoding=encoding, newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
