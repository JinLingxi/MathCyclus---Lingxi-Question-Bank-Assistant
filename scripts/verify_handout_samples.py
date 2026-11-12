"""Verify compiled handout/training samples, answer hiding and grayscale rendering."""

import argparse
import json
import re
from pathlib import Path

import fitz


def verify_samples(directory: Path) -> dict:
    variants = []
    names = ("handout_color", "handout_mono", "training_color", "training_mono",
             "formal_handout", "formal_training")
    for name in names:
        folder = directory / name
        log = (folder / "main.log").read_text(encoding="utf-8", errors="replace")
        if re.search(r"Overfull \\[hv]box|Missing character:|^!", log, re.MULTILINE):
            raise ValueError("样张存在溢出、缺字或编译错误：" + name)
        with fitz.open(folder / "main.pdf") as pdf:
            text = "\n".join(page.get_text() for page in pdf)
            normalized = re.sub(r"\s+", "", text)
            training = name.startswith("training") or name == "formal_training"
            if name.startswith(("handout_", "training_")):
                if training == ("配方得" in text):
                    raise ValueError("答案/解析显示模式错误：" + name)
                if "知识回顾" not in normalized or "易错提醒" not in normalized:
                    raise ValueError("中文盒子标题缺失")
                if ("第36步" not in normalized
                        or sum("写清研究对象" in re.sub(r"\s+", "", page.get_text()) for page in pdf) < 2):
                    raise ValueError("跨页内容不完整")
            else:
                if "第3题" not in normalized:
                    raise ValueError("正式题导出题数不完整")
                if training == ("故选A" in normalized):
                    raise ValueError("正式题答案隐藏错误")
            image_count = 0
            for page in pdf:
                for image in page.get_images():
                    for rect in page.get_image_rects(image[0]):
                        if rect.x0 < -1 or rect.x1 > page.rect.width + 1:
                            raise ValueError("图片超出纸面：" + name)
                    image_count += 1
            if name.startswith("formal_") and image_count < 2:
                raise ValueError("正式题配图缺失：" + name)
            mono = name.endswith("_mono") or name == "formal_training"
            # Rasterize all sample pages: grayscale style must not introduce
            # color; source images themselves can retain original color.
            colored_pixels = 0
            if name.startswith(("handout_", "training_")):
                for page in pdf:
                    pixels = page.get_pixmap(matrix=fitz.Matrix(0.3, 0.3), colorspace=fitz.csRGB).samples
                    colored_pixels += sum(max(r, g, b) - min(r, g, b) > 3
                                          for r, g, b in zip(pixels[0::3], pixels[1::3], pixels[2::3]))
                if mono and colored_pixels:
                    raise ValueError("黑白样张含彩色像素：" + name)
                if not mono and not colored_pixels:
                    raise ValueError("彩色样张未显示样式颜色：" + name)
            variants.append({"variant": name, "pages": len(pdf), "image_count": image_count,
                             "mode_verified": True, "colored_pixels": colored_pixels,
                             "overflow_or_missing_glyph": False})
    return {"status": "ok", "variants": variants, "backend": "tcolorbox",
            "lucide_validated": False, "notes": [
                "Lucide is not installed and could not be downloaded in this environment.",
                "Monochrome styling does not recolor user-provided images.",
                "Compiled with XeLaTeX and shell escape disabled; source data is unchanged."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = verify_samples(args.directory)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
