"""Create local runtime files that are intentionally excluded from Git."""

import csv
import os


LOG_CSV_HEADERS = ["BatchID", "Timestamp", "Action", "FileName", "FilePath"]


def ensure_log_csv(root_dir: str) -> str:
    """Create the batch-import log with its header when it is missing."""
    log_path = os.path.join(os.path.abspath(root_dir), "log.csv")
    if os.path.exists(log_path):
        return log_path

    try:
        with open(log_path, "x", newline="", encoding="utf-8") as csvfile:
            csv.DictWriter(csvfile, fieldnames=LOG_CSV_HEADERS).writeheader()
    except FileExistsError:
        pass

    return log_path


if __name__ == "__main__":
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print(f"日志文件已就绪：{ensure_log_csv(project_root)}")
