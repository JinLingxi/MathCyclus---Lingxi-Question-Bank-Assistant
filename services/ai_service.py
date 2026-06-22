import json
import re


def normalize_chat_completions_url(base_url: str) -> str:
    url = (base_url or "").rstrip("/")
    if "/v1" not in url and "/chat/completions" not in url:
        url += "/v1"
    if "/chat/completions" not in url:
        url += "/chat/completions"
    return url


def post_chat_completion(base_url: str, headers: dict, payload: dict, timeout):
    import requests

    url = normalize_chat_completions_url(base_url)
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
