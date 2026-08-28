"""Question-level helpers shared by the Streamlit UI and future API layer."""

from __future__ import annotations

import hashlib
import itertools
import os
import re
import unicodedata
from difflib import SequenceMatcher

from services.file_service import atomic_write_text
from services.operation_log import record_operation
from utils.core_config import CHAPTERS_DIR
from utils.csv_ops import CSV_HEADERS, add_to_csv_index, read_csv_index


ID_FIELD = CSV_HEADERS[0]
NAME_FIELD = CSV_HEADERS[1]
PATH_FIELD = CSV_HEADERS[2]
TYPE_FIELD = CSV_HEADERS[10]
SUBJECT_FIELD = CSV_HEADERS[7]
STEM_FIELD = CSV_HEADERS[20]

_LABEL_BLOCK_RE = re.compile(
    r"%(?: === Meta Data ===| === Begin Label Data ===)\r?\n"
    r".*?%(?: === End Meta ===| === End\s+Label Data ===)\r?\n",
    re.DOTALL,
)
_PROBLEM_RE = re.compile(
    r"\\begin\{problem\}(?:\[[^\]]*\])?(?:\s*\{[^\}]*\}){0,5}\s*"
    r"([\s\S]*?)\\end\{problem\}",
    re.DOTALL,
)
_ANSWER_RE = re.compile(r"\\begin\{answer\}[\s\S]*?\\end\{answer\}", re.DOTALL)
_SOLUTIONS_RE = re.compile(r"\\begin\{solutions?\}[\s\S]*?\\end\{solutions?\}", re.DOTALL)
_COMMENT_RE = re.compile(r"(?m)(?<!\\)%[^\r\n]*$")


class QuestionDuplicateError(ValueError):
    """Raised when a create operation finds an existing identical statement."""

    def __init__(self, matches: list[dict]):
        self.matches = matches
        super().__init__("duplicate question statement")


def extract_question_stem(content: str) -> str:
    """Extract only the problem statement used for duplicate comparison."""
    clean = _LABEL_BLOCK_RE.sub("", content or "")
    match = _PROBLEM_RE.search(clean)
    stem = match.group(1) if match else clean
    if not match:
        stem = re.sub(r"^\s*(?:\{[^{}]*\}\s*){1,5}", "", stem)
    stem = _ANSWER_RE.sub("", stem)
    stem = _SOLUTIONS_RE.sub("", stem)
    return stem.strip()


def normalize_question_text(content: str) -> str:
    """Normalize harmless LaTeX/layout differences without changing meaning."""
    text = extract_question_stem(content)
    text = _COMMENT_RE.sub("", text)
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\\(?:left|right)\b", "", text)
    text = re.sub(r"\\(?:!|,|;|:|quad|qquad|enspace)\b", "", text)
    text = re.sub(r"\\hspace\s*\{[^{}]*\}", "", text)
    text = re.sub(r"\s+", "", text)
    return text.strip()


def question_fingerprint(content: str) -> str:
    normalized = normalize_question_text(content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def create_question_file(
    file_path: str,
    content: str,
    year: str,
    paper_type: str,
    paper_name: str,
    question_number: str,
    subject: str,
    allow_duplicate: bool = False,
) -> str:
    """Create a question file and index row as one guarded operation."""
    if not file_path:
        raise ValueError("question file path is required")
    if os.path.exists(file_path):
        raise FileExistsError(file_path)

    exact_matches = [
        match
        for match in find_duplicate_matches(content, similarity_threshold=0.96, max_results=5)
        if match.get("kind") == "exact"
    ]
    if exact_matches and not allow_duplicate:
        raise QuestionDuplicateError(exact_matches)

    atomic_write_text(file_path, content, backup=False)
    try:
        question_id = add_to_csv_index(
            file_path, content, year, paper_type, paper_name, question_number, subject
        )
    except Exception:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError:
            pass
        raise

    record_operation(
        "create_question",
        path=os.path.abspath(file_path),
        question_id=str(question_id or ""),
        details="question file and index row created",
    )
    return str(question_id or "")


def _row_path(row: dict) -> str:
    relative_path = str(row.get(PATH_FIELD, "") or "").strip()
    if not relative_path:
        return ""
    return os.path.abspath(os.path.join(CHAPTERS_DIR, relative_path.replace("/", os.sep)))


def _row_stem(row: dict) -> str:
    stem = str(row.get(STEM_FIELD, "") or "").strip()
    if stem:
        return normalize_question_text(stem)

    path = _row_path(row)
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as question_file:
            return normalize_question_text(question_file.read())
    except (OSError, UnicodeError):
        return ""


def _match_payload(row: dict, score: float, kind: str) -> dict:
    return {
        "kind": kind,
        "score": round(float(score), 4),
        "question_id": str(row.get(ID_FIELD, "") or ""),
        "name": str(row.get(NAME_FIELD, "") or ""),
        "path": _row_path(row),
        "relative_path": str(row.get(PATH_FIELD, "") or ""),
        "question_type": str(row.get(TYPE_FIELD, "") or ""),
        "subject": str(row.get(SUBJECT_FIELD, "") or ""),
    }


def _can_reach_similarity(left: str, right: str, threshold: float) -> bool:
    if not left or not right:
        return False
    shorter = min(len(left), len(right))
    longer = max(len(left), len(right))
    required_ratio = threshold / (2.0 - threshold)
    return shorter / longer >= required_ratio


def find_duplicate_matches(
    content: str,
    exclude_path: str = "",
    rows: list[dict] | None = None,
    similarity_threshold: float = 0.88,
    max_results: int = 20,
) -> list[dict]:
    """Return exact and highly similar existing questions for a candidate."""
    normalized = normalize_question_text(content)
    if not normalized:
        return []

    target_path = os.path.normcase(os.path.abspath(exclude_path)) if exclude_path else ""
    target_fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    matches = []
    for row in rows if rows is not None else read_csv_index():
        row_path = _row_path(row)
        if target_path and row_path and os.path.normcase(row_path) == target_path:
            continue
        candidate = _row_stem(row)
        if not candidate:
            continue
        candidate_fingerprint = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        if candidate_fingerprint == target_fingerprint:
            matches.append(_match_payload(row, 1.0, "exact"))
            continue

        if not _can_reach_similarity(normalized, candidate, similarity_threshold):
            continue
        matcher = SequenceMatcher(None, normalized, candidate, autojunk=False)
        if matcher.quick_ratio() < similarity_threshold:
            continue
        score = matcher.ratio()
        if score >= similarity_threshold:
            matches.append(_match_payload(row, score, "similar"))

    matches.sort(key=lambda item: (item["kind"] != "exact", -item["score"], item["name"]))
    return matches[:max_results]


def scan_duplicate_pairs(
    rows: list[dict] | None = None,
    similarity_threshold: float = 0.88,
    max_pairs: int = 200,
) -> list[dict]:
    """Scan the current index and return reviewable duplicate pairs."""
    source_rows = rows if rows is not None else read_csv_index()
    prepared = []
    exact_groups: dict[str, list[dict]] = {}
    for row in source_rows:
        normalized = _row_stem(row)
        if not normalized:
            continue
        fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        item = {"row": row, "normalized": normalized, "fingerprint": fingerprint}
        prepared.append(item)
        exact_groups.setdefault(fingerprint, []).append(item)

    pairs = []
    seen = set()

    def add_pair(left: dict, right: dict, score: float, kind: str) -> None:
        left_path = _row_path(left["row"])
        right_path = _row_path(right["row"])
        pair_key = tuple(sorted((left_path, right_path)))
        if not pair_key[0] or pair_key in seen or len(pairs) >= max_pairs:
            return
        seen.add(pair_key)
        pairs.append({
            "kind": kind,
            "score": round(float(score), 4),
            "left": _match_payload(left["row"], score, kind),
            "right": _match_payload(right["row"], score, kind),
        })

    for group in exact_groups.values():
        for left, right in itertools.combinations(group, 2):
            add_pair(left, right, 1.0, "exact")
            if len(pairs) >= max_pairs:
                return pairs

    for index, left in enumerate(prepared):
        if len(pairs) >= max_pairs:
            break
        for right in prepared[index + 1:]:
            if left["fingerprint"] == right["fingerprint"]:
                continue
            if not _can_reach_similarity(left["normalized"], right["normalized"], similarity_threshold):
                continue
            matcher = SequenceMatcher(None, left["normalized"], right["normalized"], autojunk=False)
            if matcher.quick_ratio() < similarity_threshold:
                continue
            score = matcher.ratio()
            if score >= similarity_threshold:
                add_pair(left, right, score, "similar")
                if len(pairs) >= max_pairs:
                    break

    pairs.sort(key=lambda item: (item["kind"] != "exact", -item["score"]))
    return pairs
