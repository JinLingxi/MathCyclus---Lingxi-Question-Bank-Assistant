"""Record inspected answer routes; unresolved old content stays in recovery drafts."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

# These decisions follow explicit side-by-side content inspection, not a lowered
# global similarity threshold. No source stem or options are changed.
REVIEWED={
 "Q000019":"a/b+b/a two addends swapped; same expression and target",
 "Q000343":"new stem restores the requested b and x4 conclusion; solution addresses both parts",
 "Q001028":"same true/false statements; wording and old question-type annotation differ",
 "Q001029":"same true/false statements; wording and old question-type annotation differ",
 "Q000305":"bar/overline and inequality aliases; same options in same order",
 "Q000736":"ellipsis and formatting aliases only",
 "Q000346":"circled numbering, limits formatting, Chinese wording; same three conclusions",
 "Q000666":"option D abbreviates the three previously named pairs, without changing them",
 "Q000078":"inequality spelling and math/text punctuation only",
 "Q001046":"new source explicitly states e is natural base, same equation/options",
 "Q001047":"new source explicitly states e is natural base, same equation/options",
 "Q000668":"table/center/solutions environment formatting differs; preserve existing response verbatim",
 "Q000127":"old choices are the three numbered statements now included in fill-blank stem",
 "Q000195":"vec/boldsymbol notation and inequality aliases, same vector conditions/options",
 "Q000764":"source word order and old question-type annotation differ, same task",
 "Q000356":"circled statement numbering now parenthesized; same five conditions",
 "Q000470":"quad and prime-notation differences only",
 "Q001072":"old leading 1. label removed; same sets and options",
 "Q001073":"old wrong paper location; same sets/options found in other new draft",
 "Q000768":"triangle symbol spelled in Chinese and added connective",
 "Q000675":"prime and empty-center formatting only",
 "Q000033":"circled/Unicode numbered statements and answer wording only",
 "Q001126":"table layout/ellipsis and I/1 numbering; same recurrence definition",
 "Q001127":"old wrong location; same recurrence definition found in other new draft",
 "Q001129":"variance D(X) moved from options into stem; same probability table and directions",
 "Q000034":"circled versus Unicode numbering and line breaks only",
 "Q000489":"numbered statements and 1 versus I labeling, same definition",
 "Q000084":"same multi-select statements, old type annotation differs",
 "Q000503":"ellipsis expanded to show a3, same increasing integer sequence and sum",
 "Q000504":"mathfrak and numbered statement formatting, same definition",
 "Q000089":"已知 versus 若, same parameters and target",
 "Q000506":"binary expansion ellipsis omits penultimate term, same definition/options",
 "Q001193":"赢 versus 胜 and 时 omitted, same probability/options",
 "Q000780":"word order and removed empty center; same geometric target",
 "Q000212":"vector boldsymbol/overrightarrow notation, same vectors and conditions",
 "Q000090":"same statements and options, old type annotation and 实数 adjective differ",
 "Q000381":"b=1/9 equals 0.1/(1-0.1); other quantities/options unchanged",
 "Q000837":"实数 adjective and 是/为, same equation/options",
 "Q000838":"same sphere target found at another draft; connective wording only",
 "Q000781":"AB=2 moved and angle-bisector construction restated equivalently",
 "Q000540":"set/layout/ellipsis and I/1 formatting, same definitions",
 "Q000703":"same multi-select statement/options, old type annotation differs",
 "Q000625":"numbered parts spelled in Chinese and limits/ellipsis changes",
 "Q000547":"positive-integer condition restated in same set definition",
 "Q000554":"四 versus 4 and table formatting, same counting target",
 "Q000555":"array/left-right and ellipsis layout of same definition",
 "Q000388":"old inline year/source/question label removed, same derivative problem",
 "Q000564":"已知/设 wording, same function and subquestions",
 "Q000718":"same multi-select statement/options, old type annotation differs",
 "Q000840":"的 omitted, old single/multiple-choice annotation differs",
}

def build_reviewed_plan(plan):
    for entry in plan["entries"]:
        if entry["routing_status"]=="requires_review" and entry["question_id"] in REVIEWED:
            entry["route"]=entry["candidates"][0]
            entry["routing_status"]="inspected_same_position" if entry["route"]["draft_id"]==entry["draft_id"] else "inspected_other_draft"
            entry["inspection_reason"]=REVIEWED[entry["question_id"]]
    from collections import Counter
    plan["counts"]=dict(Counter(e["routing_status"] for e in plan["entries"]))
    return plan

if __name__=="__main__":
    source=ROOT/"reports/position_replacement_plan_20261103.json"
    target=ROOT/"reports/position_replacement_reviewed_20261103.json"
    if target.exists():raise FileExistsError(target)
    result=build_reviewed_plan(json.loads(source.read_text(encoding="utf8")))
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf8")
    print(json.dumps(result["counts"],ensure_ascii=False))
