import os
import csv
import datetime
import re
from .core_config import CSV_INDEX_PATH, CHAPTERS_DIR
from .latex_ops import parse_meta_data

CSV_HEADERS = [
    "题目ID", "文件名称", "相对文件路径", "年份", "试卷类型", "试卷名称", "原卷题号", "知识板块",
    "标签", "包含TikZ绘图", "题型", "难度星级", "包含解析", "组卷引用次数", "备注",
    "初次录入的时间", "最后修改时间", "题干", "答案", "解析"
]

def read_csv_index():
    """读取整个CSV索引到内存"""
    if not os.path.exists(CSV_INDEX_PATH):
        return []
    data = []
    with open(CSV_INDEX_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    return data

def write_csv_index(data):
    """将数据全量写回CSV"""
    with open(CSV_INDEX_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(data)

def get_next_id():
    """获取下一个可用的全局ID"""
    data = read_csv_index()
    max_id = 0
    for row in data:
        if row.get("题目ID") and str(row["题目ID"]).isdigit():
            max_id = max(max_id, int(row["题目ID"]))
    return max_id + 1

def _parse_tex_content(content, pname):
    """解析 tex 内容，提取题干、答案、解析、题型、Meta Data 等信息"""
    meta, clean_content = parse_meta_data(content)
    
    has_tikz = "是" if "\\begin{tikzpicture}" in clean_content else "否"
    
    # Extract problem content (题干部分)
    # 兼容多种写法： \begin{problem}{...} 或者没有参数的 \begin{problem}
    prob_match = re.search(r'\\begin\{problem\}(?:\{.*?\})*?(.*?)\\end\{problem\}', clean_content, re.DOTALL)
    stem_text = prob_match.group(1).strip() if prob_match else ""

    # Extract solution (解析部分) - 独立于 problem 之外
    sol_match = re.search(r'\\begin\{solutions?\}(.*?)\\end\{solutions?\}', clean_content, re.DOTALL)
    sol_text = sol_match.group(1).strip() if sol_match else ""

    # Extract answer (答案部分)
    ans_match = re.search(r'\\begin\{answer\}(.*?)\\end\{answer\}', clean_content, re.DOTALL)
    ans_text = ans_match.group(1).strip() if ans_match else ""
    
    has_solution = "是" if sol_text else "否"

    # 如果旧格式中，solution 嵌套在了 problem 内部，需要从 stem 中剔除它
    if sol_match and sol_match.group(0) in stem_text:
        stem_text = stem_text.replace(sol_match.group(0), "")
    if ans_match and ans_match.group(0) in stem_text:
        stem_text = stem_text.replace(ans_match.group(0), "")
    stem_text = stem_text.strip()
    
    if "\\begin{choices}" in stem_text or "\\choice" in stem_text:
        q_type = "选择题"
    elif "\\underline" in stem_text or "空" in pname:
        q_type = "填空题"
    else:
        q_type = "解答题"
        
    return has_tikz, q_type, has_solution, stem_text, ans_text, sol_text, meta

def add_to_csv_index(file_path, content, year, ptype, pname, pnum, subj):
    """录入新题时追加到CSV"""
    data = read_csv_index()
    
    name_body = os.path.basename(file_path).replace(".tex", "")
    rel_path = os.path.relpath(file_path, CHAPTERS_DIR)
    
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    has_tikz, q_type, has_solution, stem_text, ans_text, sol_text, meta = _parse_tex_content(content, pname)
    
    # 优先使用文件中记录的 ID，如果没有则生成新的
    new_id = meta.get("ID")
    if not new_id:
        new_id = get_next_id()
    
    new_row = {
        "题目ID": new_id,
        "文件名称": name_body,
        "相对文件路径": rel_path,
        "年份": year,
        "试卷类型": ptype,
        "试卷名称": pname,
        "原卷题号": pnum,
        "知识板块": subj,
        "标签": meta.get("标签", ""),
        "包含TikZ绘图": has_tikz,
        "题型": q_type,
        "难度星级": meta.get("难度星级", ""),
        "包含解析": has_solution,
        "组卷引用次数": meta.get("组卷引用次数", "0"),
        "备注": meta.get("备注", ""),
        "初次录入的时间": now_str,
        "最后修改时间": now_str,
        "题干": stem_text,
        "答案": ans_text,
        "解析": sol_text
    }
    
    data.append(new_row)
    write_csv_index(data)
    return new_id

def update_csv_index_for_edit(old_file_path, new_file_path, new_content, new_year, new_ptype, new_pname, new_pnum, new_subj):
    """修改元数据时更新CSV，如果是覆盖旧文件，根据原文件名寻找记录并更新"""
    data = read_csv_index()
    old_name_body = os.path.basename(old_file_path).replace(".tex", "")
    new_name_body = os.path.basename(new_file_path).replace(".tex", "")
    new_rel_path = os.path.relpath(new_file_path, CHAPTERS_DIR)
    
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    has_tikz, q_type, has_solution, stem_text, ans_text, sol_text, meta = _parse_tex_content(new_content, new_pname)
    
    found = False
    for row in data:
        if row["文件名称"] == old_name_body:
            row["文件名称"] = new_name_body
            row["相对文件路径"] = new_rel_path
            row["年份"] = new_year
            row["试卷类型"] = new_ptype
            row["试卷名称"] = new_pname
            row["原卷题号"] = new_pnum
            row["知识板块"] = new_subj
            row["标签"] = meta.get("标签", "")
            row["包含TikZ绘图"] = has_tikz
            row["题型"] = q_type
            row["难度星级"] = meta.get("难度星级", "")
            row["包含解析"] = has_solution
            row["组卷引用次数"] = meta.get("组卷引用次数", row.get("组卷引用次数", "0"))
            row["备注"] = meta.get("备注", "")
            row["最后修改时间"] = now_str
            row["题干"] = stem_text
            row["答案"] = ans_text
            row["解析"] = sol_text
            found = True
            break
            
    if not found:
        # 降级处理：如果没有找到旧记录，当作新题追加
        add_to_csv_index(new_file_path, new_content, new_year, new_ptype, new_pname, new_pnum, new_subj)
    else:
        write_csv_index(data)
