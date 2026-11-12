"""Shared local similarity rules for duplicate detection and recommendations.

The thresholds and score shape follow the GaokaoWeb bind-similar algorithm.
This module deliberately has no database or UI dependency so every import path
can use the same result, including offline installations.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from collections import Counter
from typing import Any


SIM_MIN_LEN = 12
SIM_MAX_LEN_RATIO = 8.0
SIM_CHOICE_TYPES = {1, 2, 11, 12}
SIM_MAIN_THRESHOLD = 0.60
SIM_SUB_THRESHOLD = 0.40
SIM_PREFIX_THRESHOLD = 0.55

# Commands whose mathematical meaning must survive normalization. Removing
# these commands would make e.g. ``\\cap`` and ``\\cup`` falsely identical.
SENSITIVE_LATEX_COMMANDS = {
    "cap", "cup", "in", "notin", "subset", "subseteq", "supset", "supseteq",
    "parallel", "perp", "le", "leq", "ge", "geq", "neq", "ne", "approx",
    "sim", "equiv", "cong", "infty", "pm", "mp", "times", "cdot", "div",
}

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_VARIABLE_RE = re.compile(r"[A-Za-z]+")
_GREEK_COMMANDS = {
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "theta", "vartheta",
    "lambda", "mu", "nu", "xi", "pi", "varpi", "rho", "sigma", "tau", "phi",
    "varphi", "psi", "omega",
}
_NON_VARIABLE_WORDS = {
    "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan",
    "sinh", "cosh", "tanh", "log", "lg", "ln", "lim", "max", "min", "exp",
    "det", "dim", "mod", "sup", "inf", "arg", "ker", "deg", "cdot", "times",
    "left", "right", "begin", "end", "text", "mathrm", "mathbf", "mathbb",
    "frac", "dfrac", "tfrac", "sqrt", "overline", "underline", "boldsymbol",
}
_TEXT_COMMAND_RE = re.compile(r"\\(?:text|textrm|textsf|texttt|mbox|operatorname)\s*\{[^{}]*\}")
_RELATION_RE = re.compile(
    r"\\(?:leqslant|geqslant|notin|subseteq|supseteq|parallel|perp|neq|leq|geq|le|ge|ne|in|subset|supset)"
    r"(?![A-Za-z])|<=|>=|!=|==|<|>|=|≤|≥|≠|≈|∈|∉|⊂|⊆|⊃|⊇|∥|⊥"
)
_RELATION_ALIASES = {
    r"\le": "<=", r"\leq": "<=", r"\leqslant": "<=", "≤": "<=",
    r"\ge": ">=", r"\geq": ">=", r"\geqslant": ">=", "≥": ">=",
    r"\ne": "!=", r"\neq": "!=", "≠": "!=",
    r"\in": "∈", "∈": "∈", r"\notin": "∉", "∉": "∉",
    r"\subset": "⊂", "⊂": "⊂", r"\subseteq": "⊆", "⊆": "⊆",
    r"\supset": "⊃", "⊃": "⊃", r"\supseteq": "⊇", "⊇": "⊇",
    r"\parallel": "∥", "∥": "∥", r"\perp": "⊥", "⊥": "⊥",
}
_CONDITION_RE = re.compile(
    r"\\(?:forall|exists|nexists)"
    r"|有且仅有|对任意|不存在|不超过|不少于|不大于|不小于|"
    r"至少(?:一个|一)?|至多(?:一个|一)?|任意|任一|所有|每个|存在"
)
_INTERVAL_MEMBERSHIP_RE = re.compile(
    r"(?:\\in|∈)\s*([\[(])\s*([^,]+?)\s*,\s*([^\]\)]+?)\s*([\]\)])"
)
_CONDITION_ALIASES = {
    r"\forall": "对任意", r"\exists": "存在", r"\nexists": "不存在",
    "至少一": "至少", "至少一个": "至少", "至多一": "至多", "至多一个": "至多",
}
_COMMAND_RE = re.compile(r"\\([A-Za-z@]+)")
_IMAGE_COMMAND_RE = re.compile(
    r"\\(?:includegraphics|questionasset|includeimage|asset)\s*"
    r"(?:\[[^\]]*\])?\s*(?:\{[^{}]*\})?",
    re.IGNORECASE,
)
_IMAGE_ENV_RE = re.compile(
    r"\\begin\{(?:figure|centerimage|image)\}[\s\S]*?\\end\{(?:figure|centerimage|image)\}",
    re.IGNORECASE,
)
_LAYOUT_COMMAND_RE = re.compile(
    r"\\(?:underline|hspace|vspace|rule|makebox|mbox)\*?\s*"
    r"(?:\[[^\]]*\])?\s*\{[^{}]*\}",
    re.IGNORECASE,
)
_COMMENT_RE = re.compile(r"(?m)(?<!\\)%[^\r\n]*$")
_SUBQUESTION_RE = re.compile(r"(?=(?:\s*[（(]\s*\d+\s*[）)]|\s*\\item\b))")


def _choice_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, dict):
        return [str(value[key]).strip() for key in sorted(value) if str(value[key]).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        return _choice_values(parsed)
    return [str(value).strip()] if str(value).strip() else []


def normalize_similarity_text(value: Any) -> tuple[str, int]:
    """Return normalized text and the number of image placeholders.

    Image paths are intentionally discarded, but image presence is preserved.
    This prevents a text-only question from being marked exact with a diagram
    question while keeping renamed assets equivalent.
    """
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = _COMMENT_RE.sub("", text)
    image_count = 0

    def replace_image(match: re.Match) -> str:
        nonlocal image_count
        image_count += 1
        return " IMAGE "

    text = _IMAGE_ENV_RE.sub(replace_image, text)
    text = _IMAGE_COMMAND_RE.sub(replace_image, text)
    text = _LAYOUT_COMMAND_RE.sub(" ", text)
    text = re.sub(r"\\(?:begin|end)\s*\{[^{}]*\}", " ", text)
    text = _COMMAND_RE.sub(
        lambda match: f" {match.group(1).lower()} "
        if match.group(1).lower() in SENSITIVE_LATEX_COMMANDS
        else " ",
        text,
    )
    # Keep operators and formula markers, remove layout punctuation. The
    # placeholder is alphabetic so it remains visible after this step.
    text = re.sub(r"[{}()（）\[\]．。，,；;：:、\\]", " ", text)
    text = re.sub(r"\s+", "", text)
    return text.strip(), image_count


def extract_similarity_payload(
    stem: Any,
    choices: Any = None,
    question_type_id: Any = None,
) -> dict[str, Any]:
    """Prepare stem/full text and lightweight features for one question."""
    choice_values = _choice_values(choices)
    try:
        type_id = int(question_type_id) if question_type_id not in (None, "") else None
    except (TypeError, ValueError):
        type_id = None
    cached = _prepared_payload(str(stem or ""), tuple(choice_values), type_id)
    return {**cached, "choices": list(cached["choices"])}


@lru_cache(maxsize=32768)
def _prepared_payload(stem, choice_values, type_id):
    stem_norm, image_count = normalize_similarity_text(stem)
    full_raw = str(stem or "")
    if type_id in SIM_CHOICE_TYPES or choice_values:
        full_raw = "\n".join([full_raw, *choice_values])
    full_norm, full_image_count = normalize_similarity_text(full_raw)
    return {
        "stem_raw": str(stem or ""),
        "full_raw": full_raw,
        "stem_norm": stem_norm,
        "full_norm": full_norm,
        "image_count": image_count,
        "full_image_count": full_image_count,
        "choices": choice_values,
        "question_type_id": type_id,
    }


@lru_cache(maxsize=32768)
def _exact_text_signature(value: str) -> str:
    # Exact classification ignores only known presentation differences.
    # Ranking normalization intentionally discards more information.
    text = _COMMENT_RE.sub("", unicodedata.normalize("NFKC", value))
    text = re.sub(r"\\(?:dfrac|tfrac)(?![A-Za-z])", lambda _: r"\frac", text)
    text = re.sub(r"\\(?:left|right)(?![A-Za-z])", "", text)
    return re.sub(r"\s+", "", text)


def _choice_signature(values: list[str]) -> tuple[str, ...]:
    return tuple(_exact_text_signature(value) for value in values)


def _semantic_differences(left: dict[str, Any], right: dict[str, Any]) -> list[dict[str, Any]]:
    """Explain high-value content changes without interpreting their math."""
    differences: list[dict[str, Any]] = []
    left_numbers = Counter(_NUMBER_RE.findall(left["stem_raw"]))
    right_numbers = Counter(_NUMBER_RE.findall(right["stem_raw"]))
    if left_numbers != right_numbers:
        only_left = list((left_numbers - right_numbers).elements())
        only_right = list((right_numbers - left_numbers).elements())
        differences.append({"kind": "numbers", "left": only_left[:8], "right": only_right[:8]})

    def symbols(pattern: re.Pattern[str], text: str, aliases: dict[str, str]) -> Counter[str]:
        return Counter(aliases.get(match.group(0), match.group(0)) for match in pattern.finditer(text))

    left_relations = symbols(_RELATION_RE, left["stem_raw"], _RELATION_ALIASES)
    right_relations = symbols(_RELATION_RE, right["stem_raw"], _RELATION_ALIASES)
    if left_relations != right_relations:
        differences.append({
            "kind": "relations",
            "left": list((left_relations - right_relations).elements())[:8],
            "right": list((right_relations - left_relations).elements())[:8],
        })

    left_conditions = symbols(_CONDITION_RE, left["stem_raw"], _CONDITION_ALIASES)
    right_conditions = symbols(_CONDITION_RE, right["stem_raw"], _CONDITION_ALIASES)
    if left_conditions != right_conditions:
        differences.append({
            "kind": "conditions",
            "left": list((left_conditions - right_conditions).elements())[:6],
            "right": list((right_conditions - left_conditions).elements())[:6],
        })

    def intervals(text: str) -> list[tuple[str, str, str, str]]:
        result = []
        for match in _INTERVAL_MEMBERSHIP_RE.finditer(text):
            start, _ = normalize_similarity_text(match.group(2))
            end, _ = normalize_similarity_text(match.group(3))
            result.append((match.group(1), start, end, match.group(4)))
        return result

    left_intervals = intervals(left["stem_raw"])
    right_intervals = intervals(right["stem_raw"])
    if left_intervals != right_intervals:
        differences.append({
            "kind": "intervals", "left": [list(value) for value in left_intervals[:4]],
            "right": [list(value) for value in right_intervals[:4]],
        })

    def variable_symbols(text: str) -> set[str]:
        text = _TEXT_COMMAND_RE.sub(" ", text)
        greek = []

        def keep_greek(match: re.Match[str]) -> str:
            command = match.group(1)
            if command in _GREEK_COMMANDS:
                greek.append(command)
            return " "

        text = _COMMAND_RE.sub(keep_greek, text)
        symbols = {
            token for token in _VARIABLE_RE.findall(text)
            if token.lower() not in _NON_VARIABLE_WORDS and len(token) == 1
        }
        return symbols | set(greek)

    left_variables = variable_symbols(left["stem_raw"])
    right_variables = variable_symbols(right["stem_raw"])
    if left_variables != right_variables:
        differences.append({
            "kind": "variables",
            "left": sorted(left_variables - right_variables)[:8],
            "right": sorted(right_variables - left_variables)[:8],
        })
    return differences


def _difference_reasons(differences: list[dict[str, Any]]) -> list[str]:
    labels = {
        "numbers": "数字内容存在变化",
        "variables": "变量符号集合存在变化",
        "relations": "关系符号有变化",
        "conditions": "条件词有变化",
        "intervals": "区间端点或开闭边界有变化",
        "image_count": "配图数量有变化",
        "visual_pending": "配图像素尚未比较，需人工查看",
    }
    return list(dict.fromkeys(labels[item["kind"]] for item in differences if item.get("kind") in labels))


@lru_cache(maxsize=65536)
def _bigrams(value: str) -> frozenset[str]:
    return frozenset(value[index:index + 2] for index in range(len(value) - 1))


def _bigram_stats(left: str, right: str) -> tuple[int, float, float]:
    left_set, right_set = _bigrams(left), _bigrams(right)
    if not left_set or not right_set:
        return 0, 0.0, 0.0
    intersection = len(left_set & right_set)
    union = len(left_set | right_set)
    containment = intersection / min(len(left_set), len(right_set))
    return intersection, intersection / union, containment


def _lcs_length(left: str, right: str) -> int:
    if not left or not right:
        return 0
    if len(left) > len(right):
        left, right = right, left
    # A bounded fallback keeps a malformed, extremely large draft from
    # blocking the Streamlit process while preserving the normal exact rule.
    if len(left) * len(right) > 12_000_000:
        common = Counter(left) & Counter(right)
        return sum(common.values())
    previous = [0] * (len(left) + 1)
    for right_char in right:
        current = [0]
        for index, left_char in enumerate(left, start=1):
            if left_char == right_char:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[-1]))
        previous = current
    return previous[-1]


def _ratio_cover(left: str, right: str) -> tuple[float, float]:
    if not left or not right:
        return 0.0, 0.0
    lcs = _lcs_length(left, right)
    return 2.0 * lcs / (len(left) + len(right)), lcs / min(len(left), len(right))


def _number_agreement(left: str, right: str) -> float:
    left_numbers = {item for item in _NUMBER_RE.findall(left) if float(item) >= 4}
    right_numbers = {item for item in _NUMBER_RE.findall(right) if float(item) >= 4}
    if not left_numbers and not right_numbers:
        return 1.0
    if not left_numbers or not right_numbers:
        return 0.0
    common = left_numbers & right_numbers
    union = left_numbers | right_numbers
    return 0.7 * len(common) / len(union) + 0.3 * (1 - 0.5 ** len(common))


def _mode_score(left_norm: str, right_norm: str, left_raw: str, right_raw: str) -> dict[str, Any] | None:
    if min(len(left_norm), len(right_norm)) < SIM_MIN_LEN:
        return None
    if max(len(left_norm), len(right_norm)) / min(len(left_norm), len(right_norm)) > SIM_MAX_LEN_RATIO:
        return None
    intersection, jaccard, containment = _bigram_stats(left_norm, right_norm)
    if intersection < 6 or (jaccard < 0.4 and containment < 0.8):
        return None
    ratio, cover = _ratio_cover(left_norm, right_norm)
    numf = _number_agreement(left_raw, right_raw)
    adjusted = ratio * (0.6 + 0.4 * numf)
    template_left = _NUMBER_RE.sub("#", left_norm)
    template_right = _NUMBER_RE.sub("#", right_norm)
    template_score, _ = _ratio_cover(template_left, template_right)
    return {
        "score": adjusted,
        "ratio": ratio,
        "cover": cover,
        "numf": numf,
        "bigram_intersection": intersection,
        "bigram_jaccard": jaccard,
        "bigram_containment": containment,
        "template_score": template_score,
    }


def _prefix_parts(raw: str) -> list[str]:
    parts = [part.strip() for part in _SUBQUESTION_RE.split(str(raw or "")) if part.strip()]
    return parts if len(parts) >= 2 else []


def _prefix_score(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    left_parts, right_parts = _prefix_parts(left["stem_raw"]), _prefix_parts(right["stem_raw"])
    if not left_parts or not right_parts:
        return None
    if len(left_parts) > len(right_parts):
        left_parts, right_parts = right_parts, left_parts
    left_raw = "\n".join(left_parts)
    right_raw = "\n".join(right_parts[: len(left_parts)])
    left_norm, _ = normalize_similarity_text(left_raw)
    right_norm, _ = normalize_similarity_text(right_raw)
    whole = _mode_score(left_norm, right_norm, left_raw, right_raw)
    if whole and whole["score"] >= SIM_PREFIX_THRESHOLD:
        whole = dict(whole)
        whole["channel"] = "前缀子题"
        return whole
    if len(left_parts) < 2:
        return None
    left_questions = "".join(left_parts[1:])
    right_questions = "".join(right_parts[1:len(left_parts)])
    left_q_norm, _ = normalize_similarity_text(left_questions)
    right_q_norm, _ = normalize_similarity_text(right_questions)
    if min(len(left_q_norm), len(right_q_norm)) < 6:
        return None
    question_ratio, _ = _ratio_cover(left_q_norm, right_q_norm)
    condition_left, _ = normalize_similarity_text(left_parts[0])
    condition_right, _ = normalize_similarity_text(right_parts[0])
    condition_ratio, _ = _ratio_cover(condition_left, condition_right)
    if question_ratio >= 0.85 and condition_ratio >= 0.35:
        return {
            "score": question_ratio,
            "ratio": question_ratio,
            "cover": 1.0,
            "numf": _number_agreement(left_questions, right_questions),
            "bigram_intersection": 0,
            "bigram_jaccard": 0.0,
            "bigram_containment": 0.0,
            "template_score": question_ratio,
            "channel": "前缀子题",
        }
    return None


def score_question_pair(
    left_stem: Any,
    right_stem: Any,
    *,
    left_choices: Any = None,
    right_choices: Any = None,
    left_question_type_id: Any = None,
    right_question_type_id: Any = None,
    allow_sub: bool = False,
) -> dict[str, Any]:
    """Score one pair using the shared GaokaoWeb-compatible rule set."""
    left = extract_similarity_payload(left_stem, left_choices, left_question_type_id)
    right = extract_similarity_payload(right_stem, right_choices, right_question_type_id)
    same_stem = (
        left["stem_norm"]
        and left["stem_norm"] == right["stem_norm"]
        and left["image_count"] == right["image_count"]
    )
    question_types_match = left["question_type_id"] == right["question_type_id"]
    option_lists_match = _choice_signature(left["choices"]) == _choice_signature(right["choices"])
    choice_question = (
        left["question_type_id"] in SIM_CHOICE_TYPES
        or right["question_type_id"] in SIM_CHOICE_TYPES
        or bool(left["choices"])
        or bool(right["choices"])
    )
    visual_evidence_pending = left["full_image_count"] > 0 or right["full_image_count"] > 0
    choices_match = not choice_question or option_lists_match
    if same_stem and choices_match and question_types_match and not visual_evidence_pending:
        differences = _semantic_differences(left, right)
        if not differences and _exact_text_signature(left["stem_raw"]) == _exact_text_signature(right["stem_raw"]):
            return {
                "score": 1.0, "base_score": 1.0, "channel": "完全相同", "kind": "exact",
                "ratio": 1.0, "cover": 1.0, "numf": 1.0, "template_score": 1.0,
                "bigram_jaccard": 1.0, "bigram_containment": 1.0,
                "choice_mode": "stem", "reasons": ["题干归一化后完全一致"], "warnings": [],
                "differences": [],
            }
    if same_stem:
        differences = _semantic_differences(left, right)
        reasons = []
        warnings = []
        if choice_question and not option_lists_match:
            reasons.append("题干完全相同，但选择题选项内容或顺序不同")
            changed_positions = [index + 1 for index, pair in enumerate(zip(
                _choice_signature(left["choices"]), _choice_signature(right["choices"])
            )) if pair[0] != pair[1]]
            if len(left["choices"]) != len(right["choices"]):
                changed_positions.extend(range(min(len(left["choices"]), len(right["choices"])) + 1,
                                               max(len(left["choices"]), len(right["choices"])) + 1))
            differences.append({"kind": "choices", "positions": changed_positions[:8]})
            warnings.append("选择题选项差异会改变题意或正确选项，请人工对照")
        if not question_types_match:
            reasons.append("题干与内容相同，但题型标记不同")
        if visual_evidence_pending:
            reasons.append("题文相同但配图像素未参与比较")
            if left["full_image_count"] != right["full_image_count"]:
                differences.append({"kind": "image_count", "left": left["full_image_count"], "right": right["full_image_count"]})
            else:
                differences.append({"kind": "visual_pending"})
            warnings.append("检测到配图占位；图片路径不代表图片内容相同，请人工查看配图")
        reasons.extend(_difference_reasons(differences))
        if not reasons:
            reasons.append("题干相同，仍需人工核对元数据")
        return {
            "score": 1.0, "base_score": 1.0, "channel": "题干相同，需核对差异",
            "kind": "similar", "ratio": 1.0, "cover": 1.0, "numf": 1.0,
            "template_score": 1.0, "bigram_jaccard": 1.0, "bigram_containment": 1.0,
            "choice_mode": "stem+choices", "reasons": reasons,
            "warnings": warnings,
            "differences": differences,
        }
    candidates: list[dict[str, Any]] = []
    stem_score = _mode_score(left["stem_norm"], right["stem_norm"], left["stem_raw"], right["stem_raw"])
    if stem_score:
        stem_score["choice_mode"] = "stem"
        candidates.append(stem_score)
    if left["choices"] or right["choices"] or left["question_type_id"] in SIM_CHOICE_TYPES or right["question_type_id"] in SIM_CHOICE_TYPES:
        full_score = _mode_score(left["full_norm"], right["full_norm"], left["full_raw"], right["full_raw"])
        if full_score:
            full_score["choice_mode"] = "stem+choices"
            candidates.append(full_score)
    prefix_score = _prefix_score(left, right)
    if prefix_score:
        prefix_score["choice_mode"] = "stem"
        candidates.append(prefix_score)
    if candidates:
        best = max(candidates, key=lambda item: (item["score"], item.get("channel") == "前缀子题"))
        channel = best.get("channel") or ("主通道" if best["score"] >= SIM_MAIN_THRESHOLD else "")
        if not channel and allow_sub and best["score"] >= SIM_SUB_THRESHOLD and best["cover"] >= 0.7 and best["bigram_containment"] >= 0.7:
            channel = "疑似小问"
        if not channel:
            channel = "备选"
        result = dict(best)
        result.update({
            "base_score": best["score"], "score": best["score"], "channel": channel,
            "kind": "similar", "reasons": [], "warnings": [],
        })
        differences = _semantic_differences(left, right)
        if best["numf"] < 0.5:
            result["warnings"].append("数字不完全一致")
            result["reasons"].append("题型结构接近但数字存在差异")
        if best["template_score"] > best["ratio"] + 0.12:
            result["reasons"].append("去数字后的题型结构接近")
        result["differences"] = differences
        result["reasons"].extend(_difference_reasons(differences))
        if not result["reasons"]:
            result["reasons"].append("题干结构接近")
        return result
    return {
        "score": None, "base_score": None, "channel": "无法计算", "kind": "none",
        "ratio": 0.0, "cover": 0.0, "numf": None, "template_score": None,
        "bigram_jaccard": 0.0, "bigram_containment": 0.0,
        "choice_mode": "stem", "reasons": [],
        "differences": [],
        "warnings": ["题目过短、长度差异过大或未通过双字预筛"],
    }


def similarity_score(left_stem: Any, right_stem: Any, **kwargs: Any) -> float | None:
    """Convenience wrapper used by callers that only need a numeric score."""
    return score_question_pair(left_stem, right_stem, **kwargs).get("score")
