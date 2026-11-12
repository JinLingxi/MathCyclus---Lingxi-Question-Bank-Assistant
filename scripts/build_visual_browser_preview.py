"""Local browser checks use the real TeX-to-Markdown conversion and original figures."""
import argparse,base64,hashlib,html,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from utils.latex_ops import latex_to_markdown

def main():
 p=argparse.ArgumentParser();p.add_argument("--year",type=int,required=True);a=p.parse_args()
 work=ROOT/f"data/imports/codex_{a.year}_restart";payload=work/"visual_payloads.json"
 items=json.loads(payload.read_text(encoding="utf8"))
 katex=ROOT/"reports/external_review/judgepeach/math-question-bank-main/static/lib/katex"
 articles=[]
 for item in items:
  text="\n\n".join(latex_to_markdown(v,show_title=False) for v in [item["stem_tex"],*item["choices"]])
  def image_ref(match):
   asset=next(x for x in item["assets"] if x["extra"]["alias"]==match.group(1))
   raw=(ROOT/asset["source_path"]).read_bytes()
   return "<img alt='"+html.escape(asset["caption"],quote=True)+"' src='data:image/png;base64,"+base64.b64encode(raw).decode()+"'/>"
  escaped=re.sub(r'\\questionasset\{([^{}]+)\}',image_ref,html.escape(text))
  articles.append("<article><h2>"+html.escape(item["source_label"])+"</h2><div class='body'>"+escaped+"</div></article>")
 page="""<!doctype html><meta charset="utf-8"><style>
body{font-family:Arial,"Microsoft YaHei",sans-serif;max-width:1200px;margin:20px auto}
article{border:1px solid #ccc;margin:20px 0;padding:20px}.body{white-space:pre-wrap;overflow-wrap:anywhere}
img{display:block;max-width:100%;max-height:500px;margin:15px 0}
</style>"""
 page+=f"<link rel='stylesheet' href='{(katex/'katex.min.css').as_uri()}'><script src='{(katex/'katex.min.js').as_uri()}'></script>"
 page+="".join(articles)
 page+=r"""<script>
window.previewErrors=[];document.querySelectorAll('.body').forEach(node=>{
const walker=document.createTreeWalker(node,NodeFilter.SHOW_TEXT);const texts=[];
while(walker.nextNode())texts.push(walker.currentNode);
for(const text of texts){const value=text.nodeValue;const regex=/\$\$([\s\S]*?)\$\$|\$([^$]*?)\$/g;
let last=0;const fragment=document.createDocumentFragment();let m;let found=false;
while((m=regex.exec(value))){found=true;fragment.append(value.slice(last,m.index));const span=document.createElement('span');
try{span.innerHTML=katex.renderToString(m[1]??m[2],{throwOnError:true,displayMode:m[1]!==undefined,trust:false,strict:"ignore",
macros:{"\\circled":"\\text{(#1)}"}})}catch(e){window.previewErrors.push(String(e));span.className='math-error';span.textContent=m[0]}
fragment.append(span);last=regex.lastIndex;}
if(found){fragment.append(value.slice(last));text.replaceWith(fragment)}
}});window.previewReady=true;
</script>"""
 (work/"browser_preview.html").write_text(page,encoding="utf8")
 print(json.dumps({"questions":len(items),"images":sum(len(x["assets"]) for x in items)}))
if __name__=="__main__":main()
