"""Display-only math and responsive option layout for native previews."""
import re


def display_style_math(markdown):
    def inline(match):
        value = match.group(1)
        return '$' + (value if r'\displaystyle' in value else r'\displaystyle ' + value) + '$'
    parts = re.split(r'(\$\$[\s\S]*?\$\$|</?(?:figure|figcaption|span|img|a|u|div|p|br)\b[^>]*>)', str(markdown or ''))
    return ''.join(p if i % 2 else
                   re.sub(r'(?<![\\$])\$(?!\$)([^$]+?)\$(?!\$)', inline, p)
                   for i,p in enumerate(parts))


CHOICE_LAYOUT = r'''<style>
[data-mc-choice-grid] {display:grid !important;grid-template-columns:minmax(0,1fr);gap:12px 20px !important;align-items:start;}
[data-mc-choice-grid][data-columns="2"] {grid-template-columns:repeat(2,minmax(0,1fr));}
[data-mc-choice-grid][data-columns="4"] {grid-template-columns:repeat(4,minmax(0,1fr));}
[data-mc-choice-grid] > div {min-width:0;}
[data-mc-choice-grid] [data-testid="stVerticalBlock"],[data-mc-choice-grid] .element-container,[data-mc-choice-grid] .stMarkdown {width:100% !important;max-width:100% !important;min-width:0 !important;}
[data-mc-choice-grid] > div:has(.mc-choice-grid-anchor) {display:none !important;}
[data-mc-choice-grid] p {margin-bottom:0 !important;line-height:1.85;}
[data-mc-choice-grid] [data-testid="stVerticalBlock"] {gap:6px;}
</style><script>
(() => {
 const install=function(css){
 const doc=document;
 const previous=window.parent.__mcChoiceLayout;
 let style=doc.getElementById('mc-choice-layout-style');
 if(!style){style=doc.createElement('style');style.id='mc-choice-layout-style';doc.head.appendChild(style);}
 if(style.textContent!==css)style.textContent=css;
 if(previous?.version===2){previous.schedule();return;}
 previous?.dispose?.();
 const measurements=new Map();
 const observed=new Map();
 const resizeObserver=new window.parent.ResizeObserver(entries=>{
  let changed=false;
  entries.forEach(entry=>{
   const width=entry.contentRect.width;
   if(width>0 && Math.abs(width-(observed.get(entry.target)||0))>1){
    observed.set(entry.target,width);changed=true;
   }
  });
  if(changed)schedule();
 });
 const refresh=() => {
  const layouts=[];
  const probes=[];
  const pending=new Map();
  // Read existing geometry before adding any measurement nodes. Previously
  // every option alternated DOM writes and reads, forcing a full page layout.
  doc.querySelectorAll('.mc-choice-grid-anchor').forEach(anchor => {
   const grid=anchor.closest('[data-testid="stVerticalBlock"]');
   if(!grid) return;
   // Streamlit rewrites class/style during size reports. Keep our layout state
   // in attributes it does not own, so those updates cannot reset it to one column.
   if(!grid.hasAttribute('data-mc-choice-grid'))grid.dataset.mcChoiceGrid='';
   const cells=[...grid.children].filter(e=>!e.contains(anchor));
   if(!cells.length) return;
   let required=0;
   const keys=[];
   cells.forEach(cell => {
    cell.querySelectorAll('[data-testid="stMarkdownContainer"] p').forEach(p=>{
     const font=getComputedStyle(p).font;
     const key=font+'\n'+p.innerHTML;
     keys.push(key);
     if(!measurements.has(key) && !pending.has(key)){
      const clone=p.cloneNode(true);clone.dataset.mcChoiceProbe='1';
      Object.assign(clone.style,{width:'max-content',maxWidth:'none',whiteSpace:'nowrap',font,pointerEvents:'none'});
      pending.set(key,clone);probes.push([key,clone]);
     }
    });
    if(cell.querySelector('iframe')) required=Math.max(required,190);
   });
   const width=grid.getBoundingClientRect().width;
   if(!observed.has(grid)){observed.set(grid,width);resizeObserver.observe(grid);}
   layouts.push({grid,cells,keys,required,width});
  });
  // Mount all probes together, measure together, then write the final grids.
  if(probes.length){
   const host=doc.createElement('div');host.dataset.mcChoiceProbe='1';
   Object.assign(host.style,{position:'fixed',left:'0',top:'0',visibility:'hidden',width:'max-content',pointerEvents:'none',contain:'layout style paint'});
   probes.forEach(([,clone])=>host.appendChild(clone));
   doc.body.appendChild(host);
   probes.forEach(([key,clone])=>measurements.set(key,clone.getBoundingClientRect().width+4));
   host.remove();
  }
  layouts.forEach(({grid,cells,keys,required,width})=>{
   keys.forEach(key=>{required=Math.max(required,measurements.get(key)||0);});
   const cols=[4,2,1].find(n=>cells.length>=n && required<=(width-20*(n-1))/n) || 1;
   if(grid.dataset.columns!==String(cols)){
    grid.dataset.columns=String(cols);
   }
  });
  // Keep the cache bounded during long editing sessions.
  while(measurements.size>256)measurements.delete(measurements.keys().next().value);
  observed.forEach((_,grid)=>{if(!grid.isConnected){resizeObserver.unobserve(grid);observed.delete(grid);}});
 };
 let timer=null;
 // Streamlit streams many individual DOM updates for one results page. Wait
 // for that burst to settle instead of measuring partial grids every frame.
 const schedule=()=>{window.clearTimeout(timer);timer=window.setTimeout(()=>{
  timer=null;window.parent.requestAnimationFrame(refresh);
 },80);};
 const observer=new window.parent.MutationObserver(records=>{
  if(records.some(r=>r.target.closest?.('[data-mc-choice-grid]') ||
   [...r.addedNodes,...r.removedNodes].some(n=>n.nodeType===1 && !n.dataset?.mcChoiceProbe &&
    (n.matches?.('.mc-choice-grid-anchor') || n.querySelector?.('.mc-choice-grid-anchor')))))schedule();
 });
 // Class changes from the framework are not content changes. Watching them
 // previously reinstalled the grid and repeatedly changed the panel's height.
 observer.observe(doc.body,{childList:true,subtree:true});
 const fontsChanged=()=>{measurements.clear();schedule();};
 window.parent.addEventListener('resize',schedule);
 doc.fonts?.ready.then(schedule);
 doc.fonts?.addEventListener('loadingdone',fontsChanged);
 window.parent.__mcChoiceLayout={version:2,schedule,dispose:()=>{
  window.clearTimeout(timer);observer.disconnect();resizeObserver.disconnect();
  window.parent.removeEventListener('resize',schedule);
  doc.fonts?.removeEventListener('loadingdone',fontsChanged);
 }};
 schedule();
 };
 const script=window.parent.document.createElement('script');
 script.textContent='('+install.toString()+')('+JSON.stringify(document.querySelector('style').textContent)+')';
 window.parent.document.body.appendChild(script);script.remove();
})();
</script>'''
