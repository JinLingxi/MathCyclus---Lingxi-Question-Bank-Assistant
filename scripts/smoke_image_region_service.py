"""Smoke test image-region cropping, with optional OpenCV detection."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.image_region_service import crop_visual_regions, detect_visual_regions, opencv_available


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mathcyclus_image_regions_") as temp_dir:
        root = Path(temp_dir)
        source = root / "page.png"
        image = Image.new("RGB", (600, 800), "white")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((180, 220, 430, 470), outline="black", width=8)
        drawing.line((180, 470, 430, 220), fill="black", width=6)
        image.save(source)
        explicit = crop_visual_regions(
            source,
            [{"bbox": [180, 220, 430, 470], "detector": "smoke"}],
            root / "crops",
            name_prefix="page_001_region",
        )
        checks = {
            "crop_created": len(explicit) == 1 and Path(explicit[0]["source_path"]).is_file(),
            "crop_margin_applied": explicit[0]["crop_bbox"] == [168, 208, 442, 482],
        }
        if opencv_available():
            detected = detect_visual_regions(source)
            checks["opencv_region_detected"] = bool(detected)
    for name, ok in checks.items():
        print(f"{name}={'ok' if ok else 'failed'}")
    print(f"opencv_available={opencv_available()}")
    print(f"status={'ok' if all(checks.values()) else 'failed'}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
