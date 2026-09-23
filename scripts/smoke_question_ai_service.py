from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import services.ai_service as ai_service


class FakeResponse:
    status_code = 200
    text = ""

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"question_type_id":1,"stem_tex":"1. 已知 𝑥 满足 $x>0$","choices":["A. 4\\\\sqrt{5}","\\\\frac{\\\\sqrt{65}}{2}"],"answer_tex":"","solution_tex":"","knowledge_topics":["函数"],"difficulty":2,"tags":["函数"]}'
                    }
                }
            ]
        }


def main() -> int:
    captured = {}
    original_post = ai_service.post_chat_completion
    old_env = {key: os.environ.get(key) for key in ("AI_API_KEY", "AI_BASE_URL", "AI_MODEL_NAME")}
    try:
        os.environ.update({"AI_API_KEY": "smoke", "AI_BASE_URL": "https://example.invalid/v1", "AI_MODEL_NAME": "qwen-vl-plus"})

        def fake_post(base_url, headers, payload, timeout):
            captured.update({"base_url": base_url, "headers": headers, "payload": payload, "timeout": timeout})
            return FakeResponse(), base_url

        ai_service.post_chat_completion = fake_post
        with tempfile.TemporaryDirectory(prefix="mathcyclus_ai_question_") as temp_dir:
            image_path = Path(temp_dir) / "question.png"
            Image.new("RGB", (320, 180), "white").save(image_path)
            result = ai_service.recognize_question_structure(
                [str(image_path)],
                extracted_text="1. x+1 的值是",
                question_number="1",
                allowed_topics=["集合", "函数", "未分类"],
            )
            question_content = captured.get("payload", {}).get("messages", [{}])[0].get("content", [])
            page_result = ai_service.recognize_document_page_tex(
                image_path,
                page_number=1,
                question_numbers=["1", "2"],
            )
        content = question_content
        checks = {
            "structured_result": result.get("question_type_id") == 1,
            "leading_number_removed": result.get("stem_tex") == "已知 x 满足 $x>0$",
            "choice_labels_removed": result.get("choices", [""])[0] == r"$4\sqrt{5}$",
            "choice_math_wrapped": result.get("choices", ["", ""])[1] == r"$\frac{\sqrt{65}}{2}$",
            "topic_constrained": result.get("topics") == ["函数"],
            "single_question_image": len([item for item in content if item.get("type") == "image_url"]) == 1,
            "target_number_in_prompt": "目标题号 1" in str(content[0].get("text") if content else ""),
            "tex_contract_in_prompt": "所有数学表达式必须使用标准 LaTeX" in str(content[0].get("text") if content else ""),
            "shared_ocr_rules_loaded": "项目根目录 ocr_prompt.txt" in str(content[0].get("text") if content else "")
            and "内部必须强制加 \\displaystyle" in str(content[0].get("text") if content else ""),
            "json_choice_override_present": "不带 \\choice 命令" in str(content[0].get("text") if content else ""),
            "second_pass_structure_check_present": "输出前必须进行第二遍结构校验" in str(content[0].get("text") if content else "")
            and "严禁自行解题" in str(content[0].get("text") if content else ""),
            "configured_model_used": captured.get("payload", {}).get("model") == "qwen-vl-plus",
            "page_tex_result": bool(page_result.get("tex")),
            "page_prompt_requests_full_tex": "一次性识别本页所有完整或部分出现的题目" in str(captured.get("payload", {}).get("messages", [{}])[0].get("content", [{}])[0].get("text", "")),
        }
        recovered = ai_service.normalize_question_structure_result(
            {
                "stem_tex": "已知函数f(x)=x+2ax+a的最大值为，A. 1 B. 2 C. 3 D. 4",
                "choices": [],
            },
            question_number="2",
        )
        checks.update(
            {
                "inline_formula_wrapped": "$f(x)=x+2ax+a$" in recovered.get("stem_tex", ""),
                "flattened_choices_recovered": recovered.get("choices") == ["$1$", "$2$", "$3$", "$4$"],
            }
        )
        for name, ok in checks.items():
            print(f"{name}={'ok' if ok else 'failed'}")
        print(f"status={'ok' if all(checks.values()) else 'failed'}")
        return 0 if all(checks.values()) else 1
    finally:
        ai_service.post_chat_completion = original_post
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
