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
from utils.latex_ops import *

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
                # 设置超时时间为 60 秒
                response = requests.post(url, headers=headers, json=payload, timeout=60)
            except requests.exceptions.Timeout:
                return "❌ 请求超时 (60s)，请检查网络或稍后重试。"
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

        st.divider()

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

            c1, c2 = st.columns(2)
            with c1:
                year = st.text_input("年份", key="entry_year")
                
                # 修复试卷类别选择：如果 session_state 中的值不在选项中，回退到默认
                current_p_type = st.session_state.get("entry_p_type", "G")
                type_opts = list(PAPER_TYPES.keys())
                if current_p_type not in type_opts:
                    current_p_type = "G"
                    st.session_state["entry_p_type"] = "G"
                default_type_idx = type_opts.index(current_p_type)
                
                p_type_code = st.selectbox("试卷类别", options=type_opts, index=default_type_idx, format_func=lambda x: f"{x} ({PAPER_TYPES[x]})")
                # 手动更新 session_state，防止 key 绑定引发的刷新问题
                st.session_state["entry_p_type"] = p_type_code
                
            with c2:
                # 知识板块推断与选择逻辑优化
                
                # 只有当内容发生实质性变化（如粘贴、AI返回）时，才去触发自动推断，
                # 而不是每次渲染都强制推断并覆盖 session_state。
                # 为此，我们对比上一次推断时的内容。
                current_content = st.session_state.get("entry_content", "")
                last_inferred_content = st.session_state.get("_last_inferred_content", None)
                
                if st.session_state.get("_ai_override_subjects", False):
                    # AI 刚刚返回，绝对优先 AI 提取的标签
                    st.session_state["_ai_override_subjects"] = False
                    st.session_state["_last_inferred_content"] = current_content # 标记当前内容已处理
                elif current_content != last_inferred_content and current_content.strip() != "":
                    # 发现内容有新变动（比如用户刚粘贴了一段文本），触发简单的关键词推断
                    inferred_subjects = []
                    for s in SUBJECTS:
                        if len(s) > 1 and s in current_content:
                            inferred_subjects.append(s)
                    if inferred_subjects:
                        st.session_state["entry_subject_multi"] = inferred_subjects
                    st.session_state["_last_inferred_content"] = current_content

                # 使用 st.multiselect，不要绑定 key 到 entry_subject_multi 强制双向绑定，
                # 而是使用 default 参数读取，这样用户可以自由增删标签。
                current_multi = st.session_state.get("entry_subject_multi", [SUBJECTS[0]])
                # 过滤掉不在 SUBJECTS 里的非法值
                valid_current_multi = [s for s in current_multi if s in SUBJECTS]
                if not valid_current_multi:
                    valid_current_multi = [SUBJECTS[0]]
                    
                subjects = st.multiselect("知识板块 (首个为主)", options=SUBJECTS, default=valid_current_multi)
                # 将用户的选择实时同步回 session_state
                st.session_state["entry_subject_multi"] = subjects
                
                subject = "，".join(subjects) if subjects else SUBJECTS[0]
                number = st.text_input("题号", key="entry_number")
                
            paper_name = st.text_input("试卷名称", key="entry_paper_name")
            
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
                
                if not s_content:
                    st.toast("题目内容不能为空", icon="⚠️")
                    return
                
                s_filename = generate_filename(s_year, s_type, s_paper, s_num, s_subj)
                primary_subj = s_subj.split("，")[0]
                s_save_dir = os.path.join(CHAPTERS_DIR, primary_subj, s_year)
                ensure_dir(s_save_dir)
                s_file_path = os.path.join(s_save_dir, s_filename)
                
                full_text = generate_latex_template(s_year, s_type, s_paper, s_num, s_subj, s_content)
                
                # 提取并替换 TikZ 代码
                full_text = extract_and_replace_tikz(full_text, s_filename, s_save_dir)
                
                try:
                    with open(s_file_path, "w", encoding="utf-8") as f:
                        f.write(full_text)
                    st.toast(f"成功保存到: {s_filename}", icon="✅")
                    # 清空内容以便下一题
                    st.session_state["entry_content"] = ""
                    # 题号自动+1
                    if s_num.isdigit():
                         st.session_state["entry_number"] = str(int(s_num) + 1)
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
                # 垂直对齐占位符 (约等于 Label 高度)
                st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                if st.button("🔄 同步", help="将当前设置的统一信息应用到下方文本框中的所有简写文件名"):
                    current_txt = st.session_state.get("batch_content", "")
                    if current_txt and u_year and u_paper:
                        # 正则查找 ---...---
                        # 替换逻辑：找到 ---...---，如果内容只是 题号-板块，则替换为全名
                        def replace_header(match):
                            content = match.group(1).strip() # e.g. "1-集合.tex"
                            name_body = content.replace('.tex', '')
                            segs = name_body.split('-')
                            if len(segs) == 2: # 只有题号和板块
                                full_name = generate_filename(u_year, u_type, u_paper, segs[0], segs[1])
                                return f"---{full_name}---"
                            return match.group(0) # 保持原样

                        new_txt = re.sub(r'---(.+?)---', replace_header, current_txt)
                        st.session_state["batch_content"] = new_txt
                        st.toast("文件名已同步更新", icon="✅")
                        st.rerun()
                    else:
                        st.warning("请先填写完整信息和文本内容")


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
                                
                                try:
                                    with open(file_path, "w", encoding="utf-8") as f:
                                        f.write(file_content)
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
                                
                                try:
                                    with open(file_path, "w", encoding="utf-8") as f:
                                        f.write(file_content)
                                    count += 1
                                    log_msg.append({"status": "success", "file": filename, "path": file_path})
                                except Exception as e:
                                    log_msg.append({"status": "error", "file": filename, "msg": str(e)})
                            else:
                                log_msg.append({"status": "skip", "file": filename, "msg": "文件名格式错误"})
                    
                    st.success(f"处理完成，共保存 {count} 个文件")
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
    browse_mode = st.radio("浏览模式", ["按知识板块浏览", "按试卷浏览"], horizontal=True, label_visibility="collapsed")
    
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

                                st.markdown(f"### {q_label}")
                                
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

                                st.markdown(f"### {q_label}")
                                
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
                
    else: # 按试卷浏览

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
                        st.subheader(q_label)
                        
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
    </style>
    """, unsafe_allow_html=True)
    
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
            st.session_state["exam_blocks"] = [
                b for b in st.session_state["exam_blocks"]
                if b["type"] == "section" or b["path"] in st.session_state["exam_selected_qs"]
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

def render_typesetting_workspace():
    st.subheader("🖨️ 试卷排版工作台")
    
    # 返回按钮与生成按钮栏
    c_back, c_gen = st.columns([1, 1])
    with c_back:
        def go_back_to_selection():
            st.session_state["exam_mode_stage"] = "selection"
        st.button("⬅️ 返回继续选题", on_click=go_back_to_selection)
    with c_gen:
        if st.button("🖨️ 确认生成试卷 (开发中)", type="primary", use_container_width=True):
            st.toast("即将开发真实的 PDF 生成与 LaTeX 拼装功能！", icon="🚀")
    
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
            
    # 第一行：大题/章节
    c_label_1, c_input_1, c_pos_1, c_submit_1 = st.columns([1.5, 3.5, 1.5, 1.5])
    with c_label_1:
        st.markdown("<div style='padding-top:8px;'><b>🗂️ 插入大题/章节</b></div>", unsafe_allow_html=True)
    with c_input_1:
        sec_title = st.text_input("文本内容", placeholder="例如：一、选择题", label_visibility="collapsed", key="sec_title_input")
    with c_pos_1:
        sec_pos = st.selectbox("插入位置", insert_positions, index=len(insert_positions)-1, label_visibility="collapsed", key="sec_pos")
    with c_submit_1:
        if st.button("确认插入", key="sec_submit", use_container_width=True):
            if sec_title:
                _insert_block("section", sec_title, sec_pos)
                st.rerun()
                
    # 第二行：小节/说明文字
    c_label_2, c_input_2, c_pos_2, c_submit_2 = st.columns([1.5, 3.5, 1.5, 1.5])
    with c_label_2:
        st.markdown("<div style='padding-top:8px; color: #8b949e;'><b>📝 插入小节/说明</b></div>", unsafe_allow_html=True)
    with c_input_2:
        subsec_title = st.text_input("文本内容", placeholder="例如：(一) 单选题", label_visibility="collapsed", key="subsec_title_input")
    with c_pos_2:
        subsec_pos = st.selectbox("插入位置", insert_positions, index=len(insert_positions)-1, label_visibility="collapsed", key="subsec_pos")
    with c_submit_2:
        if st.button("确认插入", key="subsec_submit", use_container_width=True):
            if subsec_title:
                _insert_block("subsection", subsec_title, subsec_pos)
                st.rerun()
                
    st.markdown("<br>", unsafe_allow_html=True)
    
    # 遍历显示 Blocks (单列流式布局，改为左右两栏)
    blocks = st.session_state["exam_blocks"]
    q_counter = 1
    
    for i, blk in enumerate(blocks):
        # 每一行分为左右两列：左侧显示标题和控制按钮，右侧显示渲染结果
        c_left, c_right = st.columns([3, 7], gap="large")
        
        with c_left:
            if blk["type"] == "section":
                st.markdown(f"<h4 style='color: #58a6ff; margin-top: 0;'>🗂️ {blk['title']}</h4>", unsafe_allow_html=True)
            elif blk["type"] == "subsection":
                st.markdown(f"<h5 style='color: #8b949e; margin-top: 0;'>📝 {blk['title']}</h5>", unsafe_allow_html=True)
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
            if blk["type"] == "section":
                st.markdown(f"<h3 style='color: #58a6ff; margin: 0;'>{blk['title']}</h3>", unsafe_allow_html=True)
            elif blk["type"] == "subsection":
                st.markdown(f"<h4 style='color: #8b949e; border-left: 4px solid #8b949e; padding-left: 10px; margin: 0;'>{blk['title']}</h4>", unsafe_allow_html=True)
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
    
    st.subheader("1. 全国卷名称标准化")
    st.markdown("""
    根据规则自动重命名全国卷文件：
    - 2020-2022: **新高考卷**
    - 2023-2025: **新课标卷**
    *(跳过地方卷和甲/乙卷)*
    """)
    
    if st.button("执行标准化检查与重命名"):
        count = standardize_national_papers()
        st.success(f"操作完成，共处理 {count} 个文件")

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
             with c1a: t1 = st.selectbox("一级类型", ["题目文件名", "题目内容", "解答内容", "标签"], key="te_s_t1", label_visibility="collapsed")
             with c1b: q1 = st.text_input("一级检索", placeholder="一级关键词", key="te_s_q1", label_visibility="collapsed")
             
             # Level 2
             c2a, c2b = st.columns([1, 2])
             with c2a: t2 = st.selectbox("二级类型", ["题目文件名", "题目内容", "解答内容", "标签"], key="te_s_t2", label_visibility="collapsed")
             with c2b: q2 = st.text_input("二级检索", placeholder="筛选词", key="te_s_q2", label_visibility="collapsed")
             
             # Level 3
             c3a, c3b = st.columns([1, 2])
             with c3a: t3 = st.selectbox("三级类型", ["题目文件名", "题目内容", "解答内容", "标签"], key="te_s_t3", label_visibility="collapsed")
             with c3b: q3 = st.text_input("三级检索", placeholder="筛选词", key="te_s_q3", label_visibility="collapsed")
             
             submitted = st.form_submit_button("🔍 搜索", type="primary", use_container_width=True)
             
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
                    
                    new_full_text = generate_latex_template(new_year, new_type, new_name, new_num, new_subject_str, body_content)
                    
                    try:
                        with open(new_path, "w", encoding="utf-8") as f:
                            f.write(new_full_text)
                        
                        if new_path != file_path:
                            os.remove(file_path)
                            
                        st.success(f"更新成功！\n旧: {os.path.basename(file_path)}\n新: {new_filename}")
                        st.session_state["tag_edit_file"] = new_path
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"更新失败: {e}")

# ================= 辅助函数：搜索匹配 =================
import datetime

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
                
                c_date = datetime.datetime.fromtimestamp(ctime).date().isoformat()
                
                is_today_created = ctime >= today_start
                is_today_modified = mtime >= today_start and not is_today_created
                
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
                        
                    stats["daily_activity"][c_date] = stats["daily_activity"].get(c_date, 0) + 1
                    
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
        with st.form("global_search_form"):
            st.markdown("##### 🔍 多级筛选搜索")
            
            c_s_1, c_s_2, c_s_3 = st.columns([0.25, 0.6, 0.15])
            with c_s_1:
                g_type_1 = st.selectbox("一级类型", ["题目文件名", "题目内容", "解答内容"], key="g_t1")
            with c_s_2:
                g_query_1 = st.text_input("一级关键词", placeholder="输入一级关键词...", key="g_q1")
            with c_s_3:
                # 为了让搜索按钮和输入框对齐，添加一点空白
                st.write("")
                st.write("")
                g_submit = st.form_submit_button("🔍 搜索", use_container_width=True)
                
            # 直接显示多级筛选，不使用 expander，也不使用分割线
            c_adv_1, c_adv_2 = st.columns([1, 2])
            with c_adv_1: g_type_2 = st.selectbox("二级类型", ["题目文件名", "题目内容", "解答内容"], key="g_t2")
            with c_adv_2: g_query_2 = st.text_input("二级关键词", key="g_q2")
            
            c_adv_3, c_adv_4 = st.columns([1, 2])
            with c_adv_3: g_type_3 = st.selectbox("三级类型", ["题目文件名", "题目内容", "解答内容"], key="g_t3")
            with c_adv_4: g_query_3 = st.text_input("三级关键词", key="g_q3")
            
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