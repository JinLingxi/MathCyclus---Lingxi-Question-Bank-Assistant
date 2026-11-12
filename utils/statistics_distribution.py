"""Accessible, local-only distribution views for the statistics dashboard."""
from html import escape

from utils.core_config import PAPER_TYPES, SUBJECTS


def _counts(data):
    return {str(key): int(value or 0) for key, value in (data or {}).items() if int(value or 0) > 0}


def _percent(value, total):
    ratio = value / total * 100 if total else 0
    return "<0.1%" if 0 < ratio < 0.1 else f"{ratio:.1f}%"


def generate_distribution_overview_html(stats):
    total = int(stats.get("total_questions", 0) or 0)
    primary = _counts(stats.get("subject_counts"))
    coverage = _counts(stats.get("subject_coverage_counts") or primary)
    names = set(primary) | set(coverage)
    primary_names = set(SUBJECTS)

    def ranking(mode):
        data = coverage if mode == "coverage" else primary
        shown_names = names if mode == "coverage" else primary_names
        ordered = sorted(shown_names, key=lambda name: (-data.get(name, 0), name))
        maximum = max((data.get(name, 0) for name in shown_names), default=0) or 1
        rows = []
        for index, name in enumerate(ordered, 1):
            value = data.get(name, 0)
            detail = f"主板块 {primary.get(name, 0):,} 题 · 覆盖 {coverage.get(name, 0):,} 题"
            rows.append(
                f'<li class="rank-row" title="{escape(detail, quote=True)}">'
                f'<span class="rank">{index:02}</span><div class="rank-main">'
                f'<div class="rank-label"><span>{escape(name)}</span><strong>{value:,}'
                f'<small>{escape(_percent(value, total))}</small></strong></div>'
                f'<div class="bar-track"><span style="width:{value / maximum * 100:.4f}%"></span></div>'
                '</div></li>'
            )
        if not rows:
            return '<p class="empty">暂无知识板块数据</p>'
        first = '<ol class="ranking">' + ''.join(rows[:10]) + '</ol>'
        if len(rows) > 10:
            first += (
                f'<details class="more"><summary>查看其余 {len(rows) - 10} 个板块</summary>'
                '<ol class="ranking" start="11">' + ''.join(rows[10:]) + '</ol></details>'
            )
        return first

    def composition(title, subtitle, data, palette, footnote):
        values = _counts(data)
        # A missing category is visible, rather than silently using a smaller
        # denominator and showing a distribution total different from the bank.
        missing = max(total - sum(values.values()), 0)
        if missing:
            values["未分类"] = values.get("未分类", 0) + missing
        ordered = sorted(values.items(), key=lambda item: (-item[1], item[0]))
        denominator = sum(values.values())
        segments, rows = [], []
        for index, (label, count) in enumerate(ordered):
            color = palette[index % len(palette)]
            percent = _percent(count, denominator)
            description = f"{label}：{count:,} 题，{percent}"
            segments.append(f'<span title="{escape(description, quote=True)}" style="flex:{count};background:{color}"></span>')
            rows.append(
                f'<li class="category-row"><span class="category-name"><i style="background:{color}"></i>'
                f'{escape(label)}</span><strong>{count:,}</strong><span class="share">{escape(percent)}</span></li>'
            )
        body = (
            '<div class="composition-bar" role="img" aria-label="' + escape('；'.join(
                f'{label} {count:,} 题' for label, count in ordered), quote=True) + '">' + ''.join(segments) + '</div>'
            '<ul class="categories">' + ''.join(rows) + '</ul>'
        ) if ordered else '<p class="empty">暂无分类数据</p>'
        return (
            f'<section class="panel composition"><header><h3>{title}</h3><p>{subtitle}</p></header>'
            + body + f'<p class="panel-note">{footnote}</p></section>'
        )

    papers = {}
    for code, count in _counts(stats.get("source_series_counts")).items():
        label = PAPER_TYPES.get(code, code)
        papers[label] = papers.get(label, 0) + count
    types = composition(
        "题型分布", "各类题目的数量与占比", stats.get("type_counts"),
        ["#7452b8", "#3f9188", "#c6935c", "#bc7090", "#8992a5"],
        "占比按题型统计总数计算。",
    )
    paper_view = composition(
        "试卷类型", "按题目所属的试卷类别统计", papers,
        ["#7452b8", "#b4a0d3", "#3f9188", "#c6935c", "#bc7090", "#7d96ba", "#8992a5"],
        "未识别试卷类别的题目计入未分类。",
    )
    return _STYLE + (
        '<main class="distribution" aria-label="题库结构分布">'
        '<section class="panel knowledge"><header class="knowledge-header"><div><h3>知识板块</h3>'
        f'<p><span class="coverage-summary">{len(names)} 个板块 · 包含后续新增板块</span>'
        f'<span class="primary-summary">{len(primary_names)} 个初始预设分类 · 含未分类</span></p></div>'
        '<fieldset class="mode-switch"><legend>统计口径</legend>'
        '<label><input type="radio" name="mode" value="coverage" checked><span>覆盖题数</span></label>'
        '<label><input type="radio" name="mode" value="primary"><span>主板块题数</span></label></fieldset></header>'
        '<div class="coverage-pane"><p class="definition">一题可覆盖多个板块；百分比为该板块覆盖题数占全库的比例。</p>'
        + ranking("coverage") + '</div>'
        '<div class="primary-pane"><p class="definition">仅展示初始预设分类，按每题的主板块计数；占比仍以全库题数计算，新增板块不在此归并。</p>'
        + ranking("primary") + '</div>'
        '<footer class="knowledge-footer">悬停条目可核对主板块题数与覆盖题数。</footer></section>'
        '<aside class="composition-column" aria-label="题型与试卷类型">' + types + paper_view + '</aside></main>'
    ) + _SCRIPT


_STYLE = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><style>
*{box-sizing:border-box}body{margin:0;color:#312b3b;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;font-size:14px;background:transparent}
.distribution{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:22px;align-items:start;padding:2px}
.panel{background:#fffdfd;border:1px solid #e5deee;border-radius:14px;padding:26px 28px}
header h3{margin:0;font-size:19px;line-height:1.35;font-weight:650;letter-spacing:-.02em}header p{margin:7px 0 0;color:#746b80;font-size:12px;line-height:1.5}
.knowledge-header{display:flex;justify-content:space-between;align-items:center;gap:20px;flex-wrap:wrap}
.mode-switch{display:flex;gap:2px;margin:0;padding:3px;border:0;border-radius:8px;background:#f2edf8}
.mode-switch legend{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}
.mode-switch label{position:relative;cursor:pointer}.mode-switch input{position:absolute;width:1px;height:1px;opacity:0}
.mode-switch label span{display:block;padding:7px 10px;border-radius:6px;color:#746b80;font-size:12px;line-height:1.5}
.mode-switch label:has(input:checked) span{background:#fffdfd;color:#5d3c96;font-weight:650}
.mode-switch label:has(input:focus-visible){outline:2px solid #7452b8;outline-offset:3px;border-radius:6px}
.primary-pane{display:none}.knowledge:has(input[value="primary"]:checked) .primary-pane{display:block}.knowledge:has(input[value="primary"]:checked) .coverage-pane{display:none}
.primary-summary{display:none}.knowledge:has(input[value="primary"]:checked) .primary-summary{display:inline}.knowledge:has(input[value="primary"]:checked) .coverage-summary{display:none}
.definition{margin:24px 0 15px;font-size:12px;line-height:1.7;color:#746b80}
.ranking,.categories{margin:0;padding:0;list-style:none}.rank-row{display:flex;gap:16px;align-items:center;padding:12px 0;break-inside:avoid}
.rank{width:20px;flex-shrink:0;color:#9b91a6;font-size:11px;font-variant-numeric:tabular-nums}.rank-main{flex:1;min-width:0}
.rank-label{display:flex;justify-content:space-between;align-items:baseline;gap:14px;line-height:1.5}.rank-label>span{overflow-wrap:anywhere}
strong{font-variant-numeric:tabular-nums;font-weight:600}.rank-label strong{white-space:nowrap}.rank-label small{display:inline-block;width:56px;margin-left:16px;text-align:right;color:#746b80;font-size:12px;font-weight:400}
.bar-track{height:5px;margin-top:8px;background:#f1edf7;border-radius:3px;overflow:hidden}.bar-track>span{display:block;height:100%;background:#9274be;border-radius:3px}.rank-row:first-child .bar-track>span{background:#7452b8}
.rank-row:hover .rank-label>span{color:#67439f}.rank-row:hover .bar-track>span{background:#7452b8}
.more{border-top:1px solid #eee8f3;margin-top:12px;padding-top:16px}.more summary{width:fit-content;cursor:pointer;color:#67439f;font-size:12px;padding:4px 0}.more summary:focus-visible{outline:2px solid #7452b8;outline-offset:4px}
.knowledge-footer{border-top:1px solid #eee8f3;margin-top:20px;padding-top:16px;color:#746b80;font-size:11px;line-height:1.7}
.composition-column{display:grid;gap:22px;min-width:0}.composition-bar{display:flex;width:100%;height:8px;gap:2px;border-radius:4px;overflow:hidden;margin:24px 0 18px;background:#f2edf8}.composition-bar>span{min-width:1px}
.category-row{display:grid;grid-template-columns:minmax(0,1fr) 76px 65px;align-items:center;gap:12px;padding:11px 0;border-bottom:1px solid #f0ebf5;line-height:1.5}
.category-row:last-child{border-bottom:0}.category-name{display:flex;align-items:center;gap:10px;overflow-wrap:anywhere}.category-name i{width:7px;height:7px;flex-shrink:0;border-radius:50%}.category-row strong,.share{text-align:right}.share{color:#746b80;font-size:12px;font-variant-numeric:tabular-nums}
.panel-note{margin:16px 0 0;color:#746b80;font-size:11px;line-height:1.6}.empty{padding:35px 0;color:#746b80;font-size:13px}
@media(max-width:700px){.distribution{grid-template-columns:1fr;gap:16px}.composition-column{gap:16px}.panel{padding:22px}.knowledge-header{gap:16px}.mode-switch{margin-top:2px}.definition{margin-top:18px}}
@media(max-width:360px){.panel{padding:18px 16px}.rank-row{gap:10px}.rank-label small{width:47px;margin-left:8px}.category-row{grid-template-columns:minmax(0,1fr) 60px 52px;gap:8px}}
</style></head><body>'''

_SCRIPT = '''<script>
(()=>{
 const root=document.querySelector('.distribution');let last=0,pending=false;
 const report=()=>{pending=false;const height=Math.ceil(root.getBoundingClientRect().height)+5;
  if(Math.abs(height-last)>1){last=height;
   if(window.frameElement)window.frameElement.style.height=height+'px';
   window.parent.postMessage({isStreamlitMessage:true,type:'streamlit:setFrameHeight',height},'*');
  }
 };
 const schedule=()=>{if(!pending){pending=true;requestAnimationFrame(report);}};
 new ResizeObserver(schedule).observe(root);document.fonts?.ready.then(schedule);schedule();
})();
</script></body></html>'''
