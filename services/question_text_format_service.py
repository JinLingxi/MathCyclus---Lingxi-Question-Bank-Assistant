"""Small source-format rules shared by new imports and explicit migrations."""
import re

CHOICE_BLANK_STOP = re.compile(r'([（(]\s*\\hspace\{1cm\}\s*[）)])\s*[。.]')
FILL_BLANK_STOP = re.compile(r'(\\underline\s*\{\s*\\hspace\s*\{\s*4em\s*\}\s*\})。')


def question_display_note(value):
    """Hide routine transcription boilerplate, retaining substantive review notes."""
    return str(value or '').replace('对照原书扫描页转写，保留原书答案及解法。', '').strip()


def normalize_fill_blank_stop(text: str) -> str:
    """Only change the Chinese stop directly following the specified fill blank."""
    return FILL_BLANK_STOP.sub(r'\1.', text)


def normalize_choice_blank_stop(text: str) -> str:
    return normalize_fill_blank_stop(CHOICE_BLANK_STOP.sub(r'\1', text))
