"""Render bookmark inventory pages without modifying task state."""
import argparse,json,fitz
from pathlib import Path
root=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--year',type=int,required=True);a=ap.parse_args()
work=root/f'data/imports/codex_{a.year}_restart'
inventory=json.loads((work/'source_inventory.json').read_text(encoding='utf8'))
with fitz.open(next(root.glob('1952-2026*.pdf'))) as pdf:
    for title,start,end in inventory:
        for page in range(start,end+1):
            png=work/f'page_{page}.png'
            if not png.exists():pdf[page-1].get_pixmap(matrix=fitz.Matrix(1.7,1.7),alpha=False).save(png)
            txt=work/f'page_{page}.txt'
            if not txt.exists():txt.write_text(pdf[page-1].get_text(),encoding='utf8')
print(json.dumps(dict(year=a.year,papers=len(inventory),pages=sum(p[2]-p[1]+1 for p in inventory))))
