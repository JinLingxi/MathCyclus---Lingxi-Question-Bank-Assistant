import streamlit as st
import os
import re
import time
import base64
import requests
import hashlib
import subprocess
import shutil
import uuid
from dotenv import load_dotenv
try:
    from PIL import ImageGrab
except ImportError:
    ImageGrab = None

import streamlit.components.v1 as components
import io
from services.ai_service import extract_json_obj_from_text, normalize_chat_completions_url, post_chat_completion
from services.file_service import atomic_write_text, backup_existing_file, file_change_token

# 加载环境变量
load_dotenv()

from utils.core_config import *
from utils.file_ops import *
from utils.tikz_ops import *
from utils.latex_ops import *
from utils.csv_ops import add_to_csv_index, update_csv_index_for_edit

# ================= 工具函数 =================
# 注入自定义 CSS
def inject_custom_css():
    st.markdown("""
        <style>
        html {
            scrollbar-gutter: stable;
        }
        body {
            overflow-y: scroll;
            overflow-x: hidden;
        }
        div[data-testid="stAppViewContainer"] {
            overflow-y: scroll;
            scrollbar-gutter: stable;
        }
        header[data-testid="stHeader"],
        div[data-testid="stToolbar"],
        div[data-testid="stDecoration"],
        #MainMenu {
            visibility: hidden !important;
            height: 0 !important;
        }
        .stApp {
            overflow-x: hidden;
            background: linear-gradient(180deg, #f7f8fb 0%, #f2f3f6 100%);
            color: #1d1d1f;
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", "Microsoft YaHei", sans-serif;
        }
        :root {
            --mc-bg: #f5f5f7;
            --mc-surface: rgba(255, 255, 255, 0.78);
            --mc-surface-solid: #ffffff;
            --mc-border: rgba(0, 0, 0, 0.09);
            --mc-border-strong: rgba(0, 0, 0, 0.16);
            --mc-text: #1d1d1f;
            --mc-text-muted: #6e6e73;
            --mc-blue: #007aff;
            --mc-blue-hover: #0066d6;
            --mc-shadow: 0 10px 30px rgba(0, 0, 0, 0.07);
            --mc-control-radius: 8px;
        }
        .block-container {
            padding-top: 1.35rem !important;
            padding-bottom: 2rem !important;
        }
        h1, h2, h3, h4, h5, h6 {
            color: var(--mc-text) !important;
            letter-spacing: 0 !important;
            font-weight: 650 !important;
        }
        p, li, label, span {
            letter-spacing: 0 !important;
        }
        hr {
            border-color: rgba(0, 0, 0, 0.08) !important;
        }
        section[data-testid="stSidebar"] {
            background: rgba(245, 243, 255, 0.92) !important;
            border-right: 1px solid rgba(109, 40, 217, 0.14) !important;
            backdrop-filter: blur(18px);
            -webkit-backdrop-filter: blur(18px);
        }
        div[data-testid="stExpander"],
        div[data-testid="stForm"],
        div[data-testid="stPopover"] > div {
            border: 1px solid var(--mc-border) !important;
            border-radius: 8px !important;
            background: var(--mc-surface) !important;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03) !important;
        }
        div[data-testid="stMetric"],
        div[data-testid="stAlert"] {
            border-radius: 8px !important;
            border: 1px solid var(--mc-border) !important;
            box-shadow: none !important;
        }
        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        div[data-testid="stTextArea"] textarea,
        div[data-baseweb="select"] > div {
            border-radius: var(--mc-control-radius) !important;
            border-color: var(--mc-border) !important;
            background: rgba(255, 255, 255, 0.9) !important;
            box-shadow: inset 0 1px 1px rgba(0, 0, 0, 0.02) !important;
            transition: border-color 0.14s ease, box-shadow 0.14s ease, background 0.14s ease !important;
        }
        div[data-testid="stTextInput"] input:focus,
        div[data-testid="stNumberInput"] input:focus,
        div[data-testid="stTextArea"] textarea:focus,
        div[data-baseweb="select"] > div:focus-within {
            border-color: rgba(0, 122, 255, 0.72) !important;
            box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.14) !important;
            background: #ffffff !important;
        }
        div[data-testid="stButton"] > button,
        div[data-testid="stDownloadButton"] > button,
        div[data-testid="stPopover"] > button {
            min-height: 2.32rem !important;
            border-radius: var(--mc-control-radius) !important;
            border: 1px solid var(--mc-border) !important;
            background: rgba(255, 255, 255, 0.86) !important;
            color: var(--mc-text) !important;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04) !important;
            transition: transform 0.12s ease, border-color 0.12s ease, background 0.12s ease, box-shadow 0.12s ease !important;
        }
        div[data-testid="stButton"] > button:hover,
        div[data-testid="stDownloadButton"] > button:hover,
        div[data-testid="stPopover"] > button:hover {
            border-color: var(--mc-border-strong) !important;
            background: #ffffff !important;
            box-shadow: 0 3px 10px rgba(0, 0, 0, 0.07) !important;
            transform: translateY(-1px);
        }
        div[data-testid="stButton"] > button:active,
        div[data-testid="stDownloadButton"] > button:active,
        div[data-testid="stPopover"] > button:active {
            transform: translateY(0);
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05) !important;
        }
        button[kind="primary"],
        div[data-testid="stButton"] > button[kind="primary"] {
            border-color: var(--mc-blue) !important;
            background: linear-gradient(180deg, #1388ff 0%, var(--mc-blue) 100%) !important;
            color: #ffffff !important;
            box-shadow: 0 5px 14px rgba(0, 122, 255, 0.22) !important;
        }
        button[kind="primary"]:hover,
        div[data-testid="stButton"] > button[kind="primary"]:hover {
            background: linear-gradient(180deg, #0b7df0 0%, var(--mc-blue-hover) 100%) !important;
            box-shadow: 0 7px 18px rgba(0, 122, 255, 0.28) !important;
        }
        div[data-testid="stTabs"] button {
            border-radius: 8px 8px 0 0 !important;
            color: var(--mc-text-muted) !important;
        }
        div[data-testid="stTabs"] button[aria-selected="true"] {
            color: var(--mc-blue) !important;
            font-weight: 650 !important;
        }
        div[data-testid="stDataFrame"],
        div[data-testid="stTable"] {
            border-radius: 8px !important;
            overflow: hidden !important;
            border: 1px solid var(--mc-border) !important;
            background: var(--mc-surface-solid) !important;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03) !important;
        }
        div[data-testid="stToast"] {
            border-radius: 8px !important;
            border: 1px solid var(--mc-border) !important;
            box-shadow: var(--mc-shadow) !important;
        }
        ::selection {
            background: rgba(0, 122, 255, 0.18);
        }
        .katex .boxed {
            border: 1px solid #c9d1d9 !important;
            border-radius: 4px !important;
            padding: 2px 6px !important;
        }
        /* 调整 st.dialog 的背景遮罩透明度为 40% 黑色 */
        div[data-testid="stDialog"] > div:first-child {
            background-color: rgba(0, 0, 0, 0.4) !important;
        }
        
        /* 强制 st.dialog 变得更大，更适合查看大图 */
        div[data-testid="stDialog"] div[role="dialog"] {
            width: 90vw !important;
            max-width: 1600px !important;
        }
        </style>
    """, unsafe_allow_html=True)

def format_question_title(filename):
    """
    Format a question filename into a readable title.
    Expected filename format: Year-Type-PaperName-Num-Subject.tex
    Expected output: 【Year PaperName 第Num题】 (Subject)
    """
    basename = os.path.basename(filename).replace(".tex", "")
    parts = basename.split("-")
    if len(parts) >= 5:
        year = parts[0]
        paper_name = parts[2]
        num = parts[3]
        # 处理可能包含连字符的 subject (防万一)
        subject = "-".join(parts[4:])
        return f"【{year} {paper_name} 第{num}题】 ({subject})"
    elif len(parts) >= 4:
        year = parts[0]
        paper_name = parts[2]
        num = parts[3]
        return f"【{year} {paper_name} 第{num}题】"
    else:
        return basename

def extract_problem_header_fields(tex: str):
    m = re.search(r'\\begin\{problem\}\{(.*?)\}\{(.*?)\}\{(.*?)\}\{(.*?)\}\{(.*?)\}', tex or "", re.DOTALL)
    if not m:
        return None
    y, t, p, n, s = m.groups()
    t = (t or "").strip()
    t_clean = t.split("(")[0].split("（")[0].strip()
    if t_clean in PAPER_TYPES:
        t = t_clean
    else:
        for k, v in PAPER_TYPES.items():
            if t_clean == v or t == v:
                t = k
                break
    return {
        "year": (y or "").strip(),
        "p_type": t,
        "paper": (p or "").strip(),
        "number": (n or "").strip(),
        "subject_str": (s or "").strip(),
    }

def replace_problem_header(tex: str, new_year: str, new_type: str, new_name: str, new_num: str, new_subject_str: str) -> str:
    new_header = f"\\begin{{problem}}{{{new_year}}}{{{new_type}}}{{{new_name}}}{{{new_num}}}{{{new_subject_str}}}"
    s = tex or ""
    s2 = re.sub(
        r"\\begin\{problem\}\{.*?\}\{.*?\}\{.*?\}\{.*?\}\{.*?\}",
        lambda _m: new_header,
        s,
        count=1,
    )
    if s2 == s and "\\begin{problem}" in s:
        s2 = re.sub(r"\\begin\{problem\}", lambda _m: new_header, s, count=1)
    return s2

def apply_meta_rename_and_update(old_path: str, new_year: str, new_type: str, new_name: str, new_num: str, new_subject_str: str):
    old_path = old_path or ""
    if not old_path or not os.path.exists(old_path):
        raise FileNotFoundError(old_path)

    base = os.path.basename(old_path).replace(".tex", "")
    parts = base.split("-")
    if len(parts) < 5:
        raise ValueError("invalid filename format")

    primary_subj = (new_subject_str or "").split("，")[0].strip() if new_subject_str else ""
    target_dir = os.path.join(CHAPTERS_DIR, primary_subj, str(new_year))
    ensure_dir(target_dir)

    new_filename = generate_filename(new_year, new_type, new_name, new_num, new_subject_str)
    new_path = os.path.join(target_dir, new_filename)

    with open(old_path, "r", encoding="utf-8") as f:
        old_content = f.read()

    new_content = replace_problem_header(old_content, str(new_year), new_type, new_name, new_num, new_subject_str)
    atomic_write_text(new_path, new_content, backup=os.path.exists(new_path))

    if os.path.abspath(new_path) != os.path.abspath(old_path):
        backup_existing_file(old_path)
        os.remove(old_path)

    update_csv_index_for_edit(old_path, new_path, new_content, str(new_year), new_type, new_name, new_num, new_subject_str)
    clear_statistics_cache()
    _clear_advanced_search_result_cache()
    return new_path, new_content

@st.dialog("🔍 查看大图", width="large")
def zoom_image(img):
    # 将图片转换为 Base64
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    
    # HTML/JS 缩放组件 (增大可视高度)
    html_code = f"""
    <div style="width: 100%; height: auto; min-height: 400px; overflow: visible; position: relative; display: flex; justify-content: center; align-items: flex-start; background: transparent;">
        <div id="img-container" style="transition: transform 0.1s; cursor: grab; width: 100%; display: flex; justify-content: center;">
            <img id="zoomed-img" src="data:image/png;base64,{img_str}" style="max-width: 100%; height: auto; display: block;">
        </div>
        <div style="position: fixed; top: 15px; left: 15px; background: rgba(0,0,0,0.65); padding: 35px 25px; border-radius: 35px; display: flex; align-items: center; gap: 20px; z-index: 9999; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
            <button onclick="zoomOut()" style="background: transparent; border: none; color: white; font-size: 35px; cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 0;">➖</button>
            <span id="zoom-level" style="color: white; font-family: sans-serif; font-size: 18px; font-weight: bold; min-width: 60px; text-align: center; margin: 0;">100%</span>
            <button onclick="zoomIn()" style="background: transparent; border: none; color: white; font-size: 35px; cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 0;">➕</button>
            <button onclick="resetZoom()" style="background: transparent; border: none; color: white; font-size: 20px; cursor: pointer; margin-left: 5px; display: flex; align-items: center; justify-content: center; padding: 0;">🔄</button>
        </div>
    </div>
    <script>
        let scale = 1;
        let pX = 0;
        let pY = 0;
        const container = document.getElementById('img-container');
        const zoomLevel = document.getElementById('zoom-level');
        
        function updateTransform() {{
            container.style.transform = `translate(${{pX}}px, ${{pY}}px) scale(${{scale}})`;
            zoomLevel.innerText = Math.round(scale * 100) + '%';
        }}

        function zoomIn() {{
            scale *= 1.2;
            updateTransform();
        }}

        function zoomOut() {{
            scale /= 1.2;
            updateTransform();
        }}
        
        function resetZoom() {{
            scale = 1;
            pX = 0;
            pY = 0;
            updateTransform();
        }}

        // 滚轮缩放
        document.querySelector('div').addEventListener('wheel', (e) => {{
            e.preventDefault();
            if (e.deltaY < 0) {{
                scale *= 1.1;
            }} else {{
                scale /= 1.1;
            }}
            updateTransform();
        }});

        // 简单的拖拽逻辑
        let isDragging = false;
        let startX, startY, initialPx, initialPy;

        container.addEventListener('mousedown', (e) => {{
            isDragging = true;
            startX = e.clientX;
            startY = e.clientY;
            initialPx = pX;
            initialPy = pY;
            container.style.cursor = 'grabbing';
            e.preventDefault();
        }});

        window.addEventListener('mousemove', (e) => {{
            if (!isDragging) return;
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            pX = initialPx + dx;
            pY = initialPy + dy;
            updateTransform();
        }});

        window.addEventListener('mouseup', () => {{
            isDragging = false;
            container.style.cursor = 'grab';
        }});
    </script>
    """
    components.html(html_code, height=800, scrolling=True)

@st.dialog("MathCyclus 题库介绍", width="large")
def show_mathcyclus_intro():
    intro_path = os.path.join(BASE_DIR, "MathCyclus题库介绍.html")
    if not os.path.exists(intro_path):
        st.error("未找到 MathCyclus题库介绍.html")
        return
    with open(intro_path, "r", encoding="utf-8") as f:
        demo_html = f.read()
    components.html(demo_html, height=760, scrolling=True)

def _adv_search_queries_from_session():
    t1 = st.session_state.get("adv_t1", "全文内容")
    t2 = st.session_state.get("adv_t2", "全文内容")
    t3 = st.session_state.get("adv_t3", "全文内容")

    q1 = st.session_state.get("adv_q1_sel" if t1 == "题目类型" else "adv_q1", "")
    q2 = st.session_state.get("adv_q2_sel" if t2 == "题目类型" else "adv_q2", "")
    q3 = st.session_state.get("adv_q3_sel" if t3 == "题目类型" else "adv_q3", "")
    return (q1 or ""), (q2 or ""), (q3 or "")

def _adv_search_has_query():
    q1, q2, q3 = _adv_search_queries_from_session()
    return bool(str(q1).strip() or str(q2).strip() or str(q3).strip())

def _clear_advanced_search_result_cache():
    st.session_state.pop("adv_last_query", None)
    st.session_state.pop("adv_last_results", None)

def save_modified_tex_file(file_path, new_content):
    """
    保存修改后的 tex 文件：
    将修改后的内容通过 extract_and_replace_tikz 处理（保留内联 TikZ 并在后台生成副本），然后保存。
    """
    save_dir = os.path.dirname(file_path)
    filename = os.path.basename(file_path)
    
    # 提取并生成独立文件副本，但 final_content 仍包含原生 TikZ
    final_content = extract_and_replace_tikz(new_content, filename, save_dir)
    
    # 直接写入包含原生 TikZ 的内容
    atomic_write_text(file_path, final_content, backup=True)
        
    return final_content

def ocr_image_to_latex(images=None):
    """调用 AI 接口识别图片中的数学公式 (支持多张)
    Args:
        images: List of PIL Image objects
    """
    # 动态加载 .env 配置，支持热更新
    load_dotenv(override=True)
    
    api_key = os.getenv("AI_API_KEY")
    base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
    model_name = os.getenv("AI_MODEL_NAME", "gpt-4o")
    
    # 重新读取提示词文件 (支持热更新)
    prompt = AI_OCR_PROMPT
    if os.path.exists(ocr_prompt_file):
        with open(ocr_prompt_file, "r", encoding="utf-8") as f:
            prompt = f.read()
    prompt = (
        "你是 OCR 转写助手。你只需要把图片中的内容逐字逐符号转写成 LaTeX 源码。\n"
        "禁止解题、禁止推理、禁止补全缺失步骤、禁止生成答案与解析。\n"
        "如果图片里本身包含答案/解析/提示，请原样转写；否则不要凭空生成。\n\n"
        + (prompt or "")
    )
    
    if not api_key:
        return "❌ 请先在 .env 文件中配置 AI_API_KEY"

    if not images:
        return "❌ 没有提供图片"

    try:
        from PIL import Image
        import io
        
        # 构造消息内容
        content_parts = [{"type": "text", "text": prompt}]
        
        for img in images:
            # 限制最大边长为 1024px
            max_size = 1024
            if max(img.size) > max_size:
                ratio = max_size / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            
            # 转换为 JPEG 并压缩质量
            buffered = io.BytesIO()
            img = img.convert("RGB") # 兼容 PNG 透明通道
            img.save(buffered, format="JPEG", quality=80)
            base64_image = base64.b64encode(buffered.getvalue()).decode('utf-8')
            
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{base64_image}"
                }
            })
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        # 兼容 OpenAI Vision API 格式
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": content_parts
                }
            ],
            "max_tokens": 4096
        }
        
        with st.spinner("🤖 AI 正在识别中，请稍候..."):
            # 处理 URL: 兼容不同的 Base URL 写法
            url = normalize_chat_completions_url(base_url)
            
            st.toast(f"正在请求: {url}")
            print(f"Requesting URL: {url}") # 控制台打印

            try:
                # 设置超时时间为 180 秒 (3分钟)
                response = requests.post(url, headers=headers, json=payload, timeout=180)
            except requests.exceptions.Timeout:
                return "❌ 请求超时 (180s)，请检查网络或稍后重试。"
            except requests.exceptions.RequestException as req_err:
                 return f"❌ 网络请求失败: {str(req_err)}\n请检查 URL ({url}) 是否正确及服务是否可达。"

            if response.status_code != 200:
                return f"❌ 识别失败 (HTTP {response.status_code}):\n{response.text[:500]}"
            
            try:
                result = response.json()
            except Exception as json_err:
                return f"❌ JSON 解析失败: {str(json_err)}\n\n原始响应内容(前500字符):\n{response.text[:500]}"
                
            if 'choices' in result and len(result['choices']) > 0:
                return result['choices'][0]['message']['content']
            else:
                return f"❌ 未收到有效回复: {result}"
                
    except Exception as e:
        return f"❌ 发生错误: {str(e)}"

def ocr_solution_images_to_answer_solutions(images=None) -> dict:
    load_dotenv(override=True)
    api_key = os.getenv("AI_API_KEY")
    base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
    model_name = os.getenv("AI_MODEL_NAME", "gpt-4o")

    if not api_key or not base_url or not model_name:
        return {"error": "AI 配置不完整，请检查 .env 文件"}
    if not images:
        return {"error": "没有提供图片"}

    prompt = (
        "你是 OCR 转写助手。请把图片中的“答案/解答/解析”逐字逐符号转写为 LaTeX。\n"
        "禁止解题、禁止推理、禁止补全缺失步骤、禁止凭空生成内容。\n\n"
        "严格输出 JSON，且只包含两个字段：answer_tex 与 solutions_tex。\n"
        "answer_tex：必须是完整的 \\begin{answer}...\\end{answer} 环境；如果图片里没有明确答案，则输出空字符串。\n"
        "solutions_tex：必须是完整的 \\begin{solutions}...\\end{solutions} 环境；如果图片里没有解答过程，则输出空字符串。\n"
        "禁止输出反引号 ` 或 Markdown 代码块。\n"
    )

    try:
        from PIL import Image
        import io

        content_parts = [{"type": "text", "text": prompt}]
        for img in images:
            max_size = 1400
            if max(img.size) > max_size:
                ratio = max_size / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            buffered = io.BytesIO()
            img = img.convert("RGB")
            img.save(buffered, format="JPEG", quality=85)
            base64_image = base64.b64encode(buffered.getvalue()).decode("utf-8")
            content_parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}})

        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": content_parts}],
            "temperature": 0.1,
            "max_tokens": 2600,
            "response_format": {"type": "json_object"} if "gpt" in model_name.lower() or "qwen" in model_name.lower() else None,
        }

        response, _ = post_chat_completion(base_url, headers, payload, timeout=180)
        if response.status_code != 200:
            return {"error": f"识别失败 (HTTP {response.status_code}):\n{response.text[:500]}"}

        result = response.json()
        if "choices" not in result or not result["choices"]:
            return {"error": "AI 未返回有效内容"}
        reply = result["choices"][0]["message"]["content"]
        try:
            data = _extract_json_obj_from_text(reply)
        except Exception:
            return {"error": "AI 返回格式解析失败（非 JSON）"}

        answer_tex = _repair_latex_from_json_escapes(str(data.get("answer_tex", "")).strip())
        solutions_tex = _repair_latex_from_json_escapes(str(data.get("solutions_tex", "")).strip())
        return {"answer_tex": answer_tex, "solutions_tex": solutions_tex}
    except requests.exceptions.Timeout:
        return {"error": f"请求超时（模型：{model_name}）。可重试或切换更快模型。"}
    except Exception as e:
        return {"error": f"请求发生异常: {str(e)}"}

def call_ai_for_tags(content: str) -> dict:
    """调用 AI 为题目内容生成标签和难度"""
    api_key = os.getenv("AI_API_KEY")
    base_url = os.getenv("AI_BASE_URL")
    model_name = os.getenv("AI_MODEL_NAME")
    
    if not api_key or not base_url or not model_name:
        return {"error": "AI 配置不完整，请检查 .env 文件"}
        
    prompt = f"""你是一个专业的高中数学教研专家。请分析以下 LaTeX 格式的数学题目，并为其打上合适的“难度星级”和“知识标签”。

要求：
1. 难度星级：0.0 到 6.0 的浮点数，步长为 0.5（例如 2.5, 3.0, 4.5）。其中，0-2星为基础题，3-4星为中档题，5-6星为压轴/难题。
2. 知识标签：提取 2-4 个最核心的考点标签，以中文逗号“，”分隔（例如：导数应用，零点问题，分类讨论）。
3. 必须严格以 JSON 格式输出，不要输出任何额外的解释文本。

格式如下：
{{
    "difficulty": 3.5,
    "tags": "标签1，标签2，标签3"
}}

题目内容：
{content}"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "You are a JSON output bot. You only output valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"} if "gpt" in model_name.lower() or "qwen" in model_name.lower() else None
    }
    
    try:
        response, _ = post_chat_completion(base_url, headers, payload, timeout=30)
        if response.status_code == 200:
            result = response.json()
            if 'choices' in result and len(result['choices']) > 0:
                reply = result['choices'][0]['message']['content']
                import json
                try:
                    reply_clean = reply.replace('```json', '').replace('```', '').strip()
                    data = json.loads(reply_clean)
                    return {
                        "difficulty": float(data.get("difficulty", 0.0)),
                        "tags": str(data.get("tags", ""))
                    }
                except json.JSONDecodeError:
                    return {"error": "AI 返回格式解析失败"}
            else:
                return {"error": "AI 未返回有效内容"}
        else:
            return {"error": f"API 请求失败: {response.status_code}"}
    except Exception as e:
        return {"error": f"请求发生异常: {str(e)}"}

def _extract_json_obj_from_text(text: str):
    return extract_json_obj_from_text(text)

def _extract_problem_env(tex: str) -> str:
    if not tex:
        return ""
    m = re.search(r"\\begin\{problem\}[\s\S]*?\\end\{problem\}", tex)
    return m.group(0).strip() if m else ""

def _extract_env_block(tex: str, env_name: str) -> str:
    if not tex:
        return ""
    m = re.search(rf"\\begin\{{{re.escape(env_name)}\}}[\s\S]*?\\end\{{{re.escape(env_name)}\}}", tex)
    return m.group(0).strip() if m else ""

def _replace_first_env_or_insert_after_problem(tex: str, env_name: str, new_block: str) -> str:
    new_block = (new_block or "").strip()
    if not new_block:
        return tex
    pat = re.compile(rf"\\begin\{{{re.escape(env_name)}\}}[\s\S]*?\\end\{{{re.escape(env_name)}\}}")
    if pat.search(tex):
        return pat.sub(lambda m: new_block, tex, count=1)
    if "\\end{problem}" in tex:
        return tex.replace("\\end{problem}", "\\end{problem}\n\n" + new_block, 1)
    return tex.rstrip() + "\n\n" + new_block + "\n"

def _insert_block_after(tex: str, anchor_pat: str, new_block: str) -> str:
    m = re.search(anchor_pat, tex)
    if not m:
        return tex.rstrip() + "\n\n" + new_block.strip() + "\n"
    insert_pos = m.end()
    prefix = tex[:insert_pos]
    suffix = tex[insert_pos:]
    return prefix + "\n\n" + new_block.strip() + suffix

def _insert_block_before(tex: str, anchor_pat: str, new_block: str) -> str:
    m = re.search(anchor_pat, tex)
    if not m:
        return new_block.strip() + "\n\n" + tex.lstrip()
    insert_pos = m.start()
    prefix = tex[:insert_pos]
    suffix = tex[insert_pos:]
    return prefix.rstrip() + "\n\n" + new_block.strip() + "\n\n" + suffix.lstrip()

def _replace_or_insert_answer_solutions(tex: str, new_answer: str, new_solutions: str) -> str:
    answer_pat = re.compile(r"\\begin\{answer\}[\s\S]*?\\end\{answer\}")
    sol_pat = re.compile(r"\\begin\{solutions\}[\s\S]*?\\end\{solutions\}")
    has_answer = answer_pat.search(tex) is not None
    has_sol = sol_pat.search(tex) is not None

    if has_answer and has_sol:
        updated = answer_pat.sub(lambda m: new_answer.strip(), tex, count=1)
        updated = sol_pat.sub(lambda m: new_solutions.strip(), updated, count=1)
        return updated

    if has_answer and not has_sol:
        updated = answer_pat.sub(lambda m: new_answer.strip(), tex, count=1)
        return _insert_block_after(updated, r"\\end\{answer\}", new_solutions)

    if not has_answer and has_sol:
        updated = sol_pat.sub(lambda m: new_solutions.strip(), tex, count=1)
        return _insert_block_before(updated, r"\\begin\{solutions\}", new_answer)

    if "\\end{problem}" in tex:
        return _insert_block_after(tex, r"\\end\{problem\}", (new_answer.strip() + "\n\n" + new_solutions.strip()).strip())
    return (tex.rstrip() + "\n\n" + new_answer.strip() + "\n\n" + new_solutions.strip() + "\n").strip() + "\n"

def _extract_solutions_inner(new_solutions_block: str) -> str:
    m = re.search(r"\\begin\{solutions\}(?:\[[^\]]*\])?([\s\S]*?)\\end\{solutions\}", new_solutions_block or "")
    if not m:
        return ""
    return (m.group(1) or "").strip()

def _append_alt_solutions_after_last_solutions(tex: str, new_solutions_block: str, alt_label: str) -> str:
    inner = _extract_solutions_inner(new_solutions_block)
    if not inner:
        raise ValueError("empty solutions")

    label = (alt_label or "").strip()
    if label:
        alt_block = f"\\begin{{solutions}}[{label}]\n{inner}\n\\end{{solutions}}"
    else:
        alt_block = f"\\begin{{solutions}}\n{inner}\n\\end{{solutions}}"

    matches = list(re.finditer(r"\\end\{solutions\}", tex))
    if matches:
        last = matches[-1]
        insert_pos = last.end()
        return tex[:insert_pos] + "\n\n" + alt_block + tex[insert_pos:]

    if "\\end{answer}" in tex:
        return _insert_block_after(tex, r"\\end\{answer\}", alt_block)
    if "\\end{problem}" in tex:
        return _insert_block_after(tex, r"\\end\{problem\}", alt_block)
    return tex.rstrip() + "\n\n" + alt_block + "\n"

def _prepend_line_after_begin(block: str, env_name: str, line: str) -> str:
    block = (block or "").strip()
    if not block:
        return block
    begin = f"\\begin{{{env_name}}}"
    if begin not in block:
        return block
    return block.replace(begin, begin + "\n" + line, 1)

def _split_answer_solutions_from_text(text: str):
    ans = _extract_env_block(text, "answer")
    sol = _extract_env_block(text, "solutions")
    return ans, sol

def _repair_latex_from_json_escapes(text: str) -> str:
    s = text or ""
    s = s.replace("\x08", r"\b")
    s = s.replace("\x0c", r"\f")
    s = s.replace("\x09", r"\t")
    s = s.replace("\x0d", r"\r")
    s = s.replace("\x1b", "\\")
    s = re.sub(r"\n(?=eq\b)", r"\\n", s)
    s = re.sub(r"\n(?=abla\b)", r"\\n", s)
    
    keep_cmds = {
        "nabla",
        "neq",
        "nexists",
        "nmid",
        "not",
        "notin",
        "nu",
        "nparallel",
        "nsubseteq",
        "nsupseteq",
        "nRightarrow",
        "nrightarrow",
        "nLeftarrow",
        "nleftarrow",
        "nLeftrightarrow",
        "nleftrightarrow",
        "nVdash",
        "nvDash",
        "nvdash",
        "nVDash",
    }
    
    out = []
    i = 0
    while i < len(s):
        if i + 1 < len(s) and s[i] == "\\" and s[i + 1] == "n":
            j = i + 2
            if j < len(s) and s[j].isalpha():
                k = j
                while k < len(s) and s[k].isalpha():
                    k += 1
                cmd = "n" + s[j:k]
                if cmd in keep_cmds:
                    out.append("\\" + cmd)
                else:
                    out.append("\n" + s[j:k])
                i = k
                continue
            out.append("\n")
            i += 2
            continue
        out.append(s[i])
        i += 1
    s = "".join(out)
    return s

def _normalize_ai_generated_tex_for_preview(text: str) -> str:
    s = _repair_latex_from_json_escapes(text or "")
    s = s.replace("```json", "").replace("```latex", "").replace("```", "")
    s = s.replace("`", "")
    s = re.sub(r"\$\$\s*([\s\S]*?)\s*\$\$", lambda m: "$$\n" + m.group(1).strip() + "\n$$", s)
    s = re.sub(r"(?<!\$)\$([^$\n]*?)\$(?!\$)", lambda m: "$" + m.group(1).strip() + "$", s)
    s = re.sub(r"(\$|\$\$)\s*。", r"\1.", s)
    s = re.sub(r"(\$|\$\$)\s*，", r"\1,", s)
    s = re.sub(r"(\$|\$\$)\s*；", r"\1;", s)
    s = re.sub(r"\$\$\s*([。．\.，,；;])", r"$$\n\1", s)
    s = re.sub(r"([。．\.，,；;])\s*\$\$", r"\1\n$$", s)
    s = re.sub(r"[ \t]*\$\$[ \t]*", "$$", s)
    s = re.sub(r"(?<!\n)\$\$", r"\n$$", s)
    s = re.sub(r"\$\$(?!\n)", r"$$\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)

    def _fix_answer_env(m):
        inner = (m.group(1) or "").strip()
        if not inner:
            fixed_inner = ""
        else:
            fixed_inner = re.sub(r"\\frac(?=\{)", r"\\dfrac", inner)
            has_dollar = ("$" in fixed_inner) or ("$$" in fixed_inner)
            if not has_dollar:
                fixed_inner = "$" + fixed_inner.strip() + "$"
        return "\\begin{answer}\n" + fixed_inner + "\n\\end{answer}"

    s = re.sub(r"\\begin\{answer\}\s*([\s\S]*?)\s*\\end\{answer\}", _fix_answer_env, s)
    s = re.sub(r"\\begin\{solutions\}\s*", lambda _m: "\\begin{solutions}\n", s)
    s = re.sub(r"\s*\\end\{solutions\}", lambda _m: "\n\\end{solutions}", s)
    return s.strip()

def call_ai_for_answer_solutions(problem_tex: str, fast: bool = True) -> dict:
    load_dotenv(override=True)
    api_key = os.getenv("AI_API_KEY")
    base_url = os.getenv("AI_BASE_URL")
    model_name = os.getenv("AI_SOLVER_MODEL_NAME") or "qwen3.6-flash"
    
    if not api_key or not base_url or not model_name:
        return {"error": "AI 配置不完整，请检查 .env 文件"}

    problem_tex = (problem_tex or "").strip()
    if not problem_tex:
        return {"error": "未识别到 \\begin{problem}...\\end{problem}，无法生成解答"}

    def _build_prompt() -> str:
        if fast:
            return f"""请为下面的 LaTeX problem 生成答案与解析。

严格输出 JSON，且只包含两个字段：answer_tex 与 solutions_tex。
answer_tex 必须是完整的 \\begin{{answer}}...\\end{{answer}} 环境（只写最终答案）。
solutions_tex 必须是完整的 \\begin{{solutions}}...\\end{{solutions}} 环境（步骤尽量精简，关键式子即可）。
禁止输出反引号 ` 或 Markdown 代码块。

problem_tex：
{problem_tex}"""
        return f"""你是一名资深高中数学教研专家。请为下面的 LaTeX problem 生成对应的答案与解析。

要求：
1) 严格输出 JSON 格式，包含两个字段：answer_tex 与 solutions_tex。不要输出多余解释。
2) answer_tex 必须用 \\begin{{answer}}...\\end{{answer}} 包裹，且这两句一定要单独一行，中间内容仅输出最终答案（如选项字母、数值或集合）。
3) solutions_tex 必须用 \\begin{{solutions}}...\\end{{solutions}} 包裹，且这两句一定要单独一行。
4) **解析要求极简高效**：请给出关键公式和核心推导步骤，不需要过多啰嗦的文字描述。优先采用公式表达，且因为所以采用中文，不采用数学符号做这种连接，同时避免长篇大论。
5) 保持 LaTeX 书写规范（如下），注意数学符号排版，最终结论可以使用 \\boxed{{}}；\\boxed{{}} 外面不需要打 $，内部内容涉及到公式时再单独打 $。
6) 禁止输出任何反引号 ` 或 Markdown 代码块标记。
7) solutions_tex 中每个逻辑步骤单独成段，段落之间空一行（用两个换行）。
8) 重要：你输出的是 JSON 字符串。所有 LaTeX 命令的反斜杠必须写成双反斜杠，例如 \\\\frac、\\\\boxed、\\\\neq、\\\\text、\\\\right、\\\\left、\\\\displaystyle。
9) 重要：禁止输出 $\\boxed{...}$ 或 $$\\boxed{...}$$，只能输出 \\boxed{...}。
10) 重要：换行请直接使用真实换行，不要输出 \\n 字符串来表示换行。

排版与符号规范：
- 【公式环境】行内公式用 $ 包裹，居中行间公式用 $$ 包裹。要求：$$ 必须单独占一行（不要写成 $$ 公式 $$），公式本体单独占一行。绝对禁止使用 \\(\\) 或 \\[\\]。
- 【符号规范】遇到分式、求和、累乘等公式（包含行内公式），内部必须强制加 \\displaystyle 指令！数学括号必须使用 \\left( \\right)、\\left[ \\right] 等自适应大小指令！平行用 \\mathop{{//}}。带圈数字（如①、②、③、④等）必须无条件使用 \\circled{{1}}、\\circled{{2}} 格式，绝对禁止直接输出特殊字符①②③！
- 【独立数字/字母】单独的阿拉伯数字(1, 2)或英文字母(A, a)必须、无条件用 $ $ 包裹(如 $1$, $A$)！
- 【标点与空格规范】纯中文句子的结尾正常使用中文句号 。；但紧跟在数学公式或表达式后面的句号，必须严格使用英文句号 .！
- 【文字与公式间距】数学公式与前后的中文文字之间建议加一个空格（例如：已知函数 $f(x)$ 的定义域）。但 $ 与公式内容之间严禁留空格，必须写成 $f(x)$，不要写成 $ f(x) $。每一个完整的话（或段落）之间必须空一空行！题目小问直接写（1）（2）或（a），禁止使用 {{enumerate}} 环境。

problem_tex：
{problem_tex}"""

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "You are a JSON output bot. You only output valid JSON."},
            {"role": "user", "content": _build_prompt()},
        ],
        "temperature": 0.1,
        "max_tokens": 1600 if fast else 2600,
        "response_format": {"type": "json_object"} if "gpt" in model_name.lower() or "qwen" in model_name.lower() else None,
    }

    try:
        response, _ = post_chat_completion(base_url, headers, payload, timeout=(10, 90 if fast else 150))
        if response.status_code != 200:
            return {"error": f"API 请求失败: {response.status_code}\n{response.text[:500]}"}
        result = response.json()
        if "choices" not in result or not result["choices"]:
            return {"error": "AI 未返回有效内容"}
        reply = result["choices"][0]["message"]["content"]
        try:
            data = _extract_json_obj_from_text(reply)
        except Exception:
            return {"error": "AI 返回格式解析失败（非 JSON）"}

        answer_tex = str(data.get("answer_tex", "")).strip()
        solutions_tex = str(data.get("solutions_tex", "")).strip()
        answer_tex = _repair_latex_from_json_escapes(answer_tex)
        solutions_tex = _repair_latex_from_json_escapes(solutions_tex)
        if not answer_tex or not solutions_tex:
            return {"error": "AI 返回 JSON 缺少 answer_tex / solutions_tex"}
        if "\\begin{answer}" not in answer_tex or "\\end{answer}" not in answer_tex:
            return {"error": "answer_tex 不是完整的 answer 环境"}
        if "\\begin{solutions}" not in solutions_tex or "\\end{solutions}" not in solutions_tex:
            return {"error": "solutions_tex 不是完整的 solutions 环境"}
        return {"answer_tex": answer_tex, "solutions_tex": solutions_tex}
    except requests.exceptions.Timeout:
        return {"error": f"请求超时（模型：{model_name}）。可重试或切换更快模型。"}
    except Exception as e:
        return {"error": f"请求发生异常: {str(e)}"}

def _update_csv_index_for_content_change(fpath: str, new_content: str):
    try:
        from utils.csv_ops import update_csv_index_for_edit
        basename = os.path.basename(fpath).replace(".tex", "")
        parts = basename.split("-")
        if len(parts) >= 5:
            update_csv_index_for_edit(fpath, fpath, new_content, parts[0], parts[1], parts[2], parts[3], parts[4])
    except Exception:
        return

def _save_tex_from_widget(fpath: str, widget_key: str, edit_mode_key: str = "", toast_msg: str = "文件已保存！"):
    raw = st.session_state.get(widget_key, "")
    final_content = save_modified_tex_file(fpath, raw)
    _update_csv_index_for_content_change(fpath, final_content)
    _clear_advanced_search_result_cache()
    st.session_state[widget_key] = final_content
    if edit_mode_key:
        st.session_state[edit_mode_key] = False
    st.session_state["last_saved"] = time.time()
    st.toast(toast_msg, icon="✅")

def _apply_generated_answer_solutions_to_file(fpath: str, new_answer: str, new_solutions: str, mode: str, alt_label: str = ""):
    with open(fpath, "r", encoding="utf-8") as f:
        old_tex = f.read()

    new_answer = _normalize_ai_generated_tex_for_preview((new_answer or "").strip())
    new_solutions = _normalize_ai_generated_tex_for_preview((new_solutions or "").strip())
    if mode == "replace":
        if not new_answer or not new_solutions:
            raise ValueError("empty answer/solutions")
    else:
        if not new_solutions:
            raise ValueError("empty solutions")

    if mode == "replace":
        updated = _replace_or_insert_answer_solutions(old_tex, new_answer, new_solutions)
    elif mode == "append":
        updated = _append_alt_solutions_after_last_solutions(old_tex, new_solutions, alt_label)
    else:
        raise ValueError("invalid mode")

    final_content = save_modified_tex_file(fpath, updated)
    _update_csv_index_for_content_change(fpath, final_content)
    _clear_advanced_search_result_cache()
    clear_statistics_cache()
    return final_content

def _ai_sol_keys(fpath: str, key_prefix: str):
    import hashlib
    fhash = hashlib.md5(f"{key_prefix}:{fpath}".encode()).hexdigest()[:10]
    data_key = f"ai_sol_data_{fhash}"
    editor_key = f"ai_sol_editor_{fhash}"
    return fhash, data_key, editor_key

def render_ai_solution_generate_button(fpath: str, current_content: str, key_prefix: str, use_container_width: bool = True):
    fhash, data_key, editor_key = _ai_sol_keys(fpath, key_prefix)
    c_ai, c_img = st.columns([1, 1])
    do = None
    with c_ai:
        if st.button("🤖 AI生成解答", key=f"ai_sol_gen_{fhash}", type="primary", use_container_width=use_container_width):
            do = "ai"
    upload_open_key = f"ai_sol_upload_open_{fhash}"
    with c_img:
        if st.button("🖼️ 解答图片识别", key=f"ai_sol_img_toggle_{fhash}", type="secondary", use_container_width=use_container_width):
            st.session_state[upload_open_key] = not st.session_state.get(upload_open_key, False)

    if do:
        problem_tex = _extract_problem_env(current_content)
        with st.spinner("🤖 AI 正在生成解答..."):
            res = call_ai_for_answer_solutions(problem_tex, fast=False)
        if "error" in res:
            st.toast(res["error"], icon="❌")
        else:
            combined = _normalize_ai_generated_tex_for_preview(res["answer_tex"].strip() + "\n\n" + res["solutions_tex"].strip())
            st.session_state[data_key] = {"answer_tex": res["answer_tex"], "solutions_tex": res["solutions_tex"]}
            st.session_state[editor_key] = combined
            st.toast("已生成解答（未写回文件）", icon="🪄")
            st.rerun()

def render_ai_solution_image_ocr_section(fpath: str, key_prefix: str, max_images: int = 5):
    fhash, data_key, editor_key = _ai_sol_keys(fpath, key_prefix)
    upload_open_key = f"ai_sol_upload_open_{fhash}"
    if not st.session_state.get(upload_open_key, False):
        return

    st.markdown('<hr style="border-top: 1px solid #e1e4e8; margin: 8px 0 12px 0;">', unsafe_allow_html=True)

    try:
        from PIL import Image
    except Exception:
        st.toast("缺少 pillow，无法读取图片", icon="❌")
        return

    queue_key = f"ai_sol_img_queue_{fhash}"
    prev_ids_key = f"ai_sol_img_uploader_prev_{fhash}"
    if queue_key not in st.session_state:
        st.session_state[queue_key] = []
    if prev_ids_key not in st.session_state:
        st.session_state[prev_ids_key] = []

    c_left, c_right = st.columns([1, 1])
    with c_left:
        if st.button("📋 粘贴剪贴板图片", key=f"ai_sol_img_paste_{fhash}", use_container_width=True):
            if not ImageGrab:
                st.toast("缺少 ImageGrab，无法读取剪贴板", icon="❌")
            else:
                try:
                    clip = ImageGrab.grabclipboard()
                    new_imgs = []
                    if isinstance(clip, Image.Image):
                        new_imgs.append(clip)
                    elif isinstance(clip, list):
                        for item in clip:
                            if isinstance(item, str) and os.path.isfile(item):
                                try:
                                    img = Image.open(item)
                                    img.load()
                                    new_imgs.append(img)
                                except Exception:
                                    continue
                    if not new_imgs:
                        st.toast("剪贴板中没有可用图片", icon="⚠️")
                    else:
                        room = max(0, max_images - len(st.session_state[queue_key]))
                        if room <= 0:
                            st.toast(f"队列已满（最多 {max_images} 张）", icon="⚠️")
                        else:
                            st.session_state[queue_key].extend(new_imgs[:room])
                            st.toast(f"已添加 {min(len(new_imgs), room)} 张图片", icon="✅")
                            st.rerun()
                except Exception as e:
                    st.toast(f"剪贴板读取失败: {e}", icon="❌")

    with c_right:
        uploaded_files = st.file_uploader("📂 本地上传", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key=f"ai_sol_img_uploader_{fhash}")
        if uploaded_files:
            current_ids = [f"{f.name}_{f.size}" for f in uploaded_files]
            prev_ids = st.session_state.get(prev_ids_key, [])
            room = max(0, max_images - len(st.session_state[queue_key]))
            added = 0
            for uf in uploaded_files:
                if room <= 0:
                    break
                fid = f"{uf.name}_{uf.size}"
                if fid in prev_ids:
                    continue
                try:
                    img = Image.open(uf)
                    img.load()
                    st.session_state[queue_key].append(img)
                    added += 1
                    room -= 1
                except Exception:
                    continue
            st.session_state[prev_ids_key] = current_ids
            if added > 0:
                st.toast(f"已添加 {added} 张图片", icon="✅")
                st.rerun()

    imgs = st.session_state.get(queue_key, []) or []
    c_status, c_clear = st.columns([3, 1])
    with c_status:
        st.caption(f"当前队列：{len(imgs)}/{max_images} 张")
    with c_clear:
        if st.button("清空", key=f"ai_sol_img_clear_{fhash}", use_container_width=True):
            st.session_state[queue_key] = []
            st.session_state[prev_ids_key] = []
            st.rerun()

    if imgs:
        cols = st.columns(min(max_images, len(imgs)))
        for i, img in enumerate(list(imgs)):
            with cols[i % len(cols)]:
                st.image(img, use_container_width=True)
                if st.button("🗑️ 删除", key=f"ai_sol_img_del_{fhash}_{i}", use_container_width=True):
                    try:
                        st.session_state[queue_key].pop(i)
                    except Exception:
                        pass
                    st.rerun()

    if imgs:
        if st.button(f"开始识别（{len(imgs)} 张）", key=f"ai_sol_img_run_{fhash}", type="primary", use_container_width=True):
            with st.spinner("🤖 AI 正在识别解答图片..."):
                res = ocr_solution_images_to_answer_solutions(images=imgs[:max_images])
            if "error" in res:
                st.toast(res["error"], icon="❌")
            else:
                combined = _normalize_ai_generated_tex_for_preview((res.get("answer_tex") or "").strip() + "\n\n" + (res.get("solutions_tex") or "").strip())
                st.session_state[data_key] = {"answer_tex": res.get("answer_tex") or "", "solutions_tex": res.get("solutions_tex") or ""}
                st.session_state[editor_key] = combined
                st.toast("已识别解答（未写回文件）", icon="🪄")
                st.rerun()

def render_ai_solution_panel(fpath: str, q_label: str, key_prefix: str):
    fhash, data_key, editor_key = _ai_sol_keys(fpath, key_prefix)
    if data_key not in st.session_state:
        return

    st.markdown(f"### {q_label} <span style='color: #1E90FF;'>问题的新生成解答</span>", unsafe_allow_html=True)
    
    col_close, _ = st.columns([0.15, 0.85])
    with col_close:
        if st.button("✖ 关闭面板", key=f"close_ai_panel_{fhash}", use_container_width=True):
            del st.session_state[data_key]
            st.rerun()

    c_left, c_right = st.columns([1, 1])
    with c_left:
        gen_text = st.text_area("解答源码", key=editor_key, height=320)
    with c_right:
        try:
            preview_text = _normalize_ai_generated_tex_for_preview(gen_text)
            st.markdown(latex_to_markdown(preview_text, show_title=False), unsafe_allow_html=True)
        except Exception as e:
            st.error(f"渲染错误: {e}")

    ans, sol = _split_answer_solutions_from_text(gen_text)
    if not sol:
        st.warning("解答源码中未检测到 solutions 环境，暂无法写回。")
        return

    opt_c1, opt_c2 = st.columns([1, 1])
    with opt_c1:
        if st.button("✅ 替换原本的解答与答案", key=f"ai_sol_apply_replace_{fhash}", type="primary", use_container_width=True):
            if not ans:
                st.toast("缺少 answer 环境，无法执行替换。", icon="❌")
                return
            try:
                _apply_generated_answer_solutions_to_file(fpath, ans, sol, mode="replace")
                st.toast("已替换并保存", icon="✅")
                del st.session_state[data_key]
                st.rerun()
            except Exception as e:
                st.toast(f"保存失败: {e}", icon="❌")
    with opt_c2:
        st.markdown("**保存为（另解/解法）**", unsafe_allow_html=True)
        alt_label = st.text_input("保存为（另解/解法）", value="另解", key=f"ai_sol_alt_label_{fhash}", label_visibility="collapsed")
        if st.button("💾 保存为另解/解法", key=f"ai_sol_apply_append_{fhash}", use_container_width=True):
            try:
                _apply_generated_answer_solutions_to_file(fpath, ans, sol, mode="append", alt_label=alt_label)
                st.toast("已追加并保存", icon="✅")
                del st.session_state[data_key]
                st.rerun()
            except Exception as e:
                st.toast(f"保存失败: {e}", icon="❌")

def call_ai_for_polish(intent_text: str) -> str:
    """调用 AI 润色用户的组卷意图"""
    api_key = os.getenv("AI_API_KEY")
    base_url = os.getenv("AI_BASE_URL")
    model_name = os.getenv("AI_MODEL_NAME")
    
    if not api_key or not base_url or not model_name:
        return "❌ AI 配置不完整，请检查 .env 文件"
        
    prompt = f"""你是一个资深的高中数学教研专家。请帮我润色以下组卷意图，使其更加专业、明确、富有条理。
润色后的文本将用于指导后续的 AI 抽题算法。
要求：
1. 保持原意不变，但语言更精准。
2. 直接输出润色后的文本，不要带有任何“好的”、“没问题”等废话。

原想法：
{intent_text}"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    
    try:
        response, _ = post_chat_completion(base_url, headers, payload, timeout=20)
        if response.status_code == 200:
            result = response.json()
            if 'choices' in result and len(result['choices']) > 0:
                return result['choices'][0]['message']['content'].strip()
            else:
                return "❌ AI 未返回有效内容"
        else:
            return f"❌ API 请求失败: {response.status_code}"
    except Exception as e:
        return f"❌ 请求发生异常: {str(e)}"

def process_ocr_result(ocr_result, mode):
    """处理识别结果并更新界面"""
    if "❌" in ocr_result:
        st.error(ocr_result)
    else:
        st.success("识别成功！")
        
        # 强制后处理：将公式结尾的中文句号“。”替换为英文句号“.”
        ocr_result = re.sub(r'\$(\s*)。', r'$\1.', ocr_result)
        ocr_result = re.sub(r'\$\$(\s*)。', r'$$\1.', ocr_result)
        
        if mode == "单题录入":
            st.session_state["entry_content"] = ""
            st.session_state["entry_custom_tags"] = ""
            st.session_state["entry_remark"] = ""
            st.session_state["entry_difficulty"] = 0.0
            st.session_state["entry_subject_user_locked"] = False

            # 强制清理 AI 可能生成的 ---xxx.tex--- 分隔符
            ocr_result = re.sub(r'---.*?\.tex---\n*', '', ocr_result).strip()
            
            # 解析 LaTeX 填充表单
            match = re.search(r'\\begin\{problem\}\{(.*?)\}\{(.*?)\}\{(.*?)\}\{(.*?)\}\{(.*?)\}', ocr_result, re.DOTALL)
            if match:
                y, t, n, num, s = match.groups()
                st.session_state["entry_year"] = y
                
                # 尝试匹配类型代码
                found_type = False
                # t 可能是 "XK", "XK(学考题)", "学考题" 等形式
                t_clean = t.split('(')[0].split('（')[0].strip()
                
                for k, v in PAPER_TYPES.items():
                    if k == t_clean or v == t_clean or k == t or v == t:
                        st.session_state["entry_p_type"] = k
                        found_type = True
                        break
                
                if not found_type:
                    # 如果没匹配到，默认 G，并在名称里备注原类型
                    st.session_state["entry_p_type"] = "G"
                    if t:
                        n = f"{t}-{n}"
                    
                st.session_state["entry_paper_name"] = n
                st.session_state["entry_number"] = num
                
                # 解析 AI 提取的板块 (支持多板块)
                extracted_subjects = [subj.strip() for subj in s.split("，")]
                valid_subjects = [subj for subj in extracted_subjects if subj in SUBJECTS]
                if valid_subjects:
                    st.session_state["entry_subject_multi"] = valid_subjects
                    st.session_state["entry_subject_user_locked"] = True
                
                # 标记这次内容更新来源于 AI 识别，避免在后续渲染时被本地启发式逻辑覆盖
                st.session_state["_ai_override_subjects"] = True
                
                # 如果没有解析和答案环境，自动预留并重构正确的 \end{problem} 位置
                clean_res = normalize_single_problem_structure(ocr_result.strip(), y, st.session_state.get("entry_p_type", "G"), n, num, s)
                
                # 存储完整的 LaTeX 内容（不再强行插入 Label Data，保持编辑框清爽）
                st.session_state["entry_content"] = clean_res
                st.rerun() 
            else:
                st.warning("识别内容未包含标准 problem 结构，已自动进行结构重组。")
                st.session_state["entry_content"] = normalize_single_problem_structure(ocr_result.strip())
                st.rerun()
                
        else: # 批量模式（包括同卷试题录入和批量试题录入）
            # 智能解析批量OCR结果，支持多问题识别
            processed_result = process_batch_ocr_result(ocr_result, mode)
            
            # 第二次识别直接覆盖，不追加（避免内容重复）
            st.session_state["batch_content"] = processed_result
            st.session_state["batch_items_src_hash"] = None
            st.rerun()

def normalize_single_problem_structure(text, s_year="?", s_type="?", s_paper="?", s_num="?", s_subj="?"):
    r"""安全提取并重组单题的 LaTeX 结构，确保 \begin{problem}...\end{problem} 包裹正确，并预留答案和解析。"""
    # 提取并移除答案
    ans_match = re.search(r'\\begin\{answer\}(.*?)\\end\{answer\}', text, re.DOTALL)
    ans_text = ans_match.group(0) if ans_match else ""
    
    # 提取并移除解析
    sol_match = re.search(r'\\begin\{solutions?\}(.*?)\\end\{solutions?\}', text, re.DOTALL)
    sol_text = sol_match.group(0) if sol_match else ""
    
    # 获取剩余的题干部分
    stem_text = text
    if ans_text:
        stem_text = stem_text.replace(ans_text, "")
    if sol_text:
        stem_text = stem_text.replace(sol_text, "")
        
    # 如果存在旧的 \begin{problem}{...} 参数头部，提取它以便在没有传入新参数时复用
    old_params_match = re.search(r'\\begin\{problem\}(\{.*?\})?(\{.*?\})?(\{.*?\})?(\{.*?\})?(\{.*?\})?', stem_text)
    if old_params_match and s_year == "?":
        params = [p.strip('{}') if p else "?" for p in old_params_match.groups()]
        s_year, s_type, s_paper, s_num, s_subj = (params + ["?", "?", "?", "?", "?"])[:5]
        
    # 彻底清理掉 \begin{problem} 和 \end{problem} 标签，只留纯文本题干
    stem_text = re.sub(r'\\begin\{problem\}(\{.*?\}){0,5}', '', stem_text)
    stem_text = stem_text.replace(r'\end{problem}', '')
    stem_text = stem_text.strip()
    
    # 重新组装
    full_text = f"\\begin{{problem}}{{{s_year}}}{{{s_type}}}{{{s_paper}}}{{{s_num}}}{{{s_subj}}}\n{stem_text}\n\\end{{problem}}"
    
    if ans_text:
        full_text += f"\n\n{ans_text}"
    else:
        full_text += f"\n\n\\begin{{answer}}\n\n\\end{{answer}}"
        
    if sol_text:
        full_text += f"\n\n{sol_text}"
    else:
        full_text += f"\n\n\\begin{{solutions}}\n\n\\end{{solutions}}"
        
    # 修复选择题前面缺少 (\hspace{1cm}) 的问题
    # 先把任何形式的空括号() （）删掉，或者如果已经有 (\hspace{1cm}) 则保留
    # 用更安全的字符串处理方式，避免正则表达式的 Lookbehind 在变长字符串下失效
    if r"\begin{choices}" in full_text:
        parts = full_text.split(r"\begin{choices}")
        for i in range(len(parts) - 1):
            prefix = parts[i].rstrip()
            if prefix.endswith("()") or prefix.endswith("（）"):
                prefix = prefix[:-2]
            
            # 如果结尾还不是 \hspace{1cm}，就加上
            if not prefix.endswith(r"\hspace{1cm})"):
                prefix += r" (\hspace{1cm})"
            parts[i] = prefix + "\n"
        full_text = r"\begin{choices}".join(parts)
        
    return full_text

def fix_problem_format(text):
    """修复 \begin{problem} 的非标准格式，统一转为 {年份}{类别}{试卷}{题号}{板块} 格式"""
    
    # 模式1: [xxx][yyy][zzz] ||aa||bb 格式（AI可能返回的非标准格式）
    pattern1 = r'\\begin\{problem\}\[(.*?)\]\[(.*?)\]\[(.*?)\]\s*\|\|(.*?)\|\|(.*?)\]'
    def repl1(m):
        return f'\\begin{{problem}}{{{m.group(1)}}}{{{m.group(2)}}}{{{m.group(3)}}}{{{m.group(4)}}}{{{m.group(5)}}}'
    text = re.sub(pattern1, repl1, text)
    
    # 模式2: [xxx][yyy][zzz] [aa][bb] 格式（另一种可能的非标准格式）
    pattern2 = r'\\begin\{problem\}\[(.*?)\]\[(.*?)\]\[(.*?)\]\s*\[(.*?)\]\[(.*?)\]'
    def repl2(m):
        return f'\\begin{{problem}}{{{m.group(1)}}}{{{m.group(2)}}}{{{m.group(3)}}}{{{m.group(4)}}}{{{m.group(5)}}}'
    text = re.sub(pattern2, repl2, text)
    
    # 模式3: 无参数的 \begin{problem}（确保有5个参数）
    pattern3 = r'\\begin\{problem\}(?!\{)'
    text = re.sub(pattern3, r'\\begin{problem}{?}{?}{?}{?}{?}', text)
    
    # 修复 \choice 内部的异常换行，将多行的 \choice{{...}} 合并为单行
    # 匹配 \choice{{ 开头，直到 }} 结尾的内容，将其内部的换行符替换为空格
    def fix_choice_newlines(match):
        inner_content = match.group(1).replace('\n', ' ')
        return f"\\choice{{{{{inner_content}}}}}"
    
    text = re.sub(r'\\choice\{\{(.*?)\}\}', fix_choice_newlines, text, flags=re.DOTALL)
    
    return text

def process_batch_ocr_result(ocr_result, mode):
    """处理批量模式下的OCR结果，智能解析多问题并转换格式"""
    
    # 先修复 \begin{problem} 的非标准格式（AI可能返回 [xxx][yyy] ||zzz||www 格式）
    ocr_result = fix_problem_format(ocr_result)
    
    # 尝试检测是否包含多个问题（通过 ---文件名.tex--- 分隔符或多个 \begin{problem}）
    has_file_separators = bool(re.search(r'---.+?\.tex---', ocr_result))
    multiple_problems = len(re.findall(r'\\begin\{problem\}', ocr_result)) > 1
    
    from utils.csv_ops import get_next_id
    current_id = get_next_id()
    
    def inject_label_data(match):
        nonlocal current_id
        template = f"% === Begin Label Data ===\n% ID: {current_id}\n% 难度星级: \n% 标签: \n% 备注: \n% 组卷引用次数: 0\n% === End  Label Data ==="
        current_id += 1
        return f"{match.group(1)}\n\n{template}\n\n"
    
    if has_file_separators or multiple_problems:
        # 场景1: AI返回了带分隔符的多个问题（标准格式）
        if has_file_separators:
            # 同卷模式：保留完整的文件名格式（年份/类别/试卷由表单统一提供，但文件名保持完整）
            if mode == "同卷试题录入":
                converted = convert_to_same_paper_format(ocr_result)
            # 批量模式：保留完整的 \begin{problem} 参数（年份/类别/试卷等信息来自文件名）
            else:
                converted = ocr_result
            # 给每个 ---xxx.tex--- 后面加上自动分配 ID 的 Label Data
            return re.sub(r'(---.*?---)\s*', inject_label_data, converted)
        
        # 场景2: AI返回了多个 \begin{problem} 但没有分隔符
        elif multiple_problems:
            converted = split_and_format_multiple_problems(ocr_result)
            return re.sub(r'(---.*?---)\s*', inject_label_data, converted)
    
    # 场景3: 单个问题或无法自动分割，保持原样但尝试提取信息
    extract_info_to_form(ocr_result)
    # 给每个 ---xxx.tex--- 后面加上自动分配 ID 的 Label Data
    return re.sub(r'(---.*?---)\s*', inject_label_data, ocr_result)

def convert_to_same_paper_format(ocr_result):
    """将完整的OCR结果转换为同卷试题录入格式（保留完整文件名）"""
    parts = re.split(r'(---.+?\.tex---)', ocr_result)
    
    formatted_parts = []
    first_problem_info = None
    
    for i, part in enumerate(parts):
        if part.startswith('---') and part.endswith('---'):
            # 提取文件名信息
            fname = part.replace('---', '').replace('.tex', '')
            segments = fname.split('-')
            
            # 从第一个问题中提取统一信息
            if first_problem_info is None and len(segments) >= 5:
                first_problem_info = {
                    'year': segments[0],
                    'type': segments[1],
                    'paper': segments[2]
                }
            
            # 保留完整的文件名格式（不再简化）
            formatted_parts.append(part)
        else:
            # 保留内容原样
            formatted_parts.append(part)
    
    # 如果提取到了信息，更新到表单
    if first_problem_info:
        update_batch_form_from_ocr(first_problem_info)
    
    result = ''.join(formatted_parts)
    
    # 确保每个问题之间有空行分隔
    result = re.sub(r'(---.+?\.tex---)(?!\s*\n)', r'\1\n\n', result)
    
    return result

def split_and_format_multiple_problems(ocr_result):
    """分割多个连续的问题并添加分隔符"""
    # 按 \begin{problem} 分割
    problem_pattern = r'(\\begin\{problem\}\{.*?\}\{.*?\}\{.*?\}\{.*?\}\{.*?\})'
    problems = re.split(problem_pattern, ocr_result)
    
    formatted_result = ""
    first_info = None
    
    for i in range(len(problems)):
        if re.match(r'\\begin\{problem\}', problems[i]):
            # 提取问题信息
            match = re.match(r'\\begin\{problem\}\{(.*?)\}\{(.*?)\}\{(.*?)\}\{(.*?)\}\{(.*?)\}', problems[i])
            if match:
                y, t, n, num, s = match.groups()
                
                # 记录第一个问题的信息
                if first_info is None:
                    first_info = {'year': y, 'type': t, 'paper': n}
                
                # 生成分隔符（简化格式）
                formatted_result += f"\n\n---{num}-{s}.tex---\n"
                # 使用简化的 \begin{problem}
                formatted_result += "\\begin{problem}\n"
        
        elif problems[i].strip():  # 内容部分
            formatted_result += problems[i]
    
    # 更新表单信息
    if first_info:
        update_batch_form_from_ocr(first_info)
    
    return formatted_result.strip()

def extract_info_to_form(ocr_result):
    """从单个OCR结果中提取信息并更新到表单"""
    match = re.search(r'\\begin\{problem\}\{(.*?)\}\{(.*?)\}\{(.*?)\}\{(.*?)\}\{(.*?)\}', ocr_result, re.DOTALL)
    if match:
        y, t, n, num, s = match.groups()
        info = {'year': y, 'type': t, 'paper': n}
        update_batch_form_from_ocr(info)

def update_batch_form_from_ocr(info):
    """更新同卷试题录入表单中的统一信息"""
    try:
        # 更新年份
        if info.get('year') and info['year'].isdigit():
            st.session_state["u_batch_year"] = info['year']
        
        # 更新类别
        if info.get('type'):
            t_clean = info['type'].split('(')[0].split('（')[0].strip()
            for k, v in PAPER_TYPES.items():
                if k == t_clean or v == t_clean or k == info['type'] or v == info['type']:
                    st.session_state["u_batch_type"] = k
                    break
        
        # 更新试卷名称
        if info.get('paper'):
            st.session_state["u_batch_paper"] = info['paper']
            
        st.toast("✅ 已自动提取并填入年份和试卷信息", icon="📝")
    except Exception as e:
        print(f"更新表单信息时出错: {e}")

# ================= 页面：新题录入 =================
def page_entry():
    st.header("📝 录入新题")
    
    # 初始化 Session State
    if "entry_year" not in st.session_state: st.session_state["entry_year"] = "2024"
    if "entry_p_type" not in st.session_state: st.session_state["entry_p_type"] = "G"
    if "entry_subject_multi" not in st.session_state: st.session_state["entry_subject_multi"] = []
    if "entry_number" not in st.session_state: st.session_state["entry_number"] = "1"
    if "entry_paper_name" not in st.session_state: st.session_state["entry_paper_name"] = "新高考I卷"
    if "entry_content" not in st.session_state: st.session_state["entry_content"] = ""
    if "batch_content" not in st.session_state: st.session_state["batch_content"] = ""
    if "entry_subject_user_locked" not in st.session_state: st.session_state["entry_subject_user_locked"] = False
    
    mode = st.radio("录入模式", ["单题录入", "批量试题录入", "同卷试题录入"], horizontal=True)
    
    if mode == "单题录入":
        col_left, col_mid, col_right = st.columns([1.5, 2, 2])
    else:
        col_left, col_mid, col_right = st.columns([1.5, 4, 0.01])
    
    # === 左侧：AI 识别区 ===
    with col_left:
        st.subheader("🖼️ AI 图片识别 (多图模式)")
        inject_custom_css() # 注入样式
        
        # 确保 Image 模块可用
        try:
            from PIL import Image
        except ImportError:
            st.error("缺少 PIL 库，请安装 pillow")
            return

        # 初始化图片队列
        if "ocr_queue" not in st.session_state:
            st.session_state["ocr_queue"] = []
        if "uploader_prev_files" not in st.session_state:
            st.session_state["uploader_prev_files"] = []

        # 1. 添加图片区域 (横向并列布局)
        if len(st.session_state["ocr_queue"]) < 5:
            st.markdown("##### 添加图片")
            c_add_1, c_add_2 = st.columns([1, 1])
            
            with c_add_1:
                # 粘贴/上传 (支持多选) - 本地文件
                uploaded_files = st.file_uploader("📂 本地上传", type=["png", "jpg", "jpeg"], key="queue_uploader", accept_multiple_files=True)
            
            with c_add_2:
                # 读取剪贴板按钮 - 稍微向下偏移以对齐
                st.write("") 
                st.write("")
                def _read_clipboard_image_candidates():
                    if not ImageGrab:
                        st.error("缺少 PIL 库")
                        return []
                    clipboard_content = ImageGrab.grabclipboard()
                    candidates = []
                    if isinstance(clipboard_content, Image.Image):
                        candidates.append({"label": "剪贴板图片 1", "image": clipboard_content.copy()})
                    elif isinstance(clipboard_content, list):
                        for item in clipboard_content:
                            if isinstance(item, str) and os.path.isfile(item):
                                try:
                                    img = Image.open(item)
                                    img.load()
                                    candidates.append({"label": os.path.basename(item), "image": img.copy()})
                                except Exception:
                                    pass
                    return candidates

                def _append_clipboard_first_image():
                    try:
                        candidates = _read_clipboard_image_candidates()
                    except Exception as e:
                        st.error(f"剪贴板读取失败: {e}")
                        return
                    if not candidates:
                        st.warning("剪贴板中没有图片或支持的图片文件")
                        return
                    item = candidates[0]
                    count_added = 0
                    if len(st.session_state["ocr_queue"]) < 5:
                        st.session_state["ocr_queue"].append(item["image"])
                        count_added = 1
                    else:
                        st.warning("队列已满，无法添加图片")
                    if count_added > 0:
                        st.toast(f"已从剪贴板添加 {count_added} 张图片", icon="✅")
                        st.rerun()
                    else:
                        st.warning("队列已满或没有新图片")

                if st.button("📋 粘贴剪贴板首张图片", use_container_width=True):
                    _append_clipboard_first_image()

            # 处理上传的文件 (多文件，增量添加)
            if uploaded_files:
                # 构建当前文件的简单标识列表 (文件名_大小)
                current_file_ids = [f"{f.name}_{f.size}" for f in uploaded_files]
                prev_file_ids = st.session_state["uploader_prev_files"]
                
                new_added = False
                for uf in uploaded_files:
                    fid = f"{uf.name}_{uf.size}"
                    if fid not in prev_file_ids:
                        # 这是一个新文件，添加到队列
                        if len(st.session_state["ocr_queue"]) < 5:
                            try:
                                img = Image.open(uf)
                                st.session_state["ocr_queue"].append(img)
                                new_added = True
                            except Exception as e:
                                st.error(f"图片 {uf.name} 读取失败: {e}")
                        else:
                            st.warning("队列已满，部分图片未添加")
                
                # 更新 prev state
                st.session_state["uploader_prev_files"] = current_file_ids
                
                if new_added:
                    st.rerun()
            else:
                # 如果用户清空了上传器，我们也清空记录
                st.session_state["uploader_prev_files"] = []

        else:
            st.info("已达到最大图片数量 (5张)")

        # 2. 图片队列展示与管理
        if st.session_state["ocr_queue"]:
            c_q_header, c_q_clear = st.columns([3, 1])
            with c_q_header:
                st.write(f"当前队列: {len(st.session_state['ocr_queue'])}/5 张")
            with c_q_clear:
                if st.button("🗑️ 清空", key="clear_queue", use_container_width=True):
                    st.session_state["ocr_queue"] = []
                    # 同时也建议用户手动清空上传器（无法程序化清空，但我们可以重置 prev_files 以允许重新添加）
                    st.session_state["uploader_prev_files"] = [] 
                    st.rerun()
            
            for i, img in enumerate(st.session_state["ocr_queue"]):
                c_img, c_ctrl = st.columns([1, 2])
                with c_img:
                    st.image(img, use_container_width=True)
                with c_ctrl:
                    st.caption(f"图片 {i+1}")
                    # 按钮组：上移 下移 删除 放大
                    c_btn1, c_btn2, c_btn3, c_btn4 = st.columns(4)
                    with c_btn1:
                        if i > 0:
                            if st.button("⬆️", key=f"mv_up_{i}", help="前移"):
                                st.session_state["ocr_queue"][i], st.session_state["ocr_queue"][i-1] = st.session_state["ocr_queue"][i-1], st.session_state["ocr_queue"][i]
                                st.rerun()
                    with c_btn2:
                        if i < len(st.session_state["ocr_queue"]) - 1:
                            if st.button("⬇️", key=f"mv_down_{i}", help="后移"):
                                st.session_state["ocr_queue"][i], st.session_state["ocr_queue"][i+1] = st.session_state["ocr_queue"][i+1], st.session_state["ocr_queue"][i]
                                st.rerun()
                    with c_btn3:
                        if st.button("🗑️", key=f"del_{i}", help="删除"):
                            st.session_state["ocr_queue"].pop(i)
                            st.rerun()
                    with c_btn4:
                        if st.button("🔍", key=f"zoom_{i}", help="放大"):
                            zoom_image(img)
            
            st.divider()
            
            # 3. 识别操作
            if st.button("🚀 识别所有图片", type="primary", use_container_width=True):
                 with st.spinner("🤖 AI 正在识别多张图片..."):
                    ocr_result = ocr_image_to_latex(images=st.session_state["ocr_queue"])
                    process_ocr_result(ocr_result, mode)
        else:
            st.info("请添加图片进行识别")

        # 增加手动中断提示
        st.caption("提示: 如果 AI 响应时间过长，请直接刷新页面以中断。")
    # === 中间：录入/批量区 ===
    with col_mid:
        if mode == "单题录入":
            st.subheader("📝 单题详情")
            
            def update_content_wrapper():
                """根据表单字段更新 entry_content 中的 problem 包裹"""
                content = st.session_state.get("entry_content", "")
                year = st.session_state.get("entry_year", "")
                p_type = st.session_state.get("entry_p_type", "G")
                paper = st.session_state.get("entry_paper_name", "")
                number = st.session_state.get("entry_number", "")
                subj_list = st.session_state.get("entry_subject_multi", [])
                subj = "，".join(subj_list) if subj_list else ""
                
                # 尝试匹配现有的 problem 包裹
                prob_match = re.search(r'(\\begin\{problem\})\{.*?\}\{.*?\}\{.*?\}\{.*?\}\{.*?\}', content, re.DOTALL)
                if prob_match:
                    # 替换现有的参数
                    new_header = f"\\begin{{problem}}{{{year}}}{{{p_type}}}{{{paper}}}{{{number}}}{{{subj}}}"
                    content = content[:prob_match.start()] + new_header + content[prob_match.end():]
                    st.session_state["entry_content"] = content
                elif year and p_type and paper and number:
                    # 没有 problem 包裹，添加一个
                    content = f"\\begin{{problem}}{{{year}}}{{{p_type}}}{{{paper}}}{{{number}}}{{{subj}}}\n{content}\n\\end{{problem}}"
                    st.session_state["entry_content"] = content
            
            c_r1_1, c_r1_2, c_r1_3 = st.columns([1, 2, 1.5])
            with c_r1_1:
                year = st.text_input("年份", key="entry_year", on_change=update_content_wrapper)
            with c_r1_2:
                # 知识板块推断与选择逻辑优化
                current_content = st.session_state.get("entry_content", "")
                last_inferred_content = st.session_state.get("_last_inferred_content", None)
                
                if st.session_state.get("_ai_override_subjects", False):
                    st.session_state["_ai_override_subjects"] = False
                    st.session_state["_last_inferred_content"] = current_content
                elif (not st.session_state.get("entry_subject_user_locked", False)) and current_content != last_inferred_content and current_content.strip() != "":
                    inferred_subjects = []
                    for s in SUBJECTS:
                        if len(s) > 1 and s in current_content:
                            inferred_subjects.append(s)
                    if inferred_subjects:
                        st.session_state["entry_subject_multi"] = inferred_subjects
                    st.session_state["_last_inferred_content"] = current_content

                current_multi = st.session_state.get("entry_subject_multi", [])
                valid_current_multi = [s for s in current_multi if s in SUBJECTS]
                    
                if st.session_state.get("entry_subject_multi") != valid_current_multi:
                    st.session_state["entry_subject_multi"] = valid_current_multi
                def _on_subject_change():
                    st.session_state["entry_subject_user_locked"] = True
                    update_content_wrapper()
                st.multiselect("知识板块 (首个为主)", options=SUBJECTS, key="entry_subject_multi", on_change=_on_subject_change)
                subjects = st.session_state.get("entry_subject_multi") or []
                subject = "，".join(subjects) if subjects else ""
            with c_r1_3:
                type_opts = list(PAPER_TYPES.keys())
                current_p_type = st.session_state.get("entry_p_type", "G")
                if current_p_type not in type_opts:
                    current_p_type = "G"
                    st.session_state["entry_p_type"] = "G"
                default_type_idx = type_opts.index(current_p_type)
                
                st.selectbox("试卷类别", options=type_opts, index=default_type_idx, format_func=lambda x: f"{x} ({PAPER_TYPES[x]})", key="entry_p_type", on_change=update_content_wrapper)
                p_type_code = st.session_state.get("entry_p_type", "G")

            c_r2_1, c_r2_2 = st.columns([3, 1])
            with c_r2_1:
                paper_name = st.text_input("试卷名称", key="entry_paper_name", on_change=update_content_wrapper)
            with c_r2_2:
                number = st.text_input("题号", key="entry_number", on_change=update_content_wrapper)
            
            st.markdown("##### 🏷️ 附加属性")
            c_attr1, c_attr2, c_attr3 = st.columns([1.2, 2, 2])
            with c_attr1:
                st.markdown("<div style='font-size: 14px; color: #31333F; margin-bottom: 5px;'><b>难度星级</b></div>", unsafe_allow_html=True)
                from utils.star_rating import st_star_rating
                s_difficulty_val = st_star_rating(label="", value=st.session_state.get("entry_difficulty", 0.0), max_stars=6, key="star_entry_difficulty")
                if s_difficulty_val != st.session_state.get("entry_difficulty", 0.0):
                    st.session_state["entry_difficulty"] = s_difficulty_val
            with c_attr2:
                st.markdown("<div style='font-size: 14px; color: #31333F; margin-bottom: 5px;'><b>标签 (用逗号“，”分隔)</b></div>", unsafe_allow_html=True)
                s_tags = st.text_input("标签", placeholder="例如: 压轴题, 易错点", key="entry_custom_tags", label_visibility="collapsed")
            with c_attr3:
                st.markdown("<div style='font-size: 14px; color: #31333F; margin-bottom: 5px;'><b>备注</b></div>", unsafe_allow_html=True)
                s_remark = st.text_input("备注", placeholder="例如: 2025新高考题型", key="entry_remark", label_visibility="collapsed")
            
            c_content_lbl, c_ai_btn = st.columns([3, 1], vertical_alignment="bottom")
            with c_content_lbl:
                st.markdown("##### 📝 题目内容 (LaTeX)")
            with c_ai_btn:
                def on_ai_analyze_click():
                    content = st.session_state.get("entry_content", "").strip()
                    if not content:
                        st.toast("题目内容为空，无法进行 AI 分析", icon="⚠️")
                        return
                    
                    res = call_ai_for_tags(content)
                    if "error" in res:
                        st.toast(res["error"], icon="❌")
                    else:
                        diff = res["difficulty"]
                        tags = res["tags"]
                        
                        if 0.0 <= diff <= 6.0:
                            st.session_state["entry_difficulty"] = diff
                        if tags:
                            old_tags = st.session_state.get("entry_custom_tags", "").strip()
                            if old_tags:
                                all_tags = set([t.strip() for t in old_tags.split("，") if t.strip()] + [t.strip() for t in tags.split("，") if t.strip()])
                                st.session_state["entry_custom_tags"] = "，".join(all_tags)
                            else:
                                st.session_state["entry_custom_tags"] = tags
                                
                        st.toast("AI 标签与难度评级成功！", icon="🪄")

                st.button("🪄 AI 自动打标签", on_click=on_ai_analyze_click, use_container_width=True)

        # 所有模式共用的查找替换
        def _normalize_circled_digits(text: str) -> str:
            if not text:
                return text
            mapping = {
                "①": r"\circled{1}",
                "②": r"\circled{2}",
                "③": r"\circled{3}",
                "④": r"\circled{4}",
                "⑤": r"\circled{5}",
            }
            for k, v in mapping.items():
                text = text.replace(k, v)
            return text

        def render_find_replace(target_key):
            with st.expander("🔍 查找与替换", expanded=False):
                c_f_1, c_f_2, c_f_3, c_f_4 = st.columns([2, 2, 1, 1])
                with c_f_1: f_str = st.text_input("查找", key=f"entry_find_{target_key}")
                with c_f_2: r_str = st.text_input("替换", key=f"entry_replace_{target_key}")
                with c_f_3:
                    st.write("")
                    st.write("")
                    if st.button("替换", key=f"btn_entry_replace_{target_key}"):
                        if st.session_state.get(target_key, "") and f_str:
                            st.session_state[target_key] = st.session_state[target_key].replace(f_str, r_str)
                            st.toast("替换完成", icon="✅")
                            st.rerun()
                with c_f_4:
                    st.write("")
                    st.write("")
                    if st.button("圈号→LaTeX", key=f"btn_entry_circled_{target_key}"):
                        cur = st.session_state.get(target_key, "") or ""
                        st.session_state[target_key] = _normalize_circled_digits(cur)
                        st.toast("已替换圈号 ①②③④⑤", icon="✅")
                        st.rerun()

        if mode == "单题录入":
            st.markdown("##### ⚙️ 录入配置")
            auto_solve_enabled = st.checkbox("本次录入同时生成解答", key="entry_auto_solve", value=False)

            render_find_replace("entry_content")
            
            def on_content_change():
                """当用户编辑源码框时，同步回表单字段"""
                content = st.session_state.get("entry_content", "")
                if not content:
                    return
                
                fields = extract_problem_header_fields(content)
                if fields:
                    sy = fields["year"]
                    st_type = fields["p_type"]
                    sp = fields["paper"]
                    sn = fields["number"]
                    ss = fields["subject_str"]
                    if sy:
                        st.session_state["entry_year"] = sy
                    if st_type:
                        st.session_state["entry_p_type"] = st_type
                    if sp:
                        st.session_state["entry_paper_name"] = sp
                    if sn:
                        st.session_state["entry_number"] = sn
                    extracted_subjs = [s.strip() for s in (ss or "").split("，") if s.strip()]
                    valid_subjs = [s for s in extracted_subjs if s in SUBJECTS]
                    if valid_subjs:
                        st.session_state["entry_subject_multi"] = valid_subjs
                        st.session_state["entry_subject_user_locked"] = True
            
            content = st.text_area("题目内容 (LaTeX)", height=400, placeholder="在此粘贴题目内容...", key="entry_content", label_visibility="collapsed", on_change=on_content_change)
            
        elif mode in ["批量试题录入", "同卷试题录入"]:
            def _split_batch_text_to_items(text: str):
                text = text or ""
                parts = re.split(r'---(.+\.tex)---\s*', text)
                items = []
                for i in range(1, len(parts), 2):
                    if i + 1 < len(parts):
                        fname = (parts[i] or "").strip()
                        body = (parts[i + 1] or "").lstrip()
                        if fname:
                            items.append({"filename": fname, "content": body})
                return items
            
            def _join_batch_items(items):
                out = []
                for it in items or []:
                    fname = (it.get("filename") or "").strip()
                    if fname.startswith("---") and fname.endswith("---"):
                        fname = fname[3:-3].strip()
                    fname = fname.replace("\n", " ").replace("\r", " ").strip()
                    if fname and not fname.lower().endswith(".tex"):
                        fname += ".tex"
                    body = (it.get("content") or "").rstrip()
                    if not fname:
                        continue
                    out.append(f"---{fname}---\n{body}".rstrip())
                return "\n\n".join(out).strip()

            def _write_batch_items_state(items, src_hash=None):
                old_count = int(st.session_state.get("batch_item_count") or 0)
                items = items or []
                st.session_state["batch_item_count"] = len(items)
                if src_hash is not None:
                    st.session_state["batch_items_src_hash"] = src_hash
                for idx, it in enumerate(items):
                    st.session_state[f"batch_item_name_{idx}"] = it.get("filename", "")
                    st.session_state[f"batch_item_text_{idx}"] = it.get("content", "")
                for idx in range(len(items), old_count):
                    st.session_state.pop(f"batch_item_name_{idx}", None)
                    st.session_state.pop(f"batch_item_text_{idx}", None)
             
            def _ensure_batch_items_state():
                src = st.session_state.get("batch_content", "") or ""
                src_hash = hashlib.md5(src.encode("utf-8", errors="ignore")).hexdigest()
                if st.session_state.get("batch_items_src_hash") == src_hash and st.session_state.get("batch_item_count") is not None:
                    return
                items = _split_batch_text_to_items(src)
                _write_batch_items_state(items, src_hash)
            
            def _current_items_from_state():
                n = int(st.session_state.get("batch_item_count") or 0)
                items = []
                for idx in range(n):
                    fname = st.session_state.get(f"batch_item_name_{idx}", "")
                    body = st.session_state.get(f"batch_item_text_{idx}", "")
                    items.append({"filename": fname, "content": body})
                return items

            def _set_batch_content_and_hash(new_text: str):
                new_text = (new_text or "").strip()
                st.session_state["batch_content"] = new_text
                st.session_state["batch_items_src_hash"] = hashlib.md5(new_text.encode("utf-8", errors="ignore")).hexdigest()

            def _sync_batch_content_from_items():
                _set_batch_content_and_hash(_join_batch_items(_current_items_from_state()))

            def _apply_same_paper_meta_to_items(items, year, p_type, paper):
                synced = []
                for it in items or []:
                    fname = (it.get("filename") or "").strip()
                    content = it.get("content") or ""
                    name_body = fname.replace(".tex", "")
                    segments = name_body.split("-")
                    if len(segments) >= 2:
                        q_num = segments[-2]
                        q_subj = segments[-1]
                    else:
                        q_num = "?"
                        q_subj = "未分类"

                    synced_name = generate_filename(year, p_type, paper, q_num, q_subj)
                    if content.strip():
                        if "\\begin{problem}" in content:
                            synced_content = replace_problem_header(content, year, p_type, paper, q_num, q_subj)
                        else:
                            synced_content = normalize_single_problem_structure(content.strip(), year, p_type, paper, q_num, q_subj)
                    else:
                        synced_content = content
                    synced.append({"filename": synced_name, "content": synced_content})
                return synced
            
            _ensure_batch_items_state()
            
            c_title, c_ai_btn = st.columns([3, 1], vertical_alignment="bottom")
            with c_title:
                st.markdown(f"### 📚 {mode}")
            with c_ai_btn:
                def on_batch_ai_click():
                    batch_text = _join_batch_items(_current_items_from_state())
                    if not batch_text.strip():
                        st.warning("内容为空，无法进行 AI 分析")
                        return
                    
                    # Split by `---filename---`
                    parts = re.split(r'(---.+\.tex---\s*)', batch_text)
                    new_batch_text = ""
                    if len(parts) > 1:
                        new_batch_text = parts[0]
                        from utils.latex_ops import parse_meta_data
                        
                        progress_text = "🤖 正在批量调用 AI..."
                        my_bar = st.progress(0, text=progress_text)
                        total_q = len(parts) // 2
                        
                        for i in range(1, len(parts), 2):
                            current_q = i // 2 + 1
                            my_bar.progress(current_q / total_q, text=f"{progress_text} ({current_q}/{total_q})")
                            
                            header = parts[i]
                            content = parts[i+1]
                            existing_meta, clean_content = parse_meta_data(content)
                            
                            # 调用 AI
                            ai_res = call_ai_for_tags(clean_content)
                            if "error" not in ai_res:
                                diff = ai_res["difficulty"]
                                existing_meta["难度星级"] = str(diff) if diff > 0 else ""
                                existing_meta["标签"] = ai_res["tags"]
                            else:
                                st.toast(f"第 {current_q} 题 AI 分析出错: {ai_res['error']}", icon="❌")
                                
                            meta_str = "% === Begin Label Data ===\n"
                            meta_str += f"% ID: {existing_meta.get('ID', '')}\n"
                            meta_str += f"% 难度星级: {existing_meta.get('难度星级', '')}\n"
                            meta_str += f"% 标签: {existing_meta.get('标签', '')}\n"
                            meta_str += f"% 备注: {existing_meta.get('备注', '')}\n"
                            meta_str += f"% 组卷引用次数: {existing_meta.get('组卷引用次数', '0')}\n"
                            meta_str += "% === End  Label Data ===\n\n"
                            
                            new_batch_text += header + meta_str + clean_content.lstrip()
                            
                        my_bar.empty()
                        _set_batch_content_and_hash(new_batch_text)
                        st.toast("批量 AI 自动打标签完成！", icon="🪄")
                    else:
                        st.warning("未检测到有效的分隔线格式，请确保内容符合 `---xxx.tex---` 格式")

                st.button("🪄 AI 自动打标签", key="btn_batch_ai", on_click=on_batch_ai_click, use_container_width=True)
            
            # 如果是同卷录入，提供试卷头部信息输入
            if mode == "同卷试题录入":
                st.info("💡 **同卷模式**：下方填写的【年份】【试卷名称】等信息，将自动应用到所有识别出的题目中。")
                if "u_batch_year" not in st.session_state:
                    st.session_state["u_batch_year"] = "2024"
                if "u_batch_paper" not in st.session_state:
                    st.session_state["u_batch_paper"] = "新高考I卷"
                if "u_batch_type" not in st.session_state:
                    st.session_state["u_batch_type"] = "G"
                    
                c1, c2, c3, c4 = st.columns([1.5, 2, 1.5, 1])
                batch_year = c1.text_input("统一年份", key="u_batch_year")
                batch_pname = c2.text_input("统一试卷名称", key="u_batch_paper")
                type_opts = list(PAPER_TYPES.keys())
                batch_ptype = c3.selectbox("统一试卷类别", options=type_opts, format_func=lambda x: f"{x} ({PAPER_TYPES[x]})", key="u_batch_type")
                
                with c4:
                    st.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)
                    def on_sync_click():
                        s_y = st.session_state.get("u_batch_year", "")
                        s_t = st.session_state.get("u_batch_type", "G")
                        s_p = st.session_state.get("u_batch_paper", "")
                        
                        if s_y and s_p:
                            items = _apply_same_paper_meta_to_items(_current_items_from_state(), s_y, s_t, s_p)
                            new_text = _join_batch_items(items)
                            
                            # 自动匹配并分配空的 ID
                            from utils.csv_ops import get_next_id
                            current_id = get_next_id()
                            def repl_id(m):
                                nonlocal current_id
                                val = m.group(1).strip()
                                if not val:  # 只有为空时才分配新ID，防止重复点击浪费ID
                                    val = str(current_id)
                                    current_id += 1
                                return f"% ID: {val}"
                            # 修复正则：匹配末尾可能的空格或换行符
                            new_text = re.sub(r'% ID:\s*(.*?)(?=\n|$)', repl_id, new_text)
                            _set_batch_content_and_hash(new_text)
                            _write_batch_items_state(_split_batch_text_to_items(new_text), st.session_state["batch_items_src_hash"])
                            
                    if st.button("🔄 同步更新", help="将上方填写的年份、类别和试卷名称，一键替换下方所有源码中的 problem 标签", on_click=on_sync_click, use_container_width=True, type="secondary"):
                        st.toast("已同步更新所有 problem 标签及预分配ID！", icon="✅")

            with st.expander("🔍 查找与替换", expanded=False):
                c_f_1, c_f_2, c_f_3, c_f_4 = st.columns([2, 2, 1, 1])
                with c_f_1:
                    f_str = st.text_input("查找", key="batch_find_all")
                with c_f_2:
                    r_str = st.text_input("替换", key="batch_replace_all")
                with c_f_3:
                    st.write("")
                    st.write("")
                    def _apply_batch_replace():
                        if not f_str:
                            return
                        items = _current_items_from_state()
                        for idx, it in enumerate(items):
                            # 同时替换文件名和正文内容
                            fname = (it.get("filename") or "").replace(f_str, r_str)
                            content = (it.get("content") or "").replace(f_str, r_str)
                            st.session_state[f"batch_item_name_{idx}"] = fname
                            st.session_state[f"batch_item_text_{idx}"] = content
                        _sync_batch_content_from_items()
                    if st.button("替换", key="btn_batch_replace_all", on_click=_apply_batch_replace):
                        st.toast("替换完成（含标题）", icon="✅")
                with c_f_4:
                    st.write("")
                    st.write("")
                    def _apply_batch_circled():
                        items = _current_items_from_state()
                        for idx, it in enumerate(items):
                            st.session_state[f"batch_item_text_{idx}"] = _normalize_circled_digits(it.get("content") or "")
                        _sync_batch_content_from_items()
                    if st.button("圈号→LaTeX", key="btn_batch_circled_all", on_click=_apply_batch_circled):
                        st.toast("已替换圈号 ①②③④⑤", icon="✅")

            st.markdown("##### 📝 题目内容 (LaTeX)")
            items = _current_items_from_state()
            if not items:
                st.text_area("批量内容编辑", height=260, key="batch_content_fallback", label_visibility="collapsed")
            else:
                st.markdown("""
<style>
button[kind="secondary"][data-testid="stBaseButton-secondary"][aria-label="放弃本题×"] {
    color: #dc3545 !important;
    border-color: #dc3545 !important;
}
button[kind="secondary"][data-testid="stBaseButton-secondary"][aria-label="放弃本题×"]:hover {
    color: #fff !important;
    background-color: #dc3545 !important;
    border-color: #dc3545 !important;
}
</style>
""", unsafe_allow_html=True)
                for idx, it in enumerate(items):
                    st.markdown('<hr style="border-top: 1px solid #e1e4e8; margin-top: 14px; margin-bottom: 14px;">', unsafe_allow_html=True)
                    c_src, c_prev = st.columns([1, 1])
                    with c_src:
                        c_fn_1, c_btn_1, c_btn_2 = st.columns([3, 1, 1], vertical_alignment="bottom")
                        with c_fn_1:
                            st.text_input("文件名", key=f"batch_item_name_{idx}", on_change=_sync_batch_content_from_items)
                        with c_btn_1:
                            def _apply_batch_fname():
                                _sync_batch_content_from_items()
                                st.toast("已应用文件名修改", icon="✅")
                                st.rerun()
                            st.button("应用标题", key=f"batch_apply_fname_{idx}", use_container_width=True, on_click=_apply_batch_fname)
                        with c_btn_2:
                            def _discard_batch_item(_idx=idx):
                                # 从 batch_content 中移除该题目
                                items = _current_items_from_state()
                                if 0 <= _idx < len(items):
                                    items.pop(_idx)
                                    new_text = _join_batch_items(items)
                                    _set_batch_content_and_hash(new_text)
                                    _write_batch_items_state(items, st.session_state["batch_items_src_hash"])
                                    st.toast("已放弃该题目")
                                st.rerun()
                            st.button("放弃本题×", key=f"batch_discard_fname_{idx}", use_container_width=True, on_click=_discard_batch_item, type="secondary")
                        st.text_area("题目源码", height=240, key=f"batch_item_text_{idx}", label_visibility="collapsed", on_change=_sync_batch_content_from_items)
                        st.caption("提示：编辑后点击空白处或按 Ctrl+Enter 以应用更新。")
                    with c_prev:
                        fname = (st.session_state.get(f"batch_item_name_{idx}", "") or "").strip()
                        st.markdown(f"### 📄 {fname}")
                        try:
                            preview_src = st.session_state.get(f"batch_item_text_{idx}", "") or ""
                            st.markdown(latex_to_markdown(preview_src, show_title=False), unsafe_allow_html=True)
                        except Exception as e:
                            st.error(f"预览渲染出错: {e}")
                _sync_batch_content_from_items()

            st.markdown('<hr style="border-top: 1px solid #e1e4e8; margin-top: 12px; margin-bottom: 16px;">', unsafe_allow_html=True)
            if mode == "同卷试题录入":
                c_same_title, c_same_btn = st.columns([2, 1])
                with c_same_title:
                    st.markdown("### 📚 同卷试题批量处理状态")
                with c_same_btn:
                    if st.button("💾 同卷提取并保存", type="primary", use_container_width=True, key="same_paper_save_btn"):
                        st.session_state["_run_same_paper_batch"] = True
                        st.session_state["_run_ai_tagging_batch"] = st.session_state.get("batch_enable_ai_flag", False)
                        st.session_state["batch_enable_ai_flag"] = False
                        st.rerun()
                st.info("同卷试题批量录入的处理结果会在此显示。")
                
                if st.session_state.get("_run_same_paper_batch", False):
                    st.session_state["_run_same_paper_batch"] = False
                    batch_text = st.session_state.get("batch_content", "")
                    u_year = st.session_state.get("u_batch_year", "")
                    u_paper = st.session_state.get("u_batch_paper", "")
                    u_type = st.session_state.get("u_batch_type", "G")
                    
                    if not batch_text.strip():
                        st.warning("请输入内容")
                    elif not (u_year and u_paper):
                        st.error("请完善年份和试卷名称信息")
                    else:
                        parts = re.split(r'---(.+\.tex)---\s*', batch_text)
                        count = 0
                        log_msg = []
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        total_files = len(parts) // 2
                        for i in range(1, len(parts), 2):
                            current_idx = i // 2 + 1
                            if i + 1 < len(parts):
                                raw_fname = parts[i].strip()
                                file_content = parts[i+1].strip()
                                status_text.text(f"正在处理: {raw_fname} ({current_idx}/{total_files})")
                                name_body = raw_fname.replace('.tex', '')
                                segments = name_body.split('-')
                                if len(segments) >= 2:
                                    q_num = segments[-2]
                                    q_subj = segments[-1]
                                    final_filename = generate_filename(u_year, u_type, u_paper, q_num, q_subj)
                                    primary_subj = q_subj.split("，")[0]
                                    save_dir = os.path.join(CHAPTERS_DIR, primary_subj, str(u_year))
                                    ensure_dir(save_dir)
                                    file_path = os.path.join(save_dir, final_filename)
                                    if "\\begin{problem}" in file_content:
                                        file_content = replace_problem_header(file_content, str(u_year), u_type, u_paper, q_num, q_subj)
                                    else:
                                        file_content = normalize_single_problem_structure(file_content, str(u_year), u_type, u_paper, q_num, q_subj)
                                    file_content = extract_and_replace_tikz(file_content, final_filename, save_dir)
                                    from utils.latex_ops import parse_meta_data, inject_meta_data
                                    existing_meta, clean_content = parse_meta_data(file_content)
                                    q_id = existing_meta.get("ID", "")
                                    if not q_id:
                                        from utils.csv_ops import get_next_id
                                        q_id = get_next_id()
                                    meta_dict = {"ID": q_id, "难度星级": existing_meta.get("难度星级", ""), "标签": existing_meta.get("标签", ""), "备注": existing_meta.get("备注", ""), "组卷引用次数": existing_meta.get("组卷引用次数", "0")}
                                    file_content = inject_meta_data(file_content, meta_dict)
                                    try:
                                        atomic_write_text(file_path, file_content, backup=os.path.exists(file_path))
                                        add_to_csv_index(file_path, file_content, str(u_year), u_type, u_paper, q_num, q_subj)
                                        count += 1
                                        ai_str = ""
                                        if meta_dict['难度星级'] or meta_dict['标签']:
                                            ai_str = f" [AI自动提取: 星级={meta_dict['难度星级'] or '无'} | 标签={meta_dict['标签'] or '无'}]"
                                        log_msg.append({"status": "success", "file": final_filename, "path": file_path, "ai_info": ai_str})
                                    except Exception as e:
                                        log_msg.append({"status": "error", "file": final_filename, "msg": str(e)})
                                else:
                                    log_msg.append({"status": "skip", "file": raw_fname, "msg": "文件名格式不足 (需至少包含 题号-板块)"})
                            progress_bar.progress(current_idx / total_files)
                        status_text.empty()
                        c_msg, c_jump = st.columns([3, 1])
                        c_msg.success(f"处理完成，共保存 {count} 个文件")
                        def _jump_to_browse_same_paper():
                            st.session_state["main_sidebar_radio"] = "🔍\n全局浏览与编辑"
                            st.session_state["adv_search_active"] = False
                            st.session_state["recent_saved_active"] = True
                            st.session_state["recent_saved_paths"] = [log.get("path") for log in log_msg if log.get("status") == "success" and log.get("path")]
                        c_jump.button("跳转至全局浏览查看 ↗", use_container_width=True, type="primary", key="jump_to_browse_same_paper", on_click=_jump_to_browse_same_paper)
                        st.toast(f"同卷处理完成！共保存 {count} 个文件", icon="✅")
                        with st.expander("查看处理日志", expanded=True):
                            for log in log_msg:
                                if log["status"] == "success":
                                    c1, c2 = st.columns([4, 1])
                                    ai_str = log.get('ai_info', '')
                                    c1.success(f"✅ {log['file']}{ai_str}")
                                    if c2.button("📂 打开", key=f"open_log_u_{log['file']}"):
                                        try:
                                            os.startfile(log['path'])
                                        except Exception as e:
                                            st.error(f"无法打开: {e}")
                                elif log["status"] == "error":
                                    st.error(f"❌ {log['file']}: {log['msg']}")
                                else:
                                    st.warning(f"⚠️ {log['file']}: {log['msg']}")

            elif mode == "批量试题录入":
                c_batch_title, c_batch_btn = st.columns([2, 1])
                with c_batch_title:
                    st.markdown("### 🗃️ 批量处理状态")
                with c_batch_btn:
                    if st.button("💾 批量提取并保存", type="primary", use_container_width=True, key="batch_save_btn"):
                        st.session_state["_run_batch_mode"] = True
                        st.session_state["_run_ai_tagging_global_batch"] = st.session_state.get("batch_enable_ai_flag", False)
                        st.session_state["batch_enable_ai_flag"] = False
                        st.rerun()
                st.info("批量录入的处理结果会在此显示。")
                if st.session_state.get("_run_batch_mode", False):
                    st.session_state["_run_batch_mode"] = False
                    batch_text = st.session_state.get("batch_content", "")
                    if not batch_text.strip():
                        st.warning("请输入内容")
                    else:
                        parts = re.split(r'---(.+\.tex)---\s*', batch_text)
                        count = 0
                        log_msg = []
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        total_files = len(parts) // 2
                        for i in range(1, len(parts), 2):
                            current_idx = i // 2 + 1
                            if i + 1 < len(parts):
                                filename = parts[i].strip()
                                file_content = parts[i+1].strip()
                                status_text.text(f"正在处理: {filename} ({current_idx}/{total_files})")
                                name_body = filename.replace('.tex', '')
                                segments = name_body.split('-')
                                if len(segments) >= 5:
                                    year_seg = segments[0]
                                    topic_seg = segments[-1]
                                    primary_topic = topic_seg.split("，")[0]
                                    save_dir = os.path.join(CHAPTERS_DIR, primary_topic, str(year_seg))
                                    ensure_dir(save_dir)
                                    file_path = os.path.join(save_dir, filename)
                                    file_content = extract_and_replace_tikz(file_content, filename, save_dir)
                                    from utils.latex_ops import parse_meta_data, inject_meta_data
                                    existing_meta, clean_content = parse_meta_data(file_content)
                                    q_id = existing_meta.get("ID", "")
                                    if not q_id:
                                        from utils.csv_ops import get_next_id
                                        q_id = get_next_id()
                                    meta_dict = {"ID": q_id, "难度星级": existing_meta.get("难度星级", ""), "标签": existing_meta.get("标签", ""), "备注": existing_meta.get("备注", ""), "组卷引用次数": existing_meta.get("组卷引用次数", "0")}
                                    file_content = inject_meta_data(file_content, meta_dict)
                                    try:
                                        atomic_write_text(file_path, file_content, backup=os.path.exists(file_path))
                                        add_to_csv_index(file_path, file_content, segments[0], segments[1], segments[2], segments[3], segments[4])
                                        count += 1
                                        ai_str = ""
                                        if meta_dict['难度星级'] or meta_dict['标签']:
                                            ai_str = f" [AI自动提取: 星级={meta_dict['难度星级'] or '无'} | 标签={meta_dict['标签'] or '无'}]"
                                        log_msg.append({"status": "success", "file": filename, "path": file_path, "id": q_id, "ai_info": ai_str})
                                    except Exception as e:
                                        log_msg.append({"status": "error", "file": filename, "msg": str(e)})
                                else:
                                    log_msg.append({"status": "skip", "file": filename, "msg": "文件名格式错误"})
                            progress_bar.progress(current_idx / total_files)
                        status_text.empty()
                        c_msg, c_jump = st.columns([3, 1])
                        c_msg.success(f"处理完成，共保存 {count} 个文件")
                        def _jump_to_browse_batch():
                            st.session_state["main_sidebar_radio"] = "🔍\n全局浏览与编辑"
                            st.session_state["adv_search_active"] = False
                            st.session_state["recent_saved_active"] = True
                            st.session_state["recent_saved_paths"] = [log.get("path") for log in log_msg if log.get("status") == "success" and log.get("path")]
                        c_jump.button("跳转至全局浏览查看 ↗", use_container_width=True, type="primary", key="jump_to_browse_batch", on_click=_jump_to_browse_batch)
                        clear_statistics_cache()
                        st.toast(f"批量处理完成！共保存 {count} 个文件", icon="✅")
                        with st.expander("查看处理日志", expanded=True):
                            for log in log_msg:
                                if log["status"] == "success":
                                    c1, c2 = st.columns([4, 1])
                                    ai_str = log.get('ai_info', '')
                                    c1.success(f"✅ {log['file']}{ai_str}")
                                    if c2.button("📂 打开", key=f"open_log_{log['file']}"):
                                        try:
                                            os.startfile(log['path'])
                                        except Exception as e:
                                            st.error(f"无法打开: {e}")
                                elif log["status"] == "error":
                                    st.error(f"❌ {log['file']}: {log['msg']}")
                                else:
                                    st.warning(f"⚠️ {log['file']}: {log['msg']}")
            
    # === 右侧：实时预览与保存（仅单题模式） ===
    with col_right:
        if mode == "单题录入":
            c_preview_title, c_save_btn = st.columns([2, 1])
            with c_preview_title:
                st.subheader("👁️ 实时预览与保存")
            with c_save_btn:
                def on_save_entry():
                    s_content = st.session_state.get("entry_content", "")
                    fields = extract_problem_header_fields(s_content)
                    s_year = (fields.get("year") if fields else "") or st.session_state.get("entry_year", "")
                    s_type = (fields.get("p_type") if fields else "") or st.session_state.get("entry_p_type", "")
                    s_paper = (fields.get("paper") if fields else "") or st.session_state.get("entry_paper_name", "")
                    s_num = (fields.get("number") if fields else "") or st.session_state.get("entry_number", "")
                    s_subj_from_state = "，".join(st.session_state.get("entry_subject_multi", []) or []).strip()
                    s_subj_str = ((fields.get("subject_str") if fields else "") or s_subj_from_state).strip()
                    s_subj = s_subj_str if s_subj_str else "未分类"
                    s_diff_raw = st.session_state.get("entry_difficulty", 0.0)
                    s_diff = "" if s_diff_raw == 0.0 else str(s_diff_raw)
                    s_tag = st.session_state.get("entry_custom_tags", "")
                    s_rem = st.session_state.get("entry_remark", "")
                    if not s_content:
                        st.toast("题目内容不能为空", icon="⚠️")
                        return
                    full_text = normalize_single_problem_structure(s_content.strip(), s_year, s_type, s_paper, s_num, s_subj)
                    s_filename = generate_filename(s_year, s_type, s_paper, s_num, s_subj)
                    primary_subj = s_subj.split("，")[0]
                    s_save_dir = os.path.join(CHAPTERS_DIR, primary_subj, s_year)
                    ensure_dir(s_save_dir)
                    s_file_path = os.path.join(s_save_dir, s_filename)
                    full_text = extract_and_replace_tikz(full_text, s_filename, s_save_dir)
                    from utils.csv_ops import get_next_id
                    new_id = get_next_id()
                    meta_dict = {"ID": new_id, "难度星级": s_diff, "标签": s_tag, "备注": s_rem, "组卷引用次数": 0}
                    from utils.latex_ops import inject_meta_data
                    full_text = inject_meta_data(full_text, meta_dict)
                    try:
                        with open(s_file_path, "w", encoding="utf-8") as f:
                            f.write(full_text)
                        add_to_csv_index(s_file_path, full_text, s_year, s_type, s_paper, s_num, s_subj)
                        if st.session_state.get("entry_auto_solve", False):
                            problem_tex = _extract_problem_env(full_text)
                            with st.spinner("🤖 AI 正在生成解答..."):
                                res = call_ai_for_answer_solutions(problem_tex, fast=False)
                            if "error" in res:
                                st.toast(f"自动生成解答失败: {res['error']}", icon="❌")
                            else:
                                try:
                                    _apply_generated_answer_solutions_to_file(s_file_path, res["answer_tex"], res["solutions_tex"], mode="replace")
                                    st.toast("已自动生成并写回解答", icon="🪄")
                                except Exception as e:
                                    st.toast(f"写回解答失败: {e}", icon="❌")
                        st.toast(f"成功保存到: {s_filename} (分配ID: {new_id})", icon="✅")
                        clear_statistics_cache()
                        st.session_state["entry_year"] = s_year
                        st.session_state["entry_p_type"] = s_type
                        st.session_state["entry_paper_name"] = s_paper
                        st.session_state["entry_number"] = s_num
                        st.session_state["entry_subject_multi"] = [s.strip() for s in (s_subj or "").split("，") if s.strip() and s.strip() in SUBJECTS]
                        st.session_state["entry_subject_user_locked"] = True
                        st.session_state["entry_content"] = ""
                        st.session_state["entry_difficulty"] = 0.0
                        st.session_state["entry_custom_tags"] = ""
                        st.session_state["entry_remark"] = ""
                        st.session_state["entry_number"] = ""
                    except Exception as e:
                        st.toast(f"保存失败: {e}", icon="❌")
                st.button("💾 保存题目", type="primary", on_click=on_save_entry, use_container_width=True)
            filename = generate_filename(year, p_type_code, paper_name, number, subject or "未分类")
            st.info(f"目标文件名: `{filename}`")
            if content.strip():
                st.markdown("---")
                try:
                    md_preview = latex_to_markdown(content, show_title=True)
                    st.markdown(md_preview, unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"预览渲染出错: {e}")
        else:
            st.empty()
                             
# ================= 页面：浏览/编辑 =================
def page_browse(is_exam_mode=False):
    if not is_exam_mode:
        c_header, c_search = st.columns([1, 1.5])
        with c_header:
            st.header("🔍 全局浏览与编辑")
            st.subheader("浏览模式")
            if "browse_mode" not in st.session_state:
                st.session_state["browse_mode"] = "按知识板块浏览"
            browse_mode = st.radio("浏览模式", ["按知识板块浏览", "按试卷浏览", "按录入顺序浏览"], horizontal=True, label_visibility="collapsed", key="browse_mode")
            
        with c_search:
            # 嵌入三级查找栏
            render_advanced_search_inline()
            
    else:
        if "browse_mode" not in st.session_state:
            st.session_state["browse_mode"] = "按知识板块浏览"
        browse_mode = st.radio("浏览模式", ["按知识板块浏览", "按试卷浏览", "按录入顺序浏览"], horizontal=True, label_visibility="collapsed", key="browse_mode")
    
    # 根据红线截图，我们在这里画一条醒目的红线
    st.markdown('<hr style="border-top: 1px solid #e1e4e8; margin-top: 10px; margin-bottom: 20px;">', unsafe_allow_html=True)
    
    if not is_exam_mode and st.session_state.get("recent_saved_active") and st.session_state.get("recent_saved_paths"):
        paths = [p for p in st.session_state.get("recent_saved_paths", []) if p and os.path.exists(p)]
        c1, c2 = st.columns([1, 1])
        with c1:
            st.subheader("🧾 本次录入的题目")
        with c2:
            def _clear_recent_saved():
                st.session_state["recent_saved_active"] = False
                st.session_state["recent_saved_paths"] = []
            st.button("返回正常浏览", type="secondary", use_container_width=True, on_click=_clear_recent_saved, key="recent_saved_back")
        
        if not paths:
            st.info("未找到可展示的文件（可能已移动/删除）。")
            return
        
        for fpath in paths:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                st.error(f"读取失败: {e}")
                continue
            
            fname = os.path.basename(fpath)
            q_label = format_question_title(fname)
            render_question_header(q_label, content, fpath)
            c_l, c_r = st.columns([1, 1])
            edit_mode_key = f"recent_saved_edit_mode_{fpath}"
            with c_l:
                mtime_token = int(os.path.getmtime(fpath)) if os.path.exists(fpath) else 0
                est_height = get_editor_height(content)
                is_editing = st.session_state.get(edit_mode_key, False)
                text_area_key = f"recent_saved_edit_{fpath}"
                if is_editing:
                    st.text_area("源码", value=content, height=est_height, key=text_area_key)
                    st.button("💾 保存修改", key=f"recent_saved_save_btn_{fpath}", type="primary", on_click=_save_tex_from_widget, args=(fpath, text_area_key, edit_mode_key, f"{q_label} 已保存"))
                else:
                    st.text_area("源码", value=content, height=est_height, disabled=True, key=f"{text_area_key}_readonly_{mtime_token}")
                    tag_edit_key = f"recent_saved_tag_edit_mode_{fpath}"
                    is_tag_editing = st.session_state.get(tag_edit_key, False)
                    btn_c1, btn_c2, btn_c3 = st.columns(3)
                    with btn_c1:
                        if st.button("✏️ 开始修改tex内容", key=f"recent_saved_start_btn_{fpath}"):
                            st.session_state[text_area_key] = content
                            st.session_state[edit_mode_key] = True
                            st.rerun()
                    with btn_c2:
                        if is_tag_editing:
                            if st.button("✅ 完成修改题目信息", key=f"recent_saved_tag_save_btn_{fpath}", type="primary"):
                                base = os.path.basename(fpath).replace(".tex", "")
                                parts = base.split("-")
                                if len(parts) >= 5:
                                    old_year, old_ptype, old_pname, old_pnum, old_subj = parts[0], parts[1], parts[2], parts[3], parts[4]
                                    fhash = hashlib.md5(fpath.encode()).hexdigest()[:10]
                                    new_year = st.session_state.get(f"recent_meta_year_{fhash}", old_year)
                                    new_type = st.session_state.get(f"recent_meta_type_{fhash}", old_ptype)
                                    new_name = st.session_state.get(f"recent_meta_paper_{fhash}", old_pname)
                                    new_num = st.session_state.get(f"recent_meta_num_{fhash}", old_pnum)
                                    new_subjects = st.session_state.get(f"recent_saved_tag_select_{fhash}", [old_subj])
                                    new_subject_str = "，".join(new_subjects) if isinstance(new_subjects, list) else str(new_subjects or old_subj)
                                    try:
                                        new_path, _ = apply_meta_rename_and_update(fpath, str(new_year), str(new_type), str(new_name), str(new_num), new_subject_str)
                                        old_list = st.session_state.get("recent_saved_paths") or []
                                        st.session_state["recent_saved_paths"] = [new_path if p == fpath else p for p in old_list]
                                        st.toast("修改成功！", icon="✅")
                                        st.session_state[tag_edit_key] = False
                                        time.sleep(0.5)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"修改失败: {e}")
                                else:
                                    st.error("文件名格式不支持修改")
                        else:
                            if st.button("🏷️ 开始修改题目信息", key=f"recent_saved_tag_start_btn_{fpath}"):
                                st.session_state[tag_edit_key] = True
                                st.rerun()
                    with btn_c3:
                        render_ai_solution_generate_button(fpath, content, key_prefix="ai_solution_recent_saved")
                    render_ai_solution_image_ocr_section(fpath, key_prefix="ai_solution_recent_saved")
                    if is_tag_editing:
                        base = os.path.basename(fpath).replace(".tex", "")
                        parts = base.split("-")
                        cur_year = parts[0] if len(parts) >= 5 else ""
                        cur_type = parts[1] if len(parts) >= 5 else "G"
                        cur_paper = parts[2] if len(parts) >= 5 else ""
                        cur_num = parts[3] if len(parts) >= 5 else ""
                        cur_subjects = (parts[4] if len(parts) >= 5 else "").split("，")
                        valid_tags = [t for t in cur_subjects if t in SUBJECTS] or [SUBJECTS[0]]
                        fhash = hashlib.md5(fpath.encode()).hexdigest()[:10]
                        type_opts = list(PAPER_TYPES.keys())
                        c_meta1, c_meta2 = st.columns([1, 1])
                        with c_meta1:
                            st.text_input("年份", value=str(cur_year), key=f"recent_meta_year_{fhash}")
                        with c_meta2:
                            if cur_type not in type_opts:
                                cur_type = "G"
                            st.selectbox("试卷类别", options=type_opts, index=type_opts.index(cur_type), format_func=lambda x: f"{x} ({PAPER_TYPES[x]})", key=f"recent_meta_type_{fhash}")
                        st.text_input("试卷名称", value=str(cur_paper), key=f"recent_meta_paper_{fhash}")
                        st.text_input("题号", value=str(cur_num), key=f"recent_meta_num_{fhash}")
                        st.multiselect("知识板块 (首个为主)", options=SUBJECTS, default=valid_tags, key=f"recent_saved_tag_select_{fhash}")
            with c_r:
                try:
                    st.markdown(latex_to_markdown(content, show_title=False), unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"渲染错误: {e}")
            render_ai_solution_panel(fpath, q_label, key_prefix="ai_solution_recent_saved")
            st.divider()
        return
    
    # === 如果激活了搜索，优先显示搜索结果 ===
    if not is_exam_mode and st.session_state.get("adv_search_active"):
        if _adv_search_has_query():
            render_advanced_search_results()
            return  # 搜索状态下，不显示下方的常规浏览内容
        st.session_state["adv_search_active"] = False
    
    selected_file_path = None
    
    if browse_mode == "按知识板块浏览":
        # 左右布局：左侧导航，右侧文件列表与编辑
        col_nav, col_content = st.columns([1, 2.5])
        
        with col_nav:
            st.markdown('<div id="knowledge-subject-area"></div>', unsafe_allow_html=True)
            st.markdown('<div id="left-panel-anchor"></div>', unsafe_allow_html=True)
            st.markdown("### 📂 知识板块")
            
            # 使用自定义 CSS 优化按钮样式 (圆角、紧凑) 以及固定左栏
            st.markdown("""
                <style>
                /* 固定左侧整栏 (吸顶悬浮效果) */
                /* 修复 Streamlit 的 column 高度机制导致 sticky 失效的问题 */
                div[data-testid="stHorizontalBlock"]:has(#left-panel-anchor) {
                    align-items: flex-start !important;
                }
                div[data-testid="column"]:has(#left-panel-anchor) {
                    position: -webkit-sticky !important;
                    position: sticky !important;
                    top: 2rem !important;
                    height: calc(100vh - 2rem) !important;
                    overflow-y: auto !important;
                    padding-right: 1rem !important;
                }
                
                /* 右侧栏恢复正常流 */
                div[data-testid="column"]:has(#right-panel-anchor) {
                    border-left: 1px solid #e1e4e8 !important;
                    padding-left: 1.5rem !important;
                }
                
                /* 隐藏左侧栏的滚动条以便美观 */
                div[data-testid="column"]:has(#left-panel-anchor)::-webkit-scrollbar {
                    width: 4px;
                }
                div[data-testid="column"]:has(#left-panel-anchor)::-webkit-scrollbar-thumb {
                    background-color: rgba(0,0,0,0.1);
                    border-radius: 4px;
                }
                
                /* 精准定位知识板块区域的按钮 */
                div[data-testid="column"]:has(#knowledge-subject-area) div[data-testid="stButton"] {
                    display: flex !important;
                    justify-content: center !important;
                    width: 100% !important;
                }
                div[data-testid="column"]:has(#knowledge-subject-area) div[data-testid="stButton"] button {
                    width: 85% !important;  
                    min-width: 85% !important;
                    max-width: 85% !important;
                    border-radius: 6px !important;
                    padding: 0.1rem 0.15rem !important;
                    min-height: 32px !important;
                    height: 32px !important;
                    margin-bottom: 2px !important;
                }
                div[data-testid="column"]:has(#knowledge-subject-area) div[data-testid="stButton"] button p {
                    font-size: 13px !important;
                    line-height: 1.2 !important;
                }
                </style>
            """, unsafe_allow_html=True)
            
            # 使用 session_state 记录当前选中的板块
            if "browse_subject" not in st.session_state:
                st.session_state["browse_subject"] = SUBJECTS[0]

            # 三列排列，按钮宽度缩小
            # 通过 columns 来实现三列
            for i in range(0, len(SUBJECTS), 3):
                cols = st.columns(3)
                
                # 遍历当前行的三列
                for j in range(3):
                    idx = i + j
                    if idx < len(SUBJECTS):
                        subj = SUBJECTS[idx]
                        btn_type = "primary" if st.session_state["browse_subject"] == subj else "secondary"
                        with cols[j]:
                            if st.button(subj, key=f"nav_subj_{subj}", type=btn_type, use_container_width=True):
                                st.session_state["browse_subject"] = subj
                                st.rerun()
            
            subject = st.session_state["browse_subject"]
            
            st.write("")
            st.write("")
            years = get_years(subject)
            if years:
                # 2. 选择年份 (横向排列)
                st.subheader("📅 选择年份")
                
                # 增加“显示所有年份”选项
                ALL_YEARS_OPT = "显示所有年份"
                year_options = [ALL_YEARS_OPT] + years
                
                default_year_index = 1 if len(year_options) > 1 else 0
                year = st.radio("📅 选择年份", options=year_options, index=default_year_index, key=f"browse_year_{subject}", horizontal=True, label_visibility="collapsed")
                
                st.divider()
                
                selected_option = None
                SHOW_ALL_OPT = None
                
                if year == ALL_YEARS_OPT:
                    # 获取该板块下所有年份的所有文件
                    files = []
                    for y in years:
                        y_files = get_files(subject, y)
                        if y_files:
                            # 为了区分不同年份，我们在文件名列表中带上年份信息
                            files.extend([(y, f) for f in y_files])
                            
                    if files:
                        st.subheader(f"📄 文件列表 ({subject} - 所有年份)")
                        
                        # 增加“展示全部”选项
                        SHOW_ALL_OPT = "📂 展示该板块全部问题"
                        # 格式化选项供选择
                        display_options = [f"{y}年 - {f}" for y, f in files]
                        file_options = [SHOW_ALL_OPT] + display_options

                        selected_option = st.selectbox(
                            "3. 选择文件 (支持输入搜索)", 
                            options=file_options,
                            key=f"browse_file_select_{subject}_all",
                            label_visibility="collapsed"
                        )
                else:
                    # 原来的单一年份逻辑
                    files = get_files(subject, year)
                    if files:
                        st.subheader(f"📄 文件列表 ({subject} - {year})")
                        
                        SHOW_ALL_OPT = "📂 展示该年份全部问题"
                        file_options = [SHOW_ALL_OPT] + files

                        selected_option = st.selectbox(
                            "3. 选择文件 (支持输入搜索)", 
                            options=file_options,
                            key=f"browse_file_select_{subject}_{year}",
                            label_visibility="collapsed"
                        )
            
        with col_content:
            st.markdown('<div id="right-panel-anchor"></div>', unsafe_allow_html=True)
            if years:
                if year == ALL_YEARS_OPT:
                    if files:
                        if selected_option == SHOW_ALL_OPT:
                            st.markdown(f"### {subject} - 所有年份所有题目")
                            
                            for i, (y, fname) in enumerate(files):
                                fpath = os.path.join(CHAPTERS_DIR, subject, y, fname)
                                if not os.path.exists(fpath): continue
                                
                                with open(fpath, "r", encoding="utf-8") as f:
                                    content = f.read()
                                    
                                q_label = format_question_title(fname)

                                render_question_header(q_label, content, fpath)
                                
                                if is_exam_mode:
                                    # 组卷模式：仅展示渲染结果及操作按钮
                                    st.markdown(latex_to_markdown(content), unsafe_allow_html=True)
                                    is_selected = fpath in st.session_state.get("exam_selected_qs", [])
                                    if is_selected:
                                        st.markdown('<span class="red-btn-hook"></span>', unsafe_allow_html=True)
                                        if st.button("❌ 本题取消组卷", key=f"exam_rm_{fpath}", type="primary"):
                                            st.session_state["exam_selected_qs"].remove(fpath)
                                            if st.session_state.get("ai_exam_active"):
                                                st.session_state["ai_exam_modified"] = True
                                            st.rerun()
                                    else:
                                        if st.button("➕ 本题加入组卷", key=f"exam_add_{fpath}", type="secondary"):
                                            st.session_state["exam_selected_qs"].append(fpath)
                                            if st.session_state.get("ai_exam_active"):
                                                st.session_state["ai_exam_modified"] = True
                                            st.rerun()
                                    st.divider()
                                    continue
                                
                                c1, c2 = st.columns([1, 1])
                                edit_mode_key = f"browse_edit_mode_{fpath}"
                                
                                with c1:
                                    est_height = get_editor_height(content)
                                    is_editing = st.session_state.get(edit_mode_key, False)
                                    text_area_key = f"subj_all_edit_{fpath}"
                                    
                                    if is_editing:
                                        st.text_area("源码", value=content, height=est_height, key=text_area_key)
                                        st.button("💾 保存修改", key=f"subj_save_btn_{fpath}", type="primary", on_click=_save_tex_from_widget, args=(fpath, text_area_key, edit_mode_key, f"{q_label} 已保存"))
                                    else:
                                        mtime_token = int(os.path.getmtime(fpath)) if os.path.exists(fpath) else 0
                                        st.text_area("源码", value=content, height=est_height, disabled=True, key=f"{text_area_key}_readonly_{mtime_token}")
                                        
                                        tag_edit_key = f"tag_edit_mode_{fpath}"
                                        is_tag_editing = st.session_state.get(tag_edit_key, False)
                                        
                                        btn_c1, btn_c2, btn_c3 = st.columns(3)
                                        with btn_c1:
                                            if st.button("✏️ 开始修改tex内容", key=f"subj_start_btn_{fpath}"):
                                                st.session_state[text_area_key] = content
                                                st.session_state[edit_mode_key] = True
                                                st.rerun()
                                        with btn_c2:
                                            if is_tag_editing:
                                                if st.button("✅ 完成修改题目信息", key=f"tag_save_btn_{fpath}", type="primary"):
                                                    base = os.path.basename(fpath).replace(".tex", "")
                                                    parts = base.split("-")
                                                    if len(parts) >= 5:
                                                        old_year, old_ptype, old_pname, old_pnum, old_subj = parts[0], parts[1], parts[2], parts[3], parts[4]
                                                        fhash = hashlib.md5(fpath.encode()).hexdigest()[:10]
                                                        new_year = st.session_state.get(f"subj_meta_year_{fhash}", old_year)
                                                        new_type = st.session_state.get(f"subj_meta_type_{fhash}", old_ptype)
                                                        new_name = st.session_state.get(f"subj_meta_paper_{fhash}", old_pname)
                                                        new_num = st.session_state.get(f"subj_meta_num_{fhash}", old_pnum)
                                                        new_subjects = st.session_state.get(f"tag_select_{fhash}", [old_subj])
                                                        new_subject_str = "，".join(new_subjects) if isinstance(new_subjects, list) else str(new_subjects or old_subj)
                                                        try:
                                                            apply_meta_rename_and_update(fpath, str(new_year), str(new_type), str(new_name), str(new_num), new_subject_str)
                                                            st.toast("修改成功！", icon="✅")
                                                            st.session_state[tag_edit_key] = False
                                                            time.sleep(0.5)
                                                            st.rerun()
                                                        except Exception as e:
                                                            st.error(f"修改失败: {e}")
                                                    else:
                                                        st.error("文件名格式不支持修改")
                                            else:
                                                if st.button("🏷️ 开始修改题目信息", key=f"tag_start_btn_{fpath}"):
                                                    st.session_state[tag_edit_key] = True
                                                    st.rerun()
                                        with btn_c3:
                                            render_ai_solution_generate_button(fpath, content, key_prefix="ai_solution_v1")
                                        render_ai_solution_image_ocr_section(fpath, key_prefix="ai_solution_v1")
                                                
                                        if is_tag_editing:
                                            base = os.path.basename(fpath).replace(".tex", "")
                                            parts = base.split("-")
                                            cur_year = parts[0] if len(parts) >= 5 else ""
                                            cur_type = parts[1] if len(parts) >= 5 else "G"
                                            cur_paper = parts[2] if len(parts) >= 5 else ""
                                            cur_num = parts[3] if len(parts) >= 5 else ""
                                            cur_subjects = (parts[4] if len(parts) >= 5 else "").split("，")
                                            valid_tags = [t for t in cur_subjects if t in SUBJECTS] or [SUBJECTS[0]]
                                            fhash = hashlib.md5(fpath.encode()).hexdigest()[:10]
                                            type_opts = list(PAPER_TYPES.keys())
                                            c_meta1, c_meta2 = st.columns([1, 1])
                                            with c_meta1:
                                                st.text_input("年份", value=str(cur_year), key=f"subj_meta_year_{fhash}")
                                            with c_meta2:
                                                if cur_type not in type_opts:
                                                    cur_type = "G"
                                                st.selectbox("试卷类别", options=type_opts, index=type_opts.index(cur_type), format_func=lambda x: f"{x} ({PAPER_TYPES[x]})", key=f"subj_meta_type_{fhash}")
                                            st.text_input("试卷名称", value=str(cur_paper), key=f"subj_meta_paper_{fhash}")
                                            st.text_input("题号", value=str(cur_num), key=f"subj_meta_num_{fhash}")
                                            st.multiselect("知识板块 (首个为主)", options=SUBJECTS, default=valid_tags, key=f"tag_select_{fhash}")

                                with c2:
                                    try:
                                        st.markdown(latex_to_markdown(content), unsafe_allow_html=True)
                                    except Exception as e:
                                        st.error(f"渲染错误: {e}")
                                
                                render_ai_solution_panel(fpath, q_label, key_prefix="ai_solution_v1")
                                
                                st.divider()
                        elif selected_option:
                            # 解析出真实的年份和文件名
                            sel_y = selected_option.split("年 - ")[0]
                            sel_f = selected_option.split("年 - ")[1]
                            selected_file_path = os.path.join(CHAPTERS_DIR, subject, sel_y, sel_f)
                    else:
                        st.info("该板块下暂无任何文件")
                else:
                    if files:
                        if selected_option == SHOW_ALL_OPT:
                            # 不显示底部的单文件编辑器
                            st.markdown(f"### {year}年 {subject} - 所有题目")
                            
                            for i, fname in enumerate(files):
                                fpath = os.path.join(CHAPTERS_DIR, subject, year, fname)
                                if not os.path.exists(fpath): continue
                                
                                # 读取内容
                                with open(fpath, "r", encoding="utf-8") as f:
                                    content = f.read()
                                
                                # 提取显示标签
                                q_label = format_question_title(fname)

                                render_question_header(q_label, content, fpath)
                                
                                if is_exam_mode:
                                    # 组卷模式：仅展示渲染结果及操作按钮
                                    st.markdown(latex_to_markdown(content), unsafe_allow_html=True)
                                    is_selected = fpath in st.session_state.get("exam_selected_qs", [])
                                    if is_selected:
                                        st.markdown('<span class="red-btn-hook"></span>', unsafe_allow_html=True)
                                        if st.button("❌ 本题取消组卷", key=f"exam_rm_{fpath}", type="primary"):
                                            st.session_state["exam_selected_qs"].remove(fpath)
                                            if st.session_state.get("ai_exam_active"):
                                                st.session_state["ai_exam_modified"] = True
                                            st.rerun()
                                    else:
                                        if st.button("➕ 本题加入组卷", key=f"exam_add_{fpath}", type="secondary"):
                                            st.session_state["exam_selected_qs"].append(fpath)
                                            if st.session_state.get("ai_exam_active"):
                                                st.session_state["ai_exam_modified"] = True
                                            st.rerun()
                                    st.divider()
                                    continue
                                
                                # 左右布局: 编辑 vs 预览
                                c1, c2 = st.columns([1, 1])
                                
                                # 编辑模式状态 key
                                edit_mode_key = f"browse_edit_mode_{fpath}"
                                
                                with c1:
                                    est_height = get_editor_height(content)
                                    
                                    is_editing = st.session_state.get(edit_mode_key, False)
                                    text_area_key = f"subj_all_edit_{fpath}"
                                    
                                    if is_editing:
                                        new_content = st.text_area(
                                            "源码", 
                                            value=content, 
                                            height=est_height, 
                                            key=f"{text_area_key}_{int(os.path.getmtime(fpath)) if os.path.exists(fpath) else 0}"
                                        )
                                        if st.button("💾 保存修改", key=f"subj_save_btn_{fpath}", type="primary"):
                                            final_content = save_modified_tex_file(fpath, new_content)
                                            _update_csv_index_for_content_change(fpath, final_content)
                                            st.session_state[edit_mode_key] = False
                                            st.toast(f"{q_label} 已保存", icon="✅")
                                            time.sleep(0.5)
                                            st.rerun()
                                    else:
                                        mtime_token = int(os.path.getmtime(fpath)) if os.path.exists(fpath) else 0
                                        st.text_area(
                                            "源码", 
                                            value=content, 
                                            height=est_height, 
                                            disabled=True,
                                            key=f"{text_area_key}_readonly_{mtime_token}"
                                        )
                                        
                                        tag_edit_key = f"tag_edit_mode_{fpath}"
                                        is_tag_editing = st.session_state.get(tag_edit_key, False)
                                        
                                        btn_c1, btn_c2, btn_c3 = st.columns(3)
                                        with btn_c1:
                                            if st.button("✏️ 开始修改tex内容", key=f"subj_start_btn_{fpath}"):
                                                st.session_state[edit_mode_key] = True
                                                st.rerun()
                                        with btn_c2:
                                            if is_tag_editing:
                                                if st.button("✅ 完成修改题目信息", key=f"tag_save_btn_{fpath}", type="primary"):
                                                    base = os.path.basename(fpath).replace(".tex", "")
                                                    parts = base.split("-")
                                                    if len(parts) >= 5:
                                                        old_year, old_ptype, old_pname, old_pnum, old_subj = parts[0], parts[1], parts[2], parts[3], parts[4]
                                                        fhash = hashlib.md5(fpath.encode()).hexdigest()[:10]
                                                        new_year = st.session_state.get(f"subj2_meta_year_{fhash}", old_year)
                                                        new_type = st.session_state.get(f"subj2_meta_type_{fhash}", old_ptype)
                                                        new_name = st.session_state.get(f"subj2_meta_paper_{fhash}", old_pname)
                                                        new_num = st.session_state.get(f"subj2_meta_num_{fhash}", old_pnum)
                                                        new_subjects = st.session_state.get(f"tag_select_{fhash}", [old_subj])
                                                        new_subject_str = "，".join(new_subjects) if isinstance(new_subjects, list) else str(new_subjects or old_subj)
                                                        try:
                                                            apply_meta_rename_and_update(fpath, str(new_year), str(new_type), str(new_name), str(new_num), new_subject_str)
                                                            st.toast("修改成功！", icon="✅")
                                                            st.session_state[tag_edit_key] = False
                                                            time.sleep(0.5)
                                                            st.rerun()
                                                        except Exception as e:
                                                            st.error(f"修改失败: {e}")
                                                    else:
                                                        st.error("文件名格式不支持修改")
                                            else:
                                                if st.button("🏷️ 开始修改题目信息", key=f"tag_start_btn_{fpath}"):
                                                    st.session_state[tag_edit_key] = True
                                                    st.rerun()
                                        with btn_c3:
                                            render_ai_solution_generate_button(fpath, content, key_prefix="ai_solution_v1")
                                        render_ai_solution_image_ocr_section(fpath, key_prefix="ai_solution_v1")
                                                
                                        if is_tag_editing:
                                            base = os.path.basename(fpath).replace(".tex", "")
                                            parts = base.split("-")
                                            cur_year = parts[0] if len(parts) >= 5 else ""
                                            cur_type = parts[1] if len(parts) >= 5 else "G"
                                            cur_paper = parts[2] if len(parts) >= 5 else ""
                                            cur_num = parts[3] if len(parts) >= 5 else ""
                                            cur_subjects = (parts[4] if len(parts) >= 5 else "").split("，")
                                            valid_tags = [t for t in cur_subjects if t in SUBJECTS] or [SUBJECTS[0]]
                                            fhash = hashlib.md5(fpath.encode()).hexdigest()[:10]
                                            type_opts = list(PAPER_TYPES.keys())
                                            c_meta1, c_meta2 = st.columns([1, 1])
                                            with c_meta1:
                                                st.text_input("年份", value=str(cur_year), key=f"subj2_meta_year_{fhash}")
                                            with c_meta2:
                                                if cur_type not in type_opts:
                                                    cur_type = "G"
                                                st.selectbox("试卷类别", options=type_opts, index=type_opts.index(cur_type), format_func=lambda x: f"{x} ({PAPER_TYPES[x]})", key=f"subj2_meta_type_{fhash}")
                                            st.text_input("试卷名称", value=str(cur_paper), key=f"subj2_meta_paper_{fhash}")
                                            st.text_input("题号", value=str(cur_num), key=f"subj2_meta_num_{fhash}")
                                            st.multiselect("知识板块 (首个为主)", options=SUBJECTS, default=valid_tags, key=f"tag_select_{fhash}")

                                with c2:
                                    try:
                                        st.markdown(latex_to_markdown(content), unsafe_allow_html=True)
                                    except Exception as e:
                                        st.error(f"渲染错误: {e}")
                                
                                render_ai_solution_panel(fpath, q_label, key_prefix="ai_solution_v1")
                                
                                st.divider()

                        elif selected_option and selected_option != SHOW_ALL_OPT:
                             selected_file_path = os.path.join(CHAPTERS_DIR, subject, year, selected_option)
                    else:
                        st.info("该目录下暂无文件")
            else:
                st.warning("该板块暂无年份数据")
                
    elif browse_mode == "按试卷浏览":
        # 采用一致的双栏独立滑动布局
        col_nav, col_content = st.columns([0.8, 3])
        
        with col_nav:
            st.markdown('<div id="paper-left-anchor"></div>', unsafe_allow_html=True)
            
            st.markdown("""
                <style>
                div[data-testid="stHorizontalBlock"]:has(#paper-left-anchor) {
                    height: calc(100vh - 150px) !important;
                    align-items: stretch !important;
                    overflow: hidden !important;
                }
                .stApp { overflow-y: hidden !important; }
                
                div[data-testid="column"]:has(#paper-left-anchor) {
                    height: 100% !important; 
                    overflow-y: auto !important;
                    padding-right: 1rem !important;
                }
                
                div[data-testid="column"]:has(#paper-right-anchor) {
                    height: 100% !important;
                    overflow-y: auto !important;
                    border-left: 1px solid #e1e4e8 !important;
                    padding-left: 1.5rem !important;
                }
                
                div[data-testid="column"]::-webkit-scrollbar { width: 4px; }
                div[data-testid="column"]::-webkit-scrollbar-thumb { background-color: rgba(0,0,0,0.15); border-radius: 4px; }
                </style>
            """, unsafe_allow_html=True)
            
            all_years = get_all_years_globally()
            type_opts = list(PAPER_TYPES.keys())
            def _fmt_paper_type(x):
                if x == "全部类型":
                    return "全部类型"
                return PAPER_TYPES.get(x, x)
            def _on_paper_type_change():
                st.session_state.pop("paper_year", None)
                st.session_state.pop("paper_name", None)
            st.subheader("🗂️ 类型选择")
            paper_type = st.selectbox("题目类型", options=["全部类型"] + type_opts, format_func=_fmt_paper_type, key="paper_type", label_visibility="collapsed", on_change=_on_paper_type_change)
            
            if paper_type != "全部类型":
                years_for_type = get_all_years_by_paper_type(paper_type)
            else:
                years_for_type = all_years
            
            if not years_for_type:
                st.warning("题库中暂无任何年份数据")
            else:
                st.subheader("📅 选择年份")
                def _on_paper_year_change():
                    st.session_state.pop("paper_name", None)
                year = st.radio("📅 选择年份", options=years_for_type, key="paper_year", horizontal=True, label_visibility="collapsed", on_change=_on_paper_year_change)
                
                st.write("")
                st.subheader("📂 试卷选择")
                if paper_type != "全部类型":
                    papers = get_papers_by_year_and_type(year, paper_type)
                else:
                    papers = get_papers_by_year(year)
                if papers:
                    paper_name = st.selectbox("选择试卷", options=papers, key="paper_name", label_visibility="collapsed")
                else:
                    paper_name = None
                    st.info("该年份下未找到试卷")
                    
                st.write("")
                st.subheader("👀 展示模式")
                view_mode = st.radio("展示模式", ["单题选择模式", "所有问题展示模式"], horizontal=False, label_visibility="collapsed")
                
                if all_years and year and paper_name:
                    if paper_type != "全部类型":
                        questions = get_questions_by_paper_and_type(year, paper_name, paper_type)
                    else:
                        questions = get_questions_by_paper(year, paper_name)
                    if questions and view_mode == "单题选择模式":
                        st.write("")
                        st.subheader("选择题目进行编辑")
                        
                        # 使用 session_state 记录当前选中的题目索引
                        select_key = f"selected_q_idx_{year}_{paper_name}"
                        if select_key not in st.session_state:
                            st.session_state[select_key] = 0
                        
                        # 按钮网格布局 (每行 3 个，适配左栏宽度)
                        num_cols = 3
                        rows = (len(questions) + num_cols - 1) // num_cols
                        
                        for r in range(rows):
                            cols = st.columns(num_cols)
                            for c in range(num_cols):
                                idx = r * num_cols + c
                                if idx < len(questions):
                                    q = questions[idx]
                                    q_num = q['file'].split('-')[3]
                                    btn_label = f"第{q_num}题"
                                    
                                    # 高亮当前选中的按钮
                                    is_selected = (idx == st.session_state[select_key])
                                    btn_type = "primary" if is_selected else "secondary"
                                    
                                    if cols[c].button(btn_label, key=f"q_btn_{year}_{paper_name}_{idx}", type=btn_type):
                                        st.session_state[select_key] = idx
                                        st.rerun()

                        selected_q_idx = st.session_state[select_key]
                        if selected_q_idx < len(questions):
                            selected_question = questions[selected_q_idx]
                            selected_file_path = selected_question["path"]
                        else:
                            selected_file_path = None
                    else:
                        selected_file_path = None
                        
        with col_content:
            st.markdown('<div id="paper-right-anchor"></div>', unsafe_allow_html=True)
            if all_years and year and paper_name:
                if not questions:
                     st.info("未找到该试卷的题目")
                else:
                    if view_mode == "单题选择模式":
                        # 单题模式下，右侧不展示列表，由外部逻辑(Split View)在最下方展示单题编辑
                        pass
                    else:
                        # 所有问题展示模式：逐题列出，左编辑右预览
                        for i, q in enumerate(questions):
                            q_path = q["path"]
                            if not os.path.exists(q_path): continue
                            
                            # 读取内容
                            with open(q_path, "r", encoding="utf-8") as f:
                                content = f.read()
                                
                            # 题目编号
                            q_label = format_question_title(q['file'])
                            render_question_header(q_label, content, q_path)
                            
                            if is_exam_mode:
                                # 组卷模式：不展示源码，仅展示渲染后的问题和组卷操作按钮
                                st.markdown(latex_to_markdown(content), unsafe_allow_html=True)
                                
                                is_selected = q_path in st.session_state.get("exam_selected_qs", [])
                                if is_selected:
                                    st.markdown('<span class="red-btn-hook"></span>', unsafe_allow_html=True)
                                    if st.button("❌ 本题取消组卷", key=f"exam_rm_{q_path}", type="primary"):
                                        st.session_state["exam_selected_qs"].remove(q_path)
                                        if st.session_state.get("ai_exam_active"):
                                            st.session_state["ai_exam_modified"] = True
                                        st.rerun()
                                else:
                                    if st.button("➕ 本题加入组卷", key=f"exam_add_{q_path}", type="secondary"):
                                        st.session_state["exam_selected_qs"].append(q_path)
                                        if st.session_state.get("ai_exam_active"):
                                            st.session_state["ai_exam_modified"] = True
                                        st.rerun()
                                st.divider()
                                continue
                                
                            # 左右布局
                            c1, c2 = st.columns([1, 1])
                            
                            # 编辑模式状态 key
                            edit_mode_key = f"browse_paper_edit_mode_{q_path}"
                            
                            with c1:
                                est_height = get_editor_height(content)
                                
                                is_editing = st.session_state.get(edit_mode_key, False)
                                text_area_key = f"all_edit_{q_path}"
                                
                                if is_editing:
                                    mtime_token = int(os.path.getmtime(q_path)) if os.path.exists(q_path) else 0
                                    new_content = st.text_area(
                                        "源码", 
                                        value=content, 
                                        height=est_height, 
                                        key=f"{text_area_key}_{mtime_token}"
                                    )
                                    # 保存按钮
                                    if st.button("💾 保存修改", key=f"save_btn_{q_path}", type="primary"):
                                        final_content = save_modified_tex_file(q_path, new_content)
                                        _update_csv_index_for_content_change(q_path, final_content)
                                        st.session_state[edit_mode_key] = False
                                        st.toast(f"{q_label} 已保存", icon="✅")
                                        time.sleep(0.5)
                                        st.rerun()
                                else:
                                    mtime_token = int(os.path.getmtime(q_path)) if os.path.exists(q_path) else 0
                                    st.text_area(
                                        "源码", 
                                        value=content, 
                                        height=est_height, 
                                        disabled=True,
                                        key=f"{text_area_key}_readonly_{mtime_token}"
                                    )
                                    
                                    tag_edit_key = f"tag_edit_mode_{q_path}"
                                    is_tag_editing = st.session_state.get(tag_edit_key, False)
                                    
                                    btn_c1, btn_c2, btn_c3 = st.columns(3)
                                    with btn_c1:
                                        if st.button("✏️ 开始修改tex内容", key=f"start_btn_{q_path}"):
                                            st.session_state[edit_mode_key] = True
                                            st.rerun()
                                    with btn_c2:
                                        if is_tag_editing:
                                            if st.button("✅ 完成修改题目信息", key=f"tag_save_btn_{q_path}", type="primary"):
                                                base = os.path.basename(q_path).replace(".tex", "")
                                                parts = base.split("-")
                                                if len(parts) >= 5:
                                                    old_year, old_ptype, old_pname, old_pnum, old_subj = parts[0], parts[1], parts[2], parts[3], parts[4]
                                                    fhash = hashlib.md5(q_path.encode()).hexdigest()[:10]
                                                    new_year = st.session_state.get(f"paper_meta_year_{fhash}", old_year)
                                                    new_type = st.session_state.get(f"paper_meta_type_{fhash}", old_ptype)
                                                    new_name = st.session_state.get(f"paper_meta_paper_{fhash}", old_pname)
                                                    new_num = st.session_state.get(f"paper_meta_num_{fhash}", old_pnum)
                                                    new_subjects = st.session_state.get(f"tag_select_{fhash}", [old_subj])
                                                    new_subject_str = "，".join(new_subjects) if isinstance(new_subjects, list) else str(new_subjects or old_subj)
                                                    try:
                                                        apply_meta_rename_and_update(q_path, str(new_year), str(new_type), str(new_name), str(new_num), new_subject_str)
                                                        st.toast("修改成功！", icon="✅")
                                                        st.session_state[tag_edit_key] = False
                                                        time.sleep(0.5)
                                                        st.rerun()
                                                    except Exception as e:
                                                        st.error(f"修改失败: {e}")
                                                else:
                                                    st.error("文件名格式不支持修改")
                                        else:
                                            if st.button("🏷️ 开始修改题目信息", key=f"tag_start_btn_{q_path}"):
                                                st.session_state[tag_edit_key] = True
                                                st.rerun()
                                    with btn_c3:
                                        render_ai_solution_generate_button(q_path, content, key_prefix="ai_solution_v1")
                                    render_ai_solution_image_ocr_section(q_path, key_prefix="ai_solution_v1")
                                            
                                    if is_tag_editing:
                                        base = os.path.basename(q_path).replace(".tex", "")
                                        parts = base.split("-")
                                        cur_year = parts[0] if len(parts) >= 5 else ""
                                        cur_type = parts[1] if len(parts) >= 5 else "G"
                                        cur_paper = parts[2] if len(parts) >= 5 else ""
                                        cur_num = parts[3] if len(parts) >= 5 else ""
                                        cur_subjects = (parts[4] if len(parts) >= 5 else "").split("，")
                                        valid_tags = [t for t in cur_subjects if t in SUBJECTS] or [SUBJECTS[0]]
                                        fhash = hashlib.md5(q_path.encode()).hexdigest()[:10]
                                        type_opts = list(PAPER_TYPES.keys())
                                        c_meta1, c_meta2 = st.columns([1, 1])
                                        with c_meta1:
                                            st.text_input("年份", value=str(cur_year), key=f"paper_meta_year_{fhash}")
                                        with c_meta2:
                                            if cur_type not in type_opts:
                                                cur_type = "G"
                                            st.selectbox("试卷类别", options=type_opts, index=type_opts.index(cur_type), format_func=lambda x: f"{x} ({PAPER_TYPES[x]})", key=f"paper_meta_type_{fhash}")
                                        st.text_input("试卷名称", value=str(cur_paper), key=f"paper_meta_paper_{fhash}")
                                        st.text_input("题号", value=str(cur_num), key=f"paper_meta_num_{fhash}")
                                        st.multiselect("知识板块 (首个为主)", options=SUBJECTS, default=valid_tags, key=f"tag_select_{fhash}")
    
                            with c2:
                                st.markdown(latex_to_markdown(content), unsafe_allow_html=True)
                            
                            render_ai_solution_panel(q_path, q_label, key_prefix="ai_solution_v1")
                            
                            st.divider()
    
    elif browse_mode == "按录入顺序浏览":
        # 采用一致的双栏独立滑动布局
        col_nav, col_content = st.columns([1, 2.5])
        
        with col_nav:
            st.markdown('<div id="time-left-anchor"></div>', unsafe_allow_html=True)
            st.markdown("### 🕒 浏览设置")
            
            st.markdown("""
                <style>
                div[data-testid="stHorizontalBlock"]:has(#time-left-anchor) {
                    height: calc(100vh - 150px) !important;
                    align-items: stretch !important;
                    overflow: hidden !important;
                }
                .stApp { overflow-y: hidden !important; }
                
                div[data-testid="column"]:has(#time-left-anchor) {
                    height: 100% !important; 
                    overflow-y: auto !important;
                    padding-right: 1rem !important;
                }
                
                div[data-testid="column"]:has(#time-right-anchor) {
                    height: 100% !important;
                    overflow-y: auto !important;
                    border-left: 1px solid #e1e4e8 !important;
                    padding-left: 1.5rem !important;
                }
                
                div[data-testid="column"]::-webkit-scrollbar { width: 4px; }
                div[data-testid="column"]::-webkit-scrollbar-thumb { background-color: rgba(0,0,0,0.15); border-radius: 4px; }
                </style>
            """, unsafe_allow_html=True)
            
            # 排序选项
            st.subheader("排序方式")
            sort_order = st.radio("排序方式", ["最新录入在最前", "最早录入在最前"], horizontal=False, label_visibility="collapsed")
            
            st.divider()
            
            try:
                from utils.csv_ops import read_csv_index
                csv_data = read_csv_index()
            except Exception as e:
                csv_data = []
                st.error(f"读取索引失败: {e}")
                
            if csv_data:
                st.subheader("显示数量限制")
                max_show = st.slider("最多展示题目数量", min_value=5, max_value=25, value=10, step=1, label_visibility="visible", key="time_max_show")
                if st.session_state.get("time_max_show_prev") != max_show:
                    st.session_state["time_browse_page"] = 1
                    st.session_state["time_max_show_prev"] = max_show
                
                sorted_data = sorted(
                    csv_data,
                    key=lambda r: r.get("初次录入的时间", "") or r.get("最后修改时间", ""),
                    reverse=(sort_order == "最新录入在最前"),
                )
                total_count = len(sorted_data)
                total_pages = max(1, (total_count + max_show - 1) // max_show)
                current_page = int(st.session_state.get("time_browse_page", 1) or 1)
                current_page = max(1, min(total_pages, current_page))
                st.session_state["time_browse_page"] = current_page
                
                st.divider()
                st.markdown(f"第 {current_page} 页")
                p1, p2 = st.columns(2)
                with p1:
                    if st.button("⬅️ 上一页", key="time_browse_prev", disabled=(current_page <= 1), use_container_width=True):
                        st.session_state["time_browse_page"] = current_page - 1
                        st.rerun()
                with p2:
                    if st.button("下一页 ➡️", key="time_browse_next", disabled=(current_page >= total_pages), use_container_width=True):
                        st.session_state["time_browse_page"] = current_page + 1
                        st.rerun()
                
        with col_content:
            st.markdown('<div id="time-right-anchor"></div>', unsafe_allow_html=True)
            if not csv_data:
                st.info("题库为空或索引未建立，请先一键重建题库索引。")
            else:
                total_count = len(sorted_data)
                start_idx = (current_page - 1) * max_show
                end_idx = min(start_idx + max_show, total_count)
                display_data = sorted_data[start_idx:end_idx]
                
                st.markdown(f"### 共找到 {total_count} 道题目，当前展示第 {current_page} 页。")
                
                for i, row in enumerate(display_data):
                    fpath = os.path.join(CHAPTERS_DIR, row["相对文件路径"])
                    if not os.path.exists(fpath):
                        continue

                    fname = row["文件名称"]
                    q_label = format_question_title(fname)

                    # 增加时间标识显示
                    time_str = row.get("初次录入的时间", "") or row.get("最后修改时间", "")
                    extra_label = ""
                    if time_str:
                        extra_label = f"<span style='font-size:0.5em; color:gray; font-weight:normal; margin-left: 10px;'>🕒 {time_str}</span>"
                        
                    lazy_key = hashlib.md5(f"time_browse:{fpath}".encode()).hexdigest()[:10]
                    st.markdown(f"### {q_label} {extra_label}", unsafe_allow_html=True)
                    
                    if is_exam_mode:
                        with open(fpath, "r", encoding="utf-8") as f:
                            content = f.read()
                        render_question_header(q_label, content, fpath, extra_html_label=extra_label)
                        st.markdown(latex_to_markdown(content), unsafe_allow_html=True)
                        is_selected = fpath in st.session_state.get("exam_selected_qs", [])
                        if is_selected:
                            st.markdown('<span class="red-btn-hook"></span>', unsafe_allow_html=True)
                            if st.button("❌ 本题取消组卷", key=f"exam_rm_time_{fpath}", type="primary"):
                                st.session_state["exam_selected_qs"].remove(fpath)
                                if st.session_state.get("ai_exam_active"):
                                    st.session_state["ai_exam_modified"] = True
                                st.rerun()
                        else:
                            if st.button("➕ 本题加入组卷", key=f"exam_add_time_{fpath}", type="secondary"):
                                st.session_state["exam_selected_qs"].append(fpath)
                                if st.session_state.get("ai_exam_active"):
                                    st.session_state["ai_exam_modified"] = True
                                st.rerun()
                        st.divider()
                        continue
                    
                    c1, c2 = st.columns([1, 1])
                    edit_mode_key = f"time_edit_mode_{fpath}"
                    
                    with c1:
                        is_editing = st.session_state.get(edit_mode_key, False)
                        text_area_key = f"time_edit_{fpath}"
                        tag_edit_key = f"time_tag_edit_mode_{fpath}"
                        is_tag_editing = st.session_state.get(tag_edit_key, False)
                        load_key = f"time_load_src_{lazy_key}"
                        if load_key not in st.session_state:
                            st.session_state[load_key] = False

                        if (not st.session_state.get(load_key)) and (not is_editing) and (not is_tag_editing):
                            b1, b2, b3 = st.columns(3)
                            with b1:
                                if st.button("📄 加载源码", key=f"time_load_btn_{fpath}", use_container_width=True):
                                    st.session_state[load_key] = True
                                    st.rerun()
                            with b2:
                                if st.button("🏷️ 改题目信息", key=f"time_tag_start_btn_{fpath}", use_container_width=True):
                                    st.session_state[tag_edit_key] = True
                                    st.rerun()
                            with b3:
                                fhash, data_key, editor_key = _ai_sol_keys(fpath, "ai_solution_v1")
                                upload_open_key = f"ai_sol_upload_open_{fhash}"
                                if st.button("🤖 AI生成解答", key=f"time_ai_gen_{fhash}", type="secondary", use_container_width=True):
                                    try:
                                        with open(fpath, "r", encoding="utf-8") as f:
                                            cur_tex = f.read()
                                        problem_tex = _extract_problem_env(cur_tex)
                                        with st.spinner("🤖 AI 正在生成解答..."):
                                            res = call_ai_for_answer_solutions(problem_tex, fast=False)
                                        if "error" in res:
                                            st.toast(res["error"], icon="❌")
                                        else:
                                            combined = _normalize_ai_generated_tex_for_preview(res["answer_tex"].strip() + "\n\n" + res["solutions_tex"].strip())
                                            st.session_state[data_key] = {"answer_tex": res["answer_tex"], "solutions_tex": res["solutions_tex"]}
                                            st.session_state[editor_key] = combined
                                            st.toast("已生成解答（未写回文件）", icon="🪄")
                                            st.rerun()
                                    except Exception as e:
                                        st.toast(f"生成失败: {e}", icon="❌")
                                if st.button("🖼️ 解答图片识别", key=f"time_ai_img_{fhash}", use_container_width=True):
                                    st.session_state[upload_open_key] = not st.session_state.get(upload_open_key, False)
                                    st.rerun()
                                render_ai_solution_image_ocr_section(fpath, key_prefix="ai_solution_v1")
                        else:
                            with open(fpath, "r", encoding="utf-8") as f:
                                content = f.read()

                            est_height = get_editor_height(content)

                            if (not is_editing) and (not is_tag_editing):
                                r1, r2 = st.columns([1, 1])
                                with r1:
                                    if st.button("⬆️ 收起源码", key=f"time_unload_btn_{fpath}", use_container_width=True):
                                        st.session_state[load_key] = False
                                        st.rerun()
                                with r2:
                                    st.write("")

                            if is_editing:
                                st.text_area("源码", value=content, height=est_height, key=text_area_key)
                                st.button("💾 保存修改", key=f"time_save_btn_{fpath}", type="primary", on_click=_save_tex_from_widget, args=(fpath, text_area_key, edit_mode_key, "已保存"))
                            else:
                                mtime_token = int(os.path.getmtime(fpath)) if os.path.exists(fpath) else 0
                                st.text_area("源码", value=content, height=est_height, disabled=True, key=f"{text_area_key}_readonly_{mtime_token}")

                                btn_c1, btn_c2, btn_c3 = st.columns(3)
                                with btn_c1:
                                    if st.button("✏️ 改tex内容", key=f"time_start_btn_{fpath}", use_container_width=True):
                                        st.session_state[text_area_key] = content
                                        st.session_state[edit_mode_key] = True
                                        st.rerun()
                                with btn_c2:
                                    if is_tag_editing:
                                        if st.button("✅ 完成题目信息修改", key=f"time_tag_save_btn_{fpath}", type="primary", use_container_width=True):
                                            base = os.path.basename(fpath).replace(".tex", "")
                                            parts = base.split("-")
                                            if len(parts) >= 5:
                                                old_year, old_ptype, old_pname, old_pnum, old_subj = parts[0], parts[1], parts[2], parts[3], parts[4]
                                                new_year = st.session_state.get(f"time_meta_year_{lazy_key}", old_year)
                                                new_type = st.session_state.get(f"time_meta_type_{lazy_key}", old_ptype)
                                                new_name = st.session_state.get(f"time_meta_paper_{lazy_key}", old_pname)
                                                new_num = st.session_state.get(f"time_meta_num_{lazy_key}", old_pnum)
                                                new_subjects = st.session_state.get(f"time_tag_select_{lazy_key}", [old_subj])
                                                new_subject_str = "，".join(new_subjects) if isinstance(new_subjects, list) else str(new_subjects or old_subj)
                                                try:
                                                    apply_meta_rename_and_update(fpath, str(new_year), str(new_type), str(new_name), str(new_num), new_subject_str)
                                                    st.toast("修改成功！", icon="✅")
                                                    st.session_state[tag_edit_key] = False
                                                    time.sleep(0.5)
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(f"修改失败: {e}")
                                            else:
                                                st.error("文件名格式不支持修改")
                                    else:
                                        if st.button("🏷️ 改题目信息", key=f"time_tag_start2_btn_{fpath}", use_container_width=True):
                                            st.session_state[tag_edit_key] = True
                                            st.rerun()
                                with btn_c3:
                                    render_ai_solution_generate_button(fpath, content, key_prefix="ai_solution_v1")
                                render_ai_solution_image_ocr_section(fpath, key_prefix="ai_solution_v1")

                                if is_tag_editing:
                                    base = os.path.basename(fpath).replace(".tex", "")
                                    parts = base.split("-")
                                    cur_year = parts[0] if len(parts) >= 5 else ""
                                    cur_type = parts[1] if len(parts) >= 5 else "G"
                                    cur_paper = parts[2] if len(parts) >= 5 else ""
                                    cur_num = parts[3] if len(parts) >= 5 else ""
                                    cur_subjects = (parts[4] if len(parts) >= 5 else "").split("，")
                                    valid_tags = [t for t in cur_subjects if t in SUBJECTS] or [SUBJECTS[0]]
                                    type_opts = list(PAPER_TYPES.keys())
                                    c_meta1, c_meta2 = st.columns([1, 1])
                                    with c_meta1:
                                        st.text_input("年份", value=str(cur_year), key=f"time_meta_year_{lazy_key}")
                                    with c_meta2:
                                        if cur_type not in type_opts:
                                            cur_type = "G"
                                        st.selectbox("试卷类别", options=type_opts, index=type_opts.index(cur_type), format_func=lambda x: f"{x} ({PAPER_TYPES[x]})", key=f"time_meta_type_{lazy_key}")
                                    st.text_input("试卷名称", value=str(cur_paper), key=f"time_meta_paper_{lazy_key}")
                                    st.text_input("题号", value=str(cur_num), key=f"time_meta_num_{lazy_key}")
                                    st.multiselect("知识板块 (首个为主)", options=SUBJECTS, default=valid_tags, key=f"time_tag_select_{lazy_key}")
    
                    with c2:
                        has_tikz = (row.get("包含TikZ绘图", "") or "").strip() == "是"
                        if has_tikz:
                            try:
                                with open(fpath, "r", encoding="utf-8") as f:
                                    full_content = f.read()
                                st.markdown(latex_to_markdown(full_content), unsafe_allow_html=True)
                            except Exception as e:
                                st.error(f"渲染错误: {e}")
                        else:
                            y = (row.get("年份", "") or "").strip()
                            t = (row.get("试卷类型", "") or "").strip()
                            pn = (row.get("试卷名称", "") or "").strip()
                            pnum = (row.get("原卷题号", "") or "").strip()
                            subj = (row.get("知识板块", "") or "").strip()
                            stem = row.get("题干", "") or ""
                            ans = row.get("答案", "") or ""
                            sol = row.get("解析", "") or ""
                            if re.match(r"^\{\d{4}\}\{", (stem or "").lstrip()):
                                stem = re.sub(r"^(?:\{[^\}]*\}){1,5}\s*", "", stem.lstrip()).lstrip()
                            stem = re.sub(r"^\\begin\{problem\}(?:\[[^\]]*\])?(?:\s*\{[^\}]*\}){0,5}\s*", "", stem.lstrip()).lstrip()
                            stem = re.sub(r"%(?: === Meta Data ===| === Begin Label Data ===)\r?\n([\s\S]*?)%(?: === End Meta ===| === End\s+Label Data ===)\r?\n", "", stem, flags=re.DOTALL).lstrip()
                            preview_tex = f"\\begin{{problem}}{{{y}}}{{{t}}}{{{pn}}}{{{pnum}}}{{{subj}}}\n{stem}\n\\end{{problem}}"
                            if ans.strip():
                                preview_tex += f"\n\n\\begin{{answer}}\n{ans}\n\\end{{answer}}"
                            if sol.strip():
                                preview_tex += f"\n\n\\begin{{solutions}}\n{sol}\n\\end{{solutions}}"
                            try:
                                st.markdown(latex_to_markdown(preview_tex), unsafe_allow_html=True)
                            except Exception as e:
                                st.error(f"渲染错误: {e}")
                    
                    render_ai_solution_panel(fpath, q_label, key_prefix="ai_solution_v1")
                    
                    st.divider()

    # 编辑区域 (Split View) - 仅在选择了文件时显示，并严格限制在右栏内容区内
    if selected_file_path and os.path.exists(selected_file_path):
        
        # 为了让单题模式下也能正确渲染在右侧容器中，需要判断我们现在是否还有 col_content 的上下文。
        # 如果我们在主循环外，我们需要重新打开右侧的 column 容器。
        try:
            target_container = col_content
        except NameError:
            target_container = st.container()

        with target_container:
            with open(selected_file_path, "r", encoding="utf-8") as f:
                current_content = f.read()
                
            # 渲染题目顶部属性栏和标题
            if "browse_mode" in locals():
                q_fname = os.path.basename(selected_file_path)
                q_label = format_question_title(q_fname)
                render_question_header(q_label, current_content, selected_file_path)
                
            if is_exam_mode:
                st.subheader("👁️ 问题预览")
                try:
                    md_content = latex_to_markdown(current_content)
                    st.markdown(md_content, unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"预览渲染出错: {e}")
                    
                st.write("")
                is_selected = selected_file_path in st.session_state.get("exam_selected_qs", [])
                if is_selected:
                    st.markdown('<span class="red-btn-hook"></span>', unsafe_allow_html=True)
                    if st.button("❌ 本题取消组卷", key=f"exam_rm_sv_{selected_file_path}", type="primary"):
                        st.session_state["exam_selected_qs"].remove(selected_file_path)
                        if st.session_state.get("ai_exam_active"):
                            st.session_state["ai_exam_modified"] = True
                        st.rerun()
                else:
                    if st.button("➕ 本题加入组卷", key=f"exam_add_sv_{selected_file_path}", type="secondary"):
                        st.session_state["exam_selected_qs"].append(selected_file_path)
                        if st.session_state.get("ai_exam_active"):
                            st.session_state["ai_exam_modified"] = True
                        st.rerun()
            else:
                col_edit, col_preview = st.columns([1, 1])
                
                with col_edit:
                    mtime_token = int(os.path.getmtime(selected_file_path)) if os.path.exists(selected_file_path) else 0
                    editor_key = f"editor_{selected_file_path}"
                    st.text_area("源码", value=current_content, height=600, key=editor_key, label_visibility="collapsed")
                    new_content = st.session_state.get(editor_key, current_content)
                    s1, s2 = st.columns(2)
                    with s1:
                        st.button("💾 保存修改", type="primary", key=f"save_{selected_file_path}", use_container_width=True, on_click=_save_tex_from_widget, args=(selected_file_path, editor_key, "", "文件已保存！"))
                    with s2:
                        render_ai_solution_generate_button(selected_file_path, new_content, key_prefix="ai_solution_v1", use_container_width=True)
                    render_ai_solution_image_ocr_section(selected_file_path, key_prefix="ai_solution_v1")
                        
                with col_preview:
                    try:
                        # 尝试渲染
                        md_content = latex_to_markdown(new_content)
                        st.markdown(md_content, unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"预览渲染出错: {e}")
                
                render_ai_solution_panel(selected_file_path, q_label, key_prefix="ai_solution_v1")
                        
            if not is_exam_mode:
                with st.expander("查看文件路径"):
                    st.code(selected_file_path)

def page_exam_paper_generation():
    st.header("🖨️ 组卷服务")
    
    # 注入全局按钮样式 CSS Hook
    st.markdown("""
    <style>
    /* 让按钮靠得更近，高度一致 */
    .stButton > button {
        height: 100% !important;
        min-height: 40px !important;
    }
    
    /* 使用更兼容的选择器，确保选中按钮外层的 div */
    div:has(> div > .blue-btn-hook) + div button[kind="secondary"],
    div[data-testid="column"]:has(.blue-btn-hook) button[kind="secondary"] {
        background-color: #f0f2f6 !important; /* 淡灰色底 */
        border-color: #d0d7de !important;
        color: #24292f !important;
        font-weight: bold !important;
        box-shadow: inset 0 1px 2px rgba(0,0,0,0.05) !important;
    }
    
    div:has(> div > .white-btn-hook) + div button[kind="secondary"],
    div[data-testid="column"]:has(.white-btn-hook) button[kind="secondary"] {
        background-color: white !important;
        border-color: #e1e4e8 !important;
        color: black !important;
    }
    
    div[data-testid="element-container"]:has(.red-btn-hook) + div[data-testid="stButton"] > button {
        background-color: #d73a49 !important;
        border-color: #d73a49 !important;
        color: white !important;
    }
    
    /* 针对已选问题网格布局中的红色 X 按钮 */
    div[data-testid="element-container"]:has(.white-red-text-btn-hook) + div[data-testid="stButton"] > button {
        background-color: white !important;
        border-color: #e1e4e8 !important;
        color: #d73a49 !important;
        padding: 0 !important;
        font-weight: bold !important;
    }
    div[data-testid="element-container"]:has(.white-red-text-btn-hook) + div[data-testid="stButton"] > button:hover {
        background-color: #ffeef0 !important;
        border-color: #d73a49 !important;
    }
    
    /* 取消 Streamlit 按钮点击时的下沉动画效果 */
    .stButton > button:active {
        transform: none !important;
    }
    
    /* 调整“选择组卷服务模块”的单选按钮字号，使其与 h3 (###) 差不多大 */
    div.big-radio-container + div[data-testid="stRadio"] label[data-baseweb="radio"] div {
        font-size: 1.5rem !important;
        font-weight: 600 !important;
        line-height: 1.2 !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown('<div class="big-radio-container"></div>', unsafe_allow_html=True)
    exam_service_mode = st.radio("选择组卷服务模块", ["🖨️ 试卷排版工作台", "📂 历史组卷浏览"], horizontal=True, label_visibility="collapsed")
    st.markdown("---")

    if exam_service_mode == "📂 历史组卷浏览":
        # ================= 新增：历史组卷浏览 =================
        export_base_dir = os.path.join(BASE_DIR, "Test Paper Group", "导出文件")
        if not os.path.exists(export_base_dir):
            st.info("暂无组卷记录")
        else:
            years = sorted([d for d in os.listdir(export_base_dir) if os.path.isdir(os.path.join(export_base_dir, d))], reverse=True)
            if not years:
                st.info("暂无组卷记录")
            else:
                c_y1, c_y2 = st.columns([1, 6])
                with c_y1:
                    st.markdown("##### 📅 选择年份")
                with c_y2:
                    selected_year = st.radio("选择年份", ["显示所有年份"] + years, horizontal=True, label_visibility="collapsed")
                
                months = []
                if selected_year != "显示所有年份":
                    year_dir = os.path.join(export_base_dir, selected_year)
                    if os.path.exists(year_dir):
                        months = sorted([d for d in os.listdir(year_dir) if os.path.isdir(os.path.join(year_dir, d))], reverse=True)
                else:
                    for y in years:
                        y_dir = os.path.join(export_base_dir, y)
                        months.extend([d for d in os.listdir(y_dir) if os.path.isdir(os.path.join(y_dir, d))])
                    months = sorted(list(set(months)), reverse=True)
                
                c_m1, c_m2 = st.columns([1, 6])
                with c_m1:
                    st.markdown("##### 📅 选择月份")
                with c_m2:
                    if months:
                        selected_month = st.radio("选择月份", ["显示所有月份"] + months, horizontal=True, label_visibility="collapsed")
                    else:
                        st.info("该年份下暂无记录")
                        selected_month = "显示所有月份"
                
                # 收集试卷列表
                papers = []
                years_to_search = years if selected_year == "显示所有年份" else [selected_year]
                for y in years_to_search:
                    y_dir = os.path.join(export_base_dir, y)
                    months_to_search = [m for m in os.listdir(y_dir) if os.path.isdir(os.path.join(y_dir, m))] if selected_month == "显示所有月份" else [selected_month]
                    for m in months_to_search:
                        m_dir = os.path.join(y_dir, m)
                        if os.path.exists(m_dir):
                            for p in os.listdir(m_dir):
                                p_dir = os.path.join(m_dir, p)
                                if os.path.isdir(p_dir):
                                    tex_file = os.path.join(p_dir, f"{p}.tex")
                                    if os.path.exists(tex_file):
                                        papers.append({"name": p, "path": tex_file, "dir": p_dir, "year": y, "month": m})
                
                if not papers:
                    st.info("未找到符合条件的试卷")
                else:
                    st.markdown("---")
                    paper_names = [p["name"] for p in papers]
                    selected_paper_name = st.selectbox("📄 试卷列表", paper_names)
                    selected_paper = next(p for p in papers if p["name"] == selected_paper_name)
                    
                    st.markdown("---")
                    present_mode = st.radio("呈现形式", ["以题目组合形式呈现", "以整卷形式呈现"], horizontal=True, label_visibility="collapsed")
                    
                    if present_mode == "以整卷形式呈现":
                        c_src, c_pdf = st.columns(2)
                        with c_src:
                            st.markdown("##### 📜 LaTeX 源码")
                            with open(selected_paper["path"], "r", encoding="utf-8") as f:
                                tex_content = f.read()
                            st.code(tex_content, language="latex", line_numbers=True)
                        with c_pdf:
                            st.markdown("##### 📑 PDF 预览")
                            pdf_path = os.path.join(selected_paper["dir"], f"{selected_paper['name']}.pdf")
                            if os.path.exists(pdf_path):
                                import base64
                                with open(pdf_path, "rb") as f:
                                    base64_pdf = base64.b64encode(f.read()).decode('utf-8')
                                pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800px" type="application/pdf"></iframe>'
                                st.markdown(pdf_display, unsafe_allow_html=True)
                            else:
                                st.warning("未找到生成的 PDF 文件。请确认该试卷是否已成功编译。")
                    
                    elif present_mode == "以题目组合形式呈现":
                        st.markdown("##### 🧩 题目组合排列")
                        with open(selected_paper["path"], "r", encoding="utf-8") as f:
                            tex_content = f.read()
                        
                        # 简易解析：按 \section, \subsection, \chapter, \begin{problem}, \begin{question}, \begin{lanbox} 分块
                        import re
                        blocks = []
                        
                        # 使用正则提取所有的块
                        # 查找所有的开始标记位置
                        pattern = r'(\\chapter\{.*?\}|\\section\{.*?\}|\\subsection\{.*?\}|\\begin\{problem\}.*?\\end\{problem\}|\\begin\{question\}.*?\\end\{question\}|\\begin\{lanbox\}.*?\\end\{lanbox\})'
                        matches = re.finditer(pattern, tex_content, flags=re.DOTALL)
                        
                        for idx, match in enumerate(matches):
                            block_text = match.group(1)
                            if block_text.startswith(r'\chapter{'):
                                title = re.search(r'\\chapter\{(.*?)\}', block_text).group(1)
                                title = re.sub(r'\s+', ' ', title.replace('\n', ' ')).strip()
                                blocks.append({"type": "chapter", "content": title})
                            elif block_text.startswith(r'\section{'):
                                title = re.search(r'\\section\{(.*?)\}', block_text, re.DOTALL).group(1)
                                title = re.sub(r'\s+', ' ', title.replace('\n', ' ')).strip()
                                blocks.append({"type": "section", "content": title})
                            elif block_text.startswith(r'\subsection{'):
                                title = re.search(r'\\subsection\{(.*?)\}', block_text, re.DOTALL).group(1)
                                title = re.sub(r'\s+', ' ', title.replace('\n', ' ')).strip()
                                blocks.append({"type": "subsection", "content": title})
                            else:
                                # 清除可能会遗留的 \begin{lanbox} 和 \end{lanbox} 标记
                                clean_text = re.sub(r'\\begin\{lanbox\}', '', block_text)
                                clean_text = re.sub(r'\\end\{lanbox\}', '', clean_text)
                                blocks.append({"type": "question", "content": clean_text.strip()})
                                
                        if not blocks:
                            st.info("未能从源码中解析出具体的题目和章节，这可能是因为文件尚未插入任何题目，或者结构与预期不符。")
                        else:
                            q_count = 1
                            for b in blocks:
                                if b["type"] == "chapter":
                                    st.markdown(f"### 🗂️ {b['content']}")
                                elif b["type"] == "section":
                                    st.markdown(f"#### 🗂️ {b['content']}")
                                elif b["type"] == "subsection":
                                    st.markdown(f"##### 📝 {b['content']}")
                                elif b["type"] == "question":
                                    st.markdown(f"**第 {q_count} 题**")
                                    st.markdown(latex_to_markdown(b["content"]), unsafe_allow_html=True)
                                    q_count += 1
                                st.markdown("---")
        return

    # 1. 主题选择与组卷按钮
    template_dir = os.path.join(BASE_DIR, "Test Paper Group", "主题模板")
    theme_options = []
    if os.path.exists(template_dir):
        for d in os.listdir(template_dir):
            if os.path.isdir(os.path.join(template_dir, d)):
                theme_options.append(d)
    if not theme_options:
        theme_options = ["讲义类模板", "试卷类模板", "练习类模板"]
        
    if "exam_mode_stage" not in st.session_state:
        st.session_state["exam_mode_stage"] = "selection"
    if "exam_blocks" not in st.session_state:
        st.session_state["exam_blocks"] = []
        
    if "exam_theme_select" not in st.session_state:
        st.session_state["exam_theme_select"] = theme_options[0]
        
    if "exam_theme" not in st.session_state:
        st.session_state["exam_theme"] = st.session_state["exam_theme_select"]
        
    if "exam_q_count_input" not in st.session_state:
        st.session_state["exam_q_count_input"] = 19 if "试卷类" in st.session_state["exam_theme_select"] else 10
        
    if "exam_selected_qs" not in st.session_state:
        st.session_state["exam_selected_qs"] = []
        
    if "ai_exam_active" not in st.session_state:
        st.session_state["ai_exam_active"] = False
    if "ai_exam_modified" not in st.session_state:
        st.session_state["ai_exam_modified"] = False
        
    # 如果在排版阶段，跳过选题页面渲染
    if st.session_state["exam_mode_stage"] == "typesetting":
        render_typesetting_workspace()
        return

    # ================= 阶段一：选题购物车 =================
    # 提前处理状态同步，避免在 widget 渲染后修改其 session_state 导致 StreamlitAPIException
    # 这里非常关键，必须把用户选择的 theme 实时同步并保存到持久化变量中
    if "exam_theme_select" in st.session_state:
        if st.session_state.get("exam_theme_select") != st.session_state.get("exam_theme"):
            st.session_state["exam_theme"] = st.session_state["exam_theme_select"]
            # Only change the default value if the user hasn't actively modified the count
            if "试卷类" in st.session_state["exam_theme"]:
                st.session_state["exam_q_count_input"] = 19
            else:
                st.session_state["exam_q_count_input"] = 10
            st.session_state["_count_widget"] = st.session_state["exam_q_count_input"]

    selected_count = len(st.session_state.get("exam_selected_qs", []))
    if selected_count > st.session_state.get("exam_q_count_input", 10):
        st.session_state["exam_q_count_input"] = selected_count
        st.session_state["_count_widget"] = selected_count
        st.toast("当前新增问题数已超过预设定数，已为您新增题数上限", icon="⚠️")

    # Sync state before widget to preserve value
    current_count = st.session_state.get("exam_q_count_input", 10)
    if "_count_widget" not in st.session_state:
        st.session_state["_count_widget"] = current_count

    c_theme, c_num, c_ai = st.columns([3, 2, 3])
    with c_theme:
        theme = st.selectbox("选择组卷主题", options=theme_options, key="exam_theme_select", label_visibility="collapsed")
    with c_num:
        col_num_val, col_num_add, col_num_sub = st.columns([1.5, 1, 1], gap="small")
        with col_num_val:
            # use value instead of relying purely on key, and handle on_change
            def _update_count():
                st.session_state["exam_q_count_input"] = st.session_state["_count_widget"]
            st.number_input("本次组卷数量", min_value=1, key="_count_widget", on_change=_update_count, label_visibility="collapsed")
        with col_num_add:
            def _add_q_count():
                st.session_state["exam_q_count_input"] += 1
                st.session_state["_count_widget"] = st.session_state["exam_q_count_input"]
            st.button("➕", key="exam_btn_add", use_container_width=True, on_click=_add_q_count)
        with col_num_sub:
            def _sub_q_count():
                if st.session_state.get("exam_q_count_input", 1) > 1:
                    st.session_state["exam_q_count_input"] -= 1
                    st.session_state["_count_widget"] = st.session_state["exam_q_count_input"]
            st.button("➖", key="exam_btn_sub", use_container_width=True, on_click=_sub_q_count)
    with c_ai:
        # 按钮状态逻辑：白底(未激活) -> 绿底(激活且未被修改) -> 蓝底(激活且被修改)
        ai_btn_type = "primary" if st.session_state["ai_exam_active"] else "secondary"
        if st.button("🤖 启用AI辅助预组卷", use_container_width=True, type=ai_btn_type):
            st.session_state["ai_exam_active"] = True
            st.session_state["ai_exam_modified"] = False # 重置修改状态
            st.rerun()
            
    # === 新增：AI 辅助预组卷面板 ===
    if st.session_state.get("ai_exam_active", False):
        st.markdown("---")
        st.markdown("### 🤖 智能组卷条件配置")
        with st.container(border=True):
            # 1. 知识板块约束
            st.markdown("##### 1. 考察知识板块")
            c_ai_subj, c_ai_diff = st.columns([1.5, 1])
            with c_ai_subj:
                extended_subjects = ["高考范围"] + SUBJECTS
                ai_subjects_raw = st.multiselect("选择本次组卷覆盖的知识板块", options=extended_subjects, default=["高考范围"], key="ai_exam_subjects")
            with c_ai_diff:
                # 2. 难度系数
                st.markdown("<div style='font-size: 14px; color: #31333F; margin-bottom: 5px;'><b>目标平均难度星级</b></div>", unsafe_allow_html=True)
                from utils.star_rating import st_star_rating
                ai_difficulty = st_star_rating(label="", value=st.session_state.get("ai_exam_diff_val", 3.0), max_stars=6, key="star_ai_exam_diff")
                if ai_difficulty is not None and ai_difficulty != st.session_state.get("ai_exam_diff_val", 3.0):
                    st.session_state["ai_exam_diff_val"] = ai_difficulty
            
            # 新增：组卷意图与要求
            st.markdown("##### 2. 组卷意图与附加要求")
            c_intent_lbl, c_intent_btn = st.columns([4, 1], vertical_alignment="bottom")
            with c_intent_lbl:
                intent_text = st.text_area("请填写您的组卷想法（例如：侧重考察导数的隐零点问题，解答题最后一道必须是解析几何，且不要太难）", key="ai_exam_intent", height=100)
            with c_intent_btn:
                def do_polish():
                    txt = st.session_state.get("ai_exam_intent", "").strip()
                    if not txt:
                        st.toast("请先填写初步想法", icon="⚠️")
                        return
                    res = call_ai_for_polish(txt)
                    if res.startswith("❌"):
                        st.toast(res, icon="❌")
                    else:
                        st.session_state["ai_exam_intent"] = res
                        st.toast("润色成功！", icon="✨")
                st.button("✨ AI 润色想法", on_click=do_polish, use_container_width=True)
            
            # 3. 题目数量与题型（根据主题推断，如果是试卷类则固定结构）
            st.markdown("##### 3. 试卷结构约束")
            is_paper = "试卷" in theme
            if is_paper:
                st.info("💡 当前为“试卷类模板”，系统将严格按照新高考结构（单选8+多选3+填空3+解答5=19题）抽取。")
                ai_q_count = 19
            else:
                ai_q_count = st.session_state.get("exam_q_count_input", 10)
                st.info(f"💡 当前为非试卷类模板，系统将按照您的预设，随机抽取 **{ai_q_count}** 道题目。")
            
            # 4. 执行生成按钮
            if st.button("🚀 开始智能抽题 (基于本地题库标签)", type="primary", use_container_width=True):
                if not ai_subjects_raw:
                    st.warning("请至少选择一个知识板块！")
                else:
                    with st.spinner("正在遍历题库并进行智能抽样..."):
                        # 执行基于规则的抽题算法
                        from utils.csv_ops import read_csv_index
                        csv_data = read_csv_index()
                        
                        if not csv_data:
                            st.error("题库为空或索引未建立，请先在工具页一键重建题库索引。")
                        else:
                            import random
                            # 解析“高考范围”快捷选项
                            actual_subjects = set()
                            for s in ai_subjects_raw:
                                if s == "高考范围":
                                    actual_subjects.update(["集合", "复数", "不等式", "函数", "概率", "统计", "排列组合", "圆锥曲线", "解三角形", "三角函数", "立体几何", "向量", "数列", "导数"])
                                else:
                                    actual_subjects.add(s)
                            
                            # 1. 第一轮硬过滤：过滤掉不属于所选板块的题目
                            candidates = []
                            for row in csv_data:
                                row_subj = row.get("知识板块", "")
                                # 只要该题的任何一个标签在用户选择的板块中，即可入选
                                if any(s in row_subj for s in actual_subjects):
                                    candidates.append(row)
                            
                            # 获取当前目标难度
                            current_diff = st.session_state.get("ai_exam_diff_val", 3.0)
                            
                            # 辅助函数：根据难度范围过滤并随机抽取指定数量
                            def sample_questions(pool, target_count, q_type=None, diff_range=None):
                                filtered = pool
                                if q_type:
                                    filtered = [q for q in filtered if q_type in q.get("题目类型", "")]
                                if diff_range:
                                    # 如果没有星级，默认视为基础题 (1.0)
                                    filtered = [q for q in filtered if diff_range[0] <= float(q.get("难度星级") or 1.0) <= diff_range[1]]
                                
                                if len(filtered) >= target_count:
                                    return random.sample(filtered, target_count)
                                else:
                                    # 如果指定难度不够，放宽难度限制补齐
                                    backup = [q for q in pool if q not in filtered and (q_type in q.get("题目类型", "") if q_type else True)]
                                    needed = target_count - len(filtered)
                                    return filtered + random.sample(backup, min(needed, len(backup)))

                            selected_rows = []
                            if is_paper:
                                # 新高考标准结构抽样
                                # 单选 8 题 (基础4 + 中档3 + 难题1)
                                sq_base = sample_questions(candidates, 4, q_type="选择题", diff_range=(0.0, 2.5))
                                sq_mid = sample_questions(candidates, 3, q_type="选择题", diff_range=(3.0, 4.0))
                                sq_hard = sample_questions(candidates, 1, q_type="选择题", diff_range=(4.5, 6.0))
                                
                                # 多选 3 题 (基础1 + 中档1 + 难题1)
                                mq_base = sample_questions(candidates, 1, q_type="选择题", diff_range=(0.0, 2.5))
                                mq_mid = sample_questions(candidates, 1, q_type="选择题", diff_range=(3.0, 4.0))
                                mq_hard = sample_questions(candidates, 1, q_type="选择题", diff_range=(4.5, 6.0))
                                
                                # 填空 3 题 (基础1 + 中档1 + 难题1)
                                fq_base = sample_questions(candidates, 1, q_type="填空题", diff_range=(0.0, 2.5))
                                fq_mid = sample_questions(candidates, 1, q_type="填空题", diff_range=(3.0, 4.0))
                                fq_hard = sample_questions(candidates, 1, q_type="填空题", diff_range=(4.5, 6.0))
                                
                                # 解答 5 题 (基础2 + 中档2 + 难题1)
                                aq_base = sample_questions(candidates, 2, q_type="解答题", diff_range=(0.0, 2.5))
                                aq_mid = sample_questions(candidates, 2, q_type="解答题", diff_range=(3.0, 4.0))
                                aq_hard = sample_questions(candidates, 1, q_type="解答题", diff_range=(4.5, 6.0))
                                
                                selected_rows = sq_base + sq_mid + sq_hard + mq_base + mq_mid + mq_hard + fq_base + fq_mid + fq_hard + aq_base + aq_mid + aq_hard
                            else:
                                # 非试卷类：根据目标难度和总数进行大乱炖抽样
                                # 按照正态分布近似：60% 中档，20% 基础，20% 难题 (围绕目标难度上下浮动)
                                base_count = int(ai_q_count * 0.2)
                                hard_count = int(ai_q_count * 0.2)
                                mid_count = ai_q_count - base_count - hard_count
                                
                                # 根据用户设定的 current_diff 动态平移区间
                                mid_range = (max(0.0, current_diff - 1.0), min(6.0, current_diff + 1.0))
                                base_range = (0.0, max(0.0, current_diff - 1.5))
                                hard_range = (min(6.0, current_diff + 1.5), 6.0)
                                
                                r_base = sample_questions(candidates, base_count, diff_range=base_range)
                                r_mid = sample_questions(candidates, mid_count, diff_range=mid_range)
                                r_hard = sample_questions(candidates, hard_count, diff_range=hard_range)
                                
                                selected_rows = r_base + r_mid + r_hard
                            
                            # 最终检查并转换为路径
                            final_paths = []
                            for r in selected_rows:
                                p = os.path.join(CHAPTERS_DIR, r["相对文件路径"])
                                if os.path.exists(p) and p not in final_paths:
                                    final_paths.append(p)
                                    
                            if len(final_paths) < ai_q_count:
                                st.warning(f"题库中满足条件的题目不足，仅抽取到 {len(final_paths)} 题。")
                            else:
                                st.success(f"智能组卷完成！已成功抽取 {len(final_paths)} 道题目。")
                                
                            # 强制覆盖当前购物车
                            st.session_state["exam_selected_qs"] = final_paths
                            st.session_state["exam_q_count_input"] = len(final_paths)
                            st.session_state["ai_exam_modified"] = False
                            time.sleep(1)
                            st.rerun()
            
    # 注入 CSS：美化 number_input 的边框使其明显，并隐藏原生上下箭头，以及根据状态设置 primary 按钮颜色
    css_injection = """
    <style>
    /* 隐藏 Streamlit number_input 原生内部的 - 和 + 按钮 */
    button[data-testid="stNumberInputStepDown"],
    button[data-testid="stNumberInputStepUp"] {
        display: none !important;
    }
    
    /* 隐藏原生浏览器输入框内的上下箭头 */
    input[type="number"]::-webkit-inner-spin-button,
    input[type="number"]::-webkit-outer-spin-button {
        -webkit-appearance: none;
        margin: 0;
    }
    input[type="number"] {
        -moz-appearance: textfield;
    }
    """
    
    if st.session_state["ai_exam_active"]:
        if st.session_state["ai_exam_modified"]:
            btn_color = "#1f6feb" 
        else:
            btn_color = "#2ea043"
            
        css_injection += f"""
        div[data-testid="column"]:nth-child(3) button[kind="primary"] {{
            background-color: {btn_color} !important;
            border-color: {btn_color} !important;
            color: white !important;
        }}
        """
        
    css_injection += "</style>"
    st.markdown(css_injection, unsafe_allow_html=True)
        
    st.write("")
    
    # 2. 已选展示区
    st.markdown(f"### 📋 已选问题 ({selected_count}/{st.session_state['exam_q_count_input']})")
    
    if selected_count > 0:
        if st.button("✨ 选题完成，进入排版工作台", type="primary", use_container_width=True):
            # 准备进入排版阶段
            # 1. 保留已有的 exam_blocks 中的章节块，同步题目块
            existing_paths = [b["path"] for b in st.session_state["exam_blocks"] if b["type"] == "question"]
            
            # 把新加入购物车的题目加到 exam_blocks 后面
            for p in st.session_state["exam_selected_qs"]:
                if p not in existing_paths:
                    st.session_state["exam_blocks"].append({"id": str(uuid.uuid4()), "type": "question", "path": p})
            
            # 把购物车中已经移除的题目，也从 exam_blocks 中同步移除
            # 修复点：保留 section, subsection, chapter 等非 question 类型
            st.session_state["exam_blocks"] = [
                b for b in st.session_state["exam_blocks"]
                if b["type"] in ("chapter", "section", "subsection") or b.get("path") in st.session_state["exam_selected_qs"]
            ]
            
            st.session_state["exam_mode_stage"] = "typesetting"
            st.rerun()
            
        st.markdown("---")
        
        # 采用原生单列竖向列表排版，支持取消选择
        
        if "exam_expanded_q" not in st.session_state:
            st.session_state["exam_expanded_q"] = None
            
        for i, p in enumerate(list(st.session_state["exam_selected_qs"])):
            name = os.path.basename(p).replace('.tex', '')
            
            # 使用极简两列结构: [题目名称] [删除]
            c_btn, c_del = st.columns([6, 1], gap="small")
            is_expanded = (st.session_state.get("exam_expanded_q") == p)
            
            with c_btn:
                hook_class = "blue-btn-hook" if is_expanded else "white-btn-hook"
                st.markdown(f'<span class="{hook_class}"></span>', unsafe_allow_html=True)
                if st.button(f"{i+1}. {name}", key=f"cart_view_{p}", use_container_width=True):
                    st.session_state["exam_expanded_q"] = None if is_expanded else p
                    st.rerun()
                    
            with c_del:
                st.markdown('<span class="white-red-text-btn-hook"></span>', unsafe_allow_html=True)
                if st.button("❌", key=f"cart_rm_{p}", use_container_width=True):
                    st.session_state["exam_selected_qs"].remove(p)
                    if st.session_state.get("exam_expanded_q") == p:
                        st.session_state["exam_expanded_q"] = None
                    if st.session_state.get("ai_exam_active"):
                        st.session_state["ai_exam_modified"] = True
                    st.rerun()
                    
        expanded_q = st.session_state.get("exam_expanded_q")
        if expanded_q and expanded_q in st.session_state["exam_selected_qs"]:
            st.markdown("---")
            st.subheader("👁️ 已选问题预览")
            try:
                with open(expanded_q, "r", encoding="utf-8") as f:
                    expanded_content = f.read()
                st.markdown(latex_to_markdown(expanded_content), unsafe_allow_html=True)
            except Exception as e:
                st.error(f"无法读取文件: {e}")
            st.markdown("---")
    else:
        st.info("暂未选择任何题目，请在下方浏览并添加。")
            
    st.divider()
    
    # 3. 复用浏览界面进行选题
    page_browse(is_exam_mode=True)

def generate_exam_paper(export_filename, export_dir, blocks, theme_name):
    # 确保导出目录存在
    ensure_dir(export_dir)
    
    # 读取模板内容
    template_path = os.path.join(BASE_DIR, "Test Paper Group", "主题模板", theme_name, f"{theme_name}.tex")
    if not os.path.exists(template_path):
        return None
        
    with open(template_path, "r", encoding="utf-8") as f:
        template_content = f.read()
        
    # 生成要插入的 content
    body_lines = []
    for blk in blocks:
        if blk["type"] == "chapter":
            body_lines.append(f"\\chapter{{{blk['title']}}}")
            if blk.get("content"):
                body_lines.append(blk["content"])
        elif blk["type"] == "section":
            body_lines.append(f"\\section{{{blk['title']}}}")
            if blk.get("content"):
                body_lines.append(blk["content"])
        elif blk["type"] == "subsection":
            body_lines.append(f"\\subsection{{{blk['title']}}}")
            if blk.get("content"):
                body_lines.append(blk["content"])
        elif blk["type"] == "question":
            q_path = blk["path"]
            if os.path.exists(q_path):
                with open(q_path, "r", encoding="utf-8") as qf:
                    q_content = qf.read()
                    if theme_name == "讲义类模板":
                        body_lines.append("\\begin{lanbox}\n" + q_content + "\n\\end{lanbox}")
                    else:
                        body_lines.append(q_content)
                        
    # 如果是试卷类模板，需要对题目格式和分数进行二次加工
    if theme_name == "试卷类模板":
        import re
        q_index = 0
        current_section = 0
        new_body_lines = []
        for line in body_lines:
            if line.startswith(r"\section{"):
                current_section += 1
                new_body_lines.append(line)
            elif r"\begin{problem}" in line:
                q_index += 1
                
                # 第一步：增加题目序号注释 %*
                line = f"% {q_index}.\n" + line
                
                if current_section == 4:
                    # 对于第四个 section (解答题) 后的题目
                    # 1. 替换为 \begin{problem} 并带上对应分数
                    # 2. 删除后面紧跟的5个参数括号 {...}
                    if q_index == 15:
                        points = 13
                    elif q_index in (16, 17):
                        points = 15
                    elif q_index in (18, 19):
                        points = 17
                    else:
                        points = 12 # fallback
                        
                    # 替换 \begin{problem}{...}{...}{...}{...}{...} -> \begin{problem}[points = xx]
                    # 容错：有些参数可能换行了或者有空格，用 \s* 和 dotall 处理
                    line = re.sub(r'\\begin\{problem\}\s*\{.*?\}\s*\{.*?\}\s*\{.*?\}\s*\{.*?\}\s*\{.*?\}', f'\\\\begin{{problem}}[points = {points}]', line, flags=re.DOTALL)
                else:
                    # 对于前三个 section (选择填空) 的题目
                    # 1. 替换为 \begin{question}
                    # 2. 删除后面紧跟的5个参数括号 {...}
                    # 3. 将对应的 \end{problem} 替换为 \end{question}
                    line = re.sub(r'\\begin\{problem\}\s*\{.*?\}\s*\{.*?\}\s*\{.*?\}\s*\{.*?\}\s*\{.*?\}', r'\\begin{question}', line, flags=re.DOTALL)
                    line = line.replace(r'\end{problem}', r'\end{question}')
                    
                # 【新增修复】：将 \begin{choices} 替换为没有方括号的形式（比如去除 \begin{choices}[2] 等，恢复为 exam-zh 默认选项）
                # 题库里带参数的 \begin{choices}[2] 可能会在试卷模板里报错或者不兼容
                # 用户要求类似原来模板的纯净 \begin{choices}
                # 但是实际上用户刚才提到的是 choices，而模板里使用的是 \begin{choices} \item ...
                # 题库中用的是 \choice{{...}}，模板中似乎需要 \item
                # 我们在这里将 \choice{{...}} 转换为 \item ... 
                # 同时将带参数的 \begin{choices}[2] 去除参数
                line = re.sub(r'\\begin\{choices\}\[.*?\]', r'\\begin{choices}', line)
                
                def replace_choices_with_items(text):
                    idx = 0
                    while True:
                        idx = text.find(r'\choice', idx)
                        if idx == -1: break
                        start_brace = text.find('{', idx)
                        if start_brace == -1:
                            idx += len(r'\choice')
                            continue
                        if text[idx+7:start_brace].strip() != '':
                            idx += len(r'\choice')
                            continue
                        next_char_idx = start_brace + 1
                        while next_char_idx < len(text) and text[next_char_idx].isspace():
                            next_char_idx += 1
                        is_double = False
                        if next_char_idx < len(text) and text[next_char_idx] == '{':
                            is_double = True
                            content_start = next_char_idx + 1
                        else:
                            content_start = start_brace + 1
                        brace_count = 2 if is_double else 1
                        match_end = -1
                        content = ''
                        for i in range(content_start, len(text)):
                            if text[i] == '{': brace_count += 1
                            elif text[i] == '}': brace_count -= 1
                            if brace_count == 0:
                                match_end = i + 1
                                inner = text[content_start:i]
                                if is_double:
                                    last_brace_idx = inner.rfind('}')
                                    if last_brace_idx != -1:
                                        content = inner[:last_brace_idx].strip()
                                    else:
                                        content = inner.strip()
                                else:
                                    content = inner.strip()
                                break
                        if match_end != -1:
                            prefix = text[:idx]
                            suffix = text[match_end:]
                            text = prefix + r'\item ' + content + suffix
                            idx = len(prefix) + len(r'\item ') + len(content)
                        else:
                            idx += len(r'\choice')
                    return text

                line = replace_choices_with_items(line)
                    
                new_body_lines.append(line)
            else:
                # 处理可能散落在别的行的 \end{problem} 和 \choice 等
                if current_section < 4 and r'\end{problem}' in line:
                    line = line.replace(r'\end{problem}', r'\end{question}')
                    
                line = re.sub(r'\\begin\{choices\}\[.*?\]', r'\\begin{choices}', line)
                line = replace_choices_with_items(line)
                
                new_body_lines.append(line)
        body_lines = new_body_lines

    generated_body = "\n\n".join(body_lines)
    
    # 替换标题（如果有的话）
    import re
    if theme_name == "试卷类模板":
        # 试卷类模板使用的是 \title{...}
        template_content = re.sub(r'\\title\{.*?\}', f'\\\\title{{{export_filename}}}', template_content)
    elif r'\renewcommand{\mytitle}' in template_content:
        template_content = re.sub(r'\\renewcommand\{\\mytitle\}\{.*?\}', f'\\\\renewcommand{{\\\\mytitle}}{{{export_filename}}}', template_content)
    
    # 查找 \begin{document} 之后的内容
    doc_idx = template_content.find(r'\begin{document}')
    if doc_idx != -1:
        # 寻找正文里第一个 \chapter 或者 \section 或者 \begin{problem} 或者 \begin{question} 作为切割点
        chap_idx = template_content.find(r'\chapter{', doc_idx)
        sec_idx = template_content.find(r'\section{', doc_idx)
        prob_idx = template_content.find(r'\begin{problem}', doc_idx)
        ques_idx = template_content.find(r'\begin{question}', doc_idx)
        
        candidates = [idx for idx in (chap_idx, sec_idx, prob_idx, ques_idx) if idx != -1]
        if candidates:
            insert_idx = min(candidates)
            end_idx = template_content.rfind(r'\end{document}')
            
            if end_idx != -1:
                # 头部内容保留（包括 \renewcommand{\mytitle}{...} 和所有前置的格式设置）
                pre_content = template_content[:insert_idx]
                # 尾部内容保留（\end{document}及以后）
                post_content = template_content[end_idx:]
                
                final_content = pre_content + generated_body + "\n\n" + post_content
                
                # 修改点：在年月目录下，再创建一个与试卷名相同的独立文件夹
                final_export_dir = os.path.join(export_dir, export_filename)
                ensure_dir(final_export_dir)
                
                output_file = os.path.join(final_export_dir, f"{export_filename}.tex")
                atomic_write_text(output_file, final_content, backup=os.path.exists(output_file))
                return output_file
            
    return None

def render_typesetting_workspace():
    st.subheader("🖨️ 试卷排版工作台")
    
    # 动态生成默认的输出文件名
    import datetime
    today = datetime.date.today()
    y_str = today.strftime("%Y")
    m_str = today.strftime("%m")
    d_str = today.strftime("%d")
    
    theme_name = st.session_state.get("exam_theme", "练习类模板")
    export_dir = os.path.join(BASE_DIR, "Test Paper Group", "导出文件", y_str, m_str)
    
    # 确定当天的序号
    daily_count = 1
    if os.path.exists(export_dir):
        prefix = f"{y_str}年{m_str}月{d_str}日 {theme_name}组卷"
        for f in os.listdir(export_dir):
            if f.startswith(prefix) and f.endswith(".tex"):
                daily_count += 1
                
    default_filename = f"{y_str}年{m_str}月{d_str}日 {theme_name}组卷{daily_count}"
    
    # 返回按钮与生成按钮栏
    c_back, c_name, c_gen = st.columns([1, 1.5, 1])
    with c_back:
        def go_back_to_selection():
            st.session_state["exam_mode_stage"] = "selection"
        st.button("⬅️ 返回继续选题", on_click=go_back_to_selection, use_container_width=True)
    with c_name:
        export_filename = st.text_input("输出文件名", value=default_filename, label_visibility="collapsed")
    with c_gen:
        if st.button("🖨️ 确认生成试卷", type="primary", use_container_width=True):
            if theme_name in ("练习类模板", "讲义类模板", "试卷类模板"):
                output_path = generate_exam_paper(export_filename, export_dir, st.session_state["exam_blocks"], theme_name)
                if output_path:
                    st.success(f"试卷已成功生成至：{output_path}")
                else:
                    st.error("生成失败，请检查模板文件是否存在或格式是否正确！")
            else:
                st.warning("暂不支持其他模板的生成，敬请期待！")
    
    st.markdown("---")
    
    st.subheader("📑 试卷结构与排版")
    
    # 计算当前试卷中有多少道题目（用于下拉菜单选位置）
    blocks = st.session_state["exam_blocks"]
    q_count = sum(1 for b in blocks if b["type"] == "question")
    
    # 构建插入位置选项
    # 例如: "第1题前", "第2题前", ..., "最后一题后"
    insert_positions = [f"第{i}题前" for i in range(1, q_count + 1)]
    insert_positions.append("最后一题后" if q_count > 0 else "列表最末尾")
    
    # 插入新章节/小节
    st.markdown("""
    <style>
    /* 移除表单的外边框和背景色 */
    div[data-testid="stForm"] {
        border: none !important;
        padding: 0 !important;
        background-color: transparent !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # 构建表单处理逻辑的辅助函数
    def _insert_block(blk_type, title, pos_str):
        new_block = {"id": str(uuid.uuid4()), "type": blk_type, "title": title}
        if pos_str in ("最后一题后", "列表最末尾"):
            st.session_state["exam_blocks"].append(new_block)
        else:
            target_q_num = int(pos_str.replace("第", "").replace("题前", ""))
            current_q = 0
            insert_idx = len(blocks)
            for idx, b in enumerate(blocks):
                if b["type"] == "question":
                    current_q += 1
                    if current_q == target_q_num:
                        insert_idx = idx
                        break
            st.session_state["exam_blocks"].insert(insert_idx, new_block)
            
    # 动态渲染根据不同模板决定是 2 层还是 3 层结构
    if theme_name == "讲义类模板":
        # 讲义类有 章、节、小节 三层
        c_label_0, c_input_0, c_pos_0, c_submit_0 = st.columns([1.5, 3.5, 1.5, 1.5])
        with c_label_0:
            st.markdown("<div style='padding-top:8px;'><b>📚 插入章</b></div>", unsafe_allow_html=True)
        with c_input_0:
            chap_title = st.text_input("文本内容", placeholder="例如：第一章 集合", label_visibility="collapsed", key="chap_title_input")
        with c_pos_0:
            chap_pos = st.selectbox("插入位置", insert_positions, index=0, label_visibility="collapsed", key="chap_pos")
        with c_submit_0:
            def on_chap_submit():
                t = st.session_state.get("chap_title_input", "")
                p = st.session_state.get("chap_pos", insert_positions[0])
                if t:
                    _insert_block("chapter", t, p)
                    st.session_state["chap_title_input"] = ""
            st.button("确认插入", key="chap_submit", on_click=on_chap_submit, use_container_width=True)

        # 节
        c_label_1, c_input_1, c_pos_1, c_submit_1 = st.columns([1.5, 3.5, 1.5, 1.5])
        with c_label_1:
            st.markdown("<div style='padding-top:8px; color: #58a6ff;'><b>🗂️ 插入节</b></div>", unsafe_allow_html=True)
        with c_input_1:
            sec_title = st.text_input("文本内容", placeholder="例如：第一节 集合的概念", label_visibility="collapsed", key="sec_title_input")
        with c_pos_1:
            sec_pos = st.selectbox("插入位置", insert_positions, index=0, label_visibility="collapsed", key="sec_pos")
        with c_submit_1:
            def on_sec_submit():
                t = st.session_state.get("sec_title_input", "")
                p = st.session_state.get("sec_pos", insert_positions[0])
                if t:
                    _insert_block("section", t, p)
                    st.session_state["sec_title_input"] = ""
            st.button("确认插入", key="sec_submit", on_click=on_sec_submit, use_container_width=True)
                    
        # 小节
        c_label_2, c_input_2, c_pos_2, c_submit_2 = st.columns([1.5, 3.5, 1.5, 1.5])
        with c_label_2:
            st.markdown("<div style='padding-top:8px; color: #8b949e;'><b>📝 插入小节</b></div>", unsafe_allow_html=True)
        with c_input_2:
            subsec_title = st.text_input("文本内容", placeholder="例如：考点一", label_visibility="collapsed", key="subsec_title_input")
        with c_pos_2:
            subsec_pos = st.selectbox("插入位置", insert_positions, index=0, label_visibility="collapsed", key="subsec_pos")
        with c_submit_2:
            def on_subsec_submit():
                t = st.session_state.get("subsec_title_input", "")
                p = st.session_state.get("subsec_pos", insert_positions[0])
                if t:
                    _insert_block("subsection", t, p)
                    st.session_state["subsec_title_input"] = ""
            st.button("确认插入", key="subsec_submit", on_click=on_subsec_submit, use_container_width=True)
            
    elif theme_name == "试卷类模板":
        # 试卷类模板具有四个固定的 section，提供默认内容和位置，并且只允许修改这些节，不再随意新增
        st.markdown("<div style='color: #8b949e; font-size: 0.9em; margin-bottom: 10px;'>💡 提示：试卷类模板提供四个固定的试卷题型模块，您可以直接点击下方按钮快速插入到对应位置。</div>", unsafe_allow_html=True)
        
        # 预设的四个节信息
        exam_presets = [
            {
                "label": "插入单选题节",
                "default_title": "%\n  选择题：本题共 8 小题，每小题 5 分，共 40 分。\n  在每小题给出的四个选项中，只有一项是符合题目要求的。\n",
                "default_pos_index": 0 # 第1题前
            },
            {
                "label": "插入多选题节",
                "default_title": "%\n  选择题：本题共 3 小题，每小题 6 分，共 18 分。\n  在每小题给出的选项中，有多项符合题目要求的。\n  全部选对的得 6 分，部分选择的得部分分，有选错的得 0 分。\n",
                "default_pos_index": min(8, len(insert_positions)-1) # 第9题前
            },
            {
                "label": "插入填空题节",
                "default_title": "填空题：本题共 3 小题，每小题 5 分，共 15 分。",
                "default_pos_index": min(11, len(insert_positions)-1) # 第12题前
            },
            {
                "label": "插入解答题节",
                "default_title": "解答题：本题共 5 小题，共 77 分。解答应写出文字说明、证明过程或者演算步骤。",
                "default_pos_index": min(14, len(insert_positions)-1) # 第15题前
            }
        ]
        
        for i, preset in enumerate(exam_presets):
            c_label, c_input, c_pos, c_submit = st.columns([1.5, 3.5, 1.5, 1.5])
            with c_label:
                st.markdown(f"<div style='padding-top:8px;'><b>🗂️ {preset['label']}</b></div>", unsafe_allow_html=True)
            with c_input:
                # 试卷模板的标题通常比较长，直接放入 content 中，把真正的 title 留空，或者将这段话当作 title
                # 按照用户的代码，这些其实是放在 \section{...} 里面的，所以还是算作 title
                sec_title = st.text_area("文本内容", value=preset["default_title"], height=68, label_visibility="collapsed", key=f"exam_sec_title_{i}")
            with c_pos:
                sec_pos = st.selectbox("插入位置", insert_positions, index=preset["default_pos_index"], label_visibility="collapsed", key=f"exam_sec_pos_{i}")
            with c_submit:
                def make_submit_callback(i_val):
                    def callback():
                        t = st.session_state.get(f"exam_sec_title_{i_val}", "")
                        p = st.session_state.get(f"exam_sec_pos_{i_val}", insert_positions[0])
                        if t:
                            _insert_block("section", t, p)
                    return callback
                
                # 垂直居中对齐
                st.markdown("<div style='padding-top:12px;'></div>", unsafe_allow_html=True)
                st.button("确认插入", key=f"exam_sec_submit_{i}", on_click=make_submit_callback(i), use_container_width=True)

    else:
        # 练习类及其他模板，仅保留 章节 和 小节
        c_label_1, c_input_1, c_pos_1, c_submit_1 = st.columns([1.5, 3.5, 1.5, 1.5])
        with c_label_1:
            st.markdown("<div style='padding-top:8px;'><b>🗂️ 插入章节</b></div>", unsafe_allow_html=True)
        with c_input_1:
            sec_title = st.text_input("文本内容", placeholder="例如：一、选择题", label_visibility="collapsed", key="sec_title_input")
        with c_pos_1:
            sec_pos = st.selectbox("插入位置", insert_positions, index=0, label_visibility="collapsed", key="sec_pos")
        with c_submit_1:
            def on_sec_submit():
                t = st.session_state.get("sec_title_input", "")
                p = st.session_state.get("sec_pos", insert_positions[0])
                if t:
                    _insert_block("section", t, p)
                    st.session_state["sec_title_input"] = ""
            st.button("确认插入", key="sec_submit", on_click=on_sec_submit, use_container_width=True)
                    
        c_label_2, c_input_2, c_pos_2, c_submit_2 = st.columns([1.5, 3.5, 1.5, 1.5])
        with c_label_2:
            st.markdown("<div style='padding-top:8px; color: #8b949e;'><b>📝 插入小节</b></div>", unsafe_allow_html=True)
        with c_input_2:
            subsec_title = st.text_input("文本内容", placeholder="例如：(一) 单选题", label_visibility="collapsed", key="subsec_title_input")
        with c_pos_2:
            subsec_pos = st.selectbox("插入位置", insert_positions, index=0, label_visibility="collapsed", key="subsec_pos")
        with c_submit_2:
            def on_subsec_submit():
                t = st.session_state.get("subsec_title_input", "")
                p = st.session_state.get("subsec_pos", insert_positions[0])
                if t:
                    _insert_block("subsection", t, p)
                    st.session_state["subsec_title_input"] = ""
            st.button("确认插入", key="subsec_submit", on_click=on_subsec_submit, use_container_width=True)
                    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # 遍历显示 Blocks (单列流式布局，改为左右两栏)
    blocks = st.session_state["exam_blocks"]
    q_counter = 1
    chap_counter = 0
    sec_counter = 0
    subsec_counter = 0
    
    for i, blk in enumerate(blocks):
        # 每一行分为左右两列：左侧显示标题和控制按钮，右侧显示渲染结果
        c_left, c_right = st.columns([3, 7], gap="large")
        
        with c_left:
            if blk["type"] == "chapter":
                chap_counter += 1
                sec_counter = 0
                subsec_counter = 0
                # 允许动态修改章节标题
                col_l, col_r = st.columns([1.5, 3.5])
                with col_l:
                    st.markdown(f"<div style='padding-top:8px; white-space:nowrap;'><b>📚 第{chap_counter}章标题</b></div>", unsafe_allow_html=True)
                with col_r:
                    # 修复性能问题：不将 widget 的返回值直接硬塞回 blk 中，除非它发生了改变
                    # 使用 on_change 回调或直接依赖 session_state 来存储值
                    new_val = st.text_input("章标题", value=blk['title'], key=f"blk_title_{blk['id']}", label_visibility="collapsed")
                    if new_val != blk['title']: blk['title'] = new_val
                new_c = st.text_area("内容源码", value=blk.get("content", ""), key=f"blk_content_{blk['id']}", placeholder="在此输入章说明源码（可选）", label_visibility="collapsed")
                if new_c != blk.get("content", ""): blk["content"] = new_c
            elif blk["type"] == "section":
                sec_counter += 1
                subsec_counter = 0
                # 允许动态修改章节标题
                col_l, col_r = st.columns([1.5, 3.5])
                with col_l:
                    if theme_name == "讲义类模板":
                        st.markdown(f"<div style='padding-top:8px; color: #58a6ff; white-space:nowrap;'><b>🗂️ 第{chap_counter}.{sec_counter}节标题</b></div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div style='padding-top:8px; white-space:nowrap;'><b>🗂️ 第{sec_counter}章标题</b></div>", unsafe_allow_html=True)
                with col_r:
                    new_val = st.text_input("节/章标题", value=blk['title'], key=f"blk_title_{blk['id']}", label_visibility="collapsed")
                    if new_val != blk['title']: blk['title'] = new_val
                new_c = st.text_area("内容源码", value=blk.get("content", ""), key=f"blk_content_{blk['id']}", placeholder="在此输入节/章说明源码（可选）", label_visibility="collapsed")
                if new_c != blk.get("content", ""): blk["content"] = new_c
            elif blk["type"] == "subsection":
                subsec_counter += 1
                # 允许动态修改小节标题
                col_l, col_r = st.columns([1.5, 3.5])
                with col_l:
                    if theme_name == "讲义类模板":
                        st.markdown(f"<div style='padding-top:8px; color: #8b949e; white-space:nowrap;'><b>📝 第{chap_counter}.{sec_counter}.{subsec_counter}小节标题</b></div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div style='padding-top:8px; color: #8b949e; white-space:nowrap;'><b>📝 第{sec_counter}.{subsec_counter}小节标题</b></div>", unsafe_allow_html=True)
                with col_r:
                    new_val = st.text_input("小节标题", value=blk['title'], key=f"blk_title_{blk['id']}", label_visibility="collapsed")
                    if new_val != blk['title']: blk['title'] = new_val
                new_c = st.text_area("内容源码", value=blk.get("content", ""), key=f"blk_content_{blk['id']}", placeholder="在此输入小节说明源码（可选）", label_visibility="collapsed")
                if new_c != blk.get("content", ""): blk["content"] = new_c
            else:
                name = os.path.basename(blk['path']).replace('.tex', '')
                st.markdown(f"<h5 style='color: #c9d1d9; margin-top: 0;'>📄 {name}</h5>", unsafe_allow_html=True)
                
            # 按钮栏放在标题下方
            c_up, c_down, c_del = st.columns(3)
            with c_up:
                if st.button("⬆️", key=f"blk_up_{blk['id']}", disabled=(i==0), help="上移", use_container_width=True):
                    blocks[i], blocks[i-1] = blocks[i-1], blocks[i]
                    st.rerun()
            with c_down:
                if st.button("⬇️", key=f"blk_down_{blk['id']}", disabled=(i==len(blocks)-1), help="下移", use_container_width=True):
                    blocks[i], blocks[i+1] = blocks[i+1], blocks[i]
                    st.rerun()
            with c_del:
                if st.button("❌", key=f"blk_del_{blk['id']}", help="移除", use_container_width=True):
                    removed = blocks.pop(i)
                    if removed["type"] == "question" and removed["path"] in st.session_state["exam_selected_qs"]:
                        st.session_state["exam_selected_qs"].remove(removed["path"])
                    st.rerun()
                    
        with c_right:
            # 右侧渲染内容区
            if blk["type"] == "chapter":
                st.markdown(f"<h2 style='color: #d2a8ff; margin: 0;'>{blk['title']}</h2>", unsafe_allow_html=True)
                if blk.get("content"):
                    st.markdown(f"<div style='margin-top: 10px;'>{blk['content']}</div>", unsafe_allow_html=True)
            elif blk["type"] == "section":
                st.markdown(f"<h3 style='color: #58a6ff; margin: 0;'>{blk['title']}</h3>", unsafe_allow_html=True)
                if blk.get("content"):
                    st.markdown(f"<div style='margin-top: 10px;'>{blk['content']}</div>", unsafe_allow_html=True)
            elif blk["type"] == "subsection":
                st.markdown(f"<h4 style='color: #8b949e; border-left: 4px solid #8b949e; padding-left: 10px; margin: 0;'>{blk['title']}</h4>", unsafe_allow_html=True)
                if blk.get("content"):
                    st.markdown(f"<div style='margin-top: 10px;'>{blk['content']}</div>", unsafe_allow_html=True)
            else:
                if os.path.exists(blk["path"]):
                    with open(blk["path"], "r", encoding="utf-8") as f:
                        content = f.read()
                    try:
                        md_content = latex_to_markdown(content)
                        st.markdown(f"**{q_counter}.**")
                        st.markdown(md_content, unsafe_allow_html=True)
                        q_counter += 1
                    except Exception as e:
                        st.error(f"渲染出错: {e}")
                else:
                    st.error(f"文件不存在: {blk['path']}")
                    
        st.divider()

# ================= 页面：批量工具 =================
def page_tools():
    st.header("🛠️ 批量工具箱")

    if st.session_state.get("tools_subpage") == "tag_edit":
        if st.button("⬅️ 返回批量工具箱", type="secondary"):
            st.session_state["tools_subpage"] = None
            st.rerun()
        page_tag_edit()
        return
    
    st.markdown("""
    <style>
    /* 工具卡片网格布局：一行三个 */
    .tool-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 20px;
        margin-top: 15px;
    }
    
    /* 单个工具卡片样式 */
    .tool-card {
        background-color: #ffffff;
        border: 1px solid #e1e4e8;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.04);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        min-height: 240px; /* 确保同一行的卡片高度一致 */
    }
    .tool-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 8px 15px rgba(0,0,0,0.08);
        border-color: #4c1d95; /* 悬浮时边框变紫 */
    }
    
    /* 工具卡片标题 */
    .tool-title {
        font-size: 18px;
        font-weight: 700;
        color: #24292e;
        margin-bottom: 10px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    
    /* 工具卡片描述文本 */
    .tool-desc {
        font-size: 14px;
        color: #586069;
        line-height: 1.5;
        margin-bottom: 20px;
        flex-grow: 1; /* 让描述部分占据剩余空间，把按钮推到最底 */
    }
    
    /* 强力覆盖 Streamlit 按钮在工具卡片内的样式 */
    .tool-card div[data-testid="stButton"] > button {
        width: 100% !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
    }
    
    /* 如果描述带有高亮底色 (例如第一个工具) */
    .tool-desc-highlight {
        background-color: #f1f8ff;
        border-left: 4px solid #0366d6;
        padding: 10px;
        border-radius: 4px;
        margin-bottom: 20px;
        font-size: 13px;
        color: #24292e;
        flex-grow: 1;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # 开启网格布局容器
    st.markdown('<div class="tool-grid">', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True) 
    
    # 第一行 3 个工具
    r1_c1, r1_c2, r1_c3 = st.columns([1, 1, 1])
    
    with r1_c1:
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">🗄️ 1. 数据库维护</div>
            <div class="tool-desc-highlight">
                如果您手动删除、外部复制等变动，导致与 CSV 索引不一致，或者统计数据异常，可以点击下方按钮进行一键重建。该操作会保留现有题目的 ID，并自动追加新题或删除不存在的死链接。
            </div>
        </div>
        """, unsafe_allow_html=True)
        # 负 margin 把按钮拉进卡片里
        st.markdown("<style>div:has(> button[key='btn_rebuild_db']) { margin-top: -65px; padding: 0 20px; position: relative; z-index: 10; }</style>", unsafe_allow_html=True)
        if st.button("🔄 一键重建/同步题库索引", key="btn_rebuild_db", use_container_width=True):
            with st.spinner("正在扫描所有目录并重建 CSV 索引..."):
                try:
                    init_script = os.path.join(BASE_DIR, "utils", "init_csv_index.py")
                    subprocess.run(["python", init_script], check=True, capture_output=True, text=True)
                    clear_statistics_cache()
                    st.success("题库索引重建成功！")
                    st.toast("题库索引同步完成！", icon="✅")
                    time.sleep(1)
                    st.rerun()
                except subprocess.CalledProcessError as e:
                    st.error(f"同步失败：\n{e.stderr}")
                except Exception as e:
                    st.error(f"发生错误：{str(e)}")
            
    with r1_c2:
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">📑 2. 更新板块题目索引</div>
            <div class="tool-desc">
                调用本地的脚本，自动扫描 chapters 目录下的所有题目，并为每个板块重新生成最新的 <code>content_*.tex</code> 索引文件。供主文件 <code>main.tex</code> 调用编译。
                <br><br><i>(当您新增、删除或重命名了题目文件后，请执行此操作以确保主文件目录同步)</i>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<style>div:has(> button[key='btn_update_idx']) { margin-top: -65px; padding: 0 20px; position: relative; z-index: 10; }</style>", unsafe_allow_html=True)
        if st.button("⚡ 执行更新章节索引", key="btn_update_idx", use_container_width=True):
            with st.spinner("正在运行更新脚本..."):
                try:
                    import sys
                    if BASE_DIR not in sys.path:
                        sys.path.append(BASE_DIR)
                    import utils.batch_gen as batch_gen
                    batch_gen.update_chapter_contents()
                    st.success("章节索引更新完成！")
                except Exception as e:
                    st.error(f"执行失败: {e}")

    with r1_c3:
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">🎨 3. 提取并分离 TikZ 绘图</div>
            <div class="tool-desc">
                扫描题库中所有现存的 <code>.tex</code> 文件。如果发现未被分离的 <code>\\begin{tikzpicture} ... \\end{tikzpicture}</code> 代码，将会自动将其剥离到同级目录下的 <code>相关图</code> 文件夹中生成副本，同时在主文件中保留内联 TikZ 源码。
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<style>div:has(> button[key='btn_extract_tikz']) { margin-top: -65px; padding: 0 20px; position: relative; z-index: 10; }</style>", unsafe_allow_html=True)
        if st.button("✂️ 执行全库 TikZ 剥离", key="btn_extract_tikz", use_container_width=True):
            updated_files = batch_extract_tikz_all()
            if updated_files:
                st.success(f"操作完成，共处理了 {len(updated_files)} 个文件。")
                with st.expander("查看更新的文件名单", expanded=True):
                    for f in updated_files: st.write(f"- {f}")
            else:
                st.info("未发现需要处理的文件。")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # 第二行 3 个工具
    r2_c1, r2_c2, r2_c3 = st.columns([1, 1, 1])
    
    with r2_c1:
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">✅ 4. 纠正选择题选项格式</div>
            <div class="tool-desc">
                扫描题库中所有现存的 <code>.tex</code> 文件。如果发现形如 <code>A. xxx B. xxx C. xxx D. xxx</code> 的非标准选择题格式，将自动尝试提取选项内容，并用规范的 <code>\\begin{choices} ... \\end{choices}</code> 指令进行替换。
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<style>div:has(> button[key='btn_fix_choices']) { margin-top: -65px; padding: 0 20px; position: relative; z-index: 10; }</style>", unsafe_allow_html=True)
        if st.button("🔧 执行全库选择题格式纠正", key="btn_fix_choices", use_container_width=True):
            updated_files = batch_fix_choice_formats()
            if updated_files:
                st.success(f"操作完成，共修复了 {len(updated_files)} 个文件。")
                with st.expander("查看已修复的文件名单", expanded=True):
                    for f in updated_files: st.write(f"- {f}")
            else:
                st.info("未发现需要修复的选择题格式文件。")

    with r2_c2:
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">🏷️ 5. 标签与属性修改</div>
            <div class="tool-desc">
                查找并修改某一道题或某一整套试卷的元数据：年份、试卷类别、试卷名称、题号、知识板块，并同步更新文件名与 CSV 索引。
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<style>div:has(> button[key='btn_tools_tag_edit']) { margin-top: -65px; padding: 0 20px; position: relative; z-index: 10; }</style>", unsafe_allow_html=True)
        if st.button("进入标签与属性修改", key="btn_tools_tag_edit", use_container_width=True):
            st.session_state["tools_subpage"] = "tag_edit"
            st.rerun()

def batch_fix_choice_formats():
    import re
    updated_files = []
    
    for root, dirs, files in os.walk(CHAPTERS_DIR):
        for file in files:
            if not file.endswith(".tex"): continue
            if file.startswith("content_"): continue
            if " 相关图" in root or " 图" in file: continue
            
            file_path = os.path.join(root, file)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 寻找 A. B. C. D. 模式 (支持全半角和换行)
                pattern = r'(?:A|Ａ)[\.．]\s*(.*?)\s*(?:B|Ｂ)[\.．]\s*(.*?)\s*(?:C|Ｃ)[\.．]\s*(.*?)\s*(?:D|Ｄ)[\.．]\s*(.*?)(?=\\end\{problem\}|\\begin\{solutions?\}|$)'
                
                def replace_choices(match):
                    opt_a = match.group(1).strip()
                    opt_b = match.group(2).strip()
                    opt_c = match.group(3).strip()
                    opt_d = match.group(4).strip()
                    
                    # 移除选项末尾可能多余的 \quad, \qquad 和 \\ 等
                    def clean_opt(opt):
                        opt = re.sub(r'\\quad\s*$', '', opt).strip()
                        opt = re.sub(r'\\qquad\s*$', '', opt).strip()
                        opt = re.sub(r'\\\\$', '', opt).strip() # 去除换行符 \\
                        return opt
                        
                    opt_a = clean_opt(opt_a)
                    opt_b = clean_opt(opt_b)
                    opt_c = clean_opt(opt_c)
                    opt_d = clean_opt(opt_d)
                    
                    return f"\n\\begin{{choices}}\n\\choice{{{{{opt_a}}}}}\n\\choice{{{{{opt_b}}}}}\n\\choice{{{{{opt_c}}}}}\n\\choice{{{{{opt_d}}}}}\n\\end{{choices}}\n"
                
                new_content, count = re.subn(pattern, replace_choices, content, flags=re.DOTALL)
                
                # 检查 \begin{choices} 前面是否有 (\hspace{1cm})
                if r'\begin{choices}' in new_content:
                    parts = new_content.split(r'\begin{choices}')
                    for i in range(len(parts) - 1):
                        prefix = parts[i]
                        stripped_prefix = prefix.rstrip()
                        
                        # 检查是否已经有 (\hspace{1cm}) 或者类似的占位符 (支持全角半角括号和空格)
                        has_hspace = re.search(r'[\(（]\s*\\hspace\{1cm\}\s*[\)）]$', stripped_prefix)
                        
                        if not has_hspace:
                            # 检查是否有空的括号 () 或 （），有的话直接替换掉
                            if stripped_prefix.endswith('()') or stripped_prefix.endswith('（）'):
                                stripped_prefix = stripped_prefix[:-2] + r'(\hspace{1cm})'
                            else:
                                stripped_prefix += r' (\hspace{1cm})'
                                
                        parts[i] = stripped_prefix + '\n'
                        
                    new_content = r'\begin{choices}'.join(parts)
                
                if new_content != content:
                    atomic_write_text(file_path, new_content, backup=True)
                    updated_files.append(file)
            except Exception as e:
                print(f"Error processing {file_path}: {e}")
                
    return updated_files

def batch_extract_tikz_all():
    updated_files = []
    for root, dirs, files in os.walk(CHAPTERS_DIR):
        for file in files:
            if not file.endswith(".tex"): continue
            # 跳过已经被提取出来的图文件
            if " 图" in file and " 相关图" in root: continue
            
            file_path = os.path.join(root, file)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 如果包含原生的 tikzpicture 才需要处理
                if r'\begin{tikzpicture}' in content:
                    save_dir = root
                    filename = file
                    # 复用核心抽取函数
                    new_content = extract_and_replace_tikz(content, filename, save_dir)
                    if new_content != content:
                        atomic_write_text(file_path, new_content, backup=True)
                        # 触发一次预渲染生成PNG
                        latex_to_markdown(new_content)
                        updated_files.append(file_path)
            except Exception as e:
                print(f"Error processing {file_path}: {e}")
                
    return updated_files

def add_blank_lines_to_all():
    count = 0
    for root, dirs, files in os.walk(CHAPTERS_DIR):
        for file in files:
            if not file.endswith(".tex"): continue
            
            file_path = os.path.join(root, file)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 使用简单的正则或字符串处理
                # 这里复用之前的逻辑：查找 \begin{problem}... 到 \end{problem}
                # 简单起见，我们假设文件就是标准的 problem 结构
                
                lines = content.split('\n')
                new_lines = []
                in_problem = False
                modified = False
                
                for i, line in enumerate(lines):
                    if "\\begin{problem}" in line:
                        in_problem = True
                        new_lines.append(line)
                        continue
                    if "\\end{problem}" in line:
                        in_problem = False
                        new_lines.append(line)
                        continue
                        
                    if in_problem:
                        # 如果当前行不空，且上一行不空，且不是环境开始，则加空行
                        # 但要小心不要破坏数学公式块 $ ... $
                        # 这是一个简化的处理，主要针对文本段落
                        
                        # 简单策略：如果当前行是非空文本，且上一行也是非空文本，插入空行
                        # 但为了安全，我们只处理显式的中文段落结尾？
                        # 或者复用之前的逻辑：每行后面加一个空行，如果已经有空行则不加
                        
                        # 更稳健的策略：读取内容，如果发现没有空行分隔的段落，则插入
                        # 这里我们采用保守策略：如果当前行有内容，且下一行也有内容，中间插入空行
                        # 并不容易完美自动化。
                        # 让我们回退到最安全的方式：不做复杂语法分析，仅提示用户
                        # 或者，只处理显式的文字段落。
                        
                        # 实际上，之前的 update_doc.py 逻辑比较复杂。
                        # 在这里，我们实现一个简化版本：确保 \end{problem} 前有一行空行，
                        # 以及 \begin{problem} 后有一行空行（如果不为空的话）。
                        # 真正的段落间空行最好人工确认。
                        
                        # 重新考虑：用户之前的需求是“分行加空行”。
                        # 我们可以简单地将非空行之间插入空行。
                        
                        stripped = line.strip()
                        if stripped:
                            new_lines.append(line)
                            # 如果下一行不是空行，也不是 end problem，则添加空行
                            if i + 1 < len(lines):
                                next_line = lines[i+1].strip()
                                if next_line and "\\end{problem}" not in next_line:
                                    new_lines.append("") # 插入空行
                                    modified = True
                        else:
                            new_lines.append(line)
                    else:
                        new_lines.append(line)
                
                if modified:
                    new_content = "\n".join(new_lines)
                    if new_content != content:
                        atomic_write_text(file_path, new_content, backup=True)
                        count += 1
            except Exception as e:
                print(f"Error processing {file}: {e}")
                
    return count


def standardize_national_papers():
    # 这里集成之前的重命名逻辑
    count = 0
    local_keywords = [
        "北京", "上海", "天津", "重庆", "浙江", "江苏", "江西", "山东", 
        "湖北", "湖南", "广东", "福建", "辽宁", "吉林", "黑龙江", 
        "河北", "河南", "山西", "陕西", "四川", "云南", "贵州", 
        "安徽", "广西", "海南", "内蒙古", "西藏", "青海", "宁夏", 
        "新疆", "甘肃", "港", "澳", "台"
    ]
    
    for root, dirs, files in os.walk(CHAPTERS_DIR):
        for file in files:
            if not file.endswith(".tex"): continue
            
            parts = file[:-4].split('-')
            if len(parts) != 5: continue
            
            year_str, type_str, paper_name, number, subject = parts
            try:
                year = int(year_str)
            except:
                continue
                
            # 过滤地方卷和甲乙卷
            is_local = any(kw in paper_name for kw in local_keywords)
            if is_local or "甲卷" in paper_name or "乙卷" in paper_name:
                continue
                
            new_paper_name = paper_name
            # 规则匹配
            if 2020 <= year <= 2022:
                if "新课标" in new_paper_name: new_paper_name = new_paper_name.replace("新课标", "新高考")
                if "新高考全国" in new_paper_name: new_paper_name = new_paper_name.replace("新高考全国", "新高考")
            elif 2023 <= year <= 2025:
                if "新高考" in new_paper_name: new_paper_name = new_paper_name.replace("新高考", "新课标")
                if "新课标全国" in new_paper_name: new_paper_name = new_paper_name.replace("新课标全国", "新课标")
            
            if new_paper_name != paper_name:
                # 重命名文件
                new_filename = f"{year_str}-{type_str}-{new_paper_name}-{number}-{subject}.tex"
                old_path = os.path.join(root, file)
                new_path = os.path.join(root, new_filename)
                
                # 更新内容中的标签
                try:
                    with open(old_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    # 替换 {paper_name} 为 {new_paper_name}
                    # 简单的字符串替换可能误伤，使用比较精确的替换
                    old_tag = f"{{{paper_name}}}"
                    new_tag = f"{{{new_paper_name}}}"
                    content = content.replace(old_tag, new_tag, 1) # 只替换第一个匹配（通常是标签）
                    
                    atomic_write_text(old_path, content, backup=True)
                        
                    os.rename(old_path, new_path)
                    st.write(f"已重命名: {file} -> {new_filename}")
                    count += 1
                except Exception as e:
                    st.error(f"处理 {file} 时出错: {e}")
    return count

# ================= 页面：标签与属性修改 (含搜索) =================
def page_tag_edit():
    st.header("🏷️ 标签与属性修改")
    st.info("在此模式下，您可以修改题目的元数据（年份、试卷名、题号、板块）以及文件名。")
    
    # Session state for selected file in this tab
    if "tag_edit_file" not in st.session_state:
        st.session_state["tag_edit_file"] = None

    # 定义匹配函数 (局部使用)
    # def is_match(path, s_type, s_query): ... (Use global check_search_match instead)
        
    c_left, c_right = st.columns([1, 1.5])  # 调整比例，使右侧搜索栏宽度缩小
    
    with c_left:
        st.markdown("""
        <style>
        #tag-edit-dir-label {
            font-size: 16px;
            font-weight: 700;
            margin: 0.35rem 0 0.15rem 0;
        }
        #tag-edit-dir-box div[data-testid="stSelectbox"] div[data-baseweb="select"] * {
            font-size: 16px !important;
            font-weight: 700 !important;
        }
        </style>
        """, unsafe_allow_html=True)
        st.markdown('<div id="tag-edit-dir-box"></div>', unsafe_allow_html=True)
        st.subheader("📂 目录选择")
        csv_rows = []
        all_years = get_all_years_globally()
        st.markdown('<div id="tag-edit-dir-label">年份</div>', unsafe_allow_html=True)
        year = st.selectbox("年份", options=all_years, key="te_year", label_visibility="collapsed")

        type_opts = ["全部试卷类别"] + list(PAPER_TYPES.keys())
        st.markdown('<div id="tag-edit-dir-label">试卷类别筛选</div>', unsafe_allow_html=True)
        ptype_filter = st.selectbox("试卷类别筛选", options=type_opts, key="te_ptype_filter", label_visibility="collapsed", format_func=lambda x: x if x == "全部试卷类别" else f"{x} ({PAPER_TYPES.get(x, '')})")

        paper_name = None
        if year:
            csv_token = _csv_index_cache_token()
            try:
                csv_rows = _csv_index_cached(csv_token)
            except Exception:
                from utils.csv_ops import read_csv_index
                csv_rows = read_csv_index()

            papers_set = set()
            for row in csv_rows:
                if (row.get("年份", "") or "").strip() != str(year):
                    continue
                if ptype_filter != "全部试卷类别" and (row.get("试卷类型", "") or "").strip() != ptype_filter:
                    continue
                pname = (row.get("试卷名称", "") or "").strip()
                if pname:
                    papers_set.add(pname)
            papers = sorted(papers_set) if papers_set else get_papers_by_year(year)
            if papers:
                st.markdown('<div id="tag-edit-dir-label">试卷</div>', unsafe_allow_html=True)
                paper_name = st.selectbox("试卷", options=papers, key="te_paper", label_visibility="collapsed")
        
        if year and paper_name:
            questions = get_questions_by_paper(year, paper_name)
            if questions:
                by_path = {}
                for row in csv_rows if year else []:
                    relp = (row.get("相对文件路径", "") or "").strip()
                    if not relp:
                        continue
                    by_path[os.path.join(CHAPTERS_DIR, relp)] = row

                filtered_questions = []
                for q in questions:
                    qpath = q.get("path")
                    r = by_path.get(qpath)
                    if ptype_filter != "全部试卷类别":
                        if not r or (r.get("试卷类型", "") or "").strip() != ptype_filter:
                            continue
                    filtered_questions.append(q)

                questions = filtered_questions
                q_options = ["（所有题目：本试卷）"] + [f"第{q['file'].split('-')[3]}题 ({q['subject']})" for q in questions]
                st.markdown('<div id="tag-edit-dir-label">题目</div>', unsafe_allow_html=True)
                sel_idx = st.selectbox("题目", range(len(q_options)), format_func=lambda i: q_options[i], key="te_q_select", label_visibility="collapsed")
                
                if st.button("⬇️ 加载选中题目", key="btn_load_hierarchy", use_container_width=True):
                    if sel_idx == 0:
                        st.session_state["tag_edit_file"] = None
                        st.session_state["tag_edit_bulk_paths"] = [q.get("path") for q in questions if q.get("path")]
                        st.session_state["tag_edit_bulk_meta"] = {"year": str(year), "paper": str(paper_name)}
                    else:
                        st.session_state["tag_edit_bulk_paths"] = []
                        st.session_state["tag_edit_bulk_meta"] = None
                        st.session_state["tag_edit_file"] = questions[sel_idx - 1]["path"]
                    st.rerun()

    with c_right:
        st.subheader("🔍 搜索选择")
        search_opts = ["全文内容", "题目类型", "题目内容", "解答内容", "难度星级", "标签", "备注"]
        # 因为需要级联更新 UI（selectbox -> text_input/selectbox），不能将包含动态类型的输入框直接放进 form
        # 我们改用普通的容器，最后加一个搜索按钮
        c1a, c1b = st.columns([1, 2])
        with c1a: 
            t1 = st.selectbox("一级类型", search_opts, index=0, key="te_s_t1", label_visibility="collapsed")
        with c1b: 
            if t1 == "题目类型":
                q1 = st.selectbox("一级检索", ["选择题", "填空题", "解答题"], key="te_s_q1_sel", label_visibility="collapsed")
            else:
                q1 = st.text_input("一级检索", placeholder="一级关键词", key="te_s_q1", label_visibility="collapsed")
        
        # Level 2
        c2a, c2b = st.columns([1, 2])
        with c2a: 
            t2 = st.selectbox("二级类型", search_opts, index=0, key="te_s_t2", label_visibility="collapsed")
        with c2b: 
            if t2 == "题目类型":
                q2 = st.selectbox("二级检索", ["选择题", "填空题", "解答题"], key="te_s_q2_sel", label_visibility="collapsed")
            else:
                q2 = st.text_input("二级检索", placeholder="筛选词", key="te_s_q2", label_visibility="collapsed")
        
        # Level 3
        c3a, c3b = st.columns([1, 2])
        with c3a: 
            t3 = st.selectbox("三级类型", search_opts, index=0, key="te_s_t3", label_visibility="collapsed")
        with c3b: 
            if t3 == "题目类型":
                q3 = st.selectbox("三级检索", ["选择题", "填空题", "解答题"], key="te_s_q3_sel", label_visibility="collapsed")
            else:
                q3 = st.text_input("三级检索", placeholder="筛选词", key="te_s_q3", label_visibility="collapsed")
        
        submitted = st.button("🔍 搜索", type="primary", use_container_width=True)
             
        if submitted:
            st.session_state["te_search_active"] = True
            
        if st.session_state.get("te_search_active"):
            def _row_match(row, s_type, s_query):
                s_query = (s_query or "").strip()
                if not s_query:
                    return True
                if s_type == "题目类型":
                    return s_query == (row.get("题型", "") or "").strip()
                if s_type == "题目内容":
                    return s_query in (row.get("题干", "") or "")
                if s_type == "解答内容":
                    return s_query in (row.get("解析", "") or "")
                if s_type == "难度星级":
                    return s_query in (row.get("难度星级", "") or "")
                if s_type == "标签":
                    return s_query in (row.get("标签", "") or "")
                if s_type == "备注":
                    return s_query in (row.get("备注", "") or "")
                if s_type == "全文内容":
                    hay = (row.get("题干", "") or "") + "\n" + (row.get("答案", "") or "") + "\n" + (row.get("解析", "") or "") + "\n" + (row.get("标签", "") or "") + "\n" + (row.get("备注", "") or "")
                    return s_query in hay
                return False

            csv_token = _csv_index_cache_token()
            try:
                csv_rows = _csv_index_cached(csv_token)
            except Exception:
                from utils.csv_ops import read_csv_index
                csv_rows = read_csv_index()

            results = []
            for row in csv_rows:
                if q1 and not _row_match(row, t1, q1):
                    continue
                if q2 and not _row_match(row, t2, q2):
                    continue
                if q3 and not _row_match(row, t3, q3):
                    continue
                relp = (row.get("相对文件路径", "") or "").strip()
                if not relp:
                    continue
                absp = os.path.join(CHAPTERS_DIR, relp)
                if not os.path.exists(absp):
                    continue
                fname = (row.get("文件名称", "") or "").strip()
                if fname and not fname.lower().endswith(".tex"):
                    fname = fname + ".tex"
                results.append({"file": fname or os.path.basename(absp), "path": absp})
            
            if results:
                st.success(f"找到 {len(results)} 个结果")
                res_options = [r["file"] for r in results]
                sel_res_idx = st.selectbox("选择搜索结果", range(len(results)), format_func=lambda i: res_options[i], key="te_res_select")
                
                if st.button("⬇️ 加载搜索结果", key="btn_load_search", use_container_width=True):
                    st.session_state["tag_edit_file"] = results[sel_res_idx]["path"]
                    st.rerun()
            else:
                st.warning("未找到匹配项")

    st.divider()
    
    # 编辑区域
    bulk_paths = st.session_state.get("tag_edit_bulk_paths") or []
    bulk_meta = st.session_state.get("tag_edit_bulk_meta") or {}
    if bulk_paths:
        st.subheader("🧩 批量修改（本试卷所有题目）")
        st.caption("仅修改：年份、试卷类别、试卷名称；题号与知识板块保持不变。")

        cur_year = (bulk_meta.get("year") or "").strip()
        cur_paper = (bulk_meta.get("paper") or "").strip()
        st.info(f"当前试卷：{cur_year} 年｜{cur_paper}｜共 {len(bulk_paths)} 题")

        type_opts = list(PAPER_TYPES.keys())
        with st.form("te_bulk_update_form"):
            new_year = st.text_input("统一年份", value=cur_year)
            new_type = st.selectbox("统一试卷类别", options=type_opts, format_func=lambda x: f"{x} ({PAPER_TYPES[x]})")
            new_name = st.text_input("统一试卷名称", value=cur_paper)
            submitted = st.form_submit_button("执行批量更新", type="primary")

        if submitted:
            ok, fail = 0, 0
            log_lines = []
            for old_path in bulk_paths:
                try:
                    if not old_path or not os.path.exists(old_path):
                        fail += 1
                        continue
                    base = os.path.basename(old_path).replace(".tex", "")
                    parts = base.split("-")
                    if len(parts) < 5:
                        fail += 1
                        continue
                    old_year, old_ptype, old_pname, old_pnum, old_subj = parts[0], parts[1], parts[2], parts[3], parts[4]
                    new_filename = generate_filename(new_year, new_type, new_name, old_pnum, old_subj)
                    primary_subj = old_subj.split("，")[0] if old_subj else ""
                    target_dir = os.path.join(CHAPTERS_DIR, primary_subj, str(new_year))
                    ensure_dir(target_dir)
                    new_path = os.path.join(target_dir, new_filename)
                    with open(old_path, "r", encoding="utf-8") as f:
                        old_content = f.read()
                    new_header = f"\\begin{{problem}}{{{new_year}}}{{{new_type}}}{{{new_name}}}{{{old_pnum}}}{{{old_subj}}}"
                    new_content = re.sub(r"\\begin\{problem\}\{.*?\}\{.*?\}\{.*?\}\{.*?\}\{.*?\}", lambda _m: new_header, old_content, count=1)
                    if new_content == old_content and "\\begin{problem}" in old_content:
                        new_content = re.sub(r"\\begin\{problem\}", lambda _m: new_header, old_content, count=1)
                    atomic_write_text(new_path, new_content, backup=os.path.exists(new_path))
                    if os.path.abspath(new_path) != os.path.abspath(old_path):
                        os.remove(old_path)
                    update_csv_index_for_edit(old_path, new_path, new_content, str(new_year), new_type, new_name, old_pnum, old_subj)
                    ok += 1
                    log_lines.append(f"✅ {os.path.basename(old_path)} -> {os.path.basename(new_path)}")
                except Exception as e:
                    fail += 1
                    log_lines.append(f"❌ {os.path.basename(old_path) if old_path else ''}: {e}")

            clear_statistics_cache()
            st.success(f"批量更新完成：成功 {ok}，失败 {fail}")
            with st.expander("查看日志", expanded=(fail > 0)):
                for line in log_lines:
                    st.write(line)
            st.session_state["tag_edit_bulk_paths"] = []
            st.session_state["tag_edit_bulk_meta"] = None
            time.sleep(0.5)
            st.rerun()

    file_path = st.session_state.get("tag_edit_file")
    if file_path and os.path.exists(file_path):
        # 读取文件内容
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 解析当前元数据
        current_meta = {}
        parts = os.path.basename(file_path)[:-4].split('-')
        if len(parts) >= 5:
            current_meta = {
                "year": parts[0],
                "type": parts[1],
                "name": parts[2],
                "num": parts[3],
                "subject": parts[4]
            }
        
        c_edit_left, c_edit_right = st.columns([1, 1])
        
        with c_edit_left:
            st.subheader("LaTeX 源码预览")
            est_height = get_editor_height(content)
            mtime_token = int(os.path.getmtime(file_path)) if os.path.exists(file_path) else 0
            st.text_area("源码", value=content, height=est_height, disabled=True, key=f"te_preview_left_{file_path}_{mtime_token}")
            st.caption(f"文件路径: {file_path}")
            
        with c_edit_right:
            st.subheader("修改元数据")
            with st.form("te_meta_update_form"):
                new_year = st.text_input("年份", value=current_meta.get("year", ""))
                
                type_opts = list(PAPER_TYPES.keys())
                default_type_idx = 0
                if current_meta.get("type") in type_opts:
                    default_type_idx = type_opts.index(current_meta.get("type"))
                new_type = st.selectbox("试卷类型", options=type_opts, index=default_type_idx, format_func=lambda x: f"{x} ({PAPER_TYPES[x]})")
                
                new_name = st.text_input("试卷名称", value=current_meta.get("name", ""))
                new_num = st.text_input("题号", value=current_meta.get("num", ""))
                
                # 多板块处理
                current_subjects = current_meta.get("subject", "").split("，")
                valid_current_subjects = [s for s in current_subjects if s in SUBJECTS]
                if not valid_current_subjects:
                    valid_current_subjects = [SUBJECTS[0]] if SUBJECTS else []
                
                new_subjects = st.multiselect("知识板块 (首个为主)", options=SUBJECTS, default=valid_current_subjects)
                new_subject_str = "，".join(new_subjects) if new_subjects else (SUBJECTS[0] if SUBJECTS else "")
                
                st.caption("注意：修改元数据将重命名文件并更新文件内容的 problem 头部信息。主板块(第一个)决定文件存储位置。")
                
                if st.form_submit_button("执行重命名与标签更新", type="primary"):
                    new_filename = generate_filename(new_year, new_type, new_name, new_num, new_subject_str)
                    
                    primary_subj = new_subject_str.split("，")[0] if new_subject_str else ""
                    current_primary = current_meta.get("subject", "").split("，")[0]
                    
                    target_dir = os.path.join(CHAPTERS_DIR, primary_subj, new_year)
                    if primary_subj != current_primary or new_year != current_meta.get("year"):
                        ensure_dir(target_dir)
                    new_path = os.path.join(target_dir, new_filename)

                    try:
                        new_header = f"\\begin{{problem}}{{{new_year}}}{{{new_type}}}{{{new_name}}}{{{new_num}}}{{{new_subject_str}}}"
                        new_full_text = re.sub(r"\\begin\{problem\}\{.*?\}\{.*?\}\{.*?\}\{.*?\}\{.*?\}", lambda _m: new_header, content, count=1)
                        if new_full_text == content and "\\begin{problem}" in content:
                            new_full_text = re.sub(r"\\begin\{problem\}", lambda _m: new_header, content, count=1)
                        with open(new_path, "w", encoding="utf-8") as f:
                            f.write(new_full_text)
                        
                        if new_path != file_path:
                            os.remove(file_path)
                            
                        # 同步更新到 CSV 索引
                        update_csv_index_for_edit(file_path, new_path, new_full_text, new_year, new_type, new_name, new_num, new_subject_str)
                            
                        st.success(f"更新成功！\n旧: {os.path.basename(file_path)}\n新: {new_filename}")
                        clear_statistics_cache()
                        st.session_state["tag_edit_file"] = new_path
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"更新失败: {e}")

def update_question_meta(fpath, key, value):
    from utils.latex_ops import parse_meta_data, inject_meta_data
    with open(fpath, "r", encoding="utf-8") as f:
        fc = f.read()
    fm, _ = parse_meta_data(fc)
    fm[key] = value
    new_fc = inject_meta_data(fc, fm)
    atomic_write_text(fpath, new_fc, backup=True)
    try:
        from utils.csv_ops import update_csv_index_for_edit
        # 从文件名解析基础信息
        basename = os.path.basename(fpath).replace(".tex", "")
        parts = basename.split("-")
        if len(parts) >= 5:
            new_year = parts[0]
            new_ptype = parts[1]
            new_pname = parts[2]
            new_pnum = parts[3]
            new_subj = parts[4]
            update_csv_index_for_edit(fpath, fpath, new_fc, new_year, new_ptype, new_pname, new_pnum, new_subj)
            _clear_advanced_search_result_cache()
        else:
            print("Update CSV failed: Invalid filename format.")
    except Exception as e:
        print("Update CSV failed:", e)

def render_question_header(q_label, content, fpath, extra_html_label=""):
    st.markdown(f"### {q_label} {extra_html_label}", unsafe_allow_html=True)
    
    from utils.latex_ops import parse_meta_data
    meta, _ = parse_meta_data(content)
    diff = meta.get("难度星级", "").strip()
    tags = meta.get("标签", "").strip()
    remark = meta.get("备注", "").strip()

    try:
        diff_val = float(diff)
    except:
        diff_val = 0.0

    from utils.star_rating import st_star_rating
    
    pending_key = f"pending_diff_{fpath}"
    version_key = f"star_key_version_{fpath}"
    
    # --- 注入 CSS 实现紧凑同行布局与徽章样式 ---
    st.markdown("""
    <style>
    /* 限定作用域，避免污染全局布局 */
    /* 移除对 stHorizontalBlock 的 :has 覆盖，防止左侧边栏布局崩溃 */
    
    div[data-testid="column"]:has(.star-col) {
        width: 100px !important;
        min-width: 100px !important;
        max-width: 100px !important;
        flex: 0 0 auto !important;
    }
    div[data-testid="column"]:has(.star-col) iframe {
        height: 45px !important; /* 强制约束星星组件高度 */
        margin: 0 !important;
        padding: 0 !important;
    }
    div[data-testid="column"]:has(.tight-lbl) {
        width: fit-content !important;
        min-width: fit-content !important;
        flex: 0 1 auto !important;
        padding-right: 0px !important;
        padding-left: 0px !important;
    }
    div[data-testid="column"]:has(.tight-lbl) p {
        margin: 0 !important;
        padding: 0 !important;
        line-height: 1;
        display: flex;
        align-items: center;
        min-height: 30px; /* 与按钮高度保持一致的基础高度 */
    }
    div[data-testid="column"]:has(.rem-lbl) {
        padding-left: 20px !important; /* 强制拉开备注与前面按钮的距离 */
    }
    div[data-testid="column"]:has(.tight-btn) {
        width: fit-content !important;
        min-width: 40px !important;
        flex: 0 0 auto !important;
        padding-left: 4px !important;
    }
    
    /* 淡灰色 + 按钮 */
    div[data-testid="column"]:has(.tight-btn) div[data-testid="stPopover"] > button {
        color: #666 !important;
        background-color: #f5f6f8 !important;
        border: 1px solid #ddd !important;
        padding: 0px 10px !important;
        min-height: 24px !important;
        height: 24px !important;
        line-height: 1 !important;
        width: auto !important;
        border-radius: 12px !important;
        font-size: 12px !important;
        margin: 0 !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        transform: translateY(3px); /* 微调按钮位置以完美对齐文本 */
    }
    div[data-testid="column"]:has(.tight-btn) div[data-testid="stPopover"] > button:hover {
        background-color: #e2e6ea !important;
        border-color: #ccc !important;
    }
    
    /* 现代徽章样式 (Badge) */
    .badge-tag {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        font-size: 14px; /* 调整为与 Streamlit 默认正文文本一致的字号 */
        font-weight: 600;
        line-height: 1.5;
        color: #0366d6;
        background-color: #f1f8ff;
        border: 1px solid #c8e1ff;
        border-radius: 2em;
        margin-right: 4px;
    }
    .badge-rem {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        font-size: 14px; /* 调整为与 Streamlit 默认正文文本一致的字号 */
        font-weight: 500;
        line-height: 1.5;
        color: #b08800;
        background-color: #fffdef;
        border: 1px solid #dfd8c2;
        border-radius: 4px;
        margin-right: 4px;
    }
    </style>
    """, unsafe_allow_html=True)
    
    with st.container(border=True):
        # === 统一放在同一行：星级 | 标签 + 按钮 | 备注 + 按钮 ===
        # 这里用更精细的列宽比例来挤压空间
        c_star, c_tag_lbl, c_tag_btn, c_rem_lbl, c_rem_btn, _ = st.columns([1.1, 0.7, 0.3, 0.9, 0.3, 2.7], vertical_alignment="center")
        
        with c_star:
            st.markdown("<span class='star-col'></span>", unsafe_allow_html=True)
            # 使用更全局唯一的 key，防止在不同页面（全局浏览 vs 搜索结果）复用同一个文件时产生冲突
            import hashlib
            unique_hash = hashlib.md5(f"{fpath}_{q_label}_{extra_html_label}".encode()).hexdigest()[:8]
            comp_key = f"star_rating_{unique_hash}_{st.session_state.get(version_key, 0)}"
            new_diff = st_star_rating(label="难度星级：", value=diff_val, max_stars=6, key=comp_key)
            
            if new_diff is not None and new_diff != diff_val:
                if diff_val == 0.0:
                    update_question_meta(fpath, "难度星级", str(new_diff))
                    st.session_state[version_key] = st.session_state.get(version_key, 0) + 1
                    st.rerun()
                else:
                    st.session_state[pending_key] = new_diff

        with c_tag_lbl:
            if tags:
                # 把逗号分隔的标签拆分成多个小徽章
                tag_html = "".join([f"<span class='badge-tag'>🏷️ {t.strip()}</span>" for t in tags.split("，") if t.strip()])
                st.markdown(f"<span class='tight-lbl'></span>**标签：**{tag_html}", unsafe_allow_html=True)
            else:
                st.markdown("<span class='tight-lbl'></span>**标签：**<span style='color:#aaa; font-size:12px;'>无标签</span>", unsafe_allow_html=True)
                
        with c_tag_btn:
            st.markdown("<span class='tight-btn'></span>", unsafe_allow_html=True)
            tag_popover_key = f"tag_popover_{fpath}_{st.session_state.get(f'tag_version_{fpath}', 0)}"
            with st.popover("➕", help="修改标签"):
                new_tags_str = st.text_input("编辑标签（逗号“，”分隔）", value=tags, key=f"tag_input_{tag_popover_key}")
                if not tags:
                    if st.button("直接保存", key=f"tag_save_{tag_popover_key}", type="primary"):
                        update_question_meta(fpath, "标签", new_tags_str)
                        st.session_state[f'tag_version_{fpath}'] = st.session_state.get(f'tag_version_{fpath}', 0) + 1
                        st.rerun()
                else:
                    tc1, tc2 = st.columns(2)
                    with tc1:
                        if st.button("确认", key=f"tag_ok_{tag_popover_key}", type="primary"):
                            update_question_meta(fpath, "标签", new_tags_str)
                            st.session_state[f'tag_version_{fpath}'] = st.session_state.get(f'tag_version_{fpath}', 0) + 1
                            st.rerun()
                    with tc2:
                        if st.button("取消", key=f"tag_cancel_{tag_popover_key}", type="secondary"):
                            st.session_state[f'tag_version_{fpath}'] = st.session_state.get(f'tag_version_{fpath}', 0) + 1
                            st.rerun()

        with c_rem_lbl:
            if remark:
                st.markdown(f"<span class='rem-lbl tight-lbl'></span>**备注：**<span class='badge-rem'>📝 {remark}</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span class='rem-lbl tight-lbl'></span>**备注：**<span style='color:#aaa; font-size:12px;'>无备注</span>", unsafe_allow_html=True)
                
        with c_rem_btn:
            st.markdown("<span class='tight-btn'></span>", unsafe_allow_html=True)
            rem_popover_key = f"rem_popover_{fpath}_{st.session_state.get(f'rem_version_{fpath}', 0)}"
            with st.popover("➕", help="修改备注"):
                new_rem_str = st.text_input("编辑备注", value=remark, key=f"rem_input_{rem_popover_key}")
                if not remark:
                    if st.button("直接保存", key=f"rem_save_{rem_popover_key}", type="primary"):
                        update_question_meta(fpath, "备注", new_rem_str)
                        st.session_state[f'rem_version_{fpath}'] = st.session_state.get(f'rem_version_{fpath}', 0) + 1
                        st.rerun()
                else:
                    rc1, rc2 = st.columns(2)
                    with rc1:
                        if st.button("确认", key=f"rem_ok_{rem_popover_key}", type="primary"):
                            update_question_meta(fpath, "备注", new_rem_str)
                            st.session_state[f'rem_version_{fpath}'] = st.session_state.get(f'rem_version_{fpath}', 0) + 1
                            st.rerun()
                    with rc2:
                        if st.button("取消", key=f"rem_cancel_{rem_popover_key}", type="secondary"):
                            st.session_state[f'rem_version_{fpath}'] = st.session_state.get(f'rem_version_{fpath}', 0) + 1
                            st.rerun()

        # 处理未保存的星级变更弹窗（放到最后，避免打乱单行布局）
        if pending_key in st.session_state:
            st.warning(f"确认修改为 {st.session_state[pending_key]} 星吗？")
            bc1, bc2 = st.columns(2)
            with bc1:
                if st.button("✅ 确认", key=f"diff_ok_{fpath}", type="primary"):
                    final_diff = st.session_state[pending_key]
                    update_question_meta(fpath, "难度星级", str(final_diff))
                    del st.session_state[pending_key]
                    st.session_state[version_key] = st.session_state.get(version_key, 0) + 1
                    st.rerun()
            with bc2:
                if st.button("❌ 取消", key=f"diff_cancel_{fpath}", type="secondary"):
                    del st.session_state[pending_key]
                    st.session_state[version_key] = st.session_state.get(version_key, 0) + 1
                    st.rerun()
        
# ================= 辅助函数：搜索匹配 =================
import datetime

def clear_statistics_cache():
    get_statistics.clear()

def _csv_index_cache_token():
    from utils.core_config import CSV_INDEX_PATH
    return file_change_token(CSV_INDEX_PATH)

@st.cache_data(show_spinner=False)
def _csv_index_cached(csv_token):
    from utils.csv_ops import read_csv_index
    return read_csv_index()

@st.cache_data(show_spinner=False)
def _advanced_search_index_cached(csv_token):
    from utils.csv_ops import read_csv_index

    index_rows = []
    for row in read_csv_index():
        rel_path = (row.get("相对文件路径", "") or "").strip()
        abs_path = os.path.join(CHAPTERS_DIR, rel_path) if rel_path else ""
        filename = (row.get("文件名称", "") or "").strip()
        if filename and not filename.lower().endswith(".tex"):
            filename = filename + ".tex"

        stem = row.get("题干", "") or ""
        answer = row.get("答案", "") or ""
        solution = row.get("解析", "") or ""
        tags = row.get("标签", "") or ""
        remark = row.get("备注", "") or ""

        index_rows.append({
            "row": row,
            "file": filename,
            "path": abs_path,
            "type": (row.get("题型", "") or "").strip(),
            "stem": stem,
            "answer": answer,
            "solution": solution,
            "difficulty": row.get("难度星级", "") or "",
            "tags": tags,
            "remark": remark,
            "full_text": "\n".join([stem, answer, solution, tags, remark]),
        })
    return index_rows

@st.cache_data(ttl=10)
def get_statistics():
    stats = {
        "total_questions": 0,
        "total_tikz": 0,
        "today_new_questions": 0,
        "today_mod_questions": 0,
        "today_new_tikz": 0,
        "today_mod_tikz": 0,
        "daily_activity": {},
        "hourly_activity_by_day": {},
        "subject_counts": {},
        "type_counts": {},
        "difficulty_dist": {},
        "tag_counts": {},
        "total_difficulty": 0.0,
        "difficulty_count": 0
    }
    
    today_str = datetime.date.today().isoformat()
    
    # 优先尝试从 CSV 索引表读取（性能提升 100 倍）
    try:
        from utils.csv_ops import read_csv_index
        csv_data = read_csv_index()
        if csv_data:
            stats["total_questions"] = len(csv_data)
            
            for row in csv_data:
                # 统计新增和修改
                c_time = row.get("初次录入的时间", "")
                m_time = row.get("最后修改时间", "")
                
                c_date = c_time.split(" ")[0] if c_time else ""
                m_date = m_time.split(" ")[0] if m_time else ""
                
                # 记录小时活跃度
                if c_time and " " in c_time:
                    c_hour = c_time.split(" ")[1].split(":")[0]
                    if c_date not in stats["hourly_activity_by_day"]:
                        stats["hourly_activity_by_day"][c_date] = {str(i).zfill(2): 0 for i in range(24)}
                    stats["hourly_activity_by_day"][c_date][c_hour] += 1
                if m_time and " " in m_time and m_time != c_time:
                    m_hour = m_time.split(" ")[1].split(":")[0]
                    if m_date not in stats["hourly_activity_by_day"]:
                        stats["hourly_activity_by_day"][m_date] = {str(i).zfill(2): 0 for i in range(24)}
                    stats["hourly_activity_by_day"][m_date][m_hour] += 1
                
                if c_date == today_str:
                    stats["today_new_questions"] += 1
                elif m_date == today_str:
                    stats["today_mod_questions"] += 1
                    
                # 记录每日活跃度 (热力图)
                if c_date:
                    stats["daily_activity"][c_date] = stats["daily_activity"].get(c_date, 0) + 1
                if m_date and m_date != c_date:
                    stats["daily_activity"][m_date] = stats["daily_activity"].get(m_date, 0) + 1
                    
                # 统计包含 TikZ 的题目
                if row.get("包含TikZ绘图") == "是":
                    stats["total_tikz"] += 1
                    if c_date == today_str:
                        stats["today_new_tikz"] += 1
                    elif m_date == today_str:
                        stats["today_mod_tikz"] += 1
                        
                # 新增统计：各板块分布
                subj = row.get("知识板块", "").split("，")[0] if row.get("知识板块") else "未分类"
                stats["subject_counts"][subj] = stats["subject_counts"].get(subj, 0) + 1
                
                # 新增统计：各题型分布
                q_type = row.get("题型", "未知")
                stats["type_counts"][q_type] = stats["type_counts"].get(q_type, 0) + 1
                
                # 新增统计：平均难度与分布
                diff_str = row.get("难度星级", "")
                if diff_str and diff_str.replace('.', '', 1).isdigit():
                    diff_val = float(diff_str)
                    stats["total_difficulty"] += diff_val
                    stats["difficulty_count"] += 1
                    
                    # 划分难度区间
                    if diff_val <= 2.0:
                        diff_label = "0-2星 (基础)"
                    elif diff_val <= 4.0:
                        diff_label = "3-4星 (中档)"
                    else:
                        diff_label = "5-6星 (压轴)"
                    stats["difficulty_dist"][diff_label] = stats["difficulty_dist"].get(diff_label, 0) + 1
                    
                # 新增统计：标签词云数据
                tags = row.get("标签", "")
                if tags:
                    for tag in tags.split("，"):
                        tag = tag.strip()
                        if tag:
                            stats["tag_counts"][tag] = stats["tag_counts"].get(tag, 0) + 1
                            
            return stats
    except Exception as e:
        # 如果 CSV 读取失败，回退到遍历文件夹的旧逻辑
        pass

    # ================= 降级：文件夹遍历统计 =================
    today_start = datetime.datetime.combine(datetime.date.today(), datetime.time.min).timestamp()
    
    if not os.path.exists(CHAPTERS_DIR):
        return stats
        
    for root, dirs, files in os.walk(CHAPTERS_DIR):
        is_tikz_dir = "相关图" in root
        
        for file in files:
            if not file.endswith(".tex"):
                continue
            if file.startswith("content_"):
                continue
                
            file_path = os.path.join(root, file)
            try:
                stat_info = os.stat(file_path)
                ctime = stat_info.st_ctime
                mtime = stat_info.st_mtime
                
                # 修改点：不再仅依赖文件的创建时间，而是统计每天所有题目的最后修改时间
                # 作为活跃度的依据（或者是创建时间也可以，这里我们把最后修改时间也算进去）
                c_date = datetime.datetime.fromtimestamp(ctime).date().isoformat()
                m_date = datetime.datetime.fromtimestamp(mtime).date().isoformat()
                
                c_hour = datetime.datetime.fromtimestamp(ctime).strftime('%H')
                m_hour = datetime.datetime.fromtimestamp(mtime).strftime('%H')
                
                if c_date not in stats["hourly_activity_by_day"]:
                    stats["hourly_activity_by_day"][c_date] = {str(i).zfill(2): 0 for i in range(24)}
                stats["hourly_activity_by_day"][c_date][c_hour] += 1
                
                if m_hour != c_hour or m_date != c_date:
                    if m_date not in stats["hourly_activity_by_day"]:
                        stats["hourly_activity_by_day"][m_date] = {str(i).zfill(2): 0 for i in range(24)}
                    stats["hourly_activity_by_day"][m_date][m_hour] += 1
                
                is_today_created = ctime >= today_start
                is_today_modified = mtime >= today_start and not is_today_created
                
                # 新增逻辑：无论是新创建还是修改，都记录到热力图的活跃度中
                if not is_tikz_dir and " 图" not in file:
                    stats["daily_activity"][c_date] = stats["daily_activity"].get(c_date, 0) + 1
                    if m_date != c_date:
                        stats["daily_activity"][m_date] = stats["daily_activity"].get(m_date, 0) + 1
                        
                if is_tikz_dir or " 图" in file:
                    stats["total_tikz"] += 1
                    if is_today_created:
                        stats["today_new_tikz"] += 1
                    elif is_today_modified:
                        stats["today_mod_tikz"] += 1
                else:
                    stats["total_questions"] += 1
                    if is_today_created:
                        stats["today_new_questions"] += 1
                    elif is_today_modified:
                        stats["today_mod_questions"] += 1
                    
            except Exception:
                pass
                
    return stats

def render_statistics_dashboard():
    from utils.charts import generate_heatmap_html, generate_activity_curve_html, generate_echarts_bar_html, generate_echarts_pie_html
    stats = get_statistics()
    
    st.markdown("### 📊 数据统计")
    
    # 统计页视觉层：只调整展示质感，不改统计数据。
    st.markdown("""
    <style>
    @keyframes statsFadeUp {
        from {
            opacity: 0;
            transform: translateY(8px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    div[data-testid="stMetric"],
    .stats-chart-title {
        animation: statsFadeUp 0.38s ease both;
    }
    div[data-testid="stMetric"] {
        position: relative;
        min-height: 112px;
        background:
            linear-gradient(180deg, rgba(255,255,255,0.86), rgba(255,255,255,0.68)),
            rgba(255,255,255,0.72);
        border: 1px solid rgba(109, 40, 217, 0.10);
        padding: 14px 18px 14px 20px;
        border-radius: 10px;
        box-shadow: 0 8px 24px rgba(31, 35, 48, 0.055);
        display: flex;
        flex-direction: column;
        justify-content: center;
        overflow: hidden;
        transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease, background 0.16s ease;
    }
    div[data-testid="stMetric"]::before {
        content: "";
        position: absolute;
        left: 0;
        top: 14px;
        bottom: 14px;
        width: 3px;
        border-radius: 0 999px 999px 0;
        background: linear-gradient(180deg, #a78bfa, #007aff);
        opacity: 0.82;
    }
    div[data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        border-color: rgba(109, 40, 217, 0.18);
        box-shadow: 0 14px 34px rgba(31, 35, 48, 0.09);
        background: rgba(255,255,255,0.9);
    }
    div[data-testid="stMetric"] label,
    div[data-testid="stMetric"] [data-testid="stMetricLabel"] {
        color: #5f6472 !important;
        font-size: 0.9rem !important;
        font-weight: 650 !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: #242733 !important;
        font-weight: 680 !important;
        letter-spacing: 0 !important;
    }
    .stats-chart-title {
        margin: 20px 0 10px 4px;
        color: #20232d;
        font-size: 1.05rem;
        font-weight: 720;
        letter-spacing: 0;
    }
    div[data-testid="stVerticalBlock"]:has(.stats-chart-title) iframe {
        border-radius: 12px !important;
        box-shadow: 0 10px 30px rgba(31, 35, 48, 0.065) !important;
        transition: transform 0.16s ease, box-shadow 0.16s ease, filter 0.16s ease;
    }
    div[data-testid="stVerticalBlock"]:has(.stats-chart-title) iframe:hover {
        transform: translateY(-2px);
        box-shadow: 0 16px 40px rgba(31, 35, 48, 0.10) !important;
        filter: saturate(1.03);
    }
    </style>
    """, unsafe_allow_html=True)
    
    # 计算平均难度
    avg_diff = 0.0
    if stats.get("difficulty_count", 0) > 0:
        avg_diff = stats["total_difficulty"] / stats["difficulty_count"]
    
    # 指标数据 - 恢复8个卡片两行排列
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("题库总题目数", stats["total_questions"])
    c2.metric("题库Tikz总数", stats["total_tikz"])
    c3.metric("今日新增题目", stats["today_new_questions"])
    c4.metric("今日改动题目", stats["today_mod_questions"])
    
    st.write("")
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("今日新增Tikz", stats["today_new_tikz"])
    c6.metric("今日改动Tikz", stats["today_mod_tikz"])
    c7.metric("平均难度星级", f"{avg_diff:.1f} ★" if avg_diff > 0 else "N/A")
    
    # 获取最高频的三个标签
    top_tags = sorted(stats.get("tag_counts", {}).items(), key=lambda x: x[1], reverse=True)[:3]
    top_tags_str = "、".join([t[0] for t in top_tags]) if top_tags else "暂无"
    c8.metric("热门标签", top_tags_str)
    
    st.write("")
    
    # 热力图与代码活跃时段曲线
    r2_c1, r2_c2 = st.columns([1, 1])
    with r2_c1:
        heatmap_html = generate_heatmap_html(stats["daily_activity"])
        st.markdown(heatmap_html, unsafe_allow_html=True)
    
    with r2_c2:
        import streamlit.components.v1 as components
        hourly_activity_by_day = stats.get("hourly_activity_by_day", {})
        components.html(generate_activity_curve_html(hourly_activity_by_day), height=300)

    st.write("")
    
    # 更多有趣的数据统计：图表区
    r3_c1, r3_c2 = st.columns([1, 1])
    with r3_c1:
        st.markdown('<div class="stats-chart-title">📈 各知识板块题目分布</div>', unsafe_allow_html=True)
        subj_counts = stats.get("subject_counts", {})
        components.html(generate_echarts_bar_html(subj_counts, "各知识板块题目分布"), height=370)
            
    with r3_c2:
        st.markdown('<div class="stats-chart-title">🍰 题型占比分布 & 难度分布</div>', unsafe_allow_html=True)
        type_counts = stats.get("type_counts", {})
        diff_counts = stats.get("difficulty_dist", {})
        components.html(generate_echarts_pie_html(type_counts, diff_counts, "题型与难度分布"), height=370)


# ================= 页面：规范说明 =================
def page_manual():
    st.header("📖 题库规范说明")
    st.markdown("""
    **📂 一、 文件命名规范**
    
    所有题目的 `.tex` 文件必须严格按照以下 **“五段式”** 结构命名，各部分之间使用英文连字符 `-` 连接，格式为：
    `<font color="red">**年份-试卷类别-试卷名称-题号-知识板块.tex**</font>`
    *示例：`2024-G-新高考I卷-12-数列，集合.tex`*
    - **年份**：四位纯数字（如 `2024`）；
    - **试卷类别**：必须是系统预设的缩写代码，仅限 `G`(高考题)、`M`(模拟题)、`W`(外国题)、`XK`(学考题)、`XS`(线上联考)；
    - **试卷名称**：明确试卷全称，如 `新课标I卷`、`浙江学考` 等，尽量避免包含特殊符号；
    - **题号**：纯数字（如 `12`）；
    - **知识板块**：如涉及多个板块，必须用**中文全角逗号 `，`** 分隔，且将**最核心的主板块放在最前**（如 `函数，导数`）。

    **📝 二、 LaTeX 源码书写格式**
    
    每个题目文件内部必须且仅包含一个完整的 `problem` 环境：
    ```latex
    \\begin{problem}{年份}{试卷类别}{试卷名称}{题号}{知识板块}
    这里是具体的题目题干内容...
    \\end{problem}
    ```
    如果题目附带详细解析，请使用 `\\begin{answer}` 和 `\\begin{solutions}` 环境：
    ```latex
    \\begin{answer}
    这里是答案...
    \\end{answer}
    
    \\begin{solutions}
    这里是解析...
    \\end{solutions}
    ```
    
    **💡 三、 附加规范**
    - **选择题**：请使用 `\\begin{choices}` 与 `\\choice{{选项内容}}` 宏包结构，务必确保选项内容被**两层大括号**包裹。
    - **TikZ 绘图**：直接在题干中插入 `\\begin{tikzpicture}...\\end{tikzpicture}` 代码，系统会自动提取。
    """, unsafe_allow_html=True)

def page_system_intro():
    st.header("📘 工程体系介绍（录入 · 浏览 · 标签 · 组卷）")
    st.markdown("""
### 🎯 这套系统解决什么问题？

这是一套面向高中数学的题库工程化管理系统：以 `.tex` 为数据单元，把“题目内容、标签元数据、索引检索、批量维护、组卷导出”统一在一个可视化工作流里，做到：

- 🧱 题目文件结构规范、可长期维护
- 🔎 检索与定位迅速（多维筛选/全文查找/三级查找）
- 🏷️ 标签与元数据可视化修改（并自动同步文件名/索引）
- 🖨️ 支持按模板组卷导出
- 🧠 可选的 AI 辅助：图片转写、标签提取、解答生成

---

### 🗂️ 1) 数据与目录结构（“文件即数据库”）

**核心原则：`.tex` 文件是单一事实来源（Source of Truth）。**

- 每道题对应一个 `.tex` 文件
- 物理归档采用 “知识板块/年份/文件.tex” 的层级组织
- 题内的标签与元数据会被写入专用的 Label Data 注释块，确保题目“自描述”

---

### 🧾 2) 文件命名规则（五段式，强约束）

文件名必须严格使用：

`年份-试卷类别-试卷名称-题号-知识板块.tex`

示例：`2024-G-上海卷-12-数列，集合.tex`

- 📅 年份：四位数字（如 `2024`）
- 🧩 试卷类别：系统预设代码（如 `G/M/W/XK/XS`）
- 🧾 试卷名称：建议使用普通文字，避免特殊符号
- 🔢 题号：纯数字（如 `12`）
- 🧠 知识板块：多标签用中文全角逗号 `，` 分隔；**首个为主板块**（决定题目归档目录）

---

### ✍️ 3) LaTeX 内容结构（题干、答案、解析）

每个文件内部必须且仅包含一个 `problem` 环境，且 5 个参数与文件名五段信息一致：

```latex
\\begin{problem}{年份}{试卷类别}{试卷名称}{题号}{知识板块}
题干内容...
\\end{problem}
```

如果有答案与解析（推荐），放在 `\\end{problem}` 之后：

```latex
\\begin{answer}
最终答案
\\end{answer}

\\begin{solutions}
解析步骤...
\\end{solutions}
```

补充约定：

- 🧩 选择题：用 `choices/choice` 结构（选项内容必须双层大括号）
- 🧑‍🎨 TikZ：可直接写在题干内；系统会在保存/维护过程中自动处理相关图资源

---

### 🏷️ 4) ID / 难度 / 标签：Label Data 元数据机制

为了让题目文件可长期维护与可追溯，系统把元数据写在题目文件内部的注释块中：

- 🆔 ID：每题唯一标识（用于跨文件移动/重命名时保持引用稳定）
- ⭐ 难度星级：0–6（支持 0.5 步长）
- 🏷️ 标签：自定义标签（与知识板块不同，偏“属性标签”）
- 📝 备注：人工补充说明
- 📌 组卷引用次数：用于统计与推荐

这些字段存储在题目文件里的 `% === Begin Label Data === ... % === End Label Data ===` 区块中。

---

### ⚡ 5) CSV 索引：加速检索的缓存层

系统会维护一个 `utils/题库索引表.csv` 作为“高速缓存索引”来提升检索速度：

- 🔁 索引可通过扫描全库重新生成（以 `.tex` 为准）
- ✅ 即便 CSV 丢失，也能依靠 `.tex` 里的 Label Data 重新构建
- 🚀 浏览、三级查找、统计面板优先读取 CSV，避免每次全量扫描 `.tex`
- 🧯 CSV 写入前会做基础校验，降低重复 ID、关键字段缺失导致索引损坏的风险

（对应脚本：`utils/init_csv_index.py`）

---

### 🧱 6) 工程模块分工（给开源读者的快速地图）

如果你是第一次阅读这个项目，可以按下面的层次理解代码：

- `question_bank_app.py`：主应用入口，负责 Streamlit 页面、交互状态、业务流程串联
- `utils/core_config.py`：全局路径、试卷类型、知识板块等基础配置
- `utils/csv_ops.py`：题库索引的读取、写入、增量更新与字段解析
- `utils/latex_ops.py`：LaTeX 题目结构处理、TikZ 提取、题目重命名与保存辅助
- `utils/tikz_ops.py`：TikZ 编译、缓存与预览渲染
- `utils/charts.py`：数据统计页面的图表渲染
- `services/file_service.py`：原子写入、覆盖备份等文件安全能力
- `services/ai_service.py`：AI 接口地址规范化、请求封装与 JSON 提取
- `Test Paper Group/主题模板/`：组卷导出的 LaTeX 模板来源

整体设计思路是：主应用负责“把流程跑通”，工具层负责“把单个动作做稳”，题目数据始终落回 `.tex` 文件。

---

### 🛡️ 7) 稳定性与数据安全设计

题库项目的核心风险不是页面显示，而是“误覆盖、索引错乱、题目 ID 重复、批量操作难回退”。因此系统内部做了几层保护：

- `.tex` 是最终可信数据源，CSV 只是可重建的高速索引
- 覆盖保存时使用原子写入，避免写到一半导致文件损坏
- 修改既有题目或批量处理时，会尽量在 `.backups/` 中保留覆盖前副本
- CSV 写入前会检查关键字段与重复 ID，发现异常时阻止写入
- 搜索缓存会跟随 CSV 文件变化自动失效，减少“刚保存但搜索不到”的情况

如果出现搜索结果异常、统计不准确、题目移动后找不到，优先执行“批量工具”中的一键重建/同步题库索引。

---

### 🧭 8) 日常使用工作流（给协作者的最短路径）

**📝 录入新题**

- 支持单题/批量/同卷录入
- 单题录入支持实时预览、查找替换、AI 自动打标签
- 可选 “本次录入同时生成解答”，并可选 “快速模式”

**🔍 全局浏览与编辑**

- 面向“找题 + 改题”的主工作台
- 支持预览、源码编辑保存、AI 生成解答、加入/移除组卷
- 在标签修改面板中可改年份/试卷类别/试卷名/题号/知识板块，并自动同步文件名与索引

**🔎 三级查找**

- 面向“多条件精确过滤”的检索入口
- 适合做专题筛选、交叉检索与快速定位

**🛠️ 批量工具**

- 面向“全库/批量维护”的工具集合
- 适合做批量规范化、批量修复、批量结构调整等任务

**🖨️ 组卷服务**

- 以模板为核心的排版与导出流程
- 读取 `Test Paper Group/主题模板/` 下的主题模板，并在导出目录生成成品

---

### 🧩 9) 推荐的维护习惯

为了让题库长期可维护，建议按下面的方式协作：

- 新题录入后先检查预览，再补充难度、标签、备注
- 不手动复制已有题目的 ID；ID 应保持唯一
- 不直接把 CSV 当主数据库编辑；需要修复时优先重建索引
- 批量改名、批量修复前，先确认目标范围
- 导出文件、LaTeX 编译产物、临时缓存不应作为题库核心数据维护
- 修改规则类代码后，至少检查一次录入、搜索、标签修改和组卷导出主流程

---

### 🔭 10) 适合二次开发的方向

这个项目的后续扩展可以围绕“题库质量”和“教研效率”展开：

- 更细的标签体系：考点、方法、易错点、能力层级
- 更稳定的批量导入校验：录入前预检文件名、题号、ID、题型
- 更智能的组卷策略：按难度、知识点覆盖率、近年频次进行约束
- 更清晰的题目版本记录：记录每道题的修改历史与来源变化
- 更完整的本地部署方案：后续可再考虑封装为桌面应用或 exe

""", unsafe_allow_html=False)


# ================= 页面：三级查找 =================
# ================= 页面：三级查找嵌入组件 =================
def render_advanced_search_inline():
    st.markdown("""
    <style>
    /* 隐藏多余的 Markdown 占位符防止把高度撑开 */
    div[data-testid="stMarkdownContainer"]:has(#adv-search-inputs-anchor),
    div[data-testid="stMarkdownContainer"]:has(#adv-search-btn-anchor) {
        display: none !important;
        margin: 0 !important;
        padding: 0 !important;
        height: 0 !important;
    }
    
    /* 去除列之间的默认间距，防止按钮被挤下来 */
    div[data-testid="column"]:has(#adv-search-btn-anchor) {
        display: flex !important;
        align-items: flex-start !important; /* 顶部对齐 */
        justify-content: center !important;
        height: 100% !important;
        margin-top: 0 !important;
        padding-top: 0 !important;
    }
    div[data-testid="column"]:has(#adv-search-btn-anchor) > div[data-testid="stVerticalBlock"] {
        height: 100% !important;
        width: 100% !important;
        display: flex !important;
        justify-content: flex-start !important;
        gap: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    div[data-testid="column"]:has(#adv-search-btn-anchor) button {
        height: 152px !important; /* 精确计算：3行输入框(40px*3) + 2行间隙(16px*2) = 152px */
        min-height: 152px !important;
        max-height: 152px !important;
        width: 100% !important;
        padding: 0 !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: center !important;
        justify-content: center !important;
        border-radius: 8px !important;
        margin: 0px !important;
        background-color: #ffffff !important; /* 白色底色 */
        border: 1px solid #d0d7de !important; /* 浅灰色边框 */
        color: #24292e !important; /* 深灰色文字 */
        box-shadow: 0 1px 3px rgba(0,0,0,0.04) !important;
    }
    div[data-testid="column"]:has(#adv-search-btn-anchor) button:hover {
        background-color: #f3f4f6 !important;
        border-color: #4c1d95 !important;
    }
    div[data-testid="column"]:has(#adv-search-btn-anchor) button p {
        writing-mode: horizontal-tb !important; /* 恢复水平书写模式 */
        text-orientation: mixed !important;
        letter-spacing: 2px !important;
        line-height: 1.8 !important; /* 调整行高让三行字间距更合理 */
        margin: 0 !important;
        font-size: 16px !important;
        font-weight: bold !important;
        white-space: pre-wrap !important; /* 强制保留换行符 */
        word-break: break-word !important;
        text-align: center !important;
        display: block !important;
    }
    
    /* 彻底消除左侧输入框列的顶部间距 */
    div[data-testid="column"]:has(#adv-search-inputs-anchor) {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    def on_adv_search():
        if not _adv_search_has_query():
            st.session_state["adv_search_active"] = False
            st.toast("请输入至少一个关键词后再开始查找。", icon="⚠️")
            return
        st.session_state["adv_search_active"] = True

    search_opts = ["全文内容", "题目类型", "题目内容", "解答内容", "难度星级", "标签"]
    
    col_inputs, col_btn, col_info = st.columns([2.5, 0.3, 2.3])
    
    with col_inputs:
        st.markdown('<div id="adv-search-inputs-anchor"></div>', unsafe_allow_html=True)
        c1a, c1b = st.columns([1, 2])
        with c1a: 
            t1 = st.selectbox("一级类型", search_opts, index=0, key="adv_t1", label_visibility="collapsed")
        with c1b: 
            if t1 == "题目类型":
                q1 = st.selectbox("一级关键词", ["选择题", "填空题", "解答题"], key="adv_q1_sel", label_visibility="collapsed", on_change=on_adv_search)
            else:
                q1 = st.text_input("一级关键词", placeholder="输入一级关键词...", key="adv_q1", label_visibility="collapsed", on_change=on_adv_search)
                
        c2a, c2b = st.columns([1, 2])
        with c2a: 
            t2 = st.selectbox("二级类型", search_opts, index=0, key="adv_t2", label_visibility="collapsed")
        with c2b: 
            if t2 == "题目类型":
                q2 = st.selectbox("二级关键词", ["选择题", "填空题", "解答题"], key="adv_q2_sel", label_visibility="collapsed", on_change=on_adv_search)
            else:
                q2 = st.text_input("二级关键词", placeholder="输入二级关键词...", key="adv_q2", label_visibility="collapsed", on_change=on_adv_search)
                
        c3a, c3b = st.columns([1, 2])
        with c3a: 
            t3 = st.selectbox("三级类型", search_opts, index=0, key="adv_t3", label_visibility="collapsed")
        with c3b: 
            if t3 == "题目类型":
                q3 = st.selectbox("三级关键词", ["选择题", "填空题", "解答题"], key="adv_q3_sel", label_visibility="collapsed", on_change=on_adv_search)
            else:
                q3 = st.text_input("三级关键词", placeholder="输入三级关键词...", key="adv_q3", label_visibility="collapsed", on_change=on_adv_search)
    
    with col_btn:
        st.markdown('<div id="adv-search-btn-anchor"></div>', unsafe_allow_html=True)
        st.button("🔎  \n开 始  \n查 找", use_container_width=True, type="secondary", on_click=on_adv_search)

    with col_info:
        q1 = st.session_state.get("adv_q1_sel" if t1 == "题目类型" else "adv_q1", "")
        q2 = st.session_state.get("adv_q2_sel" if t2 == "题目类型" else "adv_q2", "")
        q3 = st.session_state.get("adv_q3_sel" if t3 == "题目类型" else "adv_q3", "")
        
        if not (st.session_state.get("adv_search_active") and (q1 or q2 or q3)):
            st.info("👈 请在左侧输入查找条件，点击“开始查找”或回车即可在下方显示结果。")
            return
        
        # 动态生成搜索信息提示
        search_info = []
        if q1: search_info.append(f"{t1}: `{q1}`")
        if q2: search_info.append(f"{t2}: `{q2}`")
        if q3: search_info.append(f"{t3}: `{q3}`")
        search_str = " | ".join(search_info)
        st.markdown(f"**检索条件**: {search_str}")
        if st.button("❌ 退出搜索状态"):
            st.session_state["adv_search_active"] = False
            st.rerun()

def render_advanced_search_results():
    st.markdown("### 🎯 查找结果")
    
    t1 = st.session_state.get("adv_t1", "全文内容")
    t2 = st.session_state.get("adv_t2", "全文内容")
    t3 = st.session_state.get("adv_t3", "全文内容")
    
    q1 = st.session_state.get("adv_q1_sel" if t1 == "题目类型" else "adv_q1", "")
    q2 = st.session_state.get("adv_q2_sel" if t2 == "题目类型" else "adv_q2", "")
    q3 = st.session_state.get("adv_q3_sel" if t3 == "题目类型" else "adv_q3", "")
    
    def _row_match(item, s_type, s_query):
        s_query = (s_query or "").strip()
        if not s_query:
            return True
        if s_type == "题目类型":
            return s_query == item["type"]
        if s_type == "题目内容":
            return s_query in item["stem"]
        if s_type == "解答内容":
            return s_query in item["solution"]
        if s_type == "难度星级":
            return s_query in item["difficulty"]
        if s_type == "标签":
            return s_query in item["tags"]
        if s_type == "备注":
            return s_query in item["remark"]
        if s_type == "全文内容":
            return s_query in item["full_text"]
        return False

    query_key = (t1, q1, t2, q2, t3, q3)
    if st.session_state.get("adv_last_query") == query_key and st.session_state.get("adv_last_results") is not None:
        results = st.session_state.get("adv_last_results") or []
    else:
        search_rows = _advanced_search_index_cached(_csv_index_cache_token())

        results = []
        with st.spinner("正在全库检索中..."):
            for item in search_rows:
                if q1 and not _row_match(item, t1, q1): 
                    continue
                if q2 and not _row_match(item, t2, q2): 
                    continue
                if q3 and not _row_match(item, t3, q3): 
                    continue
                fpath = item["path"]
                if not fpath or not os.path.exists(fpath):
                    continue
                results.append({"file": item["file"] or os.path.basename(fpath), "path": fpath})

        st.session_state["adv_last_query"] = query_key
        st.session_state["adv_last_results"] = results
    
    if results:
        st.success(f"找到 {len(results)} 个匹配题目")

        page_size = st.selectbox("每页显示", options=[10, 20, 30, 50], index=2, key="adv_results_page_size")
        total_pages = (len(results) + page_size - 1) // page_size
        page = st.number_input("页码", min_value=1, max_value=max(1, total_pages), value=1, step=1, key="adv_results_page")

        start = (page - 1) * page_size
        end = min(len(results), start + page_size)
        st.caption(f"当前显示：第 {start + 1}–{end} 条 / 共 {len(results)} 条")

        for i, res in enumerate(results[start:end], start=start):
            fpath = res["path"]
            fname = res["file"]
        
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
                
            q_label = format_question_title(fname)

            render_question_header(q_label, content, fpath)
            
            c1, c2 = st.columns([1, 1])
            with c1:
                fpath_hash = hashlib.md5(fpath.encode()).hexdigest()
                edit_mode_key = f"adv_edit_mode_{fpath_hash}"
                tag_edit_key = f"adv_tag_edit_mode_{fpath_hash}"
                is_editing = st.session_state.get(edit_mode_key, False)
                est_height = get_editor_height(content)

                if is_editing:
                    text_area_key = f"adv_search_edit_{fpath_hash}"
                    st.text_area("源码", value=content, height=est_height, key=text_area_key)
                    st.button("💾 保存修改", key=f"adv_search_save_{fpath_hash}", type="primary", on_click=_save_tex_from_widget, args=(fpath, text_area_key, edit_mode_key, f"{q_label} 已保存"))
                else:
                    mtime_token = int(os.path.getmtime(fpath)) if os.path.exists(fpath) else 0
                    st.text_area("源码", value=content, height=est_height, disabled=True, key=f"adv_search_readonly_{fpath_hash}_{mtime_token}")
                    is_tag_editing = st.session_state.get(tag_edit_key, False)

                    b1, b2, b3 = st.columns(3)
                    with b1:
                        if st.button("✏️ 开始修改tex内容", key=f"adv_search_start_{fpath_hash}", use_container_width=True):
                            st.session_state[f"adv_search_edit_{fpath_hash}"] = content
                            st.session_state[edit_mode_key] = True
                            st.rerun()
                    with b2:
                        if is_tag_editing:
                            if st.button("✅ 完成修改题目信息", key=f"adv_tag_save_{fpath_hash}", type="primary", use_container_width=True):
                                base = os.path.basename(fpath).replace(".tex", "")
                                parts = base.split("-")
                                if len(parts) >= 5:
                                    old_year, old_ptype, old_pname, old_pnum, old_subj = parts[0], parts[1], parts[2], parts[3], parts[4]
                                    new_year = st.session_state.get(f"adv_meta_year_{fpath_hash}", old_year)
                                    new_type = st.session_state.get(f"adv_meta_type_{fpath_hash}", old_ptype)
                                    new_name = st.session_state.get(f"adv_meta_paper_{fpath_hash}", old_pname)
                                    new_num = st.session_state.get(f"adv_meta_num_{fpath_hash}", old_pnum)
                                    new_subjects = st.session_state.get(f"adv_tag_select_{fpath_hash}", [old_subj])
                                    new_subject_str = "，".join(new_subjects) if isinstance(new_subjects, list) else str(new_subjects or old_subj)
                                    try:
                                        apply_meta_rename_and_update(fpath, str(new_year), str(new_type), str(new_name), str(new_num), new_subject_str)
                                        st.toast("修改成功！", icon="✅")
                                        st.session_state[tag_edit_key] = False
                                        time.sleep(0.5)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"修改失败: {e}")
                                else:
                                    st.error("文件名格式不支持修改")
                        else:
                            if st.button("🏷️ 开始修改题目信息", key=f"adv_tag_start_{fpath_hash}", use_container_width=True):
                                st.session_state[tag_edit_key] = True
                                st.rerun()
                    with b3:
                        render_ai_solution_generate_button(fpath, content, key_prefix="ai_solution_v1", use_container_width=True)
                    render_ai_solution_image_ocr_section(fpath, key_prefix="ai_solution_v1")

                    if is_tag_editing:
                        base = os.path.basename(fpath).replace(".tex", "")
                        parts = base.split("-")
                        cur_year = parts[0] if len(parts) >= 5 else ""
                        cur_type = parts[1] if len(parts) >= 5 else "G"
                        cur_paper = parts[2] if len(parts) >= 5 else ""
                        cur_num = parts[3] if len(parts) >= 5 else ""
                        cur_subjects = (parts[4] if len(parts) >= 5 else "").split("，")
                        valid_tags = [t for t in cur_subjects if t in SUBJECTS] or [SUBJECTS[0]]
                        type_opts = list(PAPER_TYPES.keys())
                        c_meta1, c_meta2 = st.columns([1, 1])
                        with c_meta1:
                            st.text_input("年份", value=str(cur_year), key=f"adv_meta_year_{fpath_hash}")
                        with c_meta2:
                            if cur_type not in type_opts:
                                cur_type = "G"
                            st.selectbox("试卷类别", options=type_opts, index=type_opts.index(cur_type), format_func=lambda x: f"{x} ({PAPER_TYPES[x]})", key=f"adv_meta_type_{fpath_hash}")
                        st.text_input("试卷名称", value=str(cur_paper), key=f"adv_meta_paper_{fpath_hash}")
                        st.text_input("题号", value=str(cur_num), key=f"adv_meta_num_{fpath_hash}")
                        st.multiselect("知识板块 (首个为主)", options=SUBJECTS, default=valid_tags, key=f"adv_tag_select_{fpath_hash}")
            with c2:
                try:
                    st.markdown(latex_to_markdown(content, show_title=False), unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"渲染错误: {e}")

            render_ai_solution_panel(fpath, q_label, key_prefix="ai_solution_v1")
            st.divider()
    else:
        st.warning("未找到匹配的题目。")

def page_advanced_search():
    c_left, c_right = st.columns([1, 1.5])
    with c_left:
        st.header("🔎 三级查找")
        t1, t2, t3 = st.columns(3)
        with t1:
            st.markdown("**一级提示**\n\n先选检索字段\n\n再填关键词")
        with t2:
            st.markdown("**二级提示**\n\n可留空\n\n可继续细化")
        with t3:
            st.markdown("**三级提示**\n\n可留空\n\n可进一步过滤")
    with c_right:
        render_advanced_search_inline()
    st.markdown('<hr style="border-top: 1px solid #e1e4e8; margin-top: 10px; margin-bottom: 20px;">', unsafe_allow_html=True)
    if st.session_state.get("adv_search_active") and _adv_search_has_query():
        render_advanced_search_results()

# ================= 主程序 =================
def main():
    st.set_page_config(page_title="高中数学题库管理系统", layout="wide", initial_sidebar_state="expanded")
    
    inject_custom_css()
    
    # 注入侧边栏的自定义 CSS (SolEdu 深色极简风格)
    st.markdown("""
        <style>
        /* 隐藏默认顶部的 padding */
        .block-container {
            padding-top: 2rem !important;
        }
        
        /* ================= 侧边栏重构 (SolEdu / 暗紫色居中极简风格) ================= */
        /* 侧边栏整体背景 - 暗紫色主题 */
        [data-testid="stSidebar"] {
            background-color: #ede9fe !important;
            min-width: 110px !important;
            max-width: 110px !important;
        }

        /* 调整内部边距，让内容完全居中 */
        [data-testid="stSidebarUserContent"] {
            padding: 2rem 0rem !important;
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: flex-start !important;
        }
        
        /* 隐藏侧边栏默认组件的 Resizer，保留 Collapse 按钮并变白 */
        [data-testid="stSidebarResizer"] {
            display: none !important;
        }
        /* 强力覆盖折叠按钮颜色 */
        [data-testid="stSidebarCollapseButton"],
        [data-testid="stSidebarCollapseButton"]:hover {
            color: #5b21b6 !important;
        }
        [data-testid="stSidebarCollapseButton"] svg,
        [data-testid="stSidebarCollapseButton"] svg path,
        [data-testid="stSidebar"] button svg,
        [data-testid="stSidebar"] button svg path,
        [data-testid="collapsedControl"] svg,
        [data-testid="collapsedControl"] svg path {
            fill: #5b21b6 !important;
            color: #5b21b6 !important;
            stroke: #5b21b6 !important;
        }
        
        /* Logo 样式：白色居中 */
        .sol-logo {
            color: #5b21b6;
            font-size: 18px;
            font-weight: 800;
            text-align: center;
            margin-top: 0px;
            margin-bottom: 35px;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            letter-spacing: -0.5px;
            line-height: 1.2;
            word-wrap: break-word;
            width: 100%;
        }
        .sol-logo span {
            color: #c084fc;
        }
        
        /* 隐藏 Radio 默认的圆形按钮 */
        [data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-child {
            display: none !important;
        }

        /* 强力清除所有隐藏边距，解决文字整体偏右问题 */
        [data-testid="stSidebar"] div[role="radiogroup"] label,
        [data-testid="stSidebar"] div[role="radiogroup"] label * {
            margin-left: 0 !important;
            margin-right: 0 !important;
            padding-left: 0 !important;
            padding-right: 0 !important;
            width: 100% !important;
            box-sizing: border-box !important;
        }

        /* 强制覆盖文本容器的默认边距，实现完美居中 */
        [data-testid="stSidebar"] div[role="radiogroup"] > label > div:nth-child(2) {
            display: flex !important;
            flex-direction: column !important;
            justify-content: center !important;
            align-items: center !important;
        }
        
        /* Radio 容器间距 - 确保内容居中 */
        [data-testid="stSidebar"] div[role="radiogroup"] {
            gap: 16px !important;
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: center !important;
        }
        /* 强制把 stRadio 组件本体也居中，避免整体看起来偏移 */
        [data-testid="stSidebar"] div[data-testid="stRadio"] > div {
            display: flex !important;
            justify-content: center !important;
            padding: 0 !important;
        }

        /* Radio 项 (上下结构，图标居上文字居下) */
        [data-testid="stSidebar"] div[role="radiogroup"] > label {
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: center !important;
            padding-top: 12px !important;
            padding-bottom: 12px !important;
            margin: 0 auto !important;
            max-width: 90px !important; /* 固定宽度，居中 */
            border-radius: 12px !important;
            background-color: transparent !important;
            color: #5b21b6 !important;
            transition: all 0.2s ease !important;
            cursor: pointer !important;
        }

        /* 悬停状态：亮紫色 */
        [data-testid="stSidebar"] div[role="radiogroup"] > label:hover {
            background-color: rgba(109, 40, 217, 0.16) !important;
            color: #4c1d95 !important;
        }

        [data-testid="stSidebar"] div[role="radiogroup"] > label:hover p,
        [data-testid="stSidebar"] div[role="radiogroup"] > label:hover span {
            color: #4c1d95 !important;
        }

        [data-testid="stSidebar"] div[role="radiogroup"] > label:hover svg,
        [data-testid="stSidebar"] div[role="radiogroup"] > label:hover svg path {
            fill: #4c1d95 !important;
            color: #4c1d95 !important;
            stroke: #4c1d95 !important;
        }

        /* 选中状态：深紫色高亮 */
        [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {
            background-color: #6d28d9 !important;
            color: #ffffff !important;
            border-radius: 8px !important;
            box-shadow: 0 10px 22px rgba(109, 40, 217, 0.22) !important;
        }

        [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) p,
        [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) span {
            color: #ffffff !important;
        }

        [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) svg,
        [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) svg path {
            fill: #ffffff !important;
            color: #ffffff !important;
            stroke: #ffffff !important;
        }

        /* 图标与文字的排版 */
        [data-testid="stSidebar"] div[role="radiogroup"] p {
            font-size: 14px !important;
            font-weight: 800 !important;
            text-align: center !important;
            margin: 0 !important;
            padding: 0 !important;
            line-height: 1.6 !important;
            white-space: pre-wrap !important;
            width: 100% !important;
            color: #5b21b6 !important;
        }

        /* 针对 Streamlit 在亮色模式下覆盖 label 颜色的特殊处理 */
        [data-testid="stSidebar"] div[role="radiogroup"] p,
        [data-testid="stSidebar"] div[role="radiogroup"] span {
            color: #5b21b6 !important;
        }
        </style>
    """, unsafe_allow_html=True)
    
    # --- 最左侧：全局导航 (SolEdu / 居中极简风格) ---
    with st.sidebar:
        logo_img_path = os.path.join(BASE_DIR, "fig", "MathCyclus_logo.png")
        if os.path.exists(logo_img_path):
            st.image(logo_img_path, width=96)
        # 使用 <br> 让 MathCyclus 分成两行，避免挤出边框
        st.markdown('<div class="sol-logo" style="margin-bottom:0; padding-bottom: 10px;">Math<br><span>Cyclus</span></div>', unsafe_allow_html=True)
        if st.button("打开 MathCyclus 题库介绍", key="mathcyclus_demo_btn", help="打开 MathCyclus 题库介绍"):
            show_mathcyclus_intro()
            
        st.markdown("""
        <style>
        [data-testid="stSidebar"] div[data-testid="stImage"] {
            display: flex !important;
            justify-content: center !important;
            margin: 0 auto 4px auto !important;
        }
        [data-testid="stSidebar"] div[data-testid="stImage"] img {
            width: 96px !important;
            max-width: 96px !important;
            height: auto !important;
        }
        /* 覆盖在 Math / Cyclus 文字上的透明点击层 */
        [data-testid="stSidebar"] div.stButton:first-of-type {
            margin-top: -54px !important;
            margin-bottom: 6px !important;
            height: 48px !important;
            z-index: 10 !important;
        }
        [data-testid="stSidebar"] div.stButton:first-of-type button {
            opacity: 0 !important;
            height: 48px !important;
            cursor: pointer !important;
        }
        /* 隐藏侧边栏的规范说明菜单项 */
        [data-testid="stSidebar"] div[role="radiogroup"] label:nth-child(8) {
            display: none !important;
        }
        </style>
        """, unsafe_allow_html=True)
        
        # 恢复为上下结构的图标+文字
        nav_options = [
            "📊\n数据统计", 
            "📝\n录入新题", 
            "🔍\n全局浏览与编辑", 
            "🖨️\n组卷服务", 
            "🛠️\n批量工具",
            "🔎\n三级查找",
            "📘\n体系介绍",
            "📖\n规范说明"
        ]
        
        if "main_nav_selection" not in st.session_state:
            st.session_state["main_nav_selection"] = "📝\n录入新题"

        def _on_main_sidebar_nav_change():
            sel = st.session_state.get("main_sidebar_radio")
            if sel == "🔍\n全局浏览与编辑":
                st.session_state["adv_search_active"] = False
                st.session_state["browse_mode"] = "按知识板块浏览"
            elif sel != "🔎\n三级查找":
                st.session_state["adv_search_active"] = False
            
        selected_nav = st.radio("工作流导航", nav_options, label_visibility="collapsed", key="main_sidebar_radio", on_change=_on_main_sidebar_nav_change)
        st.session_state["main_nav_selection"] = selected_nav

    # --- 主内容区路由 ---
    if selected_nav == "📊\n数据统计":
        render_statistics_dashboard()
    elif selected_nav == "📝\n录入新题":
        page_entry()
    elif selected_nav == "🔍\n全局浏览与编辑":
        page_browse()
    elif selected_nav == "🖨️\n组卷服务":
        page_exam_paper_generation()
    elif selected_nav == "🛠️\n批量工具":
        page_tools()
    elif selected_nav == "🔎\n三级查找":
        page_advanced_search()
    elif selected_nav == "📘\n体系介绍":
        page_system_intro()
    elif selected_nav == "📖\n规范说明":
        page_manual()

if __name__ == "__main__":
    main()
