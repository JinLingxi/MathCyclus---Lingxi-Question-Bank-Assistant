from pathlib import Path
import json,sys,fitz
w=Path(sys.argv[1]);n=json.loads((w/'native_handout_checks.json').read_text(encoding='utf8'))
out=Path(n['output']);folder=out/'pages';folder.mkdir(exist_ok=True)
with fitz.open(out/'main.pdf') as d:
    for i,p in enumerate(d,1):p.get_pixmap(matrix=fitz.Matrix(1.15,1.15),alpha=False).save(folder/f'p{i:03}.png')
    print(str(folder),len(d))
