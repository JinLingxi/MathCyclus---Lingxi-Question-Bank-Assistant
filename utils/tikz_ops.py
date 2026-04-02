import os
import hashlib
import base64
import subprocess
import shutil
from .file_ops import ensure_dir

def get_tikz_image_b64(tikz_code, base_dir, source_tex_path=None, target_png_path=None):
    """
    将 TikZ 代码编译为 PNG 图片并返回 base64 编码。
    如果提供了 source_tex_path 和 target_png_path，则使用目标路径作为缓存，并基于文件修改时间更新。
    否则使用基于代码哈希的全局缓存。
    """
    needs_compile = True
    
    if source_tex_path and target_png_path:
        if os.path.exists(target_png_path) and os.path.exists(source_tex_path):
            if os.path.getmtime(target_png_path) >= os.path.getmtime(source_tex_path):
                needs_compile = False
    else:
        cache_dir = os.path.join(base_dir, ".tikz_cache")
        ensure_dir(cache_dir)
        code_hash = hashlib.md5(tikz_code.encode('utf-8')).hexdigest()
        target_png_path = os.path.join(cache_dir, f"{code_hash}.png")
        if os.path.exists(target_png_path):
            needs_compile = False
            
    if not needs_compile and os.path.exists(target_png_path):
        with open(target_png_path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8'), None
            
    compile_dir = os.path.join(base_dir, ".tikz_cache")
    ensure_dir(compile_dir)
    
    temp_hash = hashlib.md5(tikz_code.encode('utf-8')).hexdigest()
    tex_path = os.path.join(compile_dir, f"{temp_hash}.tex")
    pdf_path = os.path.join(compile_dir, f"{temp_hash}.pdf")
    temp_png_path = os.path.join(compile_dir, f"{temp_hash}.png")
    
    tex_content = f"""\\documentclass[tikz, border=2mm]{{standalone}}
\\usepackage{{ctex}}
\\usepackage{{amsmath}}
\\usepackage{{amssymb}}
\\usepackage{{tikz}}
\\usetikzlibrary{{patterns}}
\\usetikzlibrary{{calc,positioning,intersections,arrows}}
\\usetikzlibrary{{shapes.geometric,through,decorations.pathmorphing,arrows.meta,quotes,mindmap,shapes.symbols,shapes.arrows,automata,angles,3d,trees,shadows,shapes.callouts,decorations.pathreplacing,decorations.markings}}
\\begin{{document}}
{tikz_code}
\\end{{document}}"""

    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex_content)
        
    try:
        # 编译 PDF (调用系统的 xelatex)
        subprocess.run(
            ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "-output-directory", compile_dir, tex_path], 
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15
        )
        
        # 将 PDF 转为 PNG
        try:
            import fitz # 需要 pip install pymupdf
            doc = fitz.open(pdf_path)
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=150)
            pix.save(temp_png_path)
            doc.close()
        except ImportError:
            return None, "MISSING_PYMUPDF"
            
        if os.path.exists(temp_png_path):
            if target_png_path:
                ensure_dir(os.path.dirname(target_png_path))
                shutil.copy2(temp_png_path, target_png_path)
            with open(temp_png_path, "rb") as f:
                return base64.b64encode(f.read()).decode('utf-8'), None
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"
    except subprocess.CalledProcessError:
        return None, "COMPILE_ERROR"
    except Exception as e:
        return None, str(e)
        
    return None, "UNKNOWN_ERROR"