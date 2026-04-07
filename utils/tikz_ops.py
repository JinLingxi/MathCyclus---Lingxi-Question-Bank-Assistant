import os
import hashlib
import base64
import subprocess
import shutil
import uuid
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
        try:
            with open(target_png_path, "rb") as f:
                return base64.b64encode(f.read()).decode('utf-8'), None
        except Exception:
            # 如果读取缓存失败（可能正被占用），则强制重新编译
            needs_compile = True
            
    compile_dir = os.path.join(base_dir, ".tikz_cache")
    ensure_dir(compile_dir)
    
    # 使用 uuid 确保并发写入时不会出现 [WinError 32] 进程冲突
    unique_id = uuid.uuid4().hex
    tex_path = os.path.join(compile_dir, f"{unique_id}.tex")
    pdf_path = os.path.join(compile_dir, f"{unique_id}.pdf")
    temp_png_path = os.path.join(compile_dir, f"{unique_id}.png")
    aux_path = os.path.join(compile_dir, f"{unique_id}.aux")
    log_path = os.path.join(compile_dir, f"{unique_id}.log")
    
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

    try:
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_content)
            
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
                try:
                    shutil.copy2(temp_png_path, target_png_path)
                except Exception:
                    pass # 忽略并发覆盖 target 的错误
            with open(temp_png_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode('utf-8')
            return b64_data, None
            
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"
    except subprocess.CalledProcessError:
        return None, "COMPILE_ERROR"
    except Exception as e:
        return None, str(e)
    finally:
        # 清理所有独占生成的临时文件，释放空间
        for temp_file in [tex_path, pdf_path, temp_png_path, aux_path, log_path]:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass
        
    return None, "UNKNOWN_ERROR"