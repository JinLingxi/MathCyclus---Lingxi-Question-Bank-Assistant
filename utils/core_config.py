import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# ================= 配置与常量 =================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAPTERS_DIR = os.path.join(BASE_DIR, "chapters")
CSV_INDEX_PATH = os.path.join(BASE_DIR, "utils", "题库索引表.csv")

# AI 配置
AI_API_KEY = os.getenv("AI_API_KEY")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
AI_MODEL_NAME = os.getenv("AI_MODEL_NAME", "gpt-4o")

# 读取 OCR 提示词 (优先从文件读取，否则从环境变量)
ocr_prompt_file = os.path.join(BASE_DIR, "ocr_prompt.txt")
if os.path.exists(ocr_prompt_file):
    with open(ocr_prompt_file, "r", encoding="utf-8") as f:
        AI_OCR_PROMPT = f.read()
else:
    # 处理 .env 中的换行符转义
    AI_OCR_PROMPT = os.getenv("AI_OCR_PROMPT", "请识别这张图片中的数学题，并严格按照 LaTeX 格式输出。").replace('\\n', '\n')


SUBJECTS = [
    "集合", "复数", "不等式", "函数", "概率", "统计", "排列组合", 
    "圆锥曲线", "解三角形", "三角函数", "立体几何", "向量", 
    "数列", "导数", "线性规划", "数论", "命题与逻辑"
]

PAPER_TYPES = {"G": "高考题", "M": "模拟题", "W": "外国题", "XK": "学考题", "XS": "线上联考"}