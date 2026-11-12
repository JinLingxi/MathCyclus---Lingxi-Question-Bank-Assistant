"""Create a compact human-triage CSV/Markdown from the read-only conflict audit."""
import argparse
import csv
import json
from collections import Counter,defaultdict
from pathlib import Path

ORDER=("text_choices_images_identical","presentation_difference_only_candidate",
       "normalized_stem_same_options_or_details_differ","content_differs_requires_source_review")
LABELS={
 "text_choices_images_identical":"正文、选项和图片字节均相同",
 "presentation_difference_only_candidate":"仅有空格/TeX/标点等表现形式差异候选",
 "normalized_stem_same_options_or_details_differ":"题干归一化相同，但选项、题型、数字或细节需对照",
 "content_differs_requires_source_review":"其余文本差异，含TeX、TikZ与截图差异或实质题位错误，需核对",
}

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument("--input",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
 a=p.parse_args()
 if a.output.exists() or a.output.with_suffix(".md").exists():raise FileExistsError("output already exists")
 data=json.loads(a.input.read_text(encoding="utf-8"))
 rows=[];summary=defaultdict(Counter);warning_rows=[]
 for item in data["rows"]:
  same=[c for c in item["candidates"] if c["same_position_now"]]
  if item["original_skip"]=="position_conflict":
   if len(same)!=1:raise ValueError("每个位置冲突预期唯一对应正式题")
   candidate=same[0];category=candidate["category"]
   summary[str(item["year"])][category]+=1
   if item.get("source_warning"):warning_rows.append(item)
  else:
   candidate=max(item["candidates"],key=lambda c:float(c.get("score") or 0),default={})
   category=candidate.get("category","")
  rows.append({"review_priority":"核对原卷" if category=="content_differs_requires_source_review" else "抽查确认",
   "skipped_as":item["original_skip"],"year":item.get("year"),"paper":item.get("source"),
   "number":item.get("number"),"draft_id":item["draft_id"],"existing_question_id":candidate.get("question_id",""),
   "category":category,"category_label":LABELS.get(category,""),
   "text_ratio":candidate.get("stem_text_ratio"),"similarity_kind":candidate.get("classifier_kind"),
   "score":candidate.get("score"),"type_equal":candidate.get("type_equal"),
   "choices_equal":candidate.get("choices_equal"),"image_bytes_equal":candidate.get("image_bytes_equal"),
   "source_warning":item.get("source_warning") or "",
   "draft_stem":item.get("draft_stem") or "",
   "existing_stem":candidate.get("formal_stem") or "",
   "draft_choices":json.dumps(item.get("draft_choices") or [],ensure_ascii=False),
   "existing_choices":json.dumps(candidate.get("formal_choices") or [],ensure_ascii=False)})
 a.output.parent.mkdir(parents=True,exist_ok=True)
 with a.output.open("x",encoding="utf-8-sig",newline="") as f:
  writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
 exact=[r for r in rows if r["skipped_as"]=="exact_duplicate"]
 pos=[r for r in rows if r["skipped_as"]=="position_conflict"]
 lines=["# 重复内容与同位置冲突逐题复核清单","",
  "此报告只用于人工核对，不更改题目、关系、审核状态或来源。评分和文本相似属于排查线索，不是数学等价证明。","",
  f"- 完全重复模式跳过 {len(exact)} 题，其中正文、选项、图片字节相同 {sum(r['category']=='text_choices_images_identical' for r in exact)} 题；表现形式不同候选 {sum(r['category']=='presentation_difference_only_candidate' for r in exact)} 题。",
  f"- 同位置冲突跳过 {len(pos)} 题；对应正式位置题的候选分类：完全相同 {sum(r['category']=='text_choices_images_identical' for r in pos)}，表现形式不同 {sum(r['category']=='presentation_difference_only_candidate' for r in pos)}，归一化题干相同但选项/细节待核 {sum(r['category']=='normalized_stem_same_options_or_details_differ' for r in pos)}，内容明显不同 {sum(r['category']=='content_differs_requires_source_review' for r in pos)}。",
  f"- 同位置冲突中有 {len(warning_rows)} 题还带原始来源疑点备注。","",
  "510道其余差异不等于510道不同题：包括TeX写法、重绘TikZ与原图截图、题干转写和实质来源题位错误。必须进一步对照，不能仅凭字符串不相同就决定覆盖、合并或解除关系。","",
  "## 同位置冲突按年份","",
  "| 年份 | 完全相同 | 表现形式差异 | 归一化题干相同但选项/细节待核 | 其余差异待核 |",
  "| --- | ---: | ---: | ---: | ---: |"]
 for year,counts in sorted(summary.items()):
  lines.append("| "+year+" | "+" | ".join(str(counts[x]) for x in ORDER)+" |")
 lines+=["","## 处理顺序","","1. 先核对“内容明显不同”组的原 PDF 封面/卷别与题号，判断是草稿来源字段错误还是现有正式题关联错误。",
  "2. 再核对 116 道归一化题干相同但选项、题型、数字或细节不同的题，确认是否变式题或错误位置。",
  "3. 对 23 道表现形式不同候选核对原页、选项和配图；只有证据足够才讨论建立等价关系。",
  "4. 514 道内容重复跳过题不自动删除；513 道逐字段/图片字节完全一致，另 1 道存在表现形式差异候选。",
  "","逐题正文、选项、图片字节、分类评分与来源备注见同名 CSV。"]
 a.output.with_suffix(".md").write_text("\n".join(lines)+"\n",encoding="utf-8")
 print(json.dumps({"rows":len(rows),"position_conflicts":len(pos),"source_warning_conflicts":len(warning_rows)},ensure_ascii=False))

if __name__=="__main__":main()
