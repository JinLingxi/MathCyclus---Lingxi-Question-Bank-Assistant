import os
import re
from .core_config import CHAPTERS_DIR, BASE_DIR
from .file_ops import ensure_dir
from .tikz_ops import get_tikz_image_b64

def get_editor_height(content):
    line_count = content.count('\n') + 2
    # 每行大约 26 像素，设置最小高度 150，最大高度 800
    base_height = max(150, min(800, line_count * 26))
    
    # 只有当包含 TikZ 时，才额外增加高度
    tikz_count = content.count(r'\begin{tikzpicture}')
    if tikz_count > 0:
        return base_height + tikz_count * 300
    return base_height

def latex_to_markdown(content):
    """简单的 LaTeX 转 Markdown 用于预览"""
    # 提取 problem 环境参数
    header = ""
    match = re.search(r'\\begin\{problem\}\{(.*?)\}\{(.*?)\}\{(.*?)\}\{(.*?)\}\{(.*?)\}', content)
    if match:
        year, ptype, name, num, subj = match.groups()
        # 将标题格式修改为: 【年份 试卷名称，题号】（板块名称）
        header = f"**【{year}  {name}，{num}】**"
        # 移除 begin 标签
        content = content[match.end():]
    
    # 移除 end 标签
    content = content.replace(r'\end{problem}', '')
    
    # 处理 solution/solutions 环境
    content = re.sub(r'\\begin\{solutions?\}', '\n\n**【解答】**\n', content)
    content = re.sub(r'\\end\{solutions?\}', '', content)
    
    # 处理 choices 环境 (A. B. C. D. 样式)
    def replace_choices_env(match):
        content_inner = match.group(1)
        # 按 \choice 分割
        parts = re.split(r'\\choice', content_inner)
        
        new_inner = parts[0] # 保留第一个 \choice 前的内容（通常是空的或换行）
        choice_idx = 0
        
        for p in parts[1:]:
            # 生成标号 A. B. C. ... 并应用类似 Times New Roman 的正体样式
            letter = chr(65 + choice_idx)
            label = f'<span style="font-family: \'Times New Roman\', Times, serif;">{letter}.</span>'
            choice_idx += 1
            
            # 清理括号
            p = p.strip()
            if p.startswith("{{") and p.endswith("}}"):
                p = p[2:-2]
            elif p.startswith("{") and p.endswith("}"):
                p = p[1:-1]
            
            new_inner += f"\n{label} {p}\n"
            
        return new_inner

    content = re.sub(r'\\begin\{choices\}(.*?)\\end\{choices\}', replace_choices_env, content, flags=re.DOTALL)
    
    # 移除残留的标签（以防万一）
    content = content.replace(r'\begin{choices}', '').replace(r'\end{choices}', '')
    
    # 处理填空题下划线 (简单的 HTML 替换)
    content = re.sub(r'\\underline\{\\hspace\{.*?\}\}', r'<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>', content)
    content = re.sub(r'\\underline\{(.*?)\}', r'<u>\1</u>', content)
    
    # 处理剩下的 \hspace{...} 为全角空格
    content = re.sub(r'\\hspace\{.*?\}', '　', content)
    content = content.replace(r'\quad', '　')
    content = content.replace(r'\hfill', '　')
    
    # 处理 \textbf
    content = re.sub(r'\\textbf\{(.*?)\}', r'**\1**', content, flags=re.DOTALL)
    
    # 处理 \circled{} (带圈数字)
    def replace_circled(match):
        num = match.group(1)
        return f'<span style="display:inline-block; width:1.2em; height:1.2em; line-height:1.2em; text-align:center; border-radius:50%; border:1px solid currentColor; font-size:0.85em;">{num}</span>'

    content = re.sub(r'\\circled\{(.*?)\}', replace_circled, content)

    # 1. 替换被抽离的 \input{... 相关图/...} 命令为渲染图片
    def replace_input_tikz(match):
        input_path = match.group(1)
        if "相关图" in input_path or "图" in input_path:
            full_path = os.path.join(BASE_DIR, input_path)
            if not full_path.endswith('.tex'):
                full_path += '.tex'
                
            png_path = full_path.replace('.tex', '.png')
            
            if os.path.exists(full_path):
                with open(full_path, 'r', encoding='utf-8') as f:
                    tikz_code = f.read()
                
                b64, err = get_tikz_image_b64(tikz_code, BASE_DIR, source_tex_path=full_path, target_png_path=png_path)
                if b64:
                    return f"\n\n<div style='text-align: center;'><img src='data:image/png;base64,{b64}' style='max-width:100%; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin: 10px 0;'></div>\n\n"
                elif err == "MISSING_PYMUPDF":
                    return f"\n\n> ⚠️ **提示**：检测到 TikZ 绘图。请在终端运行 `pip install pymupdf` 安装依赖后，即可渲染为图片预览。\n\n```latex\n{tikz_code}\n```\n\n"
                else:
                    return f"\n\n> ⚠️ **TikZ 编译失败** (`{err}`)。请检查 LaTeX 语法或本地环境。\n\n```latex\n{tikz_code}\n```\n\n"
            else:
                return f"\n> ⚠️ 找不到引用的图片文件: `{input_path}`\n"
        return match.group(0)

    content = re.sub(r'\\input\{(.*?)\}', replace_input_tikz, content)

    # 2. 替换题库中遗留的内联 \begin{tikzpicture} ... \end{tikzpicture}
    def replace_inline_tikz(match):
        tikz_code = match.group(0)
        b64, err = get_tikz_image_b64(tikz_code, BASE_DIR)
        if b64:
            return f"\n\n<div style='text-align: center;'><img src='data:image/png;base64,{b64}' style='max-width:100%; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin: 10px 0;'></div>\n\n"
        elif err == "MISSING_PYMUPDF":
            return f"\n\n> ⚠️ **提示**：检测到 TikZ 绘图。请在终端运行 `pip install pymupdf` 安装依赖后，即可渲染为图片预览。\n\n```latex\n{tikz_code}\n```\n\n"
        else:
            return f"\n\n> ⚠️ **TikZ 编译失败** (`{err}`)。请检查 LaTeX 语法或本地环境。\n\n```latex\n{tikz_code}\n```\n\n"

    content = re.sub(r'\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}', replace_inline_tikz, content, flags=re.DOTALL)
    
    # 尝试处理表格 tabular -> Markdown Table
    def replace_tabular(match):
        table_content = match.group(1)
        table_content = table_content.replace(r'\hline', '')
        rows = [row.strip() for row in table_content.split(r'\\') if row.strip()]
        
        md_rows = []
        for row in rows:
            cols = [col.strip() for col in row.split('&')]
            md_row = '| ' + ' | '.join(cols) + ' |'
            md_rows.append(md_row)
            
        if not md_rows:
            return ""
            
        col_count = md_rows[0].count('|') - 1
        if col_count > 0:
            sep_row = '|' + '---|' * col_count
            md_rows.insert(1, sep_row)
            
        return '\n' + '\n'.join(md_rows) + '\n'

    content = re.sub(r'\\begin\{tabular\}\{.*?\}\s*(.*?)\s*\\end\{tabular\}', replace_tabular, content, flags=re.DOTALL)
    
    content = content.replace(r'\begin{center}', '').replace(r'\end{center}', '')

    def replace_enumerate(match):
        list_content = match.group(1)
        list_content = re.sub(r'\\item\[(.*?)\]', r'\n\1 ', list_content)
        list_content = re.sub(r'\\item\s+', r'\n1. ', list_content)
        return list_content + '\n'

    content = re.sub(r'\\begin\{enumerate\}(.*?)\\end\{enumerate\}', replace_enumerate, content, flags=re.DOTALL)

    def replace_itemize(match):
        list_content = match.group(1)
        list_content = re.sub(r'\\item\[(.*?)\]', r'\n- \1 ', list_content)
        list_content = re.sub(r'\\item\s+', r'\n- ', list_content)
        return list_content + '\n'

    content = re.sub(r'\\begin\{itemize\}(.*?)\\end\{itemize\}', replace_itemize, content, flags=re.DOTALL)
    
    def replace_align(match):
        content_inner = match.group(1)
        content_inner = content_inner.replace('&', '')
        lines = content_inner.split(r'\\')
        formatted_lines = []
        for line in lines:
            line = line.strip()
            if line:
                formatted_lines.append(f"$\n{line}\n$")
        return '\n\n'.join(formatted_lines) + '\n'

    content = re.sub(r'\\begin\{align\*?\}(.*?)\\end\{align\*?\}', replace_align, content, flags=re.DOTALL)

    content = re.sub(r'\\\[(.*?)\\\]', r'$$\n\1\n$$', content, flags=re.DOTALL)
    content = re.sub(r'\\\((.*?)\\\)', r'$\1$', content, flags=re.DOTALL)
    
    return header + content

def generate_filename(year, p_type, name, number, subject):
    return f"{year}-{p_type}-{name}-{number}-{subject}.tex"

def extract_tags_from_fpath(fpath):
    basename = os.path.basename(fpath).replace('.tex', '')
    parts = basename.split('-')
    if len(parts) >= 5:
        return parts[4].split("，")
    return []

def update_file_tags(old_fpath, new_tags_list):
    new_subj_str = "，".join(new_tags_list)
    
    old_filename = os.path.basename(old_fpath)
    old_dir = os.path.dirname(old_fpath)
    old_basename = old_filename.replace('.tex', '')
    
    parts = old_basename.split('-')
    if len(parts) >= 5:
        year = parts[0]
        ptype = parts[1]
        name = parts[2]
        num = parts[3]
    else:
        return False
        
    new_filename = generate_filename(year, ptype, name, num, new_subj_str)
    primary_subj = new_tags_list[0]
    new_save_dir = os.path.join(CHAPTERS_DIR, primary_subj, year)
    ensure_dir(new_save_dir)
    new_fpath = os.path.join(new_save_dir, new_filename)
    
    with open(old_fpath, "r", encoding="utf-8") as f:
        content = f.read()
        
    def replace_subj(match):
        return f"\\begin{{problem}}{{{match.group(1)}}}{{{match.group(2)}}}{{{match.group(3)}}}{{{match.group(4)}}}{{{new_subj_str}}}"
    
    content = re.sub(r'\\begin\{problem\}\{(.*?)\}\{(.*?)\}\{(.*?)\}\{(.*?)\}\{(.*?)\}', replace_subj, content, count=1)
    
    final_content = extract_and_replace_tikz(content, new_filename, new_save_dir)
    
    with open(new_fpath, "w", encoding="utf-8") as f:
        f.write(final_content)
        
    if os.path.abspath(old_fpath) != os.path.abspath(new_fpath):
        try:
            os.remove(old_fpath)
        except:
            pass
        old_tikz_dir = os.path.join(old_dir, f"{old_basename} 相关图")
        if os.path.exists(old_tikz_dir):
            import shutil
            try:
                shutil.rmtree(old_tikz_dir)
            except:
                pass
                
    return True

def extract_and_replace_tikz(content, filename, save_dir):
    """
    提取LaTeX内容中的TikZ代码块，保存为独立文件到“相关图”文件夹中。
    注意：修改后，主文件中不再替换为 \input{}，而是保留原始的 \begin{tikzpicture}...\end{tikzpicture} 代码，
    但仍会在后台生成对应的独立 .tex 副本，以便后续有其他需要。
    清理多余的旧文件。
    """
    if "相关图" in save_dir or "相关图" in filename:
        return content

    base_name = filename.replace('.tex', '')
    tikz_dir_name = f"{base_name} 相关图"
    tikz_dir_path = os.path.join(save_dir, tikz_dir_name)
    
    pattern = r'(\\input\{[^}]*?相关图/[^}]+\})|(\\begin\{tikzpicture\}.*?\\end\{tikzpicture\})'
    matches = list(re.finditer(pattern, content, re.DOTALL))
    
    if not matches:
        return content
        
    ensure_dir(tikz_dir_path)
    
    new_content = ""
    last_end = 0
    match_count = 0
    
    for match in matches:
        match_count += 1
        tikz_code = ""
        
        if match.group(1):
            input_str = match.group(1)
            m_path = re.search(r'\\input\{([^}]+)\}', input_str)
            if m_path:
                rel_path = m_path.group(1)
                if not rel_path.endswith('.tex'):
                    rel_path += '.tex'
                abs_path = os.path.join(BASE_DIR, rel_path)
                if os.path.exists(abs_path):
                    with open(abs_path, 'r', encoding='utf-8') as f:
                        tikz_code = f.read()
                else:
                    tikz_code = "% ⚠️ 找不到原文件内容\n"
        else:
            tikz_code = match.group(2)
            
        tikz_filename = f"{base_name} 图{match_count}.tex"
        tikz_file_path = os.path.join(tikz_dir_path, tikz_filename)
        with open(tikz_file_path, "w", encoding="utf-8") as f:
            f.write(tikz_code)
            
        new_content += content[last_end:match.start()]
        new_content += tikz_code
        last_end = match.end()
        
    new_content += content[last_end:]
    return new_content