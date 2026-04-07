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

# 加载环境变量
load_dotenv()

from utils.core_config import *
from utils.file_ops import *
from utils.tikz_ops import *

import importlib
import utils.latex_ops
import utils.csv_ops
importlib.reload(utils.latex_ops)
importlib.reload(utils.csv_ops)
from utils.latex_ops import *
from utils.csv_ops import add_to_csv_index, update_csv_index_for_edit

# ================= 工具函数 =================
# 注入自定义 CSS
def inject_custom_css():
    st.markdown("""
        <style>
        /* 调整 st.dialog 的背景遮罩透明度为 40% 黑色 */
        div[data-testid="stDialog"] > div:first-child {
            background-color: rgba(0, 0, 0, 0.4) !important;
        }
        </style>
    """, unsafe_allow_html=True)

@st.dialog("🔍 查看大图", width="large")
def zoom_image(img):
    # 将图片转换为 Base64
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    
    # HTML/JS 缩放组件
    html_code = f"""
    <div style="width: 100%; height: 500px; overflow: hidden; position: relative; display: flex; justify-content: center; align-items: center; background: transparent;">
        <div id="img-container" style="transition: transform 0.1s; cursor: grab;">
            <img id="zoomed-img" src="data:image/png;base64,{img_str}" style="max-width: 100%; max-height: 100%; display: block;">
        </div>
        <div style="position: absolute; bottom: 20px; left: 50%; transform: translateX(-50%); background: rgba(0,0,0,0.6); padding: 8px 15px; border-radius: 20px; display: flex; gap: 15px; z-index: 100;">
            <button onclick="zoomOut()" style="background: transparent; border: none; color: white; font-size: 18px; cursor: pointer;">➖</button>
            <span id="zoom-level" style="color: white; font-family: sans-serif; min-width: 40px; text-align: center; line-height: 26px;">100%</span>
            <button onclick="zoomIn()" style="background: transparent; border: none; color: white; font-size: 18px; cursor: pointer;">➕</button>
            <button onclick="resetZoom()" style="background: transparent; border: none; color: white; font-size: 14px; cursor: pointer; margin-left: 5px;">🔄</button>
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
    components.html(html_code, height=520)

def format_content_for_frontend(content, filename, save_dir):
    """
    废弃。由于用户要求在前端直接显示并编辑原始的 \begin{tikzpicture}，
    不再进行任何替换。
    """
    return content

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
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(final_content)
        
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
            url = base_url.rstrip('/')
            
            # 如果 Base URL 是 http://host:port，通常需要加上 /v1/chat/completions
            # 如果 Base URL 是 http://host:port/v1，通常需要加上 /chat/completions
            # 简单的启发式判断：如果没有 /v1 且没有 /chat/completions，尝试加上 /v1
            if "/v1" not in url and "/chat/completions" not in url:
                url += "/v1"
            
            if "/chat/completions" not in url:
                url += "/chat/completions"
            
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

def process_ocr_result(ocr_result, mode):
    """处理识别结果并更新界面"""
    if "❌" in ocr_result:
        st.error(ocr_result)
    else:
        st.success("识别成功！")
        
        if mode == "单题录入":
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
                
                # 提取内容部分 (去掉 begin 和 end)
                content_body = ocr_result[match.end():]
                content_body = content_body.replace(r'\end{problem}', '').strip()
                
                # 标记这次内容更新来源于 AI 识别，避免在后续渲染时被本地启发式逻辑覆盖
                st.session_state["_ai_override_subjects"] = True
                
                st.session_state["entry_content"] = content_body
                st.rerun() 
            else:
                st.warning("识别内容未包含标准 problem 结构，已填入内容框供手动调整。")
                st.session_state["entry_content"] = ocr_result
                st.rerun()
                
        else: # 批量模式
            current_batch = st.session_state["batch_content"]
            if current_batch:
                st.session_state["batch_content"] = current_batch + "\n\n" + ocr_result
            else:
                st.session_state["batch_content"] = ocr_result
            st.rerun()

# ================= 页面：新题录入 =================
def page_entry():
    st.header("📝 录入新题")
    
    # 初始化 Session State
    if "entry_year" not in st.session_state: st.session_state["entry_year"] = "2024"
    if "entry_p_type" not in st.session_state: st.session_state["entry_p_type"] = "G"
    if "entry_subject_multi" not in st.session_state: st.session_state["entry_subject_multi"] = [SUBJECTS[0]]
    if "entry_number" not in st.session_state: st.session_state["entry_number"] = "1"
    if "entry_paper_name" not in st.session_state: st.session_state["entry_paper_name"] = "新高考I卷"
    if "entry_content" not in st.session_state: st.session_state["entry_content"] = ""
    if "batch_content" not in st.session_state: st.session_state["batch_content"] = ""
    
    mode = st.radio("录入模式", ["单题录入", "批量试题录入", "同卷试题录入"], horizontal=True)
    
    # 左右布局：左侧 AI 识别，右侧 录入表单
    col_left, col_right = st.columns([1, 1.2]) # 右侧稍宽
    
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
                if st.button("📋 粘贴剪贴板图片", use_container_width=True):
                    if ImageGrab:
                        try:
                            clipboard_content = ImageGrab.grabclipboard()
                            
                            new_imgs = []
                            # 情况1: 直接是图片对象
                            if isinstance(clipboard_content, Image.Image):
                                new_imgs.append(clipboard_content)
                            
                            # 情况2: 文件路径列表 (用户在资源管理器复制了文件)
                            elif isinstance(clipboard_content, list):
                                for item in clipboard_content:
                                    if isinstance(item, str) and os.path.isfile(item):
                                        try:
                                            # 尝试作为图片打开
                                            img = Image.open(item)
                                            # 强制加载以避免文件句柄问题
                                            img.load() 
                                            new_imgs.append(img)
                                        except:
                                            pass # 忽略非图片文件

                            if new_imgs:
                                count_added = 0
                                for img in new_imgs:
                                    if len(st.session_state["ocr_queue"]) < 5:
                                        st.session_state["ocr_queue"].append(img)
                                        count_added += 1
                                    else:
                                        st.warning("队列已满，部分图片未添加")
                                        break
                                
                                if count_added > 0:
                                    st.toast(f"已从剪贴板添加 {count_added} 张图片", icon="✅")
                                    st.rerun()
                                else:
                                     st.warning("队列已满或没有新图片")
                            else:
                                st.warning("剪贴板中没有图片或支持的图片文件")
                        except Exception as e:
                            st.error(f"剪贴板读取失败: {e}")
                    else:
                        st.error("缺少 PIL 库")

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
    # === 右侧：录入/批量区 ===
    with col_right:
        if mode == "单题录入":
            st.subheader("📝 单题详情")
            
            # 单题录入的查找替换
            with st.expander("🔍 查找与替换", expanded=False):
                c_f_1, c_f_2, c_f_3 = st.columns([2, 2, 1])
                with c_f_1: f_str = st.text_input("查找", key="entry_find")
                with c_f_2: r_str = st.text_input("替换", key="entry_replace")
                with c_f_3:
                    st.write("")
                    st.write("")
                    if st.button("替换", key="btn_entry_replace"):
                        if st.session_state["entry_content"] and f_str:
                            st.session_state["entry_content"] = st.session_state["entry_content"].replace(f_str, r_str)
                            st.toast("替换完成", icon="✅")
                            st.rerun()

            c_r1_1, c_r1_2, c_r1_3 = st.columns([1, 2, 1.5])
            with c_r1_1:
                year = st.text_input("年份", key="entry_year")
            with c_r1_2:
                # 知识板块推断与选择逻辑优化
                current_content = st.session_state.get("entry_content", "")
                last_inferred_content = st.session_state.get("_last_inferred_content", None)
                
                if st.session_state.get("_ai_override_subjects", False):
                    st.session_state["_ai_override_subjects"] = False
                    st.session_state["_last_inferred_content"] = current_content
                elif current_content != last_inferred_content and current_content.strip() != "":
                    inferred_subjects = []
                    for s in SUBJECTS:
                        if len(s) > 1 and s in current_content:
                            inferred_subjects.append(s)
                    if inferred_subjects:
                        st.session_state["entry_subject_multi"] = inferred_subjects
                    st.session_state["_last_inferred_content"] = current_content

                current_multi = st.session_state.get("entry_subject_multi", [SUBJECTS[0]])
                valid_current_multi = [s for s in current_multi if s in SUBJECTS]
                if not valid_current_multi:
                    valid_current_multi = [SUBJECTS[0]]
                    
                subjects = st.multiselect("知识板块 (首个为主)", options=SUBJECTS, default=valid_current_multi)
                st.session_state["entry_subject_multi"] = subjects
                subject = "，".join(subjects) if subjects else SUBJECTS[0]
            with c_r1_3:
                current_p_type = st.session_state.get("entry_p_type", "G")
                type_opts = list(PAPER_TYPES.keys())
                if current_p_type not in type_opts:
                    current_p_type = "G"
                    st.session_state["entry_p_type"] = "G"
                default_type_idx = type_opts.index(current_p_type)
                
                p_type_code = st.selectbox("试卷类别", options=type_opts, index=default_type_idx, format_func=lambda x: f"{x} ({PAPER_TYPES[x]})")
                st.session_state["entry_p_type"] = p_type_code

            c_r2_1, c_r2_2 = st.columns([3, 1])
            with c_r2_1:
                paper_name = st.text_input("试卷名称", key="entry_paper_name")
            with c_r2_2:
                number = st.text_input("题号", key="entry_number")
            
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
            
            content = st.text_area("题目内容 (LaTeX)", height=400, placeholder="在此粘贴题目内容...", key="entry_content")
            
            # --- 新增渲染预览区 ---
            if content.strip():
                st.markdown("---")
                st.subheader("👁️ 实时渲染预览")
                try:
                    md_preview = latex_to_markdown(content)
                    st.markdown(md_preview, unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"预览渲染出错: {e}")
                st.markdown("---")
            # ----------------------
            
            # 自动生成文件名预览
            filename = generate_filename(year, p_type_code, paper_name, number, subject)
            st.info(f"目标文件名: `{filename}`")
            
            # 定义保存回调函数 (避免在组件实例化后修改 Session State)
            def on_save_entry():
                # 从 Session State 获取最新值
                s_content = st.session_state.get("entry_content", "")
                s_year = st.session_state.get("entry_year", "")
                s_type = st.session_state.get("entry_p_type", "")
                s_subj_list = st.session_state.get("entry_subject_multi", [SUBJECTS[0]])
                s_subj = "，".join(s_subj_list) if s_subj_list else SUBJECTS[0]
                s_num = st.session_state.get("entry_number", "")
                s_paper = st.session_state.get("entry_paper_name", "")
                
                # 获取附加属性
                s_diff_raw = st.session_state.get("entry_difficulty", 0.0)
                s_diff = "" if s_diff_raw == 0.0 else str(s_diff_raw)
                s_tag = st.session_state.get("entry_custom_tags", "")
                s_rem = st.session_state.get("entry_remark", "")
                
                if not s_content:
                    st.toast("题目内容不能为空", icon="⚠️")
                    return
                
                s_filename = generate_filename(s_year, s_type, s_paper, s_num, s_subj)
                primary_subj = s_subj.split("，")[0]
                s_save_dir = os.path.join(CHAPTERS_DIR, primary_subj, s_year)
                ensure_dir(s_save_dir)
                s_file_path = os.path.join(s_save_dir, s_filename)
                
                # 构造 LaTeX 模板内容
                # 注意：如果 s_content 中已经包含了 \begin{answer} 或 \begin{solution} 等环境，
                # 我们需要将其剥离出来，放到 \end{problem} 的后面，以符合结构规范。
                
                # 提取解答
                sol_match = re.search(r'\\begin\{solutions?\}(.*?)\\end\{solutions?\}', s_content, re.DOTALL)
                sol_text = sol_match.group(0) if sol_match else ""
                
                # 提取答案
                ans_match = re.search(r'\\begin\{answer\}(.*?)\\end\{answer\}', s_content, re.DOTALL)
                ans_text = ans_match.group(0) if ans_match else ""
                
                # 清理题干中的解析和答案
                clean_content = s_content
                if sol_match:
                    clean_content = clean_content.replace(sol_match.group(0), "")
                if ans_match:
                    clean_content = clean_content.replace(ans_match.group(0), "")
                clean_content = clean_content.strip()
                
                full_text = f"\\begin{{problem}}{{{s_year}}}{{{s_type}}}{{{s_paper}}}{{{s_num}}}{{{s_subj}}}\n{clean_content}\n\\end{{problem}}"
                
                if ans_text:
                    full_text += f"\n\n{ans_text}"
                if sol_text:
                    full_text += f"\n\n{sol_text}"
                
                # 提取并替换 TikZ 代码
                full_text = extract_and_replace_tikz(full_text, s_filename, s_save_dir)
                
                # 获取新ID并注入 Meta Data (新版 Label Data 格式)
                from utils.csv_ops import get_next_id
                new_id = get_next_id()
                meta_dict = {
                    "ID": new_id,
                    "难度星级": s_diff,
                    "标签": s_tag,
                    "备注": s_rem,
                    "组卷引用次数": 0
                }
                from utils.latex_ops import inject_meta_data
                full_text = inject_meta_data(full_text, meta_dict)
                
                try:
                    with open(s_file_path, "w", encoding="utf-8") as f:
                        f.write(full_text)
                    
                    # 同步追加到 CSV 索引
                    add_to_csv_index(s_file_path, full_text, s_year, s_type, s_paper, s_num, s_subj)
                    
                    st.toast(f"成功保存到: {s_filename} (分配ID: {new_id})", icon="✅")
                    # 清空缓存让统计立刻更新
                    clear_statistics_cache()
                    # 清空内容以便下一题
                    st.session_state["entry_content"] = ""
                    st.session_state["entry_difficulty"] = 0.0
                    st.session_state["entry_custom_tags"] = ""
                    st.session_state["entry_remark"] = ""
                    # 根据用户要求，取消题号自动+1，保存后清空题号以防误覆盖
                    st.session_state["entry_number"] = ""
                except Exception as e:
                    st.toast(f"保存失败: {e}", icon="❌")

            st.button("💾 保存题目", type="primary", on_click=on_save_entry)

        elif mode == "同卷试题录入":
            st.subheader("📚 同卷批量文本")
            st.info("用于同一试卷的批量录入。设置统一信息后，文件名只需写 `---题号-知识板块.tex---` 即可。")

            # 统一信息设置 (4列布局以对齐)
            c_u1, c_u2, c_u3, c_u4 = st.columns([1.5, 1.5, 2, 0.6])
            with c_u1:
                u_year = st.text_input("**统一年份**", key="u_batch_year")
            with c_u2:
                u_type = st.selectbox("**统一类别**", options=list(PAPER_TYPES.keys()), format_func=lambda x: f"{x} ({PAPER_TYPES[x]})", key="u_batch_type")
            with c_u3:
                u_paper = st.text_input("**统一试卷名称**", key="u_batch_paper")
            with c_u4:
                st.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)
                def on_sync_click():
                    current_txt = st.session_state.get("batch_content", "")
                    uy = st.session_state.get("u_batch_year", "")
                    ut = st.session_state.get("u_batch_type", "G")
                    up = st.session_state.get("u_batch_paper", "")
                    if current_txt and uy and up:
                        def replace_header(match):
                            content = match.group(1).strip()
                            name_body = content.replace('.tex', '')
                            segs = name_body.split('-')
                            # 支持用户可能带了后缀或者没带后缀
                            # 以及容错空格
                            segs = [s.strip() for s in segs]
                            
                            # 如果原本就是五段式，也需要支持"试卷名"被更新（比如用户原本填了2024-G-老名字-1-集合，想要一键改成新名字）
                            if len(segs) == 5:
                                full_name = generate_filename(uy, ut, up, segs[3], segs[4])
                                return f"---{full_name}---"
                            
                            if len(segs) == 2:
                                full_name = generate_filename(uy, ut, up, segs[0], segs[1])
                                return f"---{full_name}---"
                            return match.group(0)
                        import re
                        new_txt = re.sub(r'---(.+?)---', replace_header, current_txt)
                        st.session_state["batch_content"] = new_txt
                if st.button("🔄 同步", help="将当前设置的统一信息应用到下方文本框中的所有简写文件名", on_click=on_sync_click, use_container_width=True):
                    st.toast("同步操作已执行，请检查下方文本框", icon="✅")


            # 批量查找与替换 (同卷模式)
            with st.expander("🔍 批量查找与替换工具", expanded=False):
                c_bf_1, c_bf_2, c_bf_3 = st.columns([2, 2, 1])
                with c_bf_1: bf_str = st.text_input("查找内容", key="u_batch_find")
                with c_bf_2: br_str = st.text_input("替换为", key="u_batch_replace")
                with c_bf_3:
                    st.write("")
                    st.write("")
                    if st.button("执行替换", key="btn_u_batch_replace"):
                        if st.session_state.get("batch_content") and bf_str:
                            st.session_state["batch_content"] = st.session_state["batch_content"].replace(bf_str, br_str)
                            st.toast(f"已替换所有的 '{bf_str}'", icon="✅")
                            st.rerun()

            # 批量处理逻辑
            batch_text = st.text_area("批量文本内容", height=500, key="batch_content", placeholder="---1-集合.tex---\n\\begin{problem}...\n\n---2-复数.tex---\n\\begin{problem}...")
            
            if st.button("开始处理同卷文本", type="primary"):
                if not batch_text.strip():
                    st.warning("请输入内容")
                elif not (u_year and u_paper):
                    st.error("请完善年份和试卷名称信息")
                else:
                    parts = re.split(r'---(.+\.tex)---\s*', batch_text)
                    count = 0
                    log_msg = []
                    
                    for i in range(1, len(parts), 2):
                        if i + 1 < len(parts):
                            raw_fname = parts[i].strip()
                            file_content = parts[i+1].strip()
                            
                            # 解析题号和板块
                            name_body = raw_fname.replace('.tex', '')
                            segments = name_body.split('-')
                            
                            # 策略：取最后两个字段作为 题号 和 板块
                            # 比如 "1-集合" -> num=1, subj=集合
                            # 比如 "2023-Old-1-集合" -> num=1, subj=集合
                            if len(segments) >= 2:
                                q_num = segments[-2]
                                q_subj = segments[-1]
                                
                                # 生成完整文件名
                                final_filename = generate_filename(u_year, u_type, u_paper, q_num, q_subj)
                                
                                # 保存
                                primary_subj = q_subj.split("，")[0]
                                save_dir = os.path.join(CHAPTERS_DIR, primary_subj, str(u_year))
                                ensure_dir(save_dir)
                                file_path = os.path.join(save_dir, final_filename)
                                
                                # 提取并替换 TikZ 代码
                                file_content = extract_and_replace_tikz(file_content, final_filename, save_dir)
                                
                                # 注入 Label Data
                                from utils.csv_ops import get_next_id
                                from utils.latex_ops import inject_meta_data
                                new_id = get_next_id()
                                meta_dict = {
                                    "ID": new_id,
                                    "难度星级": "",
                                    "标签": "",
                                    "备注": "",
                                    "组卷引用次数": 0
                                }
                                file_content = inject_meta_data(file_content, meta_dict)
                                
                                try:
                                    with open(file_path, "w", encoding="utf-8") as f:
                                        f.write(file_content)
                                    # 同步追加到 CSV 索引
                                    add_to_csv_index(file_path, file_content, str(u_year), u_type, u_paper, q_num, q_subj)
                                    count += 1
                                    log_msg.append({"status": "success", "file": final_filename, "path": file_path})
                                except Exception as e:
                                    log_msg.append({"status": "error", "file": final_filename, "msg": str(e)})
                            else:
                                log_msg.append({"status": "skip", "file": raw_fname, "msg": "文件名格式不足 (需至少包含 题号-板块)"})

                    st.success(f"处理完成，共保存 {count} 个文件")
                    st.toast(f"同卷处理完成！共保存 {count} 个文件", icon="✅")
                    
                    with st.expander("查看处理日志", expanded=True):
                        for log in log_msg:
                            if log["status"] == "success":
                                c1, c2 = st.columns([4, 1])
                                c1.success(f"✅ {log['file']}")
                                if c2.button("📂 打开", key=f"open_log_u_{log['file']}"):
                                    try:
                                        os.startfile(log['path'])
                                    except Exception as e:
                                        st.error(f"无法打开: {e}")
                            elif log["status"] == "error":
                                st.error(f"❌ {log['file']}: {log['msg']}")
                            else:
                                st.warning(f"⚠️ {log['file']}: {log['msg']}")

        else: # 批量试题录入
            st.subheader("📚 批量文本")
            st.info("格式: `---文件名.tex---` 分隔。左侧 AI 识别结果会自动追加到下方。")
            
            # === 移动到此处的批量查找替换 ===
            with st.expander("🔍 批量查找与替换工具", expanded=False):
                col_find, col_replace, col_btn = st.columns([2, 2, 1])
                with col_find:
                    st.text_input("查找内容", key="batch_find_str")
                with col_replace:
                    st.text_input("替换为", key="batch_replace_str")
                with col_btn:
                    st.write("") # Spacer
                    st.write("") 
                    
                    def perform_batch_replace():
                        find_s = st.session_state.get("batch_find_str", "")
                        replace_s = st.session_state.get("batch_replace_str", "")
                        current_content = st.session_state.get("batch_content", "")
                        
                        if current_content and find_s:
                            new_c = current_content.replace(find_s, replace_s)
                            st.session_state["batch_content"] = new_c
                            st.toast(f"已替换所有的 '{find_s}'", icon="✅")
                        elif not current_content:
                            st.toast("内容为空，无法替换", icon="⚠️")
                        elif not find_s:
                            st.toast("请输入查找内容", icon="⚠️")

                    st.button("执行替换", on_click=perform_batch_replace)
            # ==============================

            batch_text = st.text_area("批量文本内容", height=600, key="batch_content", placeholder="---2024-G-新课标I卷-1-集合.tex---\n\\begin{problem}...\n...")
            
            if st.button("开始处理批量文本", type="primary"):
                if not batch_text.strip():
                    st.warning("请输入内容")
                else:
                    parts = re.split(r'---(.+\.tex)---\s*', batch_text)
                    count = 0
                    log_msg = []
                    for i in range(1, len(parts), 2):
                        if i + 1 < len(parts):
                            filename = parts[i].strip()
                            file_content = parts[i+1].strip()
                            name_body = filename.replace('.tex', '')
                            segments = name_body.split('-')
                            if len(segments) >= 5:
                                year_seg = segments[0]
                                topic_seg = segments[-1]
                                primary_topic = topic_seg.split("，")[0]
                                save_dir = os.path.join(CHAPTERS_DIR, primary_topic, str(year_seg))
                                ensure_dir(save_dir)
                                file_path = os.path.join(save_dir, filename)
                                
                                # 提取并替换 TikZ 代码
                                file_content = extract_and_replace_tikz(file_content, filename, save_dir)
                                
                                # 注入 Label Data
                                from utils.csv_ops import get_next_id
                                from utils.latex_ops import inject_meta_data
                                new_id = get_next_id()
                                meta_dict = {
                                    "ID": new_id,
                                    "难度星级": "",
                                    "标签": "",
                                    "备注": "",
                                    "组卷引用次数": 0
                                }
                                file_content = inject_meta_data(file_content, meta_dict)
                                
                                try:
                                    with open(file_path, "w", encoding="utf-8") as f:
                                        f.write(file_content)
                                        
                                    # 同步追加到 CSV 索引
                                    add_to_csv_index(
                                        file_path, file_content, 
                                        segments[0], segments[1], segments[2], segments[3], segments[4]
                                    )
                                    
                                    count += 1
                                    log_msg.append({"status": "success", "file": filename, "path": file_path, "id": new_id})
                                except Exception as e:
                                    log_msg.append({"status": "error", "file": filename, "msg": str(e)})
                            else:
                                log_msg.append({"status": "skip", "file": filename, "msg": "文件名格式错误"})
                    
                    st.success(f"处理完成，共保存 {count} 个文件")
                    clear_statistics_cache()
                    st.toast(f"批量处理完成！共保存 {count} 个文件", icon="✅")
                    
                    with st.expander("查看处理日志", expanded=True):
                        # 逐条显示日志
                        for log in log_msg:
                            if log["status"] == "success":
                                c1, c2 = st.columns([4, 1])
                                c1.success(f"✅ {log['file']}")
                                # 按钮 key 必须唯一
                                if c2.button("📂 打开", key=f"open_log_{log['file']}"):
                                    try:
                                        os.startfile(log['path'])
                                    except Exception as e:
                                        st.error(f"无法打开: {e}")
                            elif log["status"] == "error":
                                st.error(f"❌ {log['file']}: {log['msg']}")
                            else:
                                st.warning(f"⚠️ {log['file']}: {log['msg']}")
                            
    # (原批量文本查找与替换位置已移除)
    st.markdown("---")

# ================= 页面：浏览/编辑 =================
def page_browse(is_exam_mode=False):
    if not is_exam_mode:
        st.header("🔍 全局浏览与编辑")
    
    # 浏览模式选择
    if not is_exam_mode:
        st.subheader("浏览模式")
    browse_mode = st.radio("浏览模式", ["按知识板块浏览", "按试卷浏览", "按录入顺序浏览"], horizontal=True, label_visibility="collapsed")
    
    selected_file_path = None
    
    if browse_mode == "按知识板块浏览":
        # 左右布局：左侧导航，右侧文件列表与编辑
        col_nav, col_content = st.columns([1, 4])
        
        with col_nav:
            st.markdown("### 📂 知识板块")
            
            # 使用自定义 CSS 优化按钮样式 (圆角、紧凑)
            st.markdown("""
                <style>
                div.stButton > button {
                    width: 100%;
                    border-radius: 8px;
                    padding: 0.25rem 0.5rem;
                    font-size: 14px;
                    margin-bottom: 2px;
                }
                </style>
            """, unsafe_allow_html=True)
            
            # 使用 session_state 记录当前选中的板块
            if "browse_subject" not in st.session_state:
                st.session_state["browse_subject"] = SUBJECTS[0]

            # 双列排列，按钮宽度缩小
            # 通过 columns 来实现双列
            for i in range(0, len(SUBJECTS), 2):
                c1, c2 = st.columns(2)
                
                # 第一个按钮
                if i < len(SUBJECTS):
                    subj1 = SUBJECTS[i]
                    btn_type1 = "primary" if st.session_state["browse_subject"] == subj1 else "secondary"
                    with c1:
                        if st.button(subj1, key=f"nav_subj_{subj1}", type=btn_type1, use_container_width=True):
                            st.session_state["browse_subject"] = subj1
                            st.rerun()
                
                # 第二个按钮
                if i + 1 < len(SUBJECTS):
                    subj2 = SUBJECTS[i+1]
                    btn_type2 = "primary" if st.session_state["browse_subject"] == subj2 else "secondary"
                    with c2:
                        if st.button(subj2, key=f"nav_subj_{subj2}", type=btn_type2, use_container_width=True):
                            st.session_state["browse_subject"] = subj2
                            st.rerun()
            
            subject = st.session_state["browse_subject"]
            
        with col_content:
            years = get_years(subject)
            if years:
                # 2. 选择年份 (横向排列)
                st.subheader("📅 选择年份")
                
                # 增加“显示所有年份”选项
                ALL_YEARS_OPT = "显示所有年份"
                year_options = [ALL_YEARS_OPT] + years
                
                year = st.radio("📅 选择年份", options=year_options, index=0, key="browse_year", horizontal=True, label_visibility="collapsed")
                
                st.divider()
                
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
                            key=f"browse_file_select_{subject}_all"
                        )
                        
                        if selected_option == SHOW_ALL_OPT:
                            selected_file_path = None
                            st.divider()
                            st.markdown(f"### {subject} - 所有年份所有题目")
                            
                            for i, (y, fname) in enumerate(files):
                                fpath = os.path.join(CHAPTERS_DIR, subject, y, fname)
                                if not os.path.exists(fpath): continue
                                
                                with open(fpath, "r", encoding="utf-8") as f:
                                    content = f.read()
                                    
                                parts = fname.replace(".tex", "").split("-")
                                if len(parts) >= 5:
                                    q_label = f"【{parts[0]} {parts[2]} 第{parts[3]}题】 （{parts[4]}）"
                                elif len(parts) >= 4:
                                    q_label = f"【{parts[0]} {parts[2]} 第{parts[3]}题】"
                                else:
                                    q_label = fname

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
                                        new_content = st.text_area("源码", value=content, height=est_height, key=text_area_key)
                                        if st.button("💾 保存修改", key=f"subj_save_btn_{fpath}", type="primary"):
                                            save_modified_tex_file(fpath, new_content)
                                            st.session_state[edit_mode_key] = False
                                            st.toast(f"{q_label} 已保存", icon="✅")
                                            time.sleep(0.5)
                                            st.rerun()
                                    else:
                                        st.text_area("源码", value=content, height=est_height, disabled=True, key=text_area_key + "_readonly")
                                        
                                        tag_edit_key = f"tag_edit_mode_{fpath}"
                                        is_tag_editing = st.session_state.get(tag_edit_key, False)
                                        
                                        btn_c1, btn_c2 = st.columns(2)
                                        with btn_c1:
                                            if st.button("✏️ 开始修改tex内容", key=f"subj_start_btn_{fpath}"):
                                                st.session_state[edit_mode_key] = True
                                                st.rerun()
                                        with btn_c2:
                                            if is_tag_editing:
                                                if st.button("✅ 完成修改板块标签", key=f"tag_save_btn_{fpath}", type="primary"):
                                                    new_tags = st.session_state.get(f"tag_select_{fpath}")
                                                    if new_tags:
                                                        if update_file_tags(fpath, new_tags):
                                                            st.toast("标签修改成功！", icon="✅")
                                                            st.session_state[tag_edit_key] = False
                                                            time.sleep(0.5)
                                                            st.rerun()
                                                        else:
                                                            st.error("文件名格式不支持修改标签")
                                            else:
                                                if st.button("🏷️ 开始修改板块标签", key=f"tag_start_btn_{fpath}"):
                                                    st.session_state[tag_edit_key] = True
                                                    st.rerun()
                                                
                                        if is_tag_editing:
                                            current_tags = extract_tags_from_fpath(fpath)
                                            valid_tags = [t for t in current_tags if t in SUBJECTS] or [SUBJECTS[0]]
                                            st.multiselect("修改知识板块 (首个为主)", options=SUBJECTS, default=valid_tags, key=f"tag_select_{fpath}")

                                with c2:
                                    try:
                                        st.markdown(latex_to_markdown(content), unsafe_allow_html=True)
                                    except Exception as e:
                                        st.error(f"渲染错误: {e}")
                                
                                st.divider()
                        elif selected_option:
                            # 解析出真实的年份和文件名
                            sel_y = selected_option.split("年 - ")[0]
                            sel_f = selected_option.split("年 - ")[1]
                            selected_file_path = os.path.join(CHAPTERS_DIR, subject, sel_y, sel_f)
                    else:
                        st.info("该板块下暂无任何文件")
                else:
                    # 原来的单一年份逻辑
                    files = get_files(subject, year) # 假设 get_files 返回文件名列表
                    if files:
                        st.subheader(f"📄 文件列表 ({subject} - {year})")
                        
                        # 增加“展示全部”选项
                        SHOW_ALL_OPT = "📂 展示该年份全部问题"
                        file_options = [SHOW_ALL_OPT] + files

                        # 使用 selectbox 实现“既能手动选择，又能输入模糊匹配”
                        selected_option = st.selectbox(
                            "3. 选择文件 (支持输入搜索)", 
                            options=file_options,
                            key=f"browse_file_select_{subject}_{year}" # 动态 key 避免状态残留
                        )
                        
                        if selected_option == SHOW_ALL_OPT:
                            selected_file_path = None # 不显示底部的单文件编辑器
                            
                            st.divider()
                            st.markdown(f"### {year}年 {subject} - 所有题目")
                            
                            for i, fname in enumerate(files):
                                fpath = os.path.join(CHAPTERS_DIR, subject, year, fname)
                                if not os.path.exists(fpath): continue
                                
                                # 读取内容
                                with open(fpath, "r", encoding="utf-8") as f:
                                    content = f.read()
                                
                                # 提取显示标签
                                parts = fname.replace(".tex", "").split("-")
                                if len(parts) >= 5:
                                    # Year-Type-Name-Num-Subject -> [Year] Name 第Num题 (Subject)
                                    q_label = f"【{parts[0]} {parts[2]} 第{parts[3]}题】 （{parts[4]}）"
                                elif len(parts) >= 4:
                                    q_label = f"【{parts[0]} {parts[2]} 第{parts[3]}题】"
                                else:
                                    q_label = fname

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
                                            key=text_area_key
                                        )
                                        if st.button("💾 保存修改", key=f"subj_save_btn_{fpath}", type="primary"):
                                            save_modified_tex_file(fpath, new_content)
                                            st.session_state[edit_mode_key] = False
                                            st.toast(f"{q_label} 已保存", icon="✅")
                                            time.sleep(0.5)
                                            st.rerun()
                                    else:
                                        st.text_area(
                                            "源码", 
                                            value=content, 
                                            height=est_height, 
                                            disabled=True,
                                            key=text_area_key + "_readonly"
                                        )
                                        
                                        tag_edit_key = f"tag_edit_mode_{fpath}"
                                        is_tag_editing = st.session_state.get(tag_edit_key, False)
                                        
                                        btn_c1, btn_c2 = st.columns(2)
                                        with btn_c1:
                                            if st.button("✏️ 开始修改tex内容", key=f"subj_start_btn_{fpath}"):
                                                st.session_state[edit_mode_key] = True
                                                st.rerun()
                                        with btn_c2:
                                            if is_tag_editing:
                                                if st.button("✅ 完成修改板块标签", key=f"tag_save_btn_{fpath}", type="primary"):
                                                    new_tags = st.session_state.get(f"tag_select_{fpath}")
                                                    if new_tags:
                                                        if update_file_tags(fpath, new_tags):
                                                            st.toast("标签修改成功！", icon="✅")
                                                            st.session_state[tag_edit_key] = False
                                                            time.sleep(0.5)
                                                            st.rerun()
                                                        else:
                                                            st.error("文件名格式不支持修改标签")
                                            else:
                                                if st.button("🏷️ 开始修改板块标签", key=f"tag_start_btn_{fpath}"):
                                                    st.session_state[tag_edit_key] = True
                                                    st.rerun()
                                                
                                        if is_tag_editing:
                                            current_tags = extract_tags_from_fpath(fpath)
                                            valid_tags = [t for t in current_tags if t in SUBJECTS] or [SUBJECTS[0]]
                                            st.multiselect("修改知识板块 (首个为主)", options=SUBJECTS, default=valid_tags, key=f"tag_select_{fpath}")

                                with c2:
                                    try:
                                        st.markdown(latex_to_markdown(content), unsafe_allow_html=True)
                                    except Exception as e:
                                        st.error(f"渲染错误: {e}")
                                
                                st.divider()

                        elif selected_option:
                             selected_file_path = os.path.join(CHAPTERS_DIR, subject, year, selected_option)
                    else:
                        st.info("该目录下暂无文件")
            else:
                st.warning("该板块暂无年份数据")
                
    elif browse_mode == "按试卷浏览":

        all_years = get_all_years_globally()
        if not all_years:
            st.warning("题库中暂无任何年份数据")
            return
            
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📅 选择年份")
            year = st.selectbox("📅 选择年份", options=all_years, key="paper_year", label_visibility="collapsed")
        with col2:
            st.subheader("选择试卷")
            papers = get_papers_by_year(year)
            if papers:
                paper_name = st.selectbox("选择试卷", options=papers, key="paper_name", label_visibility="collapsed")
            else:
                paper_name = None
                st.warning("该年份下未找到试卷")
        
        if year and paper_name:
            st.markdown(f"### {year} {paper_name} - 所有题目")
            questions = get_questions_by_paper(year, paper_name)
            
            if not questions:
                 st.info("未找到该试卷的题目")
            else:
                # 模式选择
                view_mode = st.radio("展示模式", ["单题选择模式", "所有问题展示模式"], horizontal=True)
                
                if view_mode == "单题选择模式":
                    st.subheader("选择题目进行编辑")
                    
                    # 使用 session_state 记录当前选中的题目索引
                    select_key = f"selected_q_idx_{year}_{paper_name}"
                    if select_key not in st.session_state:
                        st.session_state[select_key] = 0
                    
                    # 按钮网格布局 (每行 8 个)
                    num_cols = 8
                    rows = (len(questions) + num_cols - 1) // num_cols
                    
                    for r in range(rows):
                        cols = st.columns(num_cols)
                        for c in range(num_cols):
                            idx = r * num_cols + c
                            if idx < len(questions):
                                q = questions[idx]
                                q_num = q['file'].split('-')[3]
                                btn_label = f"第{q_num}题\n({q['subject']})"
                                
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
                    # 所有问题展示模式：逐题列出，左编辑右预览
                    selected_file_path = None # 隐藏底部的单题编辑区
                    st.divider()
                    
                    for i, q in enumerate(questions):
                        q_path = q["path"]
                        if not os.path.exists(q_path): continue
                        
                        # 读取内容
                        with open(q_path, "r", encoding="utf-8") as f:
                            content = f.read()
                            
                        # 题目编号
                        q_label = f"第{q['file'].split('-')[3]}题 ({q['subject']})"
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
                                new_content = st.text_area(
                                    "源码", 
                                    value=content, 
                                    height=est_height, 
                                    key=text_area_key
                                )
                                # 保存按钮
                                if st.button("💾 保存修改", key=f"save_btn_{q_path}", type="primary"):
                                    save_modified_tex_file(q_path, new_content)
                                    st.session_state[edit_mode_key] = False
                                    st.toast(f"{q_label} 已保存", icon="✅")
                                    time.sleep(0.5)
                                    st.rerun()
                            else:
                                st.text_area(
                                    "源码", 
                                    value=content, 
                                    height=est_height, 
                                    disabled=True,
                                    key=text_area_key + "_readonly"
                                )
                                
                                tag_edit_key = f"tag_edit_mode_{q_path}"
                                is_tag_editing = st.session_state.get(tag_edit_key, False)
                                
                                btn_c1, btn_c2 = st.columns(2)
                                with btn_c1:
                                    if st.button("✏️ 开始修改tex内容", key=f"start_btn_{q_path}"):
                                        st.session_state[edit_mode_key] = True
                                        st.rerun()
                                with btn_c2:
                                    if is_tag_editing:
                                        if st.button("✅ 完成修改板块标签", key=f"tag_save_btn_{q_path}", type="primary"):
                                            new_tags = st.session_state.get(f"tag_select_{q_path}")
                                            if new_tags:
                                                if update_file_tags(q_path, new_tags):
                                                    st.toast("标签修改成功！", icon="✅")
                                                    st.session_state[tag_edit_key] = False
                                                    time.sleep(0.5)
                                                    st.rerun()
                                                else:
                                                    st.error("文件名格式不支持修改标签")
                                    else:
                                        if st.button("🏷️ 开始修改板块标签", key=f"tag_start_btn_{q_path}"):
                                            st.session_state[tag_edit_key] = True
                                            st.rerun()
                                        
                                if is_tag_editing:
                                    current_tags = extract_tags_from_fpath(q_path)
                                    valid_tags = [t for t in current_tags if t in SUBJECTS] or [SUBJECTS[0]]
                                    st.multiselect("修改知识板块 (首个为主)", options=SUBJECTS, default=valid_tags, key=f"tag_select_{q_path}")

                        with c2:
                            st.markdown(latex_to_markdown(content), unsafe_allow_html=True)
                        
                        st.divider()
    
    elif browse_mode == "按录入顺序浏览":
        st.subheader("🕒 按录入顺序浏览")
        
        # 排序选项
        sort_order = st.radio("排序方式", ["最新录入在最前 (从后往前)", "最早录入在最前 (从前往后)"], horizontal=True)
        
        try:
            from utils.csv_ops import read_csv_index
            csv_data = read_csv_index()
        except Exception as e:
            csv_data = []
            st.error(f"读取索引失败: {e}")
            
        if not csv_data:
            st.info("题库为空或索引未建立，请先一键重建题库索引。")
        else:
            # 根据时间排序
            def get_time(row):
                # 优先使用“初次录入的时间”，如果没有则退化为“最后修改时间”，再没有则为空字符串
                t = row.get("初次录入的时间", "")
                if not t:
                    t = row.get("最后修改时间", "")
                return t
                
            sorted_data = sorted(csv_data, key=get_time, reverse=(sort_order == "最新录入在最前 (从后往前)"))
            
            # 分页或展示数量限制 (避免一次性渲染几百个卡顿)
            max_show = st.slider("最多展示题目数量", min_value=10, max_value=200, value=50, step=10)
            display_data = sorted_data[:max_show]
            
            st.markdown(f"共找到 **{len(sorted_data)}** 道题目，当前展示前 **{len(display_data)}** 道。")
            st.divider()
            
            for i, row in enumerate(display_data):
                # 构建文件真实路径
                fpath = os.path.join(CHAPTERS_DIR, row["相对文件路径"])
                if not os.path.exists(fpath): 
                    continue
                    
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                    
                fname = row["文件名称"]
                parts = fname.split("-")
                if len(parts) >= 5:
                    q_label = f"【{parts[0]} {parts[2]} 第{parts[3]}题】 （{parts[4]}）"
                elif len(parts) >= 4:
                    q_label = f"【{parts[0]} {parts[2]} 第{parts[3]}题】"
                else:
                    q_label = fname

                # 增加时间标识显示
                time_str = get_time(row)
                extra_label = ""
                if time_str:
                    extra_label = f"<span style='font-size:0.5em; color:gray; font-weight:normal; margin-left: 10px;'>🕒 {time_str}</span>"
                    
                render_question_header(q_label, content, fpath, extra_html_label=extra_label)
                
                if is_exam_mode:
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
                    est_height = get_editor_height(content)
                    is_editing = st.session_state.get(edit_mode_key, False)
                    text_area_key = f"time_edit_{fpath}"
                    
                    if is_editing:
                        new_content = st.text_area("源码", value=content, height=est_height, key=text_area_key)
                        if st.button("💾 保存修改", key=f"time_save_btn_{fpath}", type="primary"):
                            save_modified_tex_file(fpath, new_content)
                            st.session_state[edit_mode_key] = False
                            st.toast("已保存", icon="✅")
                            time.sleep(0.5)
                            st.rerun()
                    else:
                        st.text_area("源码", value=content, height=est_height, disabled=True, key=text_area_key + "_readonly")
                        
                        tag_edit_key = f"time_tag_edit_mode_{fpath}"
                        is_tag_editing = st.session_state.get(tag_edit_key, False)
                        
                        btn_c1, btn_c2 = st.columns(2)
                        with btn_c1:
                            if st.button("✏️ 开始修改tex内容", key=f"time_start_btn_{fpath}"):
                                st.session_state[edit_mode_key] = True
                                st.rerun()
                        with btn_c2:
                            if is_tag_editing:
                                if st.button("✅ 完成修改板块标签", key=f"time_tag_save_btn_{fpath}", type="primary"):
                                    new_tags = st.session_state.get(f"time_tag_select_{fpath}")
                                    if new_tags:
                                        if update_file_tags(fpath, new_tags):
                                            st.toast("标签修改成功！", icon="✅")
                                            st.session_state[tag_edit_key] = False
                                            time.sleep(0.5)
                                            st.rerun()
                                        else:
                                            st.error("文件名格式不支持修改标签")
                            else:
                                if st.button("🏷️ 开始修改板块标签", key=f"time_tag_start_btn_{fpath}"):
                                    st.session_state[tag_edit_key] = True
                                    st.rerun()
                                
                        if is_tag_editing:
                            current_tags = extract_tags_from_fpath(fpath)
                            valid_tags = [t for t in current_tags if t in SUBJECTS] or [SUBJECTS[0]]
                            st.multiselect("修改知识板块 (首个为主)", options=SUBJECTS, default=valid_tags, key=f"time_tag_select_{fpath}")

                with c2:
                    try:
                        st.markdown(latex_to_markdown(content), unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"渲染错误: {e}")
                
                st.divider()

    # 编辑区域 (Split View) - 仅在选择了文件时显示
    if selected_file_path and os.path.exists(selected_file_path):
        st.markdown("---")
        with open(selected_file_path, "r", encoding="utf-8") as f:
            current_content = f.read()
            
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
                st.subheader("📝 编辑 LaTeX")
                editor_key = f"editor_{selected_file_path}"
                new_content = st.text_area("源码", value=current_content, height=600, key=editor_key)
                if st.button("💾 保存修改", type="primary", key=f"save_{selected_file_path}"):
                    save_modified_tex_file(selected_file_path, new_content)
                    st.session_state["last_saved"] = time.time() 
                    st.toast("文件已保存！", icon="✅")
                    
            with col_preview:
                st.subheader("👁️ 渲染预览")
                try:
                    # 尝试渲染
                    md_content = latex_to_markdown(new_content)
                    st.markdown(md_content, unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"预览渲染出错: {e}")
                    
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
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(final_content)
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
    
    # === 批量工具：重建题库索引 ===
    st.subheader("🗄️ 1. 数据库维护 (一键重建/同步题库索引)")
    st.info("如果您的题库文件出现了手动删除、外部复制等变动，导致与 CSV 索引不一致，或者统计数据异常，可以点击下方按钮进行一键重建。该操作会保留现有题目的 ID，并自动追加新题或删除不存在的死链接。")
    if st.button("🔄 一键重建/同步题库索引", type="secondary"):
        with st.spinner("正在扫描全库并同步索引，请稍候..."):
            try:
                # 运行 init_csv_index.py 脚本
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

    st.markdown("---")
    
    st.subheader("2. 自动更新板块题目索引 (content_*.tex)")
    st.markdown("""
    调用本地的 `batch_gen.py` 脚本，自动扫描 `chapters` 目录下的所有题目，
    并为每个板块重新生成最新的 `content_板块名称.tex` 索引文件，供主文件 `main.tex` 调用编译。
    *(当您新增、删除或重命名了题目文件后，请执行此操作以确保主文件目录同步)*
    """)
    if st.button("执行更新章节索引"):
        with st.spinner("正在运行更新脚本..."):
            try:
                # 调用同一目录下的 batch_gen.py 脚本
                # 注意：这里我们使用 subprocess.run 来执行独立的 python 进程
                # 但因为 batch_gen.py 中有交互逻辑 (input)，我们需要确保它以非阻塞或自动模式运行
                # 为了安全，这里我们建议我们在 batch_gen.py 里抽离了 update_chapter_contents 函数
                # 我们可以直接在这里 import 并调用，这样更稳妥且不会被 input 卡住。
                import sys
                if BASE_DIR not in sys.path:
                    sys.path.append(BASE_DIR)
                import utils.batch_gen as batch_gen
                batch_gen.update_chapter_contents()
                st.success("章节索引更新完成！请检查终端输出。")
            except Exception as e:
                st.error(f"执行失败: {e}")

    st.markdown("---")
    
    st.subheader("3. 批量提取并分离 TikZ 绘图")
    st.markdown("""
    扫描题库中所有现存的 `.tex` 文件。如果发现未被分离的 `\\begin{tikzpicture} ... \\end{tikzpicture}` 代码，
    将会自动将其剥离到同级目录下的 `相关图` 文件夹中生成副本，同时在主文件中保留内联 TikZ 源码。
    """)
    if st.button("执行全库 TikZ 剥离"):
        updated_files = batch_extract_tikz_all()
        if updated_files:
            st.success(f"操作完成，共处理并更新了 {len(updated_files)} 个包含内联 TikZ 的文件。")
            with st.expander("查看更新的文件名单", expanded=True):
                for f in updated_files:
                    st.write(f"- {f}")
        else:
            st.info("未发现需要处理的文件。")

    st.markdown("---")

    st.subheader("4. 批量纠正选择题选项格式")
    st.markdown("""
    扫描题库中所有现存的 `.tex` 文件。如果发现形如 `A. xxx B. xxx C. xxx D. xxx` 的非标准选择题格式，
    将自动尝试提取选项内容，并用规范的 `\\begin{choices}` ... `\\end{choices}` 指令进行替换。
    """)
    if st.button("执行全库选择题格式纠正"):
        updated_files = batch_fix_choice_formats()
        if updated_files:
            st.success(f"操作完成，共修复了 {len(updated_files)} 个包含非规范选择题格式的文件。")
            with st.expander("查看已修复的文件名单", expanded=True):
                for f in updated_files:
                    st.write(f"- {f}")
        else:
            st.info("未发现需要修复的选择题格式文件。")


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
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
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
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(new_content)
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
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(new_content)
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
                    
                    with open(old_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                        
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
        st.subheader("📂 目录选择")
        all_years = get_all_years_globally()
        year = st.selectbox("📅 年份", options=all_years, key="te_year")
        
        paper_name = None
        if year:
            papers = get_papers_by_year(year)
            if papers:
                paper_name = st.selectbox("📄 试卷", options=papers, key="te_paper")
        
        if year and paper_name:
            questions = get_questions_by_paper(year, paper_name)
            if questions:
                q_options = [f"第{q['file'].split('-')[3]}题 ({q['subject']})" for q in questions]
                sel_idx = st.selectbox("❓ 题目", range(len(questions)), format_func=lambda i: q_options[i], key="te_q_select")
                
                if st.button("⬇️ 加载选中题目", key="btn_load_hierarchy", use_container_width=True):
                    st.session_state["tag_edit_file"] = questions[sel_idx]["path"]
                    st.rerun()

    with c_right:
        st.subheader("🔍 搜索选择")
        with st.form("tag_edit_search"):
             # Level 1
             c1a, c1b = st.columns([1, 2])
             search_opts = ["全文内容", "题目类型", "题目内容", "解答内容", "难度星级", "标签"]
             with c1a: 
                 # 移除 form 的约束，让 selectbox 触发 rerun 以更新下一个输入框
                 pass
             
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
            results = []
            # 执行搜索
            for root, dirs, files in os.walk(CHAPTERS_DIR):
                for file in files:
                    if not file.endswith(".tex"): continue
                    path = os.path.join(root, file)
                    
                    if q1 and not check_search_match(path, t1, q1): continue
                    if q2 and not check_search_match(path, t2, q2): continue
                    if q3 and not check_search_match(path, t3, q3): continue
                    
                    results.append({"file": file, "path": path})
            
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
            st.text_area("源码", value=content, height=est_height, disabled=True, key=f"te_preview_left_{file_path}")
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
                
                # 解析原内容提取 Body
                body_match = re.search(r'\\begin\{problem\}.*?\}(.*)\\end\{problem\}', content, re.DOTALL)
                body_content = body_match.group(1) if body_match else content
                
                st.caption("注意：修改元数据将重命名文件并更新文件内容的 problem 头部信息。主板块(第一个)决定文件存储位置。")
                
                if st.form_submit_button("执行重命名与标签更新", type="primary"):
                    new_filename = generate_filename(new_year, new_type, new_name, new_num, new_subject_str)
                    
                    primary_subj = new_subject_str.split("，")[0] if new_subject_str else ""
                    current_primary = current_meta.get("subject", "").split("，")[0]
                    
                    target_dir = os.path.join(CHAPTERS_DIR, primary_subj, new_year)
                    if primary_subj != current_primary or new_year != current_meta.get("year"):
                        ensure_dir(target_dir)
                    new_path = os.path.join(target_dir, new_filename)
                    
                    # 构造 LaTeX 模板内容
                    new_full_text = f"\\begin{{problem}}{{{new_year}}}{{{new_type}}}{{{new_name}}}{{{new_num}}}{{{new_subject_str}}}\n{body_content}\n\\end{{problem}}"
                    
                    try:
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
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(new_fc)
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
    
    # --- 注入 CSS 实现紧凑同行布局 ---
    st.markdown("""
    <style>
    /* 限定作用域，避免污染全局布局 (如知识板块等) */
    div[data-testid="stHorizontalBlock"]:has(> div[data-testid="column"] .star-col),
    div[data-testid="stHorizontalBlock"]:has(> div[data-testid="column"] .rem-lbl) {
        align-items: center !important;
        gap: 0px !important;
        margin-bottom: 5px !important;
    }
    div[data-testid="column"]:has(.star-col) {
        width: 220px !important;
        min-width: 220px !important;
        max-width: 220px !important;
        flex: 0 0 auto !important;
    }
    div[data-testid="column"]:has(.tight-lbl) {
        width: fit-content !important;
        min-width: fit-content !important;
        flex: 0 1 auto !important;
        padding-right: 0px !important;
        padding-left: 0px !important;
    }
    div[data-testid="column"]:has(.tight-btn) {
        width: fit-content !important;
        min-width: fit-content !important;
        flex: 0 0 auto !important;
        padding-left: 4px !important;
    }
    /* 淡灰色 + 按钮 */
    div[data-testid="column"]:has(.tight-btn) div[data-testid="stPopover"] > button {
        color: #666 !important;
        background-color: #f5f6f8 !important;
        border: 1px solid #ddd !important;
        padding: 0px 8px !important;
        min-height: 26px !important;
        height: 26px !important;
        line-height: 1 !important;
        width: auto !important;
    }
    div[data-testid="column"]:has(.tight-btn) div[data-testid="stPopover"] > button:hover {
        background-color: #e2e6ea !important;
        border-color: #ccc !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    with st.container(border=True):
        # === Row 1: 星级与标签 ===
        c_star, c_tag_lbl, c_tag_btn, _ = st.columns([1, 1, 1, 1], vertical_alignment="center")
        
        with c_star:
            st.markdown("<span class='star-col'></span>", unsafe_allow_html=True)
            comp_key = f"star_rating_{fpath}_{st.session_state.get(version_key, 0)}"
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
                st.markdown(f"<span class='tight-lbl'></span>**标签:** **{tags}**", unsafe_allow_html=True)
            else:
                st.markdown("<span class='tight-lbl'></span>**标签:**", unsafe_allow_html=True)
                
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

        # 处理未保存的星级变更弹窗
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

        # === Row 2: 备注 ===
        c_rem_lbl, c_rem_btn, _ = st.columns([1, 1, 1], vertical_alignment="center")
        with c_rem_lbl:
            if remark:
                st.markdown(f"<span class='rem-lbl tight-lbl'></span><span style='margin-right: -18px;'>**备注:** <span style='background-color: #f0f2f6; padding: 2px 6px; border-radius: 4px; color: #555; font-size: 0.95em;'>{remark}</span></span>", unsafe_allow_html=True)
            else:
                st.markdown("<span class='rem-lbl tight-lbl'></span><span style='margin-right: -18px;'>**备注:**</span>", unsafe_allow_html=True)
                
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
        
# ================= 辅助函数：搜索匹配 =================
import datetime

def clear_statistics_cache():
    get_statistics.clear()

@st.cache_data(ttl=10)
def get_statistics():
    stats = {
        "total_questions": 0,
        "total_tikz": 0,
        "today_new_questions": 0,
        "today_mod_questions": 0,
        "today_new_tikz": 0,
        "today_mod_tikz": 0,
        "daily_activity": {}
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

def generate_heatmap_html(daily_activity):
    today = datetime.date.today()
    # 从 2026-01-01 开始计算
    start_date = datetime.date(2026, 1, 1)
    
    # 如果今天还没到2026年，或者就是为了展示全年的效果，可以固定到今天，但为了遵循“从2026年1月1日开始”
    # 我们可以计算到今年年底，或者就是计算到今天（但起点是2026-01-01）
    if today < start_date:
        today = datetime.date(2026, 12, 31) # 如果系统时间不对，默认展示2026一整年
        
    start_sunday = start_date - datetime.timedelta(days=(start_date.weekday() + 1) % 7)
    
    weeks = []
    current_date = start_sunday
    while current_date <= today:
        week = []
        for _ in range(7):
            if current_date < start_date or current_date > today:
                week.append(None)
            else:
                week.append(current_date)
            current_date += datetime.timedelta(days=1)
        weeks.append(week)
        
    months_html = '<div style="display: flex; font-size: 14px; color: #8b949e; height: 20px; align-items: flex-end; padding-bottom: 4px;">'
    current_month = None
    for week in weeks:
        day = next((d for d in week if d is not None), None)
        if day and day.month != current_month:
            months_html += f'<div style="width: 18px; overflow: visible; white-space: nowrap; color: #8b949e;">{day.strftime("%b")}</div>'
            current_month = day.month
        else:
            months_html += f'<div style="width: 18px;"></div>'
    months_html += '</div>'
    
    grid_html = '<div class="heatmap-grid">'
    for week in weeks:
        grid_html += '<div class="heatmap-col">'
        for day in week:
            if day is None:
                grid_html += '<div class="heatmap-cell hidden"></div>'
            else:
                date_str = day.isoformat()
                count = daily_activity.get(date_str, 0)
                if count == 0: level = 0
                elif count <= 2: level = 1
                elif count <= 5: level = 2
                elif count <= 10: level = 3
                else: level = 4
                
                title = f"{count} contributions on {date_str}"
                grid_html += f'<div class="heatmap-cell" data-level="{level}" title="{title}"></div>'
        grid_html += '</div>'
    grid_html += '</div>'
    
    html = f"""
    <style>
    .heatmap-container {{
        display: flex;
        flex-direction: column;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
        background-color: #0d1117;
        color: #c9d1d9;
        padding: 20px;
        border-radius: 10px;
        width: 100%;
        overflow-x: auto;
    }}
    /* 美化内部滚动条 */
    .heatmap-scroll-area {{
        display: flex;
        overflow-x: auto;
        padding-top: 35px; /* 为 tooltip 预留顶部空间 */
        padding-bottom: 15px; /* 给滚动条留出空间 */
    }}
    .heatmap-scroll-area::-webkit-scrollbar {{
        height: 8px;
    }}
    .heatmap-scroll-area::-webkit-scrollbar-track {{
        background: #0d1117;
        border-radius: 4px;
    }}
    .heatmap-scroll-area::-webkit-scrollbar-thumb {{
        background: #444c56; /* 灰色滚动条 */
        border-radius: 4px;
    }}
    .heatmap-scroll-area::-webkit-scrollbar-thumb:hover {{
        background: #768390;
    }}
    .heatmap-title {{
        font-size: 18px;
        font-weight: 600;
        margin-bottom: -10px; /* 减小标题自带的底部边距，依靠 scroll-area 的 padding-top 撑开 */
        color: #c9d1d9;
    }}
    .heatmap-grid {{
        display: flex;
        gap: 4px;
    }}
    .heatmap-col {{
        display: flex;
        flex-direction: column;
        gap: 4px;
    }}
    .heatmap-cell {{
        width: 14px;
        height: 14px;
        border-radius: 3px;
        background-color: #2d333b;
        position: relative;
    }}
    .heatmap-cell[data-level="1"] {{ background-color: #0e4429; }}
    .heatmap-cell[data-level="2"] {{ background-color: #006d32; }}
    .heatmap-cell[data-level="3"] {{ background-color: #26a641; }}
    .heatmap-cell[data-level="4"] {{ background-color: #39d353; }}
    .heatmap-cell.hidden {{ background-color: transparent; pointer-events: none; }}
    
    .heatmap-footer {{
        display: flex;
        justify-content: flex-end;
        width: 100%;
        margin-top: 10px;
        font-size: 14px;
        color: #8b949e;
        align-items: center;
    }}
    .legend {{
        display: flex;
        align-items: center;
        gap: 4px;
    }}
    .legend-cell {{
        width: 14px;
        height: 14px;
        border-radius: 3px;
    }}
    .heatmap-cell:hover::after {{
        content: attr(title);
        position: absolute;
        bottom: 100%;
        left: 50%;
        transform: translateX(-50%);
        background-color: rgba(0, 0, 0, 0.8);
        color: #fff;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 14px;
        white-space: nowrap;
        z-index: 9999; /* 提高层级，防止被月份栏遮挡 */
        pointer-events: none;
        margin-bottom: 5px;
    }}
    </style>
    <div class="heatmap-container">
        <div class="heatmap-title">Active Days</div>
        <div class="heatmap-scroll-area">
            <div style="display: flex; flex-direction: column; gap: 4px; font-size: 14px; color: #8b949e; margin-right: 8px; margin-top: 20px; position: sticky; left: 0; background-color: #0d1117; z-index: 2;">
                <div style="height: 14px;"></div>
                <div style="height: 14px; line-height: 14px;">M</div>
                <div style="height: 14px;"></div>
                <div style="height: 14px; line-height: 14px;">W</div>
                <div style="height: 14px;"></div>
                <div style="height: 14px; line-height: 14px;">F</div>
                <div style="height: 14px;"></div>
            </div>
            <div>
                {months_html}
                {grid_html}
            </div>
        </div>
        <div class="heatmap-footer">
            <div class="legend">
                Less
                <div class="legend-cell" style="background-color: #2d333b;"></div>
                <div class="legend-cell" style="background-color: #0e4429;"></div>
                <div class="legend-cell" style="background-color: #006d32;"></div>
                <div class="legend-cell" style="background-color: #26a641;"></div>
                <div class="legend-cell" style="background-color: #39d353;"></div>
                More
            </div>
        </div>
    </div>
    """
    return html

def render_statistics_dashboard():
    stats = get_statistics()
    
    st.markdown("### 📊 数据统计")
    
    # 添加指标卡片的自定义 CSS
    st.markdown("""
    <style>
    div[data-testid="stMetric"] {
        background-color: rgba(128, 128, 128, 0.05);
        border: 1px solid rgba(128, 128, 128, 0.4);
        padding: 10px 15px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # 指标数据
    cols = st.columns(6)
    cols[0].metric("题库总题目数", stats["total_questions"])
    cols[1].metric("题库Tikz总数", stats["total_tikz"])
    cols[2].metric("今日新增题目", stats["today_new_questions"])
    cols[3].metric("今日改动题目", stats["today_mod_questions"])
    cols[4].metric("今日新增Tikz", stats["today_new_tikz"])
    cols[5].metric("今日改动Tikz", stats["today_mod_tikz"])
    
    st.write("")
    
    # 热力图与滑动条
    heatmap_html = generate_heatmap_html(stats["daily_activity"])
    st.markdown(heatmap_html, unsafe_allow_html=True)


# ================= 主程序 =================
def main():
    st.set_page_config(page_title="高中数学题库管理系统", layout="wide")
    
    # 顶部布局：分为左右两列，左侧导航，右侧搜索，各占一半
    c_header_nav, c_header_search = st.columns([1, 1])
    
    # 定义导航回调
    def on_nav_change():
        st.session_state["global_search_active"] = False

    with c_header_nav:
        st.title("📚 MathCyclus-灵兮题库助手")
        st.caption("高中数学题库管理系统")
        
        st.write("")
        # 将统计面板放在标题和四大板块之间
        render_statistics_dashboard()
        st.write("")
        
        # 导航栏 (自定义按钮样式) - 放到左侧，宽度占左半边
        nav_options = ["📝 录入新题", "🔍 全局浏览与编辑", "🖨️ 组卷服务", "🛠️ 批量工具"]
        if "main_nav_selection" not in st.session_state:
            st.session_state["main_nav_selection"] = nav_options[0]
            
        st.markdown("""
            <style>
            /* 强制设置这四个导航按钮的高度和字体 */
            div[data-testid="column"] button[kind="secondary"],
            div[data-testid="column"] button[kind="primary"] {
                border-radius: 15px !important;
                height: 120px !important;       
                font-size: 1.8rem !important;  
                font-weight: bold !important;
                display: block !important;
            }
            div[data-testid="column"] button p {
                font-size: 1.8rem !important;
                font-weight: bold !important;
            }
            </style>
        """, unsafe_allow_html=True)

        # 在左侧面板，将全局搜索框移至此处（四个导航按钮上方）
        st.markdown("##### 🔍 多级筛选搜索")
        
        c_s_1, c_s_2, c_s_3 = st.columns([0.25, 0.6, 0.15])
        search_opts = ["全文内容", "题目类型", "题目内容", "解答内容", "难度星级", "标签"]
        with c_s_1:
            g_type_1 = st.selectbox("一级类型", search_opts, index=0, key="g_t1")
        with c_s_2:
            if g_type_1 == "题目类型":
                # 移除 label_visibility="collapsed" 以便对齐，并显示标签
                g_query_1 = st.selectbox("一级关键词", ["选择题", "填空题", "解答题"], key="g_q1_sel")
            else:
                g_query_1 = st.text_input("一级关键词", placeholder="输入一级关键词...", key="g_q1")
        with c_s_3:
            # 为了让搜索按钮和输入框对齐，重新加回空行
            st.write("")
            st.write("")
            g_submit = st.button("🔍 搜索", use_container_width=True)
            
        # 直接显示多级筛选，不使用 expander，也不使用分割线
        c_adv_1, c_adv_2 = st.columns([1, 2])
        with c_adv_1: 
            g_type_2 = st.selectbox("二级类型", search_opts, index=0, key="g_t2")
        with c_adv_2: 
            if g_type_2 == "题目类型":
                g_query_2 = st.selectbox("二级关键词", ["选择题", "填空题", "解答题"], key="g_q2_sel")
            else:
                g_query_2 = st.text_input("二级关键词", key="g_q2")
        
        c_adv_3, c_adv_4 = st.columns([1, 2])
        with c_adv_3: 
            g_type_3 = st.selectbox("三级类型", search_opts, index=0, key="g_t3")
        with c_adv_4: 
            if g_type_3 == "题目类型":
                g_query_3 = st.selectbox("三级关键词", ["选择题", "填空题", "解答题"], key="g_q3_sel")
            else:
                g_query_3 = st.text_input("三级关键词", key="g_q3")
            
        st.write("") # 增加一点间距

    with c_header_search:
        # 移除原先的顶部间距
        
        # --- 题库规范说明 ---
        st.markdown("""
        ### 📖 题库文件命名与书写规范说明
        
        欢迎使用 MathCyclus 题库管理系统！为了保证题库的整洁、规范以及程序的正常解析，请仔细阅读并严格遵循以下书写与命名规范。这不仅有助于您更高效地管理试题，也方便未来的协作者快速上手。
        
        **📂 一、 文件命名规范**
        
        所有题目的 `.tex` 文件必须严格按照以下 **“五段式”** 结构命名，各部分之间使用英文连字符 `-` 连接，格式为：
        `<font color="red">**年份-试卷类别-试卷名称-题号-知识板块.tex**</font>`
        *示例：`2024-G-新高考I卷-12-数列，集合.tex`*
        - **年份**：四位纯数字（如 `2024`）；
        - **试卷类别**：必须是系统预设的缩写代码，仅限 `G`(高考题)、`M`(模拟题)、`W`(外国题)、`XK`(学考题)、`XS`(线上联考)；
        - **试卷名称**：明确试卷全称，如 `新课标I卷`、`浙江学考` 等，尽量避免包含特殊符号；
        - **题号**：纯数字（如 `12`），多问不要在此体现，未来可能会更新；
        - **知识板块**：题目涉及的考点。如涉及多个板块，必须用**中文全角逗号 `，`** 分隔，且将**最核心的主板块放在最前**（如 `函数，导数，数列，圆锥曲线`）。系统会根据首个主板块自动将文件归类到对应的物理文件夹中。

        **📝 二、 LaTeX 源码书写格式**
        
        每个题目文件内部必须且仅包含一个完整的 `problem` 环境，环境后跟随的五个参数括号必须与文件名中的五段信息完全一一对应：
        ```latex
        \\begin{problem}{年份}{试卷类别}{试卷名称}{题号}{知识板块}
        这里是具体的题目题干内容...
        (注意：行内公式请用 $ 包裹，居中的行间公式请用 $$ 包裹，禁止使用 \\(\\) 或 \\[\\])
        \\end{problem}
        ```
        
        **💡 三、 附加规范与建议**
        
        1. **解答与解析**：如果题目附带详细解析，请在题干的 `\\end{problem}` 之后空出一行，并使用 `\\begin{solutions}` 和 `\\end{solutions}` 环境将解答内容包裹起来。保持代码结构清晰，不仅有助于渲染美观，更方便后续维护检索。
        2. **TikZ 绘图**：系统支持并鼓励直接在题干源码中插入原生的 `\\begin{tikzpicture}...\\end{tikzpicture}` 代码。您在前端保存时，系统会自动在后台的 `相关图` 文件夹中为您生成剥离出来的独立副本，同时主文件内仍会保留原生 TikZ 源码，以便您随时在线实现所见即所得的编辑。
        3. **选择题排版**：遇到选择题时，请使用 `\\begin{choices}` 与 `\\choice{{选项内容}}` 的宏包结构，并务必确保选项内容被**两层大括号**紧紧包裹。
        """, unsafe_allow_html=True)
        
        st.divider() # 说明和按钮之间的分割线
        
        # 将原有的三个导航按钮移到右侧规范说明的下方
        # 增加按钮之间的间距，通过在两行按钮之间插入空白行，以及在按钮列中间插入空白列来实现
        # 1. 缩小按钮宽度 (通过改变列宽比例)
        # 第一行按钮
        nav_cols_row1 = st.columns([2.5, 0.1, 2.5]) # 减小中间间隙，适当增加按钮宽度占比
        btn_type_0 = "primary" if st.session_state["main_nav_selection"] == nav_options[0] else "secondary"
        with nav_cols_row1[0]:
            if st.button(nav_options[0], key="main_nav_0", type=btn_type_0, use_container_width=True):
                st.session_state["main_nav_selection"] = nav_options[0]
                st.session_state["scroll_trigger"] = True
                on_nav_change()
                st.rerun()
                
        btn_type_1 = "primary" if st.session_state["main_nav_selection"] == nav_options[1] else "secondary"
        with nav_cols_row1[2]:
            if st.button(nav_options[1], key="main_nav_1", type=btn_type_1, use_container_width=True):
                st.session_state["main_nav_selection"] = nav_options[1]
                st.session_state["scroll_trigger"] = True
                on_nav_change()
                st.rerun()
        
        # 2. 增加垂直间距 (保留一个换行，避免太宽)
        st.write("") 

        # 第二行按钮
        nav_cols_row2 = st.columns([2.5, 0.1, 2.5])
        btn_type_2 = "primary" if st.session_state["main_nav_selection"] == nav_options[2] else "secondary"
        with nav_cols_row2[0]:
            if st.button(nav_options[2], key="main_nav_2", type=btn_type_2, use_container_width=True):
                st.session_state["main_nav_selection"] = nav_options[2]
                st.session_state["scroll_trigger"] = True
                on_nav_change()
                st.rerun()
                
        btn_type_3 = "primary" if st.session_state["main_nav_selection"] == nav_options[3] else "secondary"
        with nav_cols_row2[2]:
            if st.button(nav_options[3], key="main_nav_3", type=btn_type_3, use_container_width=True):
                st.session_state["main_nav_selection"] = nav_options[3]
                st.session_state["scroll_trigger"] = True
                on_nav_change()
                st.rerun()
                    
        selected_nav = st.session_state["main_nav_selection"]
        # --- 题库规范说明结束 ---

    st.divider()

    # 处理搜索提交
    if g_submit:
        st.session_state["global_search_active"] = True
        st.session_state["scroll_to_search"] = True
        st.session_state["g_search_params"] = {
            "t1": g_type_1, "q1": g_query_1,
            "t2": g_type_2, "q2": g_query_2,
            "t3": g_type_3, "q3": g_query_3
        }
    
    # 渲染逻辑
    if st.session_state.get("global_search_active"):
        # === 显示搜索结果 ===
        st.divider()
        c_res_header, c_res_close = st.columns([8, 1])
        with c_res_header:
            st.subheader("🔍 全局搜索结果")
        with c_res_close:
            if st.button("❌ 关闭搜索", use_container_width=True):
                st.session_state["global_search_active"] = False
                st.rerun()
                
        params = st.session_state.get("g_search_params", {})
        results = []
        
        # 执行搜索
        if params.get("q1") or params.get("q2") or params.get("q3"):
            for root, dirs, files in os.walk(CHAPTERS_DIR):
                for file in files:
                    if not file.endswith(".tex"): continue
                    if file.startswith("content_"): continue
                    if "相关图" in root or " 图" in file: continue
                    path = os.path.join(root, file)
                    
                    if params.get("q1") and not check_search_match(path, params["t1"], params["q1"]): continue
                    if params.get("q2") and not check_search_match(path, params["t2"], params["q2"]): continue
                    if params.get("q3") and not check_search_match(path, params["t3"], params["q3"]): continue
                    
                    results.append({"file": file, "path": path})
        
        if results:
            # 结果头部：信息 + 展开全部Toggle
            c_res_info, c_res_toggle = st.columns([4, 1])
            with c_res_info:
                st.info(f"找到 {len(results)} 个匹配项")
            with c_res_toggle:
                expand_all = st.checkbox("展开全部详情", value=True, key="g_expand_all_toggle")

            for idx, res in enumerate(results):
                with st.expander(f"📄 {res['file']}", expanded=expand_all):
                    file_path = res["path"]
                    edit_mode_key = f"g_edit_mode_{file_path}"
                    
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                    except:
                        st.error("无法读取文件")
                        continue
                        
                    c_edit, c_view = st.columns([1, 1])
                    
                    with c_edit:
                        est_height = get_editor_height(content)
                        is_editing = st.session_state.get(edit_mode_key, False)
                        text_area_key = f"g_text_{file_path}_{idx}"
                        
                        if is_editing:
                            new_content = st.text_area("源码", value=content, height=est_height, key=text_area_key)
                            if st.button("💾 保存修改", key=f"g_save_{idx}", type="primary"):
                                save_modified_tex_file(file_path, new_content)
                                st.session_state[edit_mode_key] = False
                                st.success("保存成功！")
                                time.sleep(0.5)
                                st.rerun()
                        else:
                            st.text_area("源码", value=content, height=est_height, disabled=True, key=text_area_key + "_readonly")
                            
                            tag_edit_key = f"tag_edit_mode_{file_path}"
                            is_tag_editing = st.session_state.get(tag_edit_key, False)
                            
                            btn_c1, btn_c2 = st.columns(2)
                            with btn_c1:
                                if st.button("✏️ 开始修改tex内容", key=f"g_start_{idx}"):
                                    st.session_state[edit_mode_key] = True
                                    st.rerun()
                            with btn_c2:
                                if is_tag_editing:
                                    if st.button("✅ 完成修改板块标签", key=f"g_tag_save_{idx}", type="primary"):
                                        new_tags = st.session_state.get(f"g_tag_select_{idx}")
                                        if new_tags:
                                            if update_file_tags(file_path, new_tags):
                                                st.toast("标签修改成功！", icon="✅")
                                                st.session_state[tag_edit_key] = False
                                                time.sleep(0.5)
                                                st.rerun()
                                            else:
                                                st.error("文件名格式不支持修改标签")
                                else:
                                    if st.button("🏷️ 开始修改板块标签", key=f"g_tag_start_{idx}"):
                                        st.session_state[tag_edit_key] = True
                                        st.rerun()
                                        
                            if is_tag_editing:
                                current_tags = extract_tags_from_fpath(file_path)
                                valid_tags = [t for t in current_tags if t in SUBJECTS] or [SUBJECTS[0]]
                                st.multiselect("修改知识板块 (首个为主)", options=SUBJECTS, default=valid_tags, key=f"g_tag_select_{idx}")
                                
                    with c_view:
                        st.markdown(latex_to_markdown(content), unsafe_allow_html=True)
                        
        else:
            st.warning("未找到匹配项")
            
    else:
        # === 显示选中的功能页面 ===
        if selected_nav == "📝 录入新题":
            page_entry()
        elif selected_nav == "🔍 全局浏览与编辑":
            page_browse()
        elif selected_nav == "🖨️ 组卷服务":
            page_exam_paper_generation()
        elif selected_nav == "🛠️ 批量工具":
            page_tools()

    if st.session_state.get("scroll_trigger", False):
        st.session_state["scroll_trigger"] = False
        import streamlit.components.v1 as components
        nav_titles = {
            "📝 录入新题": "录入新题",
            "🔍 全局浏览与编辑": "浏览与编辑",
            "🖨️ 组卷服务": "组卷服务",
            "🛠️ 批量工具": "批量工具"
        }
        title_text = nav_titles.get(selected_nav, "")
        if title_text:
            js = f"""
            <script>
                const elements = window.parent.document.querySelectorAll('h2');
                for (let el of elements) {{
                    if (el.innerText.includes('{title_text}')) {{
                        el.scrollIntoView({{behavior: 'smooth', block: 'start'}});
                        break;
                    }}
                }}
            </script>
            """
            components.html(js, height=0, width=0)

    if st.session_state.get("scroll_to_search", False):
        st.session_state["scroll_to_search"] = False
        import streamlit.components.v1 as components
        js = """
        <script>
            const elements = window.parent.document.querySelectorAll('h3');
            for (let el of elements) {
                if (el.innerText.includes('全局搜索结果')) {
                    el.scrollIntoView({behavior: 'smooth', block: 'start'});
                    break;
                }
            }
        </script>
        """
        components.html(js, height=0, width=0)

if __name__ == "__main__":
    main()