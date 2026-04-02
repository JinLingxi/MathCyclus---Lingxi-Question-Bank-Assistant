import os
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
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return False
        
    if s_type == "关键词" and s_query in content:
        return True
    if s_type == "正则":
        try:
            if re.search(s_query, content):
                return True
        except:
            return False
    return False

def search_files(s_type, s_query):
    """在所有文件中搜索"""
    import re
    results = []
    if not os.path.exists(CHAPTERS_DIR):
        return results
        
    for subject in os.listdir(CHAPTERS_DIR):
        subject_dir = os.path.join(CHAPTERS_DIR, subject)
        if not os.path.isdir(subject_dir): continue
        
        for year in os.listdir(subject_dir):
            year_dir = os.path.join(subject_dir, year)
            if not os.path.isdir(year_dir): continue
            
            for file in os.listdir(year_dir):
                if not file.endswith(".tex") or file.startswith("content_") or " 相关图" in year_dir or " 图" in file:
                    continue
                    
                path = os.path.join(year_dir, file)
                
                # Check match
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    is_match = False
                    if s_type == "关键词" and s_query in content:
                        is_match = True
                    elif s_type == "正则":
                        try:
                            if re.search(s_query, content):
                                is_match = True
                        except:
                            pass
                            
                    if is_match:
                        results.append({
                            "subject": subject,
                            "year": year,
                            "file": file,
                            "path": path
                        })
                except:
                    pass
    return results