import base64
import io
import json
import os
import re
import unicodedata
from pathlib import Path

_VERSION_SEGMENT_RE = re.compile(r"/v\d+(?:\.\d+)?/?$")
_LEADING_QUESTION_NUMBER_RE = re.compile(
    r"^\s*(?:第\s*\d+\s*题\s*[.．、:：]?|\d+\s*[.．、])\s*"
)
_LEADING_CHOICE_LABEL_RE = re.compile(
    r"^\s*(?:[A-Ha-h]\s*[.．、:：)]|[（(]\s*[A-Ha-h]\s*[）)])\s*"
)
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_LATEX_COMMAND_RE = re.compile(r"\\(?:frac|dfrac|tfrac|sqrt|sin|cos|tan|log|ln|lim|sum|prod|int|"
                               r"vec|overrightarrow|overline|underline|left|right|begin|end|"
                               r"mathbb|mathrm|operatorname|cdot|times|div|pm|geq?|leq?|neq|infty|pi|theta|alpha|beta|gamma)\b")
_MATH_TOKEN_RE = re.compile(r"(?:[A-Za-z0-9]|[=+\-*/^_<>≤≥≠±×÷∈∉∪∩∞πθ])")
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_OCR_PROMPT_PATH = _PROJECT_ROOT / "ocr_prompt.txt"
_IMAGE_MARKER_RE = re.compile(r"\[IMAGE:\s*([A-Za-z0-9_-]+)\]")
_QUESTION_ASSET_RE = re.compile(r"\\questionasset\{([^{}]+)\}")
_INLINE_CHOICE_LABEL_RE = re.compile(r"(?<![A-Za-z])([A-Da-d])[.．、:：)]\s*")
_INLINE_MATH_RUN_RE = re.compile(
    r"(?<![A-Za-z0-9$])([A-Za-z][A-Za-z0-9_]*(?:\([^$，,。；;]*\))?\s*[=<>≤≥≠±+\-*/^_]\s*[A-Za-z0-9\\{}().,]+(?:\s*[=<>≤≥≠±+\-*/^_]\s*[A-Za-z0-9\\{}().,]+)*)(?![A-Za-z0-9$])"
)


def normalize_chat_completions_url(base_url: str) -> str:
    override = os.getenv("AI_CHAT_COMPLETIONS_URL", "").strip()
    if override:
        return override
    url = (base_url or "").rstrip("/")
    if "/chat/completions" in url:
        return url
    if not _VERSION_SEGMENT_RE.search(url) and "/v1" not in url:
        url += "/v1"
    return url + "/chat/completions"


def post_chat_completion(base_url: str, headers: dict, payload: dict, timeout):
    import requests

    url = normalize_chat_completions_url(base_url)
    print(f"[AI] chat completions 最终请求 URL: {url}")
    return requests.post(url, headers=headers, json=payload, timeout=timeout), url


def extract_json_obj_from_text(text: str):
    if text is None:
        raise ValueError("empty response")
    cleaned = str(text).replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except Exception:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            raise
        return json.loads(match.group(0))


def _load_shared_ocr_typesetting_rules() -> str:
    fallback = (
        "行内公式使用 $...$，行间公式使用 $$...$$，禁止使用 \\(\\) 或 \\[\\]；"
        "分式使用 \\displaystyle；数学括号使用 \\left 与 \\right；"
        "公式与中文之间保留空格，公式后的句号使用英文句号。"
    )
    if not _OCR_PROMPT_PATH.is_file():
        return fallback
    try:
        prompt = _OCR_PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return fallback
    match = re.search(
        r"【3\.\s*数学排版红线[^】]*】([\s\S]*?)(?=【4\.)",
        prompt,
    )
    return match.group(1).strip() if match else fallback


def _normalize_tex_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return (
        text.replace("\\(", "$")
        .replace("\\)", "$")
        .replace("\\[", "$$")
        .replace("\\]", "$$")
    )


def _looks_like_standalone_math(text: str) -> bool:
    return bool(_LATEX_COMMAND_RE.search(text) or _MATH_TOKEN_RE.search(text)) and not _CJK_RE.search(text)


def _normalize_choice_tex(value: object) -> str:
    text = _LEADING_CHOICE_LABEL_RE.sub("", _normalize_tex_text(value), count=1).strip()
    if text and "$" not in text and _looks_like_standalone_math(text):
        return f"${text}$"
    return text


def _extract_inline_labeled_choices(stem: str) -> tuple[str, list[str]]:
    """Recover A-D choices when a weak OCR result flattened them into one line."""
    matches = list(_INLINE_CHOICE_LABEL_RE.finditer(stem or ""))
    if len(matches) < 2 or matches[0].start() == 0:
        return stem, []
    prefix = stem[: matches[0].start()].rstrip(" ，,；;：:")
    choices = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(stem)
        value = stem[start:end].strip(" ，,；;。")
        if value:
            choices.append(value)
    return prefix, choices if len(choices) >= 2 else []


def _wrap_inline_math_fragments(text: str) -> str:
    """Add math delimiters to simple OCR formula runs inside Chinese text."""
    if not text or "$" in text:
        return text

    def replace(match: re.Match[str]) -> str:
        value = match.group(1).strip()
        return f"${value}$" if _looks_like_standalone_math(value) else value

    return _INLINE_MATH_RUN_RE.sub(replace, text)


def normalize_question_structure_result(data: dict, *, question_number: str = "") -> dict:
    normalized = dict(data or {})
    stem = _normalize_tex_text(normalized.get("stem_tex"))
    stem = _LEADING_QUESTION_NUMBER_RE.sub("", stem, count=1).strip()
    if not normalized.get("choices"):
        stem, recovered_choices = _extract_inline_labeled_choices(stem)
        if recovered_choices:
            normalized["choices"] = recovered_choices
    if stem and "$" not in stem and _looks_like_standalone_math(stem):
        stem = f"${stem}$"
    elif stem and "$" not in stem:
        stem = _wrap_inline_math_fragments(stem)
    raw_choices = normalized.get("choices") or []
    normalized["stem_tex"] = stem
    normalized["choices"] = [
        choice
        for choice in (_normalize_choice_tex(item) for item in raw_choices)
        if choice
    ]
    normalized["answer_tex"] = _normalize_tex_text(normalized.get("answer_tex"))
    normalized["solution_tex"] = _normalize_tex_text(normalized.get("solution_tex"))
    normalized["recognizer_version"] = 2
    return normalized


def ensure_question_asset_placeholders(stem: str, assets: list[dict] | None) -> tuple[str, list[str]]:
    """Convert parser markers and recover references omitted by older AI results."""
    text = _IMAGE_MARKER_RE.sub(lambda match: f"\\questionasset{{{match.group(1)}}}", str(stem or ""))
    existing = set(_QUESTION_ASSET_RE.findall(text))
    appended: list[str] = []
    for asset in assets or []:
        alias = str(asset.get("alias") or "").strip()
        if not alias:
            extra = asset.get("extra") if isinstance(asset.get("extra"), dict) else {}
            alias = str(extra.get("alias") or asset.get("caption") or "").strip()
        if alias and alias not in existing:
            text = f"{text.rstrip()}\n\n\\questionasset{{{alias}}}".strip()
            existing.add(alias)
            appended.append(alias)
    return text, appended


def recognize_question_structure(
    image_paths: list[str],
    *,
    extracted_text: str = "",
    question_number: str = "",
    allowed_topics: list[str] | None = None,
    image_markers: list[str] | None = None,
    timeout: int = 180,
) -> dict:
    api_key = os.getenv("AI_API_KEY", "").strip()
    base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").strip()
    model_name = os.getenv("AI_MODEL_NAME", "").strip()
    if not api_key or not base_url or not model_name:
        return {"error": "AI 配置不完整，请先配置识图模型。"}
    # Long questions may span several PDF pages. Keep enough page crops to
    # preserve the complete statement while still bounding request size.
    valid_paths = [Path(path) for path in image_paths if Path(path).is_file()][:8]
    if not valid_paths:
        return {"error": "当前题没有可供 AI 识别的逐题裁剪图。"}
    topic_options = [str(item).strip() for item in allowed_topics or [] if str(item).strip()]
    topic_rule = (
        f"knowledge_topics 必须选择 1-2 个且只能来自：{'、'.join(topic_options)}。不能确定时选择“未分类”。"
        if topic_options
        else "knowledge_topics 返回 1-2 个高中数学知识板块。"
    )
    shared_typesetting_rules = _load_shared_ocr_typesetting_rules()
    marker_values = [str(item).strip() for item in image_markers or [] if str(item).strip()]
    image_rule = (
        "题干中出现的图片标记必须原样保留，不能翻译、删除或改名："
        + ", ".join(f"[IMAGE: {item}]" for item in marker_values)
        + "。图片由程序绑定，禁止自行创造文件名。"
        if marker_values
        else "如果题目图片已在题干中出现，不要虚构图片文件名。"
    )
    extracted_text = f"{extracted_text}\n\n{image_rule}"
    prompt = f"""你是高中数学试题结构化转写助手。只识别目标题号 {question_number or '未知'} 对应的一道题。
图片已经由程序裁剪，你不得判断或修改裁剪坐标，不得识别相邻题。
逐字转写，不解题、不推测缺失答案、不补写解析。数学表达式转换为 LaTeX。
stem_tex 不得保留开头的题号（例如“4.”或“第4题”）。
stem_tex 必须从裁剪图最上方开始完整覆盖题干正文；如果图片同时包含题干、选项、答案或解析，必须先完整转写题干，再输出 choices、answer_tex 和 solution_tex，禁止只返回选项或后半部分内容。
所有数学表达式必须使用标准 LaTeX 并完整放在 $...$ 中；每个 choices 项必须能够单独正确渲染。
不得输出 Unicode 数学斜体字符（例如 𝑥、𝑦、𝑎），应写成普通 LaTeX 变量 x、y、a。
不得使用 Markdown 代码块。忠实保留原题内容，不改写、不求解。

以下内容读取自项目根目录 ocr_prompt.txt，是本项目统一的数学排版规则：
{shared_typesetting_rules}

本次只复用上述规则中的数学内容与排版要求。忽略其中关于文件名、problem/answer/solutions 环境、
choices 环境和完整 TeX 文档的输出要求；本次必须按下方 JSON 字段返回。
输出前必须进行第二遍结构校验：
1. 先确认图片中只有当前题，不把页眉、页脚、大题标题、相邻题目或题号写进 stem_tex；
2. 再确认选择题的每个选项完整独立，去掉 A/B/C/D 前缀；若不是选择题，choices 必须为空数组；
3. 最后确认所有公式已经转换为 LaTeX，不能把 OCR 原始字符、Unicode 数学斜体或未转义的特殊字符直接输出；
4. 只抄录图片中实际存在的答案和解析，图片没有时 answer_tex 与 solution_tex 必须为空，严禁自行解题；
5. 保留题目小问、分段、标点和图片引用。图片引用只能使用已提供的图片别名，并写成 \\questionasset{{alias}}。
JSON 字段只承载内容，不要把 `\\begin{{problem}}`、`\\begin{{choices}}`、文件名或 Markdown 代码块放入字段；程序会在入库预览时组装外层结构。
参考提取文本如下，仅用于辅助辨认，图片内容优先：
{extracted_text[:6000]}

严格返回 JSON 对象：
{{"question_type_id":1,"stem_tex":"","choices":[],"answer_tex":"","solution_tex":"","knowledge_topics":[],"difficulty":null,"tags":[]}}
question_type_id：1 单选，2 多选，3 填空，4 解答/证明，5 其他，6 判断题。判断题即使没有 choices，也必须返回 6。
{topic_rule}
choices 每项只放选项正文，不带 A/B/C/D，不带 \\choice 命令；选项内公式仍必须用 $...$ 包裹。
图片没有答案或解析时，对应字段必须为空。"""
    try:
        from PIL import Image

        content = [{"type": "text", "text": prompt}]
        for path in valid_paths:
            with Image.open(path) as source:
                image = source.convert("RGB")
                if max(image.size) > 2400:
                    ratio = 2400 / max(image.size)
                    image = image.resize(
                        (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
                        Image.Resampling.LANCZOS,
                    )
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=88)
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}", "detail": "high"}})
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.0,
            "max_tokens": 6000,
            "response_format": {"type": "json_object"},
        }
        response, _ = post_chat_completion(
            base_url,
            {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            payload,
            timeout=timeout,
        )
        if response.status_code != 200:
            return {"error": f"AI 识别失败（HTTP {response.status_code}）：{response.text[:300]}"}
        body = response.json()
        choices = body.get("choices") or []
        if not choices:
            return {"error": "AI 没有返回有效结果。"}
        data = extract_json_obj_from_text(choices[0].get("message", {}).get("content", ""))
        question_type_id = data.get("question_type_id")
        try:
            question_type_id = int(question_type_id)
        except (TypeError, ValueError):
            question_type_id = 5
        difficulty = data.get("difficulty")
        try:
            difficulty = int(difficulty) if difficulty not in (None, "") else None
        except (TypeError, ValueError):
            difficulty = None
        raw_topics = data.get("knowledge_topics") or data.get("topics") or data.get("topic") or []
        if isinstance(raw_topics, str):
            raw_topics = [item.strip() for item in re.split(r"[，,、/|与]+", raw_topics) if item.strip()]
        normalized_topics = []
        for raw_topic in raw_topics if isinstance(raw_topics, list) else []:
            topic = str(raw_topic).strip()
            if not topic:
                continue
            match = next((option for option in topic_options if topic == option), "")
            if not match:
                match = next((option for option in topic_options if option != "未分类" and option in topic), "")
            if match and match not in normalized_topics:
                normalized_topics.append(match)
        if topic_options and not normalized_topics:
            normalized_topics = ["未分类"] if "未分类" in topic_options else [topic_options[-1]]
        result = {
            "question_type_id": question_type_id if question_type_id in {1, 2, 3, 4, 5, 6} else 5,
            "stem_tex": str(data.get("stem_tex") or "").strip(),
            "choices": [str(item).strip() for item in data.get("choices") or [] if str(item).strip()],
            "answer_tex": str(data.get("answer_tex") or "").strip(),
            "solution_tex": str(data.get("solution_tex") or "").strip(),
            "topics": normalized_topics[:2],
            "topic": "，".join(normalized_topics[:2]),
            "difficulty": difficulty if difficulty in {1, 2, 3, 4, 5} else None,
            "tags": [str(item).strip() for item in data.get("tags") or [] if str(item).strip()],
            "model_name": model_name,
        }
        normalized = normalize_question_structure_result(result, question_number=question_number)
        normalized["image_markers"] = marker_values
        return normalized
    except Exception as exc:
        return {"error": f"AI 逐题识别失败：{exc}"}


def recognize_document_page_tex(
    image_path: str | Path,
    *,
    page_number: int = 1,
    question_numbers: list[str] | None = None,
    timeout: int = 240,
) -> dict:
    """Recognize one rendered PDF page in one request.

    The response is intentionally full legacy TeX so a page containing several
    questions costs one vision request while retaining the existing parser and
    review workflow.
    """
    api_key = os.getenv("AI_API_KEY", "").strip()
    base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").strip()
    model_name = os.getenv("AI_MODEL_NAME", "").strip()
    path = Path(image_path)
    if not api_key or not base_url or not model_name:
        return {"error": "AI 配置不完整，请先配置识图模型。"}
    if not path.is_file():
        return {"error": f"PDF 页面图片不存在：{path}"}
    shared_typesetting_rules = _load_shared_ocr_typesetting_rules()
    number_text = "、".join(str(item) for item in question_numbers or [] if str(item).strip()) or "该页所有题目"
    prompt = f"""你是高中数学试卷的整页 OCR 与 LaTeX 转写助手。
当前图片是 PDF 第 {page_number} 页。请一次性识别本页所有完整或部分出现的题目，题号范围参考：{number_text}。
必须逐题输出完整的 legacy TeX 块，多个题目必须分别输出，禁止合并：
---[题号].tex---
\\begin{{problem}}{{年份}}{{类别}}{{试卷名称}}{{题号}}{{知识板块}}
题干与选项
\\end{{problem}}
\\begin{{answer}}
图片中存在的答案，没有则留空
\\end{{answer}}
\\begin{{solutions}}
图片中存在的解析，没有则留空
\\end{{solutions}}

严格要求：
- 只转写图片中出现的内容，不解题、不补答案、不补解析；
- 忽略页眉、页脚、页码、试卷说明和大题标题；
- 一道题若跨页，只输出本页能看到的内容，不要猜测另一页内容；
- 选择题必须使用 \\begin{{choices}} 与 \\choice{{{{...}}}}，不能写 A/B/C/D 前缀；
- 所有数学公式必须使用标准 LaTeX，并按统一规则使用 $...$ 或 $$...$$；
- 禁止 Markdown 代码块，禁止输出 JSON，禁止在 TeX 外添加解释；
- 题号必须保留在 problem 头中，但题干正文不能重复题号。

统一数学排版规则：
{shared_typesetting_rules}
"""
    try:
        from PIL import Image

        with Image.open(path) as source:
            image = source.convert("RGB")
            if max(image.size) > 2400:
                ratio = 2400 / max(image.size)
                image = image.resize((max(1, int(image.width * ratio)), max(1, int(image.height * ratio))), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=90)
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"}},
        ]
        response, _ = post_chat_completion(
            base_url,
            {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            {"model": model_name, "messages": [{"role": "user", "content": content}], "temperature": 0.0, "max_tokens": 12000},
            timeout=timeout,
        )
        if response.status_code != 200:
            return {"error": f"AI 页面识别失败（HTTP {response.status_code}）：{response.text[:500]}"}
        choices = response.json().get("choices") or []
        if not choices:
            return {"error": "AI 页面识别没有返回有效内容。"}
        message = choices[0].get("message") or {}
        content_text = message.get("content") or ""
        if isinstance(content_text, list):
            content_text = "".join(str(item.get("text") or "") for item in content_text if isinstance(item, dict))
        return {"tex": str(content_text).replace("```latex", "").replace("```tex", "").replace("```", "").strip(), "page_number": page_number, "model_name": model_name}
    except Exception as exc:
        return {"error": f"AI 页面识别失败：{exc}"}
