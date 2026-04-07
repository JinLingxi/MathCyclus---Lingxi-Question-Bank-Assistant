import sys
import os
import re
import csv
import datetime

# 确保能正确导入同一目录和上级目录的模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.latex_ops import parse_meta_data
from utils.core_config import BASE_DIR, CHAPTERS_DIR, CSV_INDEX_PATH

CSV_PATH = CSV_INDEX_PATH

headers = [
    "题目ID", "文件名称", "相对文件路径", "年份", "试卷类型", "试卷名称", "原卷题号", "知识板块",
    "标签", "包含TikZ绘图", "题型", "难度星级", "包含解析", "组卷引用次数", "备注",
    "初次录入的时间", "最后修改时间", "题干", "答案", "解析"
]

# 读取已有的 CSV 索引以保留题目ID和扩展标签
existing_data = {}
max_id = 0
if os.path.exists(CSV_PATH):
    try:
        with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_data[row["文件名称"]] = row
                if row["题目ID"].isdigit():
                    max_id = max(max_id, int(row["题目ID"]))
    except Exception:
        pass

data = []

if os.path.exists(CHAPTERS_DIR):
    for root, dirs, files in os.walk(CHAPTERS_DIR):
        if "相关图" in root: continue
        for file in files:
            if not file.endswith(".tex"): continue
            if file.startswith("content_"): continue

            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, CHAPTERS_DIR)
            
            # File stats
            try:
                stat = os.stat(file_path)
                c_time = datetime.datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
                m_time = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            except:
                c_time = ""
                m_time = ""

            # Parse filename
            name_body = file[:-4]
            segs = name_body.split("-")
            year = segs[0] if len(segs) > 0 else ""
            ptype = segs[1] if len(segs) > 1 else ""
            pname = segs[2] if len(segs) > 2 else ""
            pnum = segs[3] if len(segs) > 3 else ""
            subj = segs[4] if len(segs) > 4 else ""

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            has_tikz = "是" if "\\begin{tikzpicture}" in content else "否"
            
            # 解析 Label Data 以提取 ID、标签、备注、难度等
            meta_dict, _ = parse_meta_data(content)
            
            # Extract problem content (题干部分)
            # 兼容多种写法： \begin{problem}{...} 或者没有参数的 \begin{problem}
            prob_match = re.search(r'\\begin\{problem\}(?:\{.*?\})*?(.*?)\\end\{problem\}', content, re.DOTALL)
            stem_text = prob_match.group(1).strip() if prob_match else ""

            # Extract solution (解析部分) - 现在独立于 problem 之外，因为它们可能并列存在
            sol_match = re.search(r'\\begin\{solutions?\}(.*?)\\end\{solutions?\}', content, re.DOTALL)
            sol_text = sol_match.group(1).strip() if sol_match else ""

            # Extract answer (答案部分)
            ans_match = re.search(r'\\begin\{answer\}(.*?)\\end\{answer\}', content, re.DOTALL)
            ans_text = ans_match.group(1).strip() if ans_match else ""
            
            has_solution = "是" if sol_text else "否"
            
            # 如果旧格式中，solution 嵌套在了 problem 内部，需要从 stem 中剔除它
            if sol_match and sol_match.group(0) in stem_text:
                stem_text = stem_text.replace(sol_match.group(0), "")
            if ans_match and ans_match.group(0) in stem_text:
                stem_text = stem_text.replace(ans_match.group(0), "")
                
            stem_text = stem_text.strip()
            
            # Determine question type based on stem
            if "\\begin{choices}" in stem_text or "\\choice" in stem_text:
                q_type = "选择题"
            elif "\\underline" in stem_text or "空" in pname:
                q_type = "填空题"
            else:
                q_type = "解答题"
                
            # 保留旧的 ID 和用户手工填写的扩展标签
            old_row = existing_data.get(name_body, {})
            
            q_id = meta_dict.get("ID", old_row.get("题目ID", 0))
            diff_star = meta_dict.get("难度星级", old_row.get("难度星级", ""))
            tags = meta_dict.get("标签", old_row.get("标签", ""))
            remark = meta_dict.get("备注", old_row.get("备注", ""))
            usage_cnt = meta_dict.get("组卷引用次数", old_row.get("组卷引用次数", 0))
            
            # 如果初次录入时间已经存在，保留旧的时间以防文件被修改导致时间变动
            orig_c_time = old_row.get("初次录入的时间", c_time) if old_row.get("初次录入的时间") else c_time

            data.append({
                "题目ID": q_id,
                "文件名称": name_body,
                "相对文件路径": rel_path,
                "年份": year,
                "试卷类型": ptype,
                "试卷名称": pname,
                "原卷题号": pnum,
                "知识板块": subj,
                "标签": tags,
                "包含TikZ绘图": has_tikz,
                "题型": q_type,
                "难度星级": diff_star,
                "包含解析": has_solution,
                "组卷引用次数": usage_cnt,
                "备注": remark,
                "初次录入的时间": orig_c_time,
                "最后修改时间": m_time,
                "题干": stem_text,
                "答案": ans_text,
                "解析": sol_text
            })

# 处理新增题目：为没有 ID 的题目分配新的递增 ID
new_items = [item for item in data if not item["题目ID"]]
new_items.sort(key=lambda x: (x["初次录入的时间"], x["文件名称"]))

for item in new_items:
    max_id += 1
    item["题目ID"] = max_id

# 按照 ID 升序排列
data.sort(key=lambda x: int(x["题目ID"]) if str(x["题目ID"]).isdigit() else 999999)

with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=headers)
    writer.writeheader()
    writer.writerows(data)

print(f"Successfully generated CSV with {len(data)} records!")
