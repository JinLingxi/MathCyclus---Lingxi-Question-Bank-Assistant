import os
import re
from .core_config import CHAPTERS_DIR, SUBJECTS

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def get_all_years_globally():
    """获取所有板块中包含的年份集合"""
    years = set()
    if not os.path.exists(CHAPTERS_DIR):
        return []
    for subject in os.listdir(CHAPTERS_DIR):
        subject_dir = os.path.join(CHAPTERS_DIR, subject)
        if os.path.isdir(subject_dir):
            for year in os.listdir(subject_dir):
                if year.isdigit() and os.path.isdir(os.path.join(subject_dir, year)):
                    years.add(year)
    return sorted(list(years), reverse=True)

def get_years(subject):
    subject_dir = os.path.join(CHAPTERS_DIR, subject)
    if not os.path.exists(subject_dir):
        return []
    years = [d for d in os.listdir(subject_dir) if os.path.isdir(os.path.join(subject_dir, d))]
    return sorted(years, reverse=True)

def get_files(subject, year):
    target_dir = os.path.join(CHAPTERS_DIR, subject, year)
    if not os.path.exists(target_dir):
        return []
    files = [f for f in os.listdir(target_dir) if f.endswith(".tex") and not f.startswith("content_") and " 相关图" not in target_dir and " 图" not in f]
    return sorted(files)

def get_papers_by_year(year):
    """获取某一年份下的所有试卷名称"""
    papers = set()
    for subject in SUBJECTS:
        target_dir = os.path.join(CHAPTERS_DIR, subject, year)
        if os.path.exists(target_dir):
            for f in os.listdir(target_dir):
                if f.endswith(".tex") and not f.startswith("content_") and " 相关图" not in target_dir and " 图" not in f:
                    parts = f[:-4].split('-')
                    if len(parts) >= 5:
                        papers.add(parts[2])
    return sorted(list(papers))

def get_questions_by_paper(year, paper_name):
    """获取某年某试卷的所有题目"""
    questions = []
    for subject in SUBJECTS:
        target_dir = os.path.join(CHAPTERS_DIR, subject, year)
        if os.path.exists(target_dir):
            for f in os.listdir(target_dir):
                if f.endswith(".tex") and not f.startswith("content_") and " 图" not in f and f"-{paper_name}-" in f:
                    file_path = os.path.join(target_dir, f)
                    parts = f[:-4].split('-')
                    real_subject = parts[4] if len(parts) >= 5 else subject
                    questions.append({
                        "file": f,
                        "path": file_path,
                        "subject": real_subject
                    })
    # Sort by question number (assuming part 4 of filename is number)
    def sort_key(q):
        try:
            return int(q["file"][:-4].split('-')[3])
        except:
            return 999
    return sorted(questions, key=sort_key)

def check_search_match(path, s_type, s_query):
    """判断文件内容是否匹配搜索条件"""
    if s_type == "题目文件名":
        return s_query in os.path.basename(path)
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return False
        
    if s_type == "全文内容":
        return s_query in content
        
    if s_type == "题目类型":
        # 兼容多种写法： \begin{problem}{...} 或者没有参数的 \begin{problem}
        prob_match = re.search(r'\\begin\{problem\}(?:\{.*?\})*?(.*?)\\end\{problem\}', content, re.DOTALL)
        stem_text = prob_match.group(1).strip() if prob_match else ""

        sol_match = re.search(r'\\begin\{solutions?\}(.*?)\\end\{solutions?\}', content, re.DOTALL)
        ans_match = re.search(r'\\begin\{answer\}(.*?)\\end\{answer\}', content, re.DOTALL)
        
        if sol_match and sol_match.group(0) in stem_text:
            stem_text = stem_text.replace(sol_match.group(0), "")
        if ans_match and ans_match.group(0) in stem_text:
            stem_text = stem_text.replace(ans_match.group(0), "")
        stem_text = stem_text.strip()
        
        # 判断类型
        if "\\begin{choices}" in stem_text or "\\choice" in stem_text:
            actual_type = "选择题"
        elif "\\underline" in stem_text or "空" in os.path.basename(path):
            actual_type = "填空题"
        else:
            actual_type = "解答题"
            
        return s_query == actual_type

    if s_type in ["难度星级", "标签", "备注"]:
        # 提取 Label Data 块
        pattern = r'%(?: === Meta Data ===| === Begin Label Data ===)\n(.*?)%(?: === End Meta ===| === End\s+Label Data ===)\n'
        match = re.search(pattern, content, re.DOTALL)
        if match:
            meta_block = match.group(1)
            for line in meta_block.split('\n'):
                if line.startswith('% '):
                    parts = line[2:].split(':', 1)
                    if len(parts) == 2 and parts[0].strip() == s_type:
                        return s_query in parts[1].strip()
        return False
        
    if s_type == "题目内容":
        # 限定在 \begin{problem} 和 \end{problem} 之间检索
        parts = re.split(r'\\begin\{problem\}', content)
        if len(parts) > 1:
            # 提取第一个匹配的problem内容块
            prob_str = re.split(r'\\end\{problem\}', parts[1])[0]
            return s_query in prob_str
        return False
        
    elif s_type == "解答内容":
        # 限定在 \begin{solution} 和 \end{solution} (或者 solutions) 之间检索
        parts = re.split(r'\\begin\{solutions?\}', content)
        if len(parts) > 1:
            sol_str = re.split(r'\\end\{solutions?\}', parts[1])[0]
            return s_query in sol_str
        return False
        
    # 兼容原有的"关键词"和"正则"单级搜索
    if s_type == "关键词" and s_query in content:
        return True
    if s_type == "正则":
        try:
            if re.search(s_query, content):
                return True
        except:
            return False
            
    return False