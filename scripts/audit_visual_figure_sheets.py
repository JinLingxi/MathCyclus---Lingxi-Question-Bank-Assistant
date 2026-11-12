"""Build labelled contact sheets for manual inspection, without asserting review."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--year', type=int, required=True)
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    work = root / f'data/imports/codex_{args.year}_restart'
    payloads = json.loads((work / 'visual_payloads.json').read_text(encoding='utf8'))
    assets = [(p['source_item_id'], a) for p in payloads for a in p['assets']]
    out = work / 'figure_audit'
    out.mkdir(exist_ok=True)
    manifest = []
    for start in range(0, len(assets), 12):
        canvas = Image.new('RGB', (1200, 1400), 'white')
        draw = ImageDraw.Draw(canvas)
        for j, (source_id, asset) in enumerate(assets[start:start+12]):
            path = root / asset['source_path']
            with Image.open(path) as im:
                thumb = ImageOps.contain(im.convert('RGB'), (380, 305))
                x, y = (j % 3) * 400, (j // 3) * 350
                canvas.paste(thumb, (x+(400-thumb.width)//2, y+35))
                draw.text((x+8,y+8), source_id+' / '+asset['caption'], fill='black')
                manifest.append({'source_item_id': source_id, 'path': asset['source_path'], 'size': list(im.size), 'sheet': start//12+1})
        canvas.save(out / f'sheet_{start//12+1:02d}.png')
    (out / 'manifest.json').write_text(json.dumps({'assets':manifest,'human_visual_review':'pending'}, indent=2), encoding='utf8')
    print(json.dumps({'assets':len(assets),'sheets':(len(assets)+11)//12,'path':str(out)}))

if __name__ == '__main__':
    main()
