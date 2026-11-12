"""Conservative text helpers for reviewed response relocation; no automatic approval."""
import re
from collections import Counter
from difflib import SequenceMatcher


def canonical(text):
    text=re.sub(r"\\begin\{tikzpicture\}[\s\S]*?\\end\{tikzpicture\}","",text)
    text=re.sub(r"\\(?:questionasset|includegraphics)(?:\[[^\]]*\])?\{[^{}]*\}","",text)
    text=re.sub(r"\\(?:underline|hspace)\s*\{(?:[^{}]|\{[^{}]*\})*\}","",text)
    text=re.sub(r"\\(?:dfrac|tfrac)\b",lambda _:r"\frac",text)
    text=re.sub(r"\\(?:leq|leqslant)\b",lambda _:r"\le",text)
    text=re.sub(r"\\(?:geq|geqslant)\b",lambda _:r"\ge",text)
    text=re.sub(r"\\(?:left|right|displaystyle|textstyle)\b","",text)
    text=re.sub(r"\\(?:mathrm|mathbf|mathbb|text)\b","",text)
    text=re.sub(r"(?m)(?<!\\)%[^\n]*","",text)
    return re.sub(r"[\s{}$，,。．.；;：:（()）]","",text)


def numeric(text):
    return Counter(re.findall(r"\d+(?:\.\d+)?",canonical(text)))


def score(left,right):
    a,b=canonical(left),canonical(right)
    return SequenceMatcher(None,a,b,autojunk=False).ratio() if a and b else 0
