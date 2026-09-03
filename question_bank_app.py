import streamlit as st
import os
import re
import time
import datetime
import base64
import json
import requests
import hashlib
import html
import subprocess
import shutil
import uuid
import sys
import tempfile
from dotenv import load_dotenv, dotenv_values
try:
    from PIL import ImageGrab
except ImportError:
    ImageGrab = None

import streamlit.components.v1 as components
import io
from services.ai_service import extract_json_obj_from_text, normalize_chat_completions_url, post_chat_completion
from services.file_service import atomic_write_text, backup_existing_file, file_change_token
from services.operation_log import read_recent_operations, record_operation
from services.question_service import (
    QuestionDuplicateError,
    create_question_file,
    find_duplicate_matches,
    question_fingerprint,
    scan_duplicate_pairs,
)
from services.semantic_search_service import (
    SemanticSearchError,
    build_index as build_semantic_index,
    invalidate_path as invalidate_semantic_path,
    index_status as semantic_index_status,
    search as semantic_search,
)
from services.draft_parse_service import (
    asset_caption_from_source_path as _service_asset_caption_from_source_path,
    extract_batch_info_from_ocr as _extract_batch_info_from_ocr,
    extract_choice_items as _service_extract_choice_items,
    extract_choices_from_stem as _service_extract_choices_from_stem,
    extra_dict as _service_extra_dict,
    fix_problem_format as _service_fix_problem_format,
    increment_question_number as _service_increment_question_number,
    join_number_and_sub_number as _service_join_number_and_sub_number,
    json_list_text as _service_json_list_text,
    normalize_single_problem_structure as _service_normalize_single_problem_structure,
    parse_asset_lines as _service_parse_asset_lines,
    parse_single_ocr_result as _parse_single_ocr_result,
    process_batch_ocr_result as _service_process_batch_ocr_result,
    read_balanced_argument as _service_read_balanced_argument,
    source_label as _service_source_label,
    split_input_items as _service_split_input_items,
    split_problem_block_by_choices as _service_split_problem_block_by_choices,
    split_text_list as _service_split_text_list,
    strip_problem_body as _service_strip_problem_body,
)
from utils.runtime_files import ensure_log_csv
from utils.sortable_list import st_sortable_list
from utils.local_stats import sync_question_activity

def _compat_container(*, key=None, **kwargs):
    return st.container(**kwargs)


def _question_key(prefix: str, fpath: str) -> str:
    return hashlib.md5(f"{prefix}:{fpath}".encode("utf-8", errors="ignore")).hexdigest()[:12]


APP_ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(APP_ROOT, ".env"))
ensure_log_csv(APP_ROOT)

from utils.core_config import *
from utils.file_ops import *
from utils.tikz_ops import *
from utils.latex_ops import *
from utils.csv_ops import add_to_csv_index, read_csv_index, update_csv_index_for_edit

# ================= 工具函数 =================
def _save_batch_question_if_new(
    file_path,
    content,
    year,
    paper_type,
    paper_name,
    question_number,
    subject,
    duplicate_matches_out=None,
):
    """Save a batch result only when its path and statement are new."""
    if os.path.exists(file_path):
        return False

    try:
        create_question_file(
            file_path,
            content,
            year,
            paper_type,
            paper_name,
            question_number,
            subject,
        )
    except QuestionDuplicateError as exc:
        if duplicate_matches_out is not None:
            duplicate_matches_out.extend(exc.matches)
        return False
    return True


def _editable_paper_type_options(paper_type_scope=None):
    """Keep WK confined to the dedicated cloze-question workspace."""
    if paper_type_scope == "WK":
        return ["WK"]
    return [paper_type for paper_type in PAPER_TYPES if paper_type != "WK"]


def render_question_preview(content: str, show_title: bool = False, prepared_markdown: str = None):
    """Render a question preview with typography isolated from surrounding UI."""
    st.markdown('<span class="mc-question-preview-anchor"></span>', unsafe_allow_html=True)
    preview_markdown = prepared_markdown
    if preview_markdown is None:
        preview_markdown = _cached_latex_to_markdown(content, show_title)
    st.markdown(preview_markdown, unsafe_allow_html=True)


@st.cache_data(show_spinner=False, max_entries=256)
def _cached_latex_to_markdown(content: str, show_title: bool = False):
    return latex_to_markdown(content, show_title=show_title)


@st.cache_data(show_spinner=False, max_entries=512)
def _read_question_text_cached(fpath: str, change_token):
    with open(fpath, "r", encoding="utf-8") as question_file:
        return question_file.read()


def read_question_text(fpath: str):
    return _read_question_text_cached(fpath, file_change_token(fpath))


@st.cache_data(show_spinner=False, max_entries=512)
def _load_question_editor_assets_cached(fpath: str, change_token):
    with open(fpath, "r", encoding="utf-8") as question_file:
        content = question_file.read()
    meta, _ = parse_meta_data(content)
    return {
        "content": content,
        "meta": meta,
        "editor_height": get_editor_height(content),
        "preview_markdown": latex_to_markdown(content, show_title=False),
    }


def load_question_editor_assets(fpath: str):
    return _load_question_editor_assets_cached(fpath, file_change_token(fpath))


@st.cache_data(show_spinner=False, max_entries=512)
def _cached_editor_height(content: str):
    return get_editor_height(content)


@st.cache_data(show_spinner=False, max_entries=512)
def _cached_question_meta(content: str):
    meta, _ = parse_meta_data(content)
    return meta


# 注入自定义 CSS
def inject_custom_css():
    st.markdown("""
        <style>
        html {
            scrollbar-gutter: stable;
        }
        body {
            overflow-y: scroll;
            overflow-x: hidden;
        }
        div[data-testid="stAppViewContainer"] {
            overflow-y: scroll;
            scrollbar-gutter: stable;
        }
        header[data-testid="stHeader"] {
            background: transparent !important;
            height: 0 !important;
            overflow: visible !important;
        }
        div[data-testid="stToolbar"],
        div[data-testid="stDecoration"],
        #MainMenu {
            visibility: hidden !important;
            height: 0 !important;
        }
        .stApp {
            overflow-x: hidden;
            background: linear-gradient(180deg, #f7f8fb 0%, #f2f3f6 100%);
            color: #1d1d1f;
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", "Microsoft YaHei", sans-serif;
        }
        :root {
            --mc-bg: #f5f5f7;
            --mc-surface: rgba(255, 255, 255, 0.78);
            --mc-surface-solid: #ffffff;
            --mc-border: rgba(0, 0, 0, 0.09);
            --mc-border-strong: rgba(0, 0, 0, 0.16);
            --mc-text: #1d1d1f;
            --mc-text-muted: #6e6e73;
            --mc-blue: #007aff;
            --mc-blue-hover: #0066d6;
            --mc-shadow: 0 10px 30px rgba(0, 0, 0, 0.07);
            --mc-control-radius: 8px;
        }
        .block-container,
        div[data-testid="stAppViewBlockContainer"] {
            padding-top: 0 !important;
            padding-bottom: 2rem !important;
        }
        section.main > div.block-container,
        main .block-container,
        div[data-testid="stMainBlockContainer"] {
            padding-top: 0 !important;
        }
        h1, h2, h3, h4, h5, h6 {
            color: var(--mc-text) !important;
            letter-spacing: 0 !important;
            font-weight: 650 !important;
        }
        .block-container h1:first-child,
        .block-container h2:first-child,
        .block-container h3:first-child {
            margin-top: 0 !important;
        }
        div[data-testid="stMarkdownContainer"] h1,
        div[data-testid="stMarkdownContainer"] h2 {
            margin-top: 0 !important;
            padding-top: 0 !important;
        }
        p, li, label, span {
            letter-spacing: 0 !important;
        }
        hr {
            border-color: rgba(0, 0, 0, 0.08) !important;
        }
        section[data-testid="stSidebar"] {
            background: rgba(245, 243, 255, 0.92) !important;
            border-right: 1px solid rgba(109, 40, 217, 0.14) !important;
            backdrop-filter: blur(18px);
            -webkit-backdrop-filter: blur(18px);
        }
        div[data-testid="stExpander"],
        div[data-testid="stForm"],
        div[data-testid="stPopover"] > div {
            border: 1px solid var(--mc-border) !important;
            border-radius: 8px !important;
            background: var(--mc-surface) !important;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03) !important;
        }
        div[data-testid="stMetric"],
        div[data-testid="stAlert"] {
            border-radius: 8px !important;
            border: 1px solid var(--mc-border) !important;
            box-shadow: none !important;
        }
        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        div[data-testid="stTextArea"] textarea,
        div[data-baseweb="select"] > div {
            border-radius: var(--mc-control-radius) !important;
            border-color: var(--mc-border) !important;
            background: rgba(255, 255, 255, 0.9) !important;
            box-shadow: inset 0 1px 1px rgba(0, 0, 0, 0.02) !important;
            transition: border-color 0.14s ease, box-shadow 0.14s ease, background 0.14s ease !important;
        }
        div[data-testid="stTextInput"] input:focus,
        div[data-testid="stNumberInput"] input:focus,
        div[data-testid="stTextArea"] textarea:focus,
        div[data-baseweb="select"] > div:focus-within {
            border-color: rgba(0, 122, 255, 0.72) !important;
            box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.14) !important;
            background: #ffffff !important;
        }
        div[data-testid="stButton"] > button,
        div[data-testid="stDownloadButton"] > button,
        div[data-testid="stPopover"] > button {
            min-height: 2.32rem !important;
            border-radius: var(--mc-control-radius) !important;
            border: 1px solid var(--mc-border) !important;
            background: rgba(255, 255, 255, 0.86) !important;
            color: var(--mc-text) !important;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04) !important;
            transition: transform 0.12s ease, border-color 0.12s ease, background 0.12s ease, box-shadow 0.12s ease !important;
        }
        body:has(#mc-entry-page-anchor) div[data-testid="stVerticalBlock"]:has(#entry-save-button-anchor) div[data-testid="stButton"] > button[kind="primary"] {
            background: #bfdbfe !important;
            border-color: #93c5fd !important;
            color: #17324d !important;
            box-shadow: 0 8px 18px rgba(59, 130, 246, 0.16) !important;
        }
        body:has(#mc-entry-page-anchor) div[data-testid="stVerticalBlock"]:has(#entry-save-button-anchor) div[data-testid="stButton"] > button[kind="primary"]:hover {
            background: #93c5fd !important;
            border-color: #60a5fa !important;
            color: #12283d !important;
        }
        body:has(#mc-entry-page-anchor) div[data-testid="stVerticalBlock"]:has(#entry-save-button-anchor) div[data-testid="stButton"] > button[kind="primary"]:focus-visible {
            outline: 3px solid rgba(96, 165, 250, 0.28) !important;
            outline-offset: 2px !important;
        }
        div[data-testid="stButton"] > button:hover,
        div[data-testid="stDownloadButton"] > button:hover,
        div[data-testid="stPopover"] > button:hover {
            border-color: var(--mc-border-strong) !important;
            background: #ffffff !important;
            box-shadow: 0 3px 10px rgba(0, 0, 0, 0.07) !important;
            transform: translateY(-1px);
        }
        div[data-testid="stButton"] > button:active,
        div[data-testid="stDownloadButton"] > button:active,
        div[data-testid="stPopover"] > button:active {
            transform: translateY(0);
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05) !important;
        }
        button[kind="primary"],
        div[data-testid="stButton"] > button[kind="primary"] {
            border-color: var(--mc-blue) !important;
            background: linear-gradient(180deg, #1388ff 0%, var(--mc-blue) 100%) !important;
            color: #ffffff !important;
            box-shadow: 0 5px 14px rgba(0, 122, 255, 0.22) !important;
        }
        button[kind="primary"]:hover,
        div[data-testid="stButton"] > button[kind="primary"]:hover {
            background: linear-gradient(180deg, #0b7df0 0%, var(--mc-blue-hover) 100%) !important;
            box-shadow: 0 7px 18px rgba(0, 122, 255, 0.28) !important;
        }
        div[data-testid="stTabs"] button {
            border-radius: 8px 8px 0 0 !important;
            color: var(--mc-text-muted) !important;
        }
        div[data-testid="stTabs"] button[aria-selected="true"] {
            color: var(--mc-blue) !important;
            font-weight: 650 !important;
        }
        div[data-testid="stDataFrame"],
        div[data-testid="stTable"] {
            border-radius: 8px !important;
            overflow: hidden !important;
            border: 1px solid var(--mc-border) !important;
            background: var(--mc-surface-solid) !important;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03) !important;
        }
        div[data-testid="stToast"] {
            border-radius: 8px !important;
            border: 1px solid var(--mc-border) !important;
            box-shadow: var(--mc-shadow) !important;
        }
        ::selection {
            background: rgba(0, 122, 255, 0.18);
        }
        .katex .boxed {
            border: 1px solid #c9d1d9 !important;
            border-radius: 4px !important;
            padding: 2px 6px !important;
        }
        div[data-testid="stMarkdownContainer"]:has(> .mc-question-preview-anchor) {
            display: none !important;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-question-actions-grid-anchor) {
            border: 0 !important;
            background: transparent !important;
            box-shadow: none !important;
            padding: 0 !important;
            margin-top: 0.62rem !important;
        }
        div[data-testid="stMarkdownContainer"]:has(> .mc-question-actions-grid-anchor),
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-question-actions-grid-anchor) div[data-testid="stElementContainer"]:has(.mc-question-actions-grid-anchor) {
            display: none !important;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-question-actions-grid-anchor) div[data-testid="stButton"] {
            width: 100% !important;
            min-width: 0 !important;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-question-actions-grid-anchor) div[data-testid="stButton"] > button {
            width: 100% !important;
            min-height: 2.45rem !important;
            justify-content: center !important;
            white-space: normal !important;
        }
        div[data-testid="column"]:has(.mc-question-preview-anchor):not(:has(div[data-testid="column"] .mc-question-preview-anchor)) div[data-testid="stMarkdownContainer"] {
            font-size: 1rem !important;
            line-height: 1.65 !important;
        }
        div[data-testid="column"]:has(.mc-question-preview-anchor):not(:has(div[data-testid="column"] .mc-question-preview-anchor)) div[data-testid="stMarkdownContainer"] p,
        div[data-testid="column"]:has(.mc-question-preview-anchor):not(:has(div[data-testid="column"] .mc-question-preview-anchor)) div[data-testid="stMarkdownContainer"] li {
            line-height: 1.65 !important;
            margin-top: 0 !important;
            margin-bottom: 0.7rem !important;
        }
        div[data-testid="column"]:has(.mc-question-preview-anchor):not(:has(div[data-testid="column"] .mc-question-preview-anchor)) .katex-display {
            margin: 0.8rem 0 !important;
        }
        div[data-testid="column"]:has(.mc-question-preview-anchor):not(:has(div[data-testid="column"] .mc-question-preview-anchor)) .katex {
            line-height: normal !important;
        }
        div[data-testid="stHorizontalBlock"]:has(#left-panel-anchor),
        div[data-testid="stHorizontalBlock"]:has(#paper-left-anchor),
        div[data-testid="stHorizontalBlock"]:has(#time-left-anchor),
        div[data-testid="stHorizontalBlock"]:has(#adv-search-left-anchor) {
            display: flex !important;
            flex-flow: row nowrap !important;
            align-items: flex-start !important;
            width: 100% !important;
            gap: 1rem !important;
            overflow: visible !important;
        }
        div[data-testid="stHorizontalBlock"]:has(#adv-search-left-anchor):has(#adv-search-right-anchor) {
            display: grid !important;
            grid-template-columns: minmax(300px, 20%) minmax(0, 80%) !important;
            align-items: start !important;
        }
        div[data-testid="stHorizontalBlock"]:has(#adv-search-left-anchor):has(#adv-search-right-anchor) > div[data-testid="column"] {
            width: auto !important;
            max-width: none !important;
            min-width: 0 !important;
            flex: initial !important;
        }
        div[data-testid="column"]:has(#left-panel-anchor),
        div[data-testid="column"]:has(#time-left-anchor) {
            flex: 0 0 28% !important;
            width: 28% !important;
            max-width: 28% !important;
        }
        div[data-testid="column"]:has(#paper-left-anchor) {
            flex: 0 0 21% !important;
            width: 21% !important;
            max-width: 21% !important;
        }
        div[data-testid="column"]:has(#adv-search-left-anchor) {
            flex: 0 0 20% !important;
            width: 20% !important;
            max-width: 20% !important;
        }
        div[data-testid="column"]:has(#right-panel-anchor) {
            flex: 1 1 0% !important;
            width: auto !important;
            max-width: none !important;
        }
        div[data-testid="column"]:has(#time-right-anchor) {
            flex: 0 0 70% !important;
            width: 70% !important;
            max-width: 70% !important;
        }
        div[data-testid="column"]:has(#paper-right-anchor) {
            flex: 0 0 77% !important;
            width: 77% !important;
            max-width: 77% !important;
        }
        div[data-testid="column"]:has(#adv-search-right-anchor) {
            flex: 0 0 78% !important;
            width: 78% !important;
            max-width: 78% !important;
        }
        div[data-testid="column"]:has(#left-panel-anchor),
        div[data-testid="column"]:has(#paper-left-anchor),
        div[data-testid="column"]:has(#time-left-anchor),
        div[data-testid="column"]:has(#adv-search-left-anchor),
        div[data-testid="column"]:has(#right-panel-anchor),
        div[data-testid="column"]:has(#paper-right-anchor),
        div[data-testid="column"]:has(#time-right-anchor),
        div[data-testid="column"]:has(#adv-search-right-anchor) {
            min-width: 0 !important;
            flex-shrink: 0 !important;
            height: auto !important;
            box-sizing: border-box !important;
        }
        div[data-testid="column"]:has(#left-panel-anchor),
        div[data-testid="column"]:has(#paper-left-anchor),
        div[data-testid="column"]:has(#time-left-anchor),
        div[data-testid="column"]:has(#adv-search-left-anchor) {
            overflow: visible !important;
            padding-right: 1rem !important;
        }
        div[data-testid="column"]:has(#left-panel-anchor),
        div[data-testid="column"]:has(#paper-left-anchor),
        div[data-testid="column"]:has(#time-left-anchor),
        div[data-testid="column"]:has(#adv-search-left-anchor) {
            position: sticky !important;
            top: 56px !important;
            align-self: flex-start !important;
            max-height: calc(100vh - 72px) !important;
            overflow-y: auto !important;
            overflow-x: hidden !important;
            scrollbar-gutter: stable !important;
        }
        div[data-testid="column"]:has(#left-panel-anchor)::-webkit-scrollbar,
        div[data-testid="column"]:has(#paper-left-anchor)::-webkit-scrollbar,
        div[data-testid="column"]:has(#time-left-anchor)::-webkit-scrollbar,
        div[data-testid="column"]:has(#adv-search-left-anchor)::-webkit-scrollbar {
            width: 8px;
        }
        div[data-testid="column"]:has(#left-panel-anchor)::-webkit-scrollbar-thumb,
        div[data-testid="column"]:has(#paper-left-anchor)::-webkit-scrollbar-thumb,
        div[data-testid="column"]:has(#time-left-anchor)::-webkit-scrollbar-thumb,
        div[data-testid="column"]:has(#adv-search-left-anchor)::-webkit-scrollbar-thumb {
            background: rgba(119, 102, 142, 0.28);
            border-radius: 999px;
        }
        div[data-testid="column"]:has(#right-panel-anchor),
        div[data-testid="column"]:has(#paper-right-anchor),
        div[data-testid="column"]:has(#time-right-anchor),
        div[data-testid="column"]:has(#adv-search-right-anchor) {
            overflow: visible !important;
            border-left: 1px solid #e1e4e8 !important;
            padding-left: 1.5rem !important;
        }
        div[data-testid="column"]:has(#right-panel-anchor) > div[data-testid="stVerticalBlock"],
        div[data-testid="column"]:has(#paper-right-anchor) > div[data-testid="stVerticalBlock"],
        div[data-testid="column"]:has(#time-right-anchor) > div[data-testid="stVerticalBlock"],
        div[data-testid="column"]:has(#adv-search-right-anchor) > div[data-testid="stVerticalBlock"],
        div[data-testid="column"]:has(#right-panel-anchor) > div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"],
        div[data-testid="column"]:has(#paper-right-anchor) > div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"],
        div[data-testid="column"]:has(#time-right-anchor) > div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"],
        div[data-testid="column"]:has(#adv-search-right-anchor) > div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"] {
            width: 100% !important;
            min-width: 0 !important;
            max-width: none !important;
            align-self: stretch !important;
            box-sizing: border-box !important;
        }
        /* Fill the detail pane with the editor/preview split instead of its intrinsic content width. */
        div[data-testid="column"]:has(#right-panel-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor),
        div[data-testid="column"]:has(#paper-right-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor),
        div[data-testid="column"]:has(#time-right-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor),
        div[data-testid="column"]:has(#adv-search-right-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor) {
            display: grid !important;
            grid-template-columns: minmax(0, 0.95fr) minmax(0, 1.05fr) !important;
            width: 100% !important;
            min-width: 0 !important;
            max-width: none !important;
            gap: 1rem !important;
            align-items: start !important;
        }
        div[data-testid="column"]:has(#right-panel-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor) > div[data-testid="column"],
        div[data-testid="column"]:has(#paper-right-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor) > div[data-testid="column"],
        div[data-testid="column"]:has(#time-right-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor) > div[data-testid="column"],
        div[data-testid="column"]:has(#adv-search-right-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor) > div[data-testid="column"] {
            width: auto !important;
            min-width: 0 !important;
            max-width: none !important;
            flex: initial !important;
            box-sizing: border-box !important;
        }
        div[data-testid="column"]:has(#right-panel-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor) .stMarkdownContainer,
        div[data-testid="column"]:has(#paper-right-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor) .stMarkdownContainer,
        div[data-testid="column"]:has(#time-right-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor) .stMarkdownContainer,
        div[data-testid="column"]:has(#adv-search-right-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor) .stMarkdownContainer {
            width: 100% !important;
            max-width: none !important;
            overflow-wrap: anywhere;
        }
        @media (max-width: 980px) {
            div[data-testid="column"]:has(#left-panel-anchor),
            div[data-testid="column"]:has(#paper-left-anchor),
            div[data-testid="column"]:has(#time-left-anchor),
            div[data-testid="column"]:has(#adv-search-left-anchor) {
                position: static !important;
                max-height: none !important;
                overflow: visible !important;
                padding-right: 0 !important;
            }
            div[data-testid="column"]:has(#right-panel-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor),
            div[data-testid="column"]:has(#paper-right-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor),
            div[data-testid="column"]:has(#time-right-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor),
            div[data-testid="column"]:has(#adv-search-right-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor) {
                grid-template-columns: minmax(0, 1fr) !important;
            }
        }
        div[data-testid="column"]:has(#right-panel-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor) div[data-testid="stTextArea"],
        div[data-testid="column"]:has(#paper-right-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor) div[data-testid="stTextArea"],
        div[data-testid="column"]:has(#time-right-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor) div[data-testid="stTextArea"],
        div[data-testid="column"]:has(#adv-search-right-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-question-preview-anchor) div[data-testid="stTextArea"] {
            width: 100% !important;
            max-width: none !important;
        }
        /* 调整 st.dialog 的背景遮罩透明度为 40% 黑色 */
        div[data-testid="stDialog"] > div:first-child {
            background-color: rgba(0, 0, 0, 0.4) !important;
        }

        /* 强制 st.dialog 变得更大，更适合查看大图 */
        div[data-testid="stDialog"] div[role="dialog"] {
            width: 90vw !important;
            max-width: 1600px !important;
        }
        </style>
    """, unsafe_allow_html=True)

def inject_sidebar_layout_switch(layout: str):
    """Keep sidebar controls stable while Streamlit rebuilds its native buttons."""
    components.html(
        f"""
        <script>
        (() => {{
            const parentWindow = window.parent;
            const doc = parentWindow.document;
            const modeButtonId = "mc-sidebar-layout-switch";
            const collapseButtonId = "mc-sidebar-collapse-switch";
            const observerKey = "__mcSidebarControlsObserver";
            const nativeButtonLabel = "切换为顶部导航";
            const layout = {layout!r};
            const expandedControlSelector = '[data-testid="stSidebarCollapseButton"]';
            const collapsedControlSelector = '[data-testid="collapsedControl"], [data-testid="stSidebarCollapsedControl"]';
            const nativeCollapseSelector = expandedControlSelector + ", " + collapsedControlSelector;

            ["mc-sidebar-navigation-controls", "mc-navigation-layout-switch"].forEach((id) => {{
                const legacy = doc.getElementById(id);
                if (legacy) legacy.remove();
            }});

            if (parentWindow[observerKey]) {{
                parentWindow[observerKey].disconnect();
                delete parentWindow[observerKey];
            }}

            const removeCustomControls = () => {{
                [modeButtonId, collapseButtonId].forEach((id) => {{
                    const control = doc.getElementById(id);
                    if (control) control.remove();
                }});
            }};

            if (layout !== "sidebar") {{
                removeCustomControls();
                return;
            }}

            function nativeLayoutButton() {{
                return Array.from(doc.querySelectorAll("button")).find((candidate) =>
                    candidate.id !== modeButtonId
                    && candidate.id !== collapseButtonId
                    && candidate.textContent.trim() === nativeButtonLabel
                ) || null;
            }}

            function nativeCollapseButton() {{
                const control = doc.querySelector(nativeCollapseSelector);
                if (!control) return null;
                return control.matches("button") ? control : control.querySelector("button");
            }}

            function hideNativeButtons() {{
                const nativeLayout = nativeLayoutButton();
                if (nativeLayout) {{
                    const container = nativeLayout.closest('[data-testid="stElementContainer"]');
                    (container || nativeLayout).style.setProperty("display", "none", "important");
                }}

                doc.querySelectorAll(nativeCollapseSelector).forEach((control) => {{
                    control.style.setProperty("display", "none", "important");
                }});
            }}

            function readSidebarCollapsedState() {{
                if (doc.querySelector(collapsedControlSelector)) return true;
                if (doc.querySelector(expandedControlSelector)) return false;
                return null;
            }}

            const modeButton = doc.getElementById(modeButtonId) || doc.createElement("button");
            const collapseButton = doc.getElementById(collapseButtonId) || doc.createElement("button");
            const modeButtonIsNew = !modeButton.id;
            const collapseButtonIsNew = !collapseButton.id;

            modeButton.id = modeButtonId;
            modeButton.type = "button";
                modeButton.textContent = "⇄";
            modeButton.title = "切换为顶部导航";
            modeButton.setAttribute("aria-label", "切换为顶部导航");
            Object.assign(modeButton.style, {{
                position: "fixed",
                top: "2px",
                left: "40px",
                zIndex: "2147483647",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: "31px",
                height: "30px",
                margin: "0",
                padding: "0",
                border: "1px solid rgba(109, 40, 217, 0.14)",
                borderRadius: "5px 0 0 5px",
                background: "transparent",
                boxShadow: "none",
                color: "#5b21b6",
                fontFamily: "Arial, sans-serif",
                fontSize: "16px",
                fontWeight: "700",
                lineHeight: "1",
                cursor: "pointer",
                transition: "opacity 180ms cubic-bezier(0.16, 1, 0.3, 1), transform 180ms cubic-bezier(0.16, 1, 0.3, 1), background 140ms ease"
            }});
            modeButton.onmouseenter = () => {{ modeButton.style.background = "rgba(109, 40, 217, 0.10)"; }};
            modeButton.onmouseleave = () => {{ modeButton.style.background = "transparent"; }};
            modeButton.onclick = () => {{
                const native = nativeLayoutButton();
                if (!native || modeButton.dataset.switching === "true") return;
                modeButton.dataset.switching = "true";
                modeButton.style.opacity = "0";
                modeButton.style.pointerEvents = "none";
                native.click();
            }};

            collapseButton.id = collapseButtonId;
            collapseButton.type = "button";
            collapseButton.title = "收缩侧边栏";
            collapseButton.setAttribute("aria-label", "收缩侧边栏");
            Object.assign(collapseButton.style, {{
                position: "fixed",
                top: "2px",
                left: "70px",
                zIndex: "2147483647",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: "31px",
                height: "30px",
                margin: "0",
                padding: "0",
                border: "1px solid rgba(109, 40, 217, 0.14)",
                borderLeft: "0",
                borderRadius: "0 5px 5px 0",
                background: "transparent",
                boxShadow: "none",
                color: "#5b21b6",
                fontFamily: "Arial, sans-serif",
                fontSize: "16px",
                fontWeight: "700",
                lineHeight: "1",
                cursor: "pointer",
                transition: "background 140ms ease, color 140ms ease, transform 140ms ease"
            }});
            collapseButton.onmouseenter = () => {{ collapseButton.style.background = "rgba(109, 40, 217, 0.10)"; }};
            collapseButton.onmouseleave = () => {{ collapseButton.style.background = "transparent"; }};

            let sidebarCollapsed = readSidebarCollapsedState();
            if (sidebarCollapsed === null) sidebarCollapsed = false;

            function applySidebarState(isCollapsed) {{
                sidebarCollapsed = isCollapsed;
                collapseButton.textContent = isCollapsed ? ">>" : "<<";
                collapseButton.title = isCollapsed ? "展开侧边栏" : "收缩侧边栏";
                collapseButton.setAttribute("aria-label", collapseButton.title);
                modeButton.dataset.sidebarCollapsed = isCollapsed ? "true" : "false";
                modeButton.setAttribute("aria-hidden", isCollapsed ? "true" : "false");
                modeButton.tabIndex = isCollapsed ? -1 : 0;
                if (!isCollapsed) {{
                    delete modeButton.dataset.switching;
                    modeButton.style.opacity = "";
                    modeButton.style.pointerEvents = "";
                }}
            }}

            collapseButton.onclick = () => {{
                if (collapseButton.dataset.switching === "true") return;
                const native = nativeCollapseButton();
                if (!native) return;
                collapseButton.dataset.switching = "true";
                applySidebarState(!sidebarCollapsed);
                native.click();
                parentWindow.setTimeout(() => {{
                    delete collapseButton.dataset.switching;
                }}, 420);
            }};

            if (modeButtonIsNew) doc.body.appendChild(modeButton);
            if (collapseButtonIsNew) doc.body.appendChild(collapseButton);

            const syncControls = () => {{
                hideNativeButtons();
                const actualState = readSidebarCollapsedState();
                if (actualState !== null) applySidebarState(actualState);
            }};

            applySidebarState(sidebarCollapsed);
            syncControls();

            const observer = new parentWindow.MutationObserver(syncControls);
            observer.observe(doc.body, {{ childList: true, subtree: true }});
            parentWindow[observerKey] = observer;
        }})();
        </script>
        """,
        height=0,
    )

AI_ENV_DEFAULTS = {
    "AI_API_KEY": "",
    "AI_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "AI_MODEL_NAME": "qwen-vl-plus",
    "AI_SOLVER_MODEL_NAME": "qwen3.6-flash",
    "AI_EMBEDDING_MODEL_NAME": "",
    "AI_OCR_PROMPT": (
        "请识别图片中的数学题，并严格按照 LaTeX 格式输出。"
        "如果图片中有多道独立题目，必须逐题输出独立的文件名分隔符和完整 problem、answer、solutions 环境，"
        "禁止把多道题合并进同一个 problem 环境。"
    ),
}

AI_ENV_WRITE_ORDER = (
    "AI_API_KEY",
    "AI_BASE_URL",
    "AI_MODEL_NAME",
    "AI_SOLVER_MODEL_NAME",
    "AI_EMBEDDING_MODEL_NAME",
)

def _root_env_path() -> str:
    return os.path.join(APP_ROOT, ".env")

def _read_root_ai_env_config() -> dict:
    env_path = _root_env_path()
    file_exists = os.path.exists(env_path)
    raw = {}
    if file_exists:
        try:
            raw = {k: (v or "") for k, v in dotenv_values(env_path).items() if k}
        except Exception:
            raw = {}

    values = {}
    for key, default in AI_ENV_DEFAULTS.items():
        if file_exists:
            values[key] = raw.get(key, default)
        else:
            values[key] = os.getenv(key, default)
    return values

def _format_env_value(value: str) -> str:
    value = (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    value = value.replace("\n", "\\n")
    if value == "":
        return ""
    if re.search(r"\s|#|\"|'|\\", value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value

def _write_root_ai_env_config(updates: dict):
    env_path = _root_env_path()
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    else:
        lines = [
            "# AI service configuration.",
            "# Managed by MathCyclus API 设置.",
            "",
        ]

    seen = set()
    output = []
    env_line_re = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
    for line in lines:
        match = env_line_re.match(line)
        if match and match.group(1) in updates:
            key = match.group(1)
            output.append(f"{key}={_format_env_value(updates[key])}")
            seen.add(key)
        else:
            output.append(line)

    missing = [key for key in AI_ENV_WRITE_ORDER if key in updates and key not in seen]
    if missing and output and output[-1].strip():
        output.append("")
    for key in missing:
        output.append(f"{key}={_format_env_value(updates[key])}")

    atomic_write_text(env_path, "\n".join(output).rstrip() + "\n", backup=False)
    load_dotenv(env_path, override=True)

    if os.path.exists(ocr_prompt_file):
        with open(ocr_prompt_file, "r", encoding="utf-8") as f:
            globals()["AI_OCR_PROMPT"] = f.read()
    else:
        globals()["AI_OCR_PROMPT"] = os.getenv(
            "AI_OCR_PROMPT",
            AI_ENV_DEFAULTS["AI_OCR_PROMPT"],
        ).replace("\\n", "\n")

def _read_ocr_prompt_for_settings(config: dict) -> tuple[str, bool]:
    if os.path.exists(ocr_prompt_file):
        with open(ocr_prompt_file, "r", encoding="utf-8") as f:
            return f.read(), True
    return config.get("AI_OCR_PROMPT", AI_ENV_DEFAULTS["AI_OCR_PROMPT"]).replace("\\n", "\n"), False

def _write_ocr_prompt_file(prompt: str):
    normalized = (prompt or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    atomic_write_text(ocr_prompt_file, normalized + ("\n" if normalized else ""), backup=False)
    globals()["AI_OCR_PROMPT"] = normalized

@st.dialog("API 设置", width="large")
def api_settings_dialog():
    env_path = _root_env_path()
    config = _read_root_ai_env_config()
    ocr_prompt_value, prompt_file_exists = _read_ocr_prompt_for_settings(config)
    env_state = "已读取根目录 .env" if os.path.exists(env_path) else "未找到 .env，保存时会自动创建"
    prompt_state = "已读取根目录 ocr_prompt.txt" if prompt_file_exists else "未找到 ocr_prompt.txt，保存时会自动创建"

    st.markdown(
        """
        <style>
        /* API 设置保持与淡紫主题一致，覆盖 BaseWeb 的原生错误红框。 */
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-testid="stTextInput"] input,
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-testid="stTextArea"] textarea,
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-baseweb="input"],
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-baseweb="textarea"],
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-baseweb="input"] > div,
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-baseweb="textarea"] > div {
            border: 1px solid var(--mc-border) !important;
            border-color: var(--mc-border) !important;
            outline: none !important;
            box-shadow: inset 0 1px 1px rgba(44, 39, 51, 0.03) !important;
        }
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-testid="stTextInput"] input:focus,
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-testid="stTextArea"] textarea:focus,
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-baseweb="input"]:focus-within,
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-baseweb="textarea"]:focus-within,
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-baseweb="input"] > div:focus-within,
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-baseweb="textarea"] > div:focus-within {
            border: 1px solid var(--mc-action-border) !important;
            border-color: var(--mc-action-border) !important;
            box-shadow: 0 0 0 3px var(--mc-focus), inset 0 1px 1px rgba(44, 39, 51, 0.03) !important;
            background: #ffffff !important;
        }
        [role="dialog"]:has(#mc-api-settings-anchor) input:invalid,
        [role="dialog"]:has(#mc-api-settings-anchor) textarea:invalid,
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-baseweb="input"]:has(input:invalid),
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-baseweb="textarea"]:has(textarea:invalid),
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-baseweb="input"]:has(input[aria-invalid="true"]) > div,
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-baseweb="textarea"]:has(textarea[aria-invalid="true"]) > div,
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-baseweb="input"]:has(input[aria-invalid="true"]),
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-baseweb="textarea"]:has(textarea[aria-invalid="true"]),
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-testid="stTextInput"] input[aria-invalid="true"],
        [role="dialog"]:has(#mc-api-settings-anchor) div[data-testid="stTextArea"] textarea[aria-invalid="true"] {
            border: 1px solid var(--mc-action-border) !important;
            border-color: var(--mc-action-border) !important;
            outline: none !important;
            box-shadow: 0 0 0 3px rgba(109, 40, 217, 0.12), inset 0 1px 1px rgba(44, 39, 51, 0.03) !important;
        }
        </style>
        <span id="mc-api-settings-anchor"></span>
        """,
        unsafe_allow_html=True,
    )

    st.caption(f"{env_state}：{env_path}")
    st.caption(f"{prompt_state}：{ocr_prompt_file}")
    st.info("OCR 实际优先使用 ocr_prompt.txt。下方提示词框显示并保存的就是这个文件内容；.env 里的 AI_OCR_PROMPT 只作为文件不存在时的备用。", icon="ℹ️")

    with st.form("api_settings_form"):
        api_key = st.text_input(
            "API Key（密钥字符串，例如 sk-... 或 DashScope API Key）",
            value=config.get("AI_API_KEY", ""),
            type="password",
            placeholder="sk-... / dashscope_xxx",
        )
        base_url = st.text_input(
            "Base URL（接口根地址，例如 https://dashscope.aliyuncs.com/compatible-mode/v1）",
            value=config.get("AI_BASE_URL", AI_ENV_DEFAULTS["AI_BASE_URL"]),
            placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        model_name = st.text_input(
            "OCR / 图片识别模型（模型名，例如 qwen-vl-plus 或 gpt-4o）",
            value=config.get("AI_MODEL_NAME", AI_ENV_DEFAULTS["AI_MODEL_NAME"]),
            placeholder="qwen-vl-plus",
        )
        solver_model = st.text_input(
            "解题模型（可选，例如 qwen3.6-flash；留空则使用默认解题模型）",
            value=config.get("AI_SOLVER_MODEL_NAME", AI_ENV_DEFAULTS["AI_SOLVER_MODEL_NAME"]),
            placeholder="qwen3.6-flash",
        )
        embedding_model = st.text_input(
            "Embedding 模型（可选；用于语义/混合搜索）",
            value=config.get("AI_EMBEDDING_MODEL_NAME", AI_ENV_DEFAULTS["AI_EMBEDDING_MODEL_NAME"]),
            placeholder="例如 text-embedding-v4",
            help="留空即可继续使用精确搜索；填写后可在搜索页启用语义检索。",
        )
        ocr_prompt = st.text_area(
            "OCR 提示词（保存到 ocr_prompt.txt）",
            value=ocr_prompt_value,
            height=260,
        )

        submitted = st.form_submit_button("保存 API 配置", type="primary", use_container_width=True)

    if submitted:
        required_missing = []
        if not api_key.strip():
            required_missing.append("API Key")
        if not base_url.strip():
            required_missing.append("Base URL")
        if not model_name.strip():
            required_missing.append("OCR / 图片识别模型")

        if required_missing:
            st.error("请补全：" + "、".join(required_missing))
            return

        try:
            _write_root_ai_env_config({
                "AI_API_KEY": api_key.strip(),
                "AI_BASE_URL": base_url.strip(),
                "AI_MODEL_NAME": model_name.strip(),
                "AI_SOLVER_MODEL_NAME": solver_model.strip(),
                "AI_EMBEDDING_MODEL_NAME": embedding_model.strip(),
            })
            _write_ocr_prompt_file(ocr_prompt)
            st.success(".env 与 ocr_prompt.txt 已保存，当前会话已重新加载 API 配置。")
        except Exception as e:
            st.error(f"保存失败：{e}")

def _query_param_enabled(name: str) -> bool:
    try:
        value = st.query_params.get(name, "")
    except Exception:
        return False
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value).lower() in {"1", "true", "yes", "on"}

def _remove_query_param(name: str):
    try:
        if name in st.query_params:
            del st.query_params[name]
    except Exception:
        pass

def format_question_title(filename):
    """
    Format a question filename into a readable title.
    Expected filename format: Year-Type-PaperName-Num-Subject.tex
    Expected output: 【Year PaperName 第Num题】 (Subject)
    """
    basename = os.path.basename(filename).replace(".tex", "")
    parts = basename.split("-")
    if len(parts) >= 5:
        year = parts[0]
        paper_name = parts[2]
        num = parts[3]
        # 处理可能包含连字符的 subject (防万一)
        subject = "-".join(parts[4:])
        return f"【{year} {paper_name} 第{num}题】 ({subject})"
    elif len(parts) >= 4:
        year = parts[0]
        paper_name = parts[2]
        num = parts[3]
        return f"【{year} {paper_name} 第{num}题】"
    else:
        return basename

def extract_problem_header_fields(tex: str):
    m = re.search(r'\\begin\{problem\}\{(.*?)\}\{(.*?)\}\{(.*?)\}\{(.*?)\}\{(.*?)\}', tex or "", re.DOTALL)
    if not m:
        return None
    y, t, p, n, s = m.groups()
    t = (t or "").strip()
    t_clean = t.split("(")[0].split("（")[0].strip()
    if t_clean in PAPER_TYPES:
        t = t_clean
    else:
        for k, v in PAPER_TYPES.items():
            if t_clean == v or t == v:
                t = k
                break
    return {
        "year": (y or "").strip(),
        "p_type": t,
        "paper": (p or "").strip(),
        "number": (n or "").strip(),
        "subject_str": (s or "").strip(),
    }

def replace_problem_header(tex: str, new_year: str, new_type: str, new_name: str, new_num: str, new_subject_str: str) -> str:
    new_header = f"\\begin{{problem}}{{{new_year}}}{{{new_type}}}{{{new_name}}}{{{new_num}}}{{{new_subject_str}}}"
    s = tex or ""
    s2 = re.sub(
        r"\\begin\{problem\}\{.*?\}\{.*?\}\{.*?\}\{.*?\}\{.*?\}",
        lambda _m: new_header,
        s,
        count=1,
    )
    if s2 == s and "\\begin{problem}" in s:
        s2 = re.sub(r"\\begin\{problem\}", lambda _m: new_header, s, count=1)
    return s2

def apply_meta_rename_and_update(old_path: str, new_year: str, new_type: str, new_name: str, new_num: str, new_subject_str: str):
    old_path = old_path or ""
    if not old_path or not os.path.exists(old_path):
        raise FileNotFoundError(old_path)

    base = os.path.basename(old_path).replace(".tex", "")
    parts = base.split("-")
    if len(parts) < 5:
        raise ValueError("invalid filename format")

    primary_subj = (new_subject_str or "").split("，")[0].strip() if new_subject_str else ""
    target_dir = os.path.join(CHAPTERS_DIR, primary_subj, str(new_year))
    ensure_dir(target_dir)

    new_filename = generate_filename(new_year, new_type, new_name, new_num, new_subject_str)
    new_path = os.path.join(target_dir, new_filename)

    with open(old_path, "r", encoding="utf-8") as f:
        old_content = f.read()

    new_content = replace_problem_header(old_content, str(new_year), new_type, new_name, new_num, new_subject_str)
    same_path = os.path.normcase(os.path.abspath(new_path)) == os.path.normcase(os.path.abspath(old_path))
    if not same_path and os.path.exists(new_path):
        raise FileExistsError(f"目标题目文件已存在：{new_path}")

    backup_path = ""
    if same_path:
        atomic_write_text(new_path, new_content, backup=True)
    else:
        atomic_write_text(new_path, new_content, backup=False)
        try:
            backup_path = backup_existing_file(old_path)
            os.remove(old_path)
        except Exception:
            if os.path.exists(new_path):
                os.remove(new_path)
            raise

    try:
        update_csv_index_for_edit(old_path, new_path, new_content, str(new_year), new_type, new_name, new_num, new_subject_str)
    except Exception:
        if not same_path:
            try:
                if os.path.exists(new_path):
                    os.remove(new_path)
                if backup_path and os.path.exists(backup_path):
                    ensure_dir(os.path.dirname(old_path))
                    shutil.copy2(backup_path, old_path)
            except OSError:
                pass
        raise

    record_operation(
        "rename_question" if not same_path else "update_question_meta",
        path=os.path.abspath(new_path),
        related_path=os.path.abspath(old_path) if not same_path else "",
        details="metadata and filename updated",
    )
    _invalidate_semantic_for_file(old_path)
    _invalidate_semantic_for_file(new_path)
    clear_statistics_cache()
    _clear_advanced_search_result_cache()
    return new_path, new_content


def inject_unified_visual_system_css():
    """Apply the shared MathCyclus visual language after page-specific styles."""
    st.markdown(
        """
        <style>
        :root {
            --mc-bg: #f5f2fb;
            --mc-surface: #fffdfd;
            --mc-surface-soft: #eee9f8;
            --mc-sidebar: #ebe5f5;
            --mc-border: #d9d1e6;
            --mc-border-strong: #b8a9ca;
            --mc-text: #2c2733;
            --mc-muted: #71687d;
            --mc-accent: #6d28d9;
            --mc-accent-dark: #5b21b6;
            --mc-accent-soft: #ede9fe;
            --mc-action-bg: #d6c4ee;
            --mc-action-bg-hover: #c5abe5;
            --mc-action-border: #b49ad2;
            --mc-action-text: #332442;
            --mc-action-shadow: 0 5px 14px rgba(91, 33, 182, 0.12);
            --mc-focus: rgba(109, 40, 217, 0.2);
            --mc-radius: 7px;
            --mc-shadow: 0 8px 24px rgba(80, 60, 110, 0.08);
        }

        html { scroll-behavior: smooth; }
        body,
        .stApp,
        .stApp button,
        .stApp input,
        .stApp textarea,
        .stApp select {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif !important;
        }
        body { background: var(--mc-bg) !important; color: var(--mc-text) !important; }
        .stApp,
        div[data-testid="stAppViewContainer"],
        div[data-testid="stAppViewContainer"] > section {
            background: var(--mc-bg) !important;
            color: var(--mc-text) !important;
        }
        .block-container {
            width: calc(100% - 1rem) !important;
            max-width: 1680px !important;
            padding: 1.55rem 1.25rem 3.2rem !important;
            background: transparent !important;
        }
        section[data-testid="stMain"],
        section[data-testid="stMain"] > div,
        div[data-testid="stAppViewContainer"] > section {
            background: var(--mc-bg) !important;
        }
        body:has(#mc-exam-page-anchor) .block-container,
        body:has(.mc-browse-page-anchor) .block-container {
            background: transparent !important;
        }
        body:has(#mc-exam-page-anchor) [data-testid="stVerticalBlockBorderWrapper"],
        body:has(.mc-browse-page-anchor) [data-testid="stVerticalBlockBorderWrapper"] {
            background: transparent !important;
        }
        body:has(#mc-exam-page-anchor) [data-testid="stVerticalBlockBorderWrapper"]:has(.mc-exam-card-anchor),
        body:has(.mc-browse-page-anchor) [data-testid="stVerticalBlockBorderWrapper"]:has(.mc-question-preview-anchor) {
            background: transparent !important;
            box-shadow: none !important;
        }
        h1, h2, h3, h4, h5, h6 {
            color: var(--mc-text) !important;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif !important;
            font-weight: 600 !important;
            letter-spacing: -0.015em !important;
            text-wrap: balance;
        }
        h1 { font-size: clamp(1.95rem, 3vw, 2.75rem) !important; line-height: 1.15 !important; }
        h2 { font-size: clamp(1.4rem, 2vw, 1.85rem) !important; line-height: 1.25 !important; }
        h3, h4 { letter-spacing: 0 !important; }
        p, li, label, span, input, textarea, button { letter-spacing: 0 !important; }
        p, li { color: var(--mc-text); }
        a { color: var(--mc-accent-dark); text-underline-offset: 3px; }
        hr { border-color: var(--mc-border) !important; }
        ::selection { background: var(--mc-accent-soft) !important; color: var(--mc-text) !important; }
        ::-webkit-scrollbar { width: 10px; height: 10px; }
        ::-webkit-scrollbar-track { background: var(--mc-bg); }
        ::-webkit-scrollbar-thumb { background: #c2b5d1; border: 3px solid var(--mc-bg); border-radius: 8px; }
        ::-webkit-scrollbar-thumb:hover { background: #a998bd; }

        div[data-testid="stExpander"],
        div[data-testid="stForm"],
        div[data-testid="stPopover"] > div,
        div[data-testid="stAlert"],
        div[data-testid="stMetric"] {
            border: 1px solid var(--mc-border) !important;
            border-radius: var(--mc-radius) !important;
            background: var(--mc-surface) !important;
            box-shadow: none !important;
        }
        div[data-testid="stExpander"] summary:hover { background: var(--mc-surface-soft) !important; }
        div[data-testid="stTextArea"] textarea,
        div[data-baseweb="select"] > div {
            border: 1px solid var(--mc-border) !important;
            border-radius: var(--mc-radius) !important;
            background: var(--mc-surface) !important;
            color: var(--mc-text) !important;
            box-shadow: none !important;
            transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease !important;
        }
        div[data-testid="stTextArea"] textarea:focus,
        div[data-baseweb="select"] > div:focus-within {
            border-color: var(--mc-accent) !important;
            box-shadow: 0 0 0 3px var(--mc-focus) !important;
            background: #ffffff !important;
        }
        div[data-testid="stTextInput"] [data-baseweb="input"],
        div[data-testid="stNumberInput"] [data-baseweb="input"] {
            border: 1px solid var(--mc-border) !important;
            border-radius: var(--mc-radius) !important;
            background: var(--mc-surface) !important;
            outline: none !important;
            box-shadow: none !important;
            transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease !important;
        }
        div[data-testid="stTextInput"] [data-baseweb="input"]:focus-within,
        div[data-testid="stNumberInput"] [data-baseweb="input"]:focus-within {
            border-color: var(--mc-accent) !important;
            outline: none !important;
            box-shadow: 0 0 0 2px var(--mc-focus) !important;
            background: #ffffff !important;
        }
        div[data-testid="stTextInput"] input:focus,
        div[data-testid="stNumberInput"] input:focus,
        div[data-testid="stTextArea"] textarea:focus,
        input:focus-visible,
        textarea:focus-visible {
            outline: none !important;
        }
        div[data-testid="stTextInput"] [data-baseweb="input"] input,
        div[data-testid="stNumberInput"] [data-baseweb="input"] input {
            border: 0 !important;
            outline: none !important;
            box-shadow: none !important;
            background: transparent !important;
        }
        div[data-testid="stTextInput"] input::placeholder,
        div[data-testid="stTextArea"] textarea::placeholder { color: #877b95 !important; opacity: 1 !important; }

        div[data-testid="stButton"] > button,
        div[data-testid="stDownloadButton"] > button,
        div[data-testid="stFormSubmitButton"] > button,
        div[data-testid="stPopover"] > button {
            min-height: 2.36rem !important;
            border: 1px solid var(--mc-border-strong) !important;
            border-radius: var(--mc-radius) !important;
            background: var(--mc-surface) !important;
            color: var(--mc-text) !important;
            box-shadow: none !important;
            font-weight: 600 !important;
            transition: transform 150ms ease, border-color 150ms ease, background 150ms ease, color 150ms ease !important;
        }
        div[data-testid="stButton"] > button:hover,
        div[data-testid="stDownloadButton"] > button:hover,
        div[data-testid="stFormSubmitButton"] > button:hover,
        div[data-testid="stPopover"] > button:hover {
            border-color: var(--mc-accent) !important;
            background: var(--mc-accent-soft) !important;
            color: var(--mc-accent-dark) !important;
            box-shadow: none !important;
            transform: translateY(-1px);
        }
        div[data-testid="stButton"] > button:active,
        div[data-testid="stDownloadButton"] > button:active,
        div[data-testid="stFormSubmitButton"] > button:active,
        div[data-testid="stPopover"] > button:active { transform: translateY(0) scale(0.985); }
        div[data-testid="stButton"] > button:focus-visible,
        div[data-testid="stDownloadButton"] > button:focus-visible,
        div[data-testid="stFormSubmitButton"] > button:focus-visible,
        div[data-testid="stPopover"] > button:focus-visible,
        input:focus-visible, textarea:focus-visible { outline: 3px solid var(--mc-focus) !important; outline-offset: 1px !important; }
        button[kind="primary"],
        div[data-testid="stButton"] > button[kind="primary"],
        div[data-testid="stFormSubmitButton"] > button[kind="primary"] {
            border-color: var(--mc-action-border) !important;
            background: var(--mc-action-bg) !important;
            color: var(--mc-action-text) !important;
            box-shadow: var(--mc-action-shadow) !important;
        }
        button[kind="primary"] p,
        button[kind="primary"] span,
        div[data-testid="stButton"] > button[kind="primary"] p,
        div[data-testid="stButton"] > button[kind="primary"] span,
        div[data-testid="stFormSubmitButton"] > button[kind="primary"] p,
        div[data-testid="stFormSubmitButton"] > button[kind="primary"] span { color: var(--mc-action-text) !important; }
        button[kind="primary"]:hover,
        div[data-testid="stButton"] > button[kind="primary"]:hover,
        div[data-testid="stFormSubmitButton"] > button[kind="primary"]:hover {
            border-color: var(--mc-action-border) !important;
            background: var(--mc-action-bg-hover) !important;
            color: var(--mc-action-text) !important;
            box-shadow: 0 7px 18px rgba(91, 33, 182, 0.16) !important;
        }
        button[kind="primary"]:hover p,
        button[kind="primary"]:hover span,
        div[data-testid="stButton"] > button[kind="primary"]:hover p,
        div[data-testid="stButton"] > button[kind="primary"]:hover span,
        div[data-testid="stFormSubmitButton"] > button[kind="primary"]:hover p,
        div[data-testid="stFormSubmitButton"] > button[kind="primary"]:hover span { color: var(--mc-action-text) !important; }
        body:has(#mc-entry-page-anchor) div[data-testid="stVerticalBlock"]:has(#entry-save-button-anchor) div[data-testid="stButton"] > button[kind="primary"] {
            background: #bfdbfe !important;
            border-color: #93c5fd !important;
            color: #17324d !important;
            box-shadow: 0 8px 18px rgba(59, 130, 246, 0.16) !important;
        }
        body:has(#mc-entry-page-anchor) div[data-testid="stVerticalBlock"]:has(#entry-save-button-anchor) div[data-testid="stButton"] > button[kind="primary"]:hover {
            background: #93c5fd !important;
            border-color: #60a5fa !important;
            color: #12283d !important;
        }
        div[data-testid="stTabs"] button { color: var(--mc-muted) !important; border-radius: 0 !important; }
        div[data-testid="stTabs"] button[aria-selected="true"] { color: var(--mc-accent-dark) !important; font-weight: 700 !important; }
        div[data-testid="stTabs"] [data-baseweb="tab-highlight"] { background: var(--mc-accent) !important; }
        div[data-testid="stDataFrame"], div[data-testid="stTable"] {
            border: 1px solid var(--mc-border) !important;
            border-radius: var(--mc-radius) !important;
            background: var(--mc-surface) !important;
            box-shadow: none !important;
            overflow: hidden !important;
        }
        div[data-testid="stToast"] { border: 1px solid var(--mc-border) !important; border-radius: var(--mc-radius) !important; box-shadow: var(--mc-shadow) !important; }

        section[data-testid="stSidebar"] {
            background: var(--mc-sidebar) !important;
            border-right: 1px solid var(--mc-border) !important;
            box-shadow: none !important;
            backdrop-filter: none !important;
            -webkit-backdrop-filter: none !important;
        }
        [data-testid="stSidebarUserContent"] { padding: 0.6rem 0.5rem 1.2rem !important; }
        [data-testid="stSidebar"] div[role="radiogroup"] { gap: 8px !important; }
        [data-testid="stSidebar"] div[role="radiogroup"] > label {
            max-width: 96px !important;
            min-height: 58px !important;
            padding: 8px 6px !important;
            border: 1px solid transparent !important;
            border-radius: 6px !important;
            color: #665d78 !important;
            background: transparent !important;
            box-shadow: none !important;
            transition: background 150ms ease, border-color 150ms ease, color 150ms ease, transform 150ms ease !important;
        }
        [data-testid="stSidebar"] div[role="radiogroup"] > label:hover {
            background: rgba(109, 40, 217, 0.08) !important;
            border-color: rgba(109, 40, 217, 0.18) !important;
            color: var(--mc-accent-dark) !important;
            transform: translateY(-1px);
        }
        [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {
            background: var(--mc-action-bg) !important;
            border-color: var(--mc-action-border) !important;
            color: var(--mc-action-text) !important;
            box-shadow: var(--mc-action-shadow) !important;
        }
        [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) p,
        [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) span { color: var(--mc-action-text) !important; }
        [data-testid="stSidebar"] div[role="radiogroup"] p {
            color: inherit !important;
            font-size: 13px !important;
            font-weight: 650 !important;
            line-height: 1.35 !important;
        }
        .sol-logo, .sol-logo-link, .sol-logo-link:visited { color: var(--mc-accent-dark) !important; }
        .sol-logo span, .sol-logo-link span { color: var(--mc-accent) !important; }
        #mc-sidebar-layout-switch, #mc-sidebar-collapse-switch {
            color: var(--mc-accent-dark) !important;
            border-color: rgba(109, 40, 217, 0.22) !important;
        }
        #mc-sidebar-layout-switch:hover, #mc-sidebar-collapse-switch:hover { background: var(--mc-accent-soft) !important; }

        div[data-testid="stHorizontalBlock"]:has(#mc-top-nav-anchor) {
            background: var(--mc-surface) !important;
            border-bottom-color: var(--mc-border) !important;
        }
        div[data-testid="stHorizontalBlock"]:has(#mc-top-nav-anchor) div[role="radiogroup"] > label { color: #665d78 !important; }
        div[data-testid="stHorizontalBlock"]:has(#mc-top-nav-anchor) div[role="radiogroup"] > label:hover { background: var(--mc-accent-soft) !important; color: var(--mc-accent-dark) !important; }
        div[data-testid="stHorizontalBlock"]:has(#mc-top-nav-anchor) div[role="radiogroup"] > label:has(input:checked) { color: var(--mc-accent-dark) !important; border-bottom-color: var(--mc-accent) !important; }
        div[class*="st-key-top-nav-layout-toggle"] button, div[class*="st-key-top-nav-api-settings"] button { color: var(--mc-accent-dark) !important; }
        div[class*="st-key-top-nav-layout-toggle"] button:hover, div[class*="st-key-top-nav-api-settings"] button:hover { background: var(--mc-accent-soft) !important; color: var(--mc-accent-dark) !important; }

        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after { scroll-behavior: auto !important; transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
@st.dialog("🔍 查看大图", width="large")
def zoom_image(img):
    # 将图片转换为 Base64
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()

    # HTML/JS 缩放组件 (增大可视高度)
    html_code = f"""
    <div style="width: 100%; height: auto; min-height: 400px; overflow: visible; position: relative; display: flex; justify-content: center; align-items: flex-start; background: transparent;">
        <div id="img-container" style="transition: transform 0.1s; cursor: grab; width: 100%; display: flex; justify-content: center;">
            <img id="zoomed-img" src="data:image/png;base64,{img_str}" style="max-width: 100%; height: auto; display: block;">
        </div>
        <div style="position: fixed; top: 15px; left: 15px; background: rgba(0,0,0,0.65); padding: 35px 25px; border-radius: 35px; display: flex; align-items: center; gap: 20px; z-index: 9999; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
            <button onclick="zoomOut()" style="background: transparent; border: none; color: white; font-size: 35px; cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 0;">➖</button>
            <span id="zoom-level" style="color: white; font-family: sans-serif; font-size: 18px; font-weight: bold; min-width: 60px; text-align: center; margin: 0;">100%</span>
            <button onclick="zoomIn()" style="background: transparent; border: none; color: white; font-size: 35px; cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 0;">➕</button>
            <button onclick="resetZoom()" style="background: transparent; border: none; color: white; font-size: 20px; cursor: pointer; margin-left: 5px; display: flex; align-items: center; justify-content: center; padding: 0;">🔄</button>
        </div>
    </div>
    <script>
        let scale = 1;
        let pX = 0;
        let pY = 0;
        const container = document.getElementById('img-container');
        const zoomLevel = document.getElementById('zoom-level');

        function updateTransform() {{
            container.style.transform = `translate(${{pX}}px, ${{pY}}px) scale(${{scale}})`;
            zoomLevel.innerText = Math.round(scale * 100) + '%';
        }}

        function zoomIn() {{
            scale *= 1.2;
            updateTransform();
        }}

        function zoomOut() {{
            scale /= 1.2;
            updateTransform();
        }}

        function resetZoom() {{
            scale = 1;
            pX = 0;
            pY = 0;
            updateTransform();
        }}

        // 滚轮缩放
        document.querySelector('div').addEventListener('wheel', (e) => {{
            e.preventDefault();
            if (e.deltaY < 0) {{
                scale *= 1.1;
            }} else {{
                scale /= 1.1;
            }}
            updateTransform();
        }});

        // 简单的拖拽逻辑
        let isDragging = false;
        let startX, startY, initialPx, initialPy;

        container.addEventListener('mousedown', (e) => {{
            isDragging = true;
            startX = e.clientX;
            startY = e.clientY;
            initialPx = pX;
            initialPy = pY;
            container.style.cursor = 'grabbing';
            e.preventDefault();
        }});

        window.addEventListener('mousemove', (e) => {{
            if (!isDragging) return;
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            pX = initialPx + dx;
            pY = initialPy + dy;
            updateTransform();
        }});

        window.addEventListener('mouseup', () => {{
            isDragging = false;
            container.style.cursor = 'grab';
        }});
    </script>
    """
    components.html(html_code, height=800, scrolling=True)

@st.dialog("MathCyclus 题库介绍", width="large")
def show_mathcyclus_intro():
    page_system_intro()

def _adv_search_queries_from_session():
    t1 = st.session_state.get("adv_t1", "全文内容")
    t2 = st.session_state.get("adv_t2", "全文内容")
    t3 = st.session_state.get("adv_t3", "全文内容")

    q1 = st.session_state.get("adv_q1_sel" if t1 == "题目类型" else "adv_q1", "")
    q2 = st.session_state.get("adv_q2_sel" if t2 == "题目类型" else "adv_q2", "")
    q3 = st.session_state.get("adv_q3_sel" if t3 == "题目类型" else "adv_q3", "")
    return (q1 or ""), (q2 or ""), (q3 or "")

def _adv_search_has_query():
    q1, q2, q3 = _adv_search_queries_from_session()
    search_mode = st.session_state.get("adv_search_mode", "精确筛选")
    semantic_query = st.session_state.get("adv_semantic_query", "") if search_mode != "精确筛选" else ""
    return bool(str(q1).strip() or str(q2).strip() or str(q3).strip() or str(semantic_query).strip())


def _semantic_api_config() -> dict:
    config = _read_root_ai_env_config()
    return {
        "base_url": config.get("AI_BASE_URL", ""),
        "api_key": config.get("AI_API_KEY", ""),
        "model_name": config.get("AI_EMBEDDING_MODEL_NAME", ""),
    }


def _semantic_lexical_boost(text: str, query: str) -> float:
    """Small lexical boost keeps exact terminology ahead of merely related text."""
    haystack = (text or "").casefold()
    needle = (query or "").strip().casefold()
    if not needle:
        return 0.0
    score = 0.25 if needle in haystack else 0.0
    tokens = re.findall(r"[A-Za-z0-9_]+", needle)
    for chinese_run in re.findall(r"[\u4e00-\u9fff]{2,}", needle):
        tokens.extend(chinese_run[index:index + 2] for index in range(len(chinese_run) - 1))
    if tokens:
        matched_ratio = sum(token in haystack for token in tokens) / len(tokens)
        score += 0.2 * matched_ratio
    return score


def _semantic_item_text(item: dict) -> str:
    return "\n".join([
        item["full_text"],
        item["type"],
        item["file"],
        item["row"].get("知识板块", "") or "",
    ])


def _invalidate_semantic_for_file(file_path: str) -> None:
    try:
        relative_path = os.path.relpath(file_path, CHAPTERS_DIR)
        invalidate_semantic_path(relative_path)
    except Exception:
        # Semantic search is optional and must never block a normal save/delete.
        pass

def _clear_advanced_search_result_cache():
    st.session_state.pop("adv_last_query", None)
    st.session_state.pop("adv_last_results", None)

def _duplicate_save_confirmation(file_path: str, content: str, scope: str = "edit") -> bool:
    """Require a second click before an edit creates a duplicate statement."""
    matches = find_duplicate_matches(
        content,
        exclude_path=file_path,
        similarity_threshold=0.88,
        max_results=5,
    )
    key_hash = hashlib.md5(f"{scope}:{file_path}".encode("utf-8", errors="ignore")).hexdigest()[:12]
    state_key = f"duplicate_save_confirmation_{key_hash}"
    fingerprint = question_fingerprint(content)
    if not matches:
        st.session_state.pop(state_key, None)
        return True

    pending = st.session_state.get(state_key) or {}
    if pending.get("fingerprint") != fingerprint:
        st.session_state[state_key] = {"fingerprint": fingerprint, "matches": matches}
        first_match = matches[0]
        st.toast(
            f"检测到可能重复题目：{first_match.get('name') or first_match.get('relative_path')}；再次点击保存以确认",
            icon="⚠️",
        )
        return False

    st.session_state.pop(state_key, None)
    return True

def save_modified_tex_file(file_path, new_content):
    """
    保存修改后的 tex 文件：
    将修改后的内容通过 extract_and_replace_tikz 处理（保留内联 TikZ 并在后台生成副本），然后保存。
    """
    save_dir = os.path.dirname(file_path)
    filename = os.path.basename(file_path)

    # 提取并生成独立文件副本，但 final_content 仍包含原生 TikZ
    final_content = extract_and_replace_tikz(new_content, filename, save_dir)

    # 直接写入包含原生 TikZ 的内容
    atomic_write_text(file_path, final_content, backup=True)
    record_operation(
        "update_question_content",
        path=os.path.abspath(file_path),
        details="LaTeX content updated",
    )
    _invalidate_semantic_for_file(file_path)

    return final_content

def _norm_abs_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path or ""))

def _is_managed_question_file(file_path: str) -> bool:
    abs_path = os.path.abspath(file_path or "")
    chapters_abs = os.path.abspath(CHAPTERS_DIR)
    try:
        if os.path.commonpath([chapters_abs, abs_path]) != chapters_abs:
            return False
    except ValueError:
        return False

    rel_path = os.path.relpath(abs_path, chapters_abs)
    rel_parts = os.path.normpath(rel_path).split(os.sep)
    basename = os.path.basename(abs_path)

    return (
        os.path.isfile(abs_path)
        and basename.endswith(".tex")
        and not basename.startswith("content_")
        and not any("相关图" in part for part in rel_parts)
        and " 图" not in basename
    )

def _remove_question_from_csv_index(file_path: str) -> int:
    from utils.csv_ops import read_csv_index, write_csv_index

    abs_path = os.path.abspath(file_path)
    rel_path = os.path.relpath(abs_path, CHAPTERS_DIR)
    target_rel = os.path.normcase(os.path.normpath(rel_path))
    target_name = os.path.basename(abs_path).replace(".tex", "")

    rows = read_csv_index()
    kept_rows = []
    removed_count = 0
    for row in rows:
        row_rel = os.path.normcase(os.path.normpath(row.get("相对文件路径", "") or ""))
        row_name = (row.get("文件名称", "") or "").strip()
        if row_rel == target_rel or (not row_rel and row_name == target_name):
            removed_count += 1
            continue
        kept_rows.append(row)

    if removed_count:
        write_csv_index(kept_rows)
    return removed_count

def _get_question_csv_rows(file_path: str):
    from utils.csv_ops import read_csv_index

    abs_path = os.path.abspath(file_path)
    rel_path = os.path.relpath(abs_path, CHAPTERS_DIR)
    target_rel = os.path.normcase(os.path.normpath(rel_path))
    target_name = os.path.basename(abs_path).replace(".tex", "")

    matched_rows = []
    for row in read_csv_index():
        row_rel = os.path.normcase(os.path.normpath(row.get("相对文件路径", "") or ""))
        row_name = (row.get("文件名称", "") or "").strip()
        if row_rel == target_rel or (not row_rel and row_name == target_name):
            matched_rows.append(dict(row))
    return matched_rows

def _csv_has_question_record(file_path: str) -> bool:
    return bool(_get_question_csv_rows(file_path))

def _forget_deleted_question_path(file_path: str):
    target = _norm_abs_path(file_path)

    for key in ("adv_last_results",):
        rows = st.session_state.get(key)
        if isinstance(rows, list):
            st.session_state[key] = [
                row for row in rows
                if _norm_abs_path(row.get("path") if isinstance(row, dict) else row) != target
            ]

    for key in ("exam_selected_qs", "recent_saved_paths"):
        paths = st.session_state.get(key)
        if isinstance(paths, list):
            st.session_state[key] = [p for p in paths if _norm_abs_path(p) != target]

def _related_tikz_dir_for_question(file_path: str) -> str:
    base_name = os.path.basename(file_path).replace(".tex", "")
    return os.path.join(os.path.dirname(file_path), f"{base_name} 相关图")

def _backup_related_tikz_dir(file_path: str) -> str:
    tikz_dir = _related_tikz_dir_for_question(file_path)
    if not os.path.isdir(tikz_dir):
        return ""

    root_dir = os.getcwd()
    try:
        rel_path = os.path.relpath(os.path.abspath(tikz_dir), root_dir)
        if rel_path.startswith(".."):
            rel_path = os.path.basename(tikz_dir)
    except ValueError:
        rel_path = os.path.basename(tikz_dir)

    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_dir = os.path.join(root_dir, ".backups", rel_path + f".{timestamp}")
    shutil.copytree(tikz_dir, backup_dir)
    return backup_dir

def _remove_related_tikz_dir(file_path: str):
    tikz_dir = _related_tikz_dir_for_question(file_path)
    if os.path.isdir(tikz_dir):
        shutil.rmtree(tikz_dir)

def _update_chapter_indexes_from_ui():
    try:
        import utils.batch_gen as batch_gen
        batch_gen.update_chapter_contents()
    except Exception as e:
        st.toast(f"章节索引更新失败：{e}", icon="⚠️")

def _remember_deleted_question(record: dict):
    history = st.session_state.setdefault("delete_mode_deleted_records", [])
    history.insert(0, record)

def delete_question_file_and_sync(file_path: str):
    if not _is_managed_question_file(file_path):
        raise ValueError("只能删除 chapters 目录下的普通题目 .tex 文件。")

    abs_path = os.path.abspath(file_path)
    with open(abs_path, "r", encoding="utf-8") as f:
        original_content = f.read()
    original_csv_rows = _get_question_csv_rows(abs_path)
    q_label = format_question_title(os.path.basename(abs_path))
    backup_path = backup_existing_file(abs_path)
    tikz_backup_path = _backup_related_tikz_dir(abs_path)
    try:
        os.remove(abs_path)
        removed_rows = _remove_question_from_csv_index(abs_path)
    except Exception:
        if backup_path and os.path.exists(backup_path) and not os.path.exists(abs_path):
            ensure_dir(os.path.dirname(abs_path))
            shutil.copy2(backup_path, abs_path)
        raise

    try:
        _remove_related_tikz_dir(abs_path)
    except Exception as e:
        st.toast(f"题目已删除，但相关图目录未能删除：{e}", icon="⚠️")
    _forget_deleted_question_path(abs_path)
    _invalidate_semantic_for_file(abs_path)
    _clear_advanced_search_result_cache()
    clear_statistics_cache()

    _update_chapter_indexes_from_ui()

    _remember_deleted_question({
        "id": hashlib.md5(f"{abs_path}:{time.time()}".encode("utf-8")).hexdigest()[:12],
        "label": q_label,
        "original_path": abs_path,
        "backup_path": backup_path,
        "tikz_backup_path": tikz_backup_path,
        "content": original_content,
        "csv_rows": original_csv_rows,
        "deleted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "restored": False,
    })

    question_id = ""
    if original_csv_rows:
        question_id = str(next(iter(original_csv_rows[0].values()), "") or "")
    record_operation(
        "delete_question",
        path=abs_path,
        question_id=question_id,
        details=f"removed_index_rows={removed_rows}",
    )

    return backup_path or tikz_backup_path, removed_rows

def restore_deleted_question_and_sync(record: dict):
    original_path = record.get("original_path") or ""
    backup_path = record.get("backup_path") or ""
    tikz_backup_path = record.get("tikz_backup_path") or ""

    if not original_path or not backup_path or not os.path.exists(backup_path):
        raise FileNotFoundError("未找到该题的备份文件，无法恢复。")
    if os.path.exists(original_path):
        raise FileExistsError("原位置已经存在同名题目文件，请先检查题库目录。")

    from utils.csv_ops import read_csv_index, write_csv_index
    csv_rows = record.get("csv_rows") or []
    if csv_rows:
        data = read_csv_index()
        existing_rels = {
            os.path.normcase(os.path.normpath(row.get("相对文件路径", "") or ""))
            for row in data
        }
        added_any = False
        for row in csv_rows:
            rel_path = os.path.normcase(os.path.normpath(row.get("相对文件路径", "") or ""))
            if rel_path not in existing_rels:
                data.append(row)
                existing_rels.add(rel_path)
                added_any = True
        if added_any:
            write_csv_index(data)
    else:
        basename = os.path.basename(original_path).replace(".tex", "")
        parts = basename.split("-")
        if len(parts) >= 5 and not _csv_has_question_record(original_path):
            with open(backup_path, "r", encoding="utf-8") as f:
                restored_content = f.read()
            add_to_csv_index(original_path, restored_content, parts[0], parts[1], parts[2], parts[3], parts[4])

    ensure_dir(os.path.dirname(original_path))
    shutil.copy2(backup_path, original_path)

    if tikz_backup_path and os.path.isdir(tikz_backup_path):
        base_name = os.path.basename(original_path).replace(".tex", "")
        tikz_target = os.path.join(os.path.dirname(original_path), f"{base_name} 相关图")
        if not os.path.exists(tikz_target):
            shutil.copytree(tikz_backup_path, tikz_target)

    record["restored"] = True
    record_operation(
        "restore_question",
        path=os.path.abspath(original_path),
        related_path=os.path.abspath(backup_path),
        details="question and related assets restored",
    )
    _clear_advanced_search_result_cache()
    clear_statistics_cache()
    _update_chapter_indexes_from_ui()

def _backup_root_dir() -> str:
    return os.path.join(BASE_DIR, ".backups")

def _strip_backup_timestamp(filename: str) -> str:
    stem, ext = os.path.splitext(filename)
    stem = re.sub(r"\.\d{8}-\d{6}(?:-\d{6})?$", "", stem)
    return stem + (ext or ".tex")

def _backup_original_path(backup_path: str) -> str:
    rel_path = os.path.relpath(os.path.abspath(backup_path), _backup_root_dir())
    rel_dir = os.path.dirname(rel_path)
    original_filename = _strip_backup_timestamp(os.path.basename(backup_path))
    return os.path.join(BASE_DIR, rel_dir, original_filename)

def _backup_deleted_at(backup_path: str) -> str:
    stem = os.path.splitext(os.path.basename(backup_path))[0]
    match = re.search(r"\.(\d{8})-(\d{6})(?:-(\d{6}))?$", stem)
    if not match:
        return ""
    date_s, time_s, micro_s = match.groups()
    try:
        dt = datetime.datetime.strptime(date_s + time_s, "%Y%m%d%H%M%S")
        if micro_s:
            dt = dt.replace(microsecond=int(micro_s))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""

def _find_tikz_backup_for_question_backup(backup_path: str, original_path: str) -> str:
    root = _backup_root_dir()
    base_name = os.path.basename(original_path).replace(".tex", "")
    rel_original_dir = os.path.relpath(os.path.dirname(original_path), BASE_DIR)
    backup_parent = os.path.join(root, rel_original_dir)
    if not os.path.isdir(backup_parent):
        return ""

    candidates = []
    prefix = f"{base_name} 相关图."
    for name in os.listdir(backup_parent):
        full_path = os.path.join(backup_parent, name)
        if os.path.isdir(full_path) and name.startswith(prefix):
            candidates.append(full_path)
    if not candidates:
        return ""
    return max(candidates, key=lambda p: os.path.getmtime(p))

def scan_question_backup_records():
    root = _backup_root_dir()
    chapters_backup = os.path.join(root, "chapters")
    if not os.path.isdir(chapters_backup):
        return []

    records = []
    for walk_root, dirs, files in os.walk(chapters_backup):
        dirs[:] = [d for d in dirs if "相关图" not in d]
        for filename in files:
            if not filename.endswith(".tex"):
                continue
            if filename.startswith("content_") or " 图" in filename:
                continue
            backup_path = os.path.join(walk_root, filename)
            original_path = _backup_original_path(backup_path)
            original_filename = os.path.basename(original_path)
            try:
                with open(backup_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                content = ""

            records.append({
                "id": hashlib.md5(backup_path.encode("utf-8")).hexdigest()[:12],
                "label": format_question_title(original_filename),
                "original_path": original_path,
                "backup_path": backup_path,
                "tikz_backup_path": _find_tikz_backup_for_question_backup(backup_path, original_path),
                "content": content,
                "csv_rows": [],
                "deleted_at": _backup_deleted_at(backup_path),
                "restored": os.path.exists(original_path),
            })

    records.sort(key=lambda rec: os.path.getmtime(rec["backup_path"]) if os.path.exists(rec["backup_path"]) else 0, reverse=True)
    return records

def permanently_delete_backup_record(record: dict):
    backup_path = record.get("backup_path") or ""
    tikz_backup_path = record.get("tikz_backup_path") or ""

    root = os.path.abspath(_backup_root_dir())
    targets = []
    if backup_path and os.path.isfile(backup_path):
        targets.append(os.path.abspath(backup_path))
    if tikz_backup_path and os.path.isdir(tikz_backup_path):
        targets.append(os.path.abspath(tikz_backup_path))

    for target in targets:
        try:
            if os.path.commonpath([root, target]) != root:
                raise ValueError("备份路径不在 .backups 目录内，已拒绝删除。")
        except ValueError:
            raise ValueError("备份路径不在 .backups 目录内，已拒绝删除。")

    for target in targets:
        if os.path.isdir(target):
            shutil.rmtree(target)
        elif os.path.isfile(target):
            os.remove(target)

    record_operation(
        "permanently_delete_backup",
        path=backup_path,
        related_path=tikz_backup_path,
        details="backup removed permanently",
    )

def clear_all_question_backups():
    records = scan_question_backup_records()
    deleted_count = 0
    for record in records:
        permanently_delete_backup_record(record)
        deleted_count += 1

    chapters_backup = os.path.join(_backup_root_dir(), "chapters")
    if os.path.isdir(chapters_backup):
        for walk_root, dirs, files in os.walk(chapters_backup, topdown=False):
            for dirname in dirs:
                full_path = os.path.join(walk_root, dirname)
                if "相关图." in dirname and os.path.isdir(full_path):
                    shutil.rmtree(full_path)
            if walk_root != chapters_backup and not os.listdir(walk_root):
                os.rmdir(walk_root)
    return deleted_count

@st.dialog("恢复误删题目", width="large")
def restore_deleted_questions_dialog():
    records = st.session_state.get("delete_mode_deleted_records", [])

    c_title, c_exit = st.columns([4, 1], vertical_alignment="center")
    with c_title:
        st.caption("这里显示本次删除模式中删除、且尚未恢复的题目。恢复会复制备份回原路径，并同步 CSV 索引和章节索引。")
    with c_exit:
        st.markdown('<span class="delete-exit-btn-hook"></span>', unsafe_allow_html=True)
        with _compat_container(key="restore_deleted_close_wrap"):
            if st.button("退出恢复界面", key="restore_deleted_close", use_container_width=True):
                st.rerun()

    active_records = [
        rec for rec in records
        if not rec.get("restored") and rec.get("backup_path") and os.path.exists(rec.get("backup_path"))
    ]

    if not active_records:
        st.info("本次删除模式中暂无可恢复的误删题目。")
        return

    for idx, rec in enumerate(active_records):
        q_label = rec.get("label") or format_question_title(os.path.basename(rec.get("original_path", "")))
        content = rec.get("content", "")
        extra_label = ""
        if rec.get("deleted_at"):
            extra_label = f"<span style='font-size:0.5em; color:gray; font-weight:normal; margin-left: 10px;'>删除于 {html.escape(rec.get('deleted_at'))}</span>"

        render_static_question_header(q_label, content, rec.get("original_path", ""), extra_html_label=extra_label)
        try:
            st.markdown(latex_to_markdown(content, show_title=False), unsafe_allow_html=True)
        except Exception as e:
            st.error(f"渲染错误: {e}")

        st.markdown('<span class="blue-restore-btn-hook"></span>', unsafe_allow_html=True)
        restore_key = f"restore_deleted_{rec.get('id', idx)}"
        original_exists = os.path.exists(rec.get("original_path", ""))
        restore_label = "原位置已有同名题" if original_exists else "↩️ 恢复该题"
        with _compat_container(key=f"restore_deleted_btn_wrap_{rec.get('id', idx)}"):
            if st.button(
                restore_label,
                key=restore_key,
                type="primary",
                use_container_width=True,
                disabled=original_exists,
            ):
                try:
                    restore_deleted_question_and_sync(rec)
                    st.toast(f"已恢复 {q_label}", icon="✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"恢复失败: {_format_file_write_error(e)}")
        st.divider()

@st.dialog("管理备份问题", width="large")
def manage_backup_questions_dialog():
    records = scan_question_backup_records()

    c_search, c_clear, c_exit = st.columns([3.1, 1.35, 1.05], vertical_alignment="bottom")
    with c_search:
        query = st.text_input(
            "查找备份题目",
            placeholder="输入题号、试卷名、知识板块或题干关键词...",
            key="backup_manager_query",
            label_visibility="collapsed",
        )
    with c_clear:
        st.markdown('<span class="backup-manage-btn-hook"></span>', unsafe_allow_html=True)
        with _compat_container(key="backup_manager_clear_all_wrap"):
            if st.button("清除所有备份问题", key="backup_manager_clear_all", use_container_width=True):
                st.session_state["backup_manager_confirm_clear"] = True
    with c_exit:
        st.markdown('<span class="delete-exit-btn-hook"></span>', unsafe_allow_html=True)
        with _compat_container(key="backup_manager_close_wrap"):
            if st.button("退出备份管理界面", key="backup_manager_close", use_container_width=True):
                st.session_state["backup_manager_confirm_clear"] = False
                st.rerun()

    if st.session_state.get("backup_manager_confirm_clear"):
        st.warning("确认永久删除所有题目备份吗？该操作不会进入回收站，也无法通过本系统恢复。")
        c_ok, c_cancel, _ = st.columns([1, 1, 3])
        with c_ok:
            st.markdown('<span class="red-btn-hook"></span>', unsafe_allow_html=True)
            with _compat_container(key="backup_manager_clear_ok_wrap"):
                if st.button("确认清除", key="backup_manager_clear_ok", type="primary", use_container_width=True):
                    try:
                        count = clear_all_question_backups()
                        st.session_state["backup_manager_confirm_clear"] = False
                        st.toast(f"已清除 {count} 条题目备份。", icon="✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"清除失败: {_format_file_write_error(e)}")
        with c_cancel:
            if st.button("取消", key="backup_manager_clear_cancel", use_container_width=True):
                st.session_state["backup_manager_confirm_clear"] = False
                st.rerun()

    if not records:
        st.info("当前没有可管理的题目备份。")
        return

    q = (query or "").strip()
    if q:
        records = [
            rec for rec in records
            if q in (rec.get("label", "") or "")
            or q in (rec.get("content", "") or "")
            or q in (rec.get("original_path", "") or "")
            or q in (rec.get("backup_path", "") or "")
            or q in (rec.get("deleted_at", "") or "")
        ]

    st.caption(f"当前显示 {len(records)} 条题目备份。恢复会复制备份回原路径；永久删除只会删除 .backups 中的备份文件。")

    if not records:
        st.warning("未找到匹配的备份题目。")
        return

    for idx, rec in enumerate(records):
        q_label = rec.get("label") or format_question_title(os.path.basename(rec.get("original_path", "")))
        content = rec.get("content", "")
        extra_label = ""
        if rec.get("deleted_at"):
            extra_label = f"<span style='font-size:0.5em; color:gray; font-weight:normal; margin-left: 10px;'>备份于 {html.escape(rec.get('deleted_at'))}</span>"

        render_static_question_header(q_label, content, rec.get("original_path", ""), extra_html_label=extra_label)
        try:
            st.markdown(latex_to_markdown(content, show_title=False), unsafe_allow_html=True)
        except Exception as e:
            st.error(f"渲染错误: {e}")

        c_restore, c_delete = st.columns([1, 1])
        with c_restore:
            st.markdown('<span class="blue-restore-btn-hook"></span>', unsafe_allow_html=True)
            original_exists = os.path.exists(rec.get("original_path", ""))
            restore_label = "原位置已有同名题" if original_exists else "↩️ 恢复该题"
            with _compat_container(key=f"backup_restore_btn_wrap_{rec.get('id', idx)}"):
                if st.button(
                    restore_label,
                    key=f"backup_restore_{rec.get('id', idx)}",
                    type="primary",
                    use_container_width=True,
                    disabled=original_exists,
                ):
                    try:
                        restore_deleted_question_and_sync(rec)
                        st.toast(f"已恢复 {q_label}", icon="✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"恢复失败: {_format_file_write_error(e)}")
        with c_delete:
            st.markdown('<span class="red-btn-hook"></span>', unsafe_allow_html=True)
            with _compat_container(key=f"backup_delete_wrap_{rec.get('id', idx)}"):
                if st.button("永久删除", key=f"backup_delete_{rec.get('id', idx)}", type="primary", use_container_width=True):
                    try:
                        permanently_delete_backup_record(rec)
                        st.toast(f"已永久删除 {q_label} 的备份。", icon="✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"永久删除失败: {_format_file_write_error(e)}")
        st.divider()

DELETE_SKIP_CONFIRM_KEY = "delete_skip_confirm_until_refresh"

def _format_file_write_error(e: Exception) -> str:
    msg = str(e)
    is_permission_error = isinstance(e, PermissionError)
    has_windows_lock_code = "WinError 32" in msg or "WinError 5" in msg
    if "题库索引表.csv" in msg:
        return (
            f"{msg}\n\n"
            "处理办法：请先关闭 Excel/WPS/编辑器中打开的 utils/题库索引表.csv，"
            "并确认只保留一个题库系统页面在执行删除/恢复，然后重试。"
        )
    if is_permission_error or has_windows_lock_code or "无法写入文件" in msg:
        return (
            f"{msg}\n\n"
            "处理办法：请关闭正在打开相关题目文件、备份文件或目录的编辑器/预览程序，"
            "并避免同时点击多个删除/恢复/清除按钮，然后重试。"
        )
    return msg

def _execute_delete_question_from_ui(fpath: str, q_label: str):
    try:
        backup_path, removed_rows = delete_question_file_and_sync(fpath)
        st.toast(f"已删除 {q_label}，移除索引记录 {removed_rows} 条。", icon="✅")
        if backup_path:
            st.session_state["last_deleted_question_backup"] = backup_path
        st.rerun()
    except Exception as e:
        st.error(f"删除失败: {_format_file_write_error(e)}")

@st.dialog("确认删除该题", width="small")
def confirm_delete_question_dialog(fpath: str, q_label: str, key_hash: str):
    st.warning(f"确认删除：{q_label}？")
    st.caption("删除会移除题目文件、CSV 索引记录和章节索引引用，原题目文件会自动备份到 .backups。若误删，可点删除模式右上角的“恢复误删题目”恢复本次删除记录，或点“管理备份问题”查找历史备份；当前备份不会自动定期清理。")

    c_opt, c_ok, c_cancel = st.columns([2.2, 1, 1], vertical_alignment="bottom")
    with c_opt:
        skip_confirm = st.checkbox(
            "本次彻底刷新页面前不再提醒",
            key=f"delete_skip_confirm_checkbox_{key_hash}",
        )
    with c_ok:
        if st.button("确认", key=f"delete_confirm_ok_{key_hash}", type="primary", use_container_width=True):
            if skip_confirm:
                st.session_state[DELETE_SKIP_CONFIRM_KEY] = True
            _execute_delete_question_from_ui(fpath, q_label)
    with c_cancel:
        if st.button("取消", key=f"delete_confirm_cancel_{key_hash}", use_container_width=True):
            st.rerun()

def render_static_question_header(q_label: str, content: str, fpath: str, extra_html_label: str = ""):
    st.markdown(f"### {html.escape(q_label)} {extra_html_label}", unsafe_allow_html=True)

    meta = _cached_question_meta(content)
    diff = (meta.get("难度星级", "") or "").strip()
    tags = (meta.get("标签", "") or "").strip()
    remark = (meta.get("备注", "") or "").strip()

    tag_badges = ""
    for tag in [t.strip() for t in tags.split("，") if t.strip()]:
        tag_badges += f"<span class='static-meta-badge static-meta-tag'>🏷️ {html.escape(tag)}</span>"
    if not tag_badges:
        tag_badges = "<span class='static-meta-empty'>无标签</span>"

    diff_text = html.escape(diff) if diff else "未设置"
    remark_text = html.escape(remark) if remark else "无备注"

    st.markdown("""
    <style>
    .static-meta-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px 14px;
        align-items: center;
        margin: -2px 0 12px 0;
        padding: 10px 12px;
        border: 1px solid rgba(0,0,0,0.08);
        border-radius: 8px;
        background: rgba(255,255,255,0.72);
    }
    .static-meta-item {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        color: #1f2328;
        font-size: 14px;
        line-height: 1.45;
    }
    .static-meta-label {
        font-weight: 700;
    }
    .static-meta-badge {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 14px;
        line-height: 1.45;
        font-weight: 600;
    }
    .static-meta-tag {
        color: #0366d6;
        background-color: #f1f8ff;
        border: 1px solid #c8e1ff;
    }
    .static-meta-empty {
        color: #8c959f;
        font-size: 13px;
    }
    .static-meta-remark {
        padding: 2px 8px;
        color: #8a6500;
        background-color: #fffdef;
        border: 1px solid #dfd8c2;
        border-radius: 6px;
        font-weight: 500;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(
        f"""
        <div class="static-meta-row">
            <div class="static-meta-item"><span class="static-meta-label">难度星级：</span><span>{diff_text}</span></div>
            <div class="static-meta-item"><span class="static-meta-label">标签：</span>{tag_badges}</div>
            <div class="static-meta-item"><span class="static-meta-label">备注：</span><span class="static-meta-remark">{remark_text}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_delete_question_item(fpath: str, q_label: str = None, content: str = None, key_prefix: str = "delete_mode", extra_html_label: str = "", show_header: bool = True):
    if not fpath or not os.path.exists(fpath):
        return

    if content is None:
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

    q_label = q_label or format_question_title(os.path.basename(fpath))
    if show_header:
        render_static_question_header(q_label, content, fpath, extra_html_label=extra_html_label)

    try:
        st.markdown(latex_to_markdown(content, show_title=False), unsafe_allow_html=True)
    except Exception as e:
        st.error(f"渲染错误: {e}")

    key_hash = hashlib.md5(f"{key_prefix}:{fpath}".encode("utf-8")).hexdigest()[:12]
    st.markdown('<span class="red-btn-hook"></span>', unsafe_allow_html=True)
    if st.button("🗑️ 删除该题", key=f"{key_prefix}_delete_{key_hash}", type="primary", use_container_width=True):
        if st.session_state.get(DELETE_SKIP_CONFIRM_KEY):
            _execute_delete_question_from_ui(fpath, q_label)
        else:
            confirm_delete_question_dialog(fpath, q_label, key_hash)

def ocr_image_to_latex(images=None, max_image_size: int = 1024, max_tokens: int = 4096, spinner_text: str = "🤖 AI 正在识别中，请稍候..."):
    """调用 AI 接口识别图片中的数学公式 (支持多张)
    Args:
        images: List of PIL Image objects
        max_image_size: 发送给视觉模型前的图片最长边限制。
        max_tokens: 本次 OCR 请求允许返回的最大 token 数。
    """
    # 动态加载 .env 配置，支持热更新
    load_dotenv(_root_env_path(), override=True)

    api_key = os.getenv("AI_API_KEY")
    base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
    model_name = os.getenv("AI_MODEL_NAME", "gpt-4o")

    # 重新读取提示词文件 (支持热更新)
    prompt = AI_OCR_PROMPT
    if os.path.exists(ocr_prompt_file):
        with open(ocr_prompt_file, "r", encoding="utf-8") as f:
            prompt = f.read()
    prompt = (
        "你是 OCR 转写助手。你只需要把图片中的内容逐字逐符号转写成 LaTeX 源码。\n"
        "禁止解题、禁止推理、禁止补全缺失步骤、禁止生成答案与解析。\n"
        "如果图片里本身包含答案/解析/提示，请原样转写；否则不要凭空生成。\n\n"
        + (prompt or "")
    )

    if not api_key:
        return "❌ 请先在 .env 文件中配置 AI_API_KEY"

    if not images:
        return "❌ 没有提供图片"

    try:
        from PIL import Image
        import io

        # 构造消息内容
        content_parts = [{"type": "text", "text": prompt}]

        for img in images:
            # 限制最大边长，避免请求体过大；PDF 页面可使用更高分辨率。
            if max(img.size) > max_image_size:
                ratio = max_image_size / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            # 转换为 JPEG 并压缩质量
            buffered = io.BytesIO()
            img = img.convert("RGB") # 兼容 PNG 透明通道
            img.save(buffered, format="JPEG", quality=80)
            base64_image = base64.b64encode(buffered.getvalue()).decode('utf-8')

            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{base64_image}"
                }
            })

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        # 兼容 OpenAI Vision API 格式
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": content_parts
                }
            ],
            "max_tokens": max_tokens
        }

        with st.spinner(spinner_text):
            # 处理 URL: 兼容不同的 Base URL 写法
            url = normalize_chat_completions_url(base_url)

            st.toast(f"正在请求: {url}")
            print(f"Requesting URL: {url}") # 控制台打印

            try:
                # 设置超时时间为 180 秒 (3分钟)
                response = requests.post(url, headers=headers, json=payload, timeout=180)
            except requests.exceptions.Timeout:
                return "❌ 请求超时 (180s)，请检查网络或稍后重试。"
            except requests.exceptions.RequestException as req_err:
                 return f"❌ 网络请求失败: {str(req_err)}\n请检查 URL ({url}) 是否正确及服务是否可达。"

            if response.status_code != 200:
                return f"❌ 识别失败 (HTTP {response.status_code}):\n{response.text[:500]}"

            try:
                result = response.json()
            except Exception as json_err:
                return f"❌ JSON 解析失败: {str(json_err)}\n\n原始响应内容(前500字符):\n{response.text[:500]}"

            if 'choices' in result and len(result['choices']) > 0:
                return result['choices'][0]['message']['content']
            else:
                return f"❌ 未收到有效回复: {result}"

    except Exception as e:
        return f"❌ 发生错误: {str(e)}"

def render_pdf_pages_to_images(pdf_bytes: bytes, page_numbers, dpi: int = 160):
    """Render selected 1-based PDF pages into in-memory PIL images for OCR."""
    try:
        import fitz
        from PIL import Image
    except ImportError as e:
        return [], f"缺少 PDF 识别依赖：{e}"

    try:
        images = []
        with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf_doc:
            if pdf_doc.needs_pass:
                return [], "PDF 已加密，暂不支持识别受密码保护的文件。"

            for page_number in page_numbers:
                if not 1 <= page_number <= pdf_doc.page_count:
                    return [], f"页码 {page_number} 超出 PDF 的有效范围。"

                page = pdf_doc.load_page(page_number - 1)
                pix = page.get_pixmap(dpi=dpi, alpha=False)
                with Image.open(io.BytesIO(pix.tobytes("png"))) as rendered_image:
                    rendered_image.load()
                    images.append(rendered_image.convert("RGB").copy())

        return images, ""
    except Exception as e:
        return [], f"PDF 页面渲染失败：{e}"

def ocr_solution_images_to_answer_solutions(images=None) -> dict:
    load_dotenv(_root_env_path(), override=True)
    api_key = os.getenv("AI_API_KEY")
    base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
    model_name = os.getenv("AI_MODEL_NAME", "gpt-4o")

    if not api_key or not base_url or not model_name:
        return {"error": "AI 配置不完整，请检查 .env 文件"}
    if not images:
        return {"error": "没有提供图片"}

    prompt = (
        "你是 OCR 转写助手。请把图片中的“答案/解答/解析”逐字逐符号转写为 LaTeX。\n"
        "禁止解题、禁止推理、禁止补全缺失步骤、禁止凭空生成内容。\n\n"
        "严格输出 JSON，且只包含两个字段：answer_tex 与 solutions_tex。\n"
        "answer_tex：必须是完整的 \\begin{answer}...\\end{answer} 环境；如果图片里没有明确答案，则输出空字符串。\n"
        "solutions_tex：必须是完整的 \\begin{solutions}...\\end{solutions} 环境；如果图片里没有解答过程，则输出空字符串。\n"
        "禁止输出反引号 ` 或 Markdown 代码块。\n"
    )

    try:
        from PIL import Image
        import io

        content_parts = [{"type": "text", "text": prompt}]
        for img in images:
            max_size = 1400
            if max(img.size) > max_size:
                ratio = max_size / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            buffered = io.BytesIO()
            img = img.convert("RGB")
            img.save(buffered, format="JPEG", quality=85)
            base64_image = base64.b64encode(buffered.getvalue()).decode("utf-8")
            content_parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}})

        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": content_parts}],
            "temperature": 0.1,
            "max_tokens": 2600,
            "response_format": {"type": "json_object"} if "gpt" in model_name.lower() or "qwen" in model_name.lower() else None,
        }

        response, _ = post_chat_completion(base_url, headers, payload, timeout=180)
        if response.status_code != 200:
            return {"error": f"识别失败 (HTTP {response.status_code}):\n{response.text[:500]}"}

        result = response.json()
        if "choices" not in result or not result["choices"]:
            return {"error": "AI 未返回有效内容"}
        reply = result["choices"][0]["message"]["content"]
        try:
            data = _extract_json_obj_from_text(reply)
        except Exception:
            return {"error": "AI 返回格式解析失败（非 JSON）"}

        answer_tex = _repair_latex_from_json_escapes(str(data.get("answer_tex", "")).strip())
        solutions_tex = _repair_latex_from_json_escapes(str(data.get("solutions_tex", "")).strip())
        return {"answer_tex": answer_tex, "solutions_tex": solutions_tex}
    except requests.exceptions.Timeout:
        return {"error": f"请求超时（模型：{model_name}）。可重试或切换更快模型。"}
    except Exception as e:
        return {"error": f"请求发生异常: {str(e)}"}

def call_ai_for_tags(content: str) -> dict:
    """调用 AI 为题目内容生成标签和难度"""
    api_key = os.getenv("AI_API_KEY")
    base_url = os.getenv("AI_BASE_URL")
    model_name = os.getenv("AI_MODEL_NAME")

    if not api_key or not base_url or not model_name:
        return {"error": "AI 配置不完整，请检查 .env 文件"}

    prompt = f"""你是一个专业的高中数学教研专家。请分析以下 LaTeX 格式的数学题目，并为其打上合适的“难度星级”和“知识标签”。

要求：
1. 难度星级：0.0 到 6.0 的浮点数，步长为 0.5（例如 2.5, 3.0, 4.5）。其中，0-2星为基础题，3-4星为中档题，5-6星为压轴/难题。
2. 知识标签：提取 2-4 个最核心的考点标签，以中文逗号“，”分隔（例如：导数应用，零点问题，分类讨论）。
3. 必须严格以 JSON 格式输出，不要输出任何额外的解释文本。

格式如下：
{{
    "difficulty": 3.5,
    "tags": "标签1，标签2，标签3"
}}

题目内容：
{content}"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "You are a JSON output bot. You only output valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"} if "gpt" in model_name.lower() or "qwen" in model_name.lower() else None
    }

    try:
        response, _ = post_chat_completion(base_url, headers, payload, timeout=30)
        if response.status_code == 200:
            result = response.json()
            if 'choices' in result and len(result['choices']) > 0:
                reply = result['choices'][0]['message']['content']
                import json
                try:
                    reply_clean = reply.replace('```json', '').replace('```', '').strip()
                    data = json.loads(reply_clean)
                    return {
                        "difficulty": float(data.get("difficulty", 0.0)),
                        "tags": str(data.get("tags", ""))
                    }
                except json.JSONDecodeError:
                    return {"error": "AI 返回格式解析失败"}
            else:
                return {"error": "AI 未返回有效内容"}
        else:
            return {"error": f"API 请求失败: {response.status_code}"}
    except Exception as e:
        return {"error": f"请求发生异常: {str(e)}"}

def _extract_json_obj_from_text(text: str):
    return extract_json_obj_from_text(text)

def _extract_problem_env(tex: str) -> str:
    if not tex:
        return ""
    m = re.search(r"\\begin\{problem\}[\s\S]*?\\end\{problem\}", tex)
    return m.group(0).strip() if m else ""

def _extract_env_block(tex: str, env_name: str) -> str:
    if not tex:
        return ""
    m = re.search(rf"\\begin\{{{re.escape(env_name)}\}}[\s\S]*?\\end\{{{re.escape(env_name)}\}}", tex)
    return m.group(0).strip() if m else ""

def _extract_env_inner_text(tex: str, env_pattern: str) -> str:
    if not tex:
        return ""
    m = re.search(rf"\\begin\{{{env_pattern}\}}(?:\[[^\]]*\])?([\s\S]*?)\\end\{{{env_pattern}\}}", tex)
    return (m.group(1) or "").strip() if m else ""

def _has_nonempty_answer_and_solution(tex: str) -> bool:
    answer_inner = _extract_env_inner_text(tex, "answer")
    solution_inner = _extract_env_inner_text(tex, "solutions?")
    return bool(answer_inner.strip()) and bool(solution_inner.strip())

def _strip_label_data_for_export(tex: str) -> str:
    try:
        _, clean_content = parse_meta_data(tex or "")
        return clean_content.strip()
    except Exception:
        return re.sub(
            r'%(?: === Meta Data ===| === Begin Label Data ===)\r?\n([\s\S]*?)%(?: === End Meta ===| === End\s+Label Data ===)\r?\n',
            '',
            tex or '',
            flags=re.DOTALL,
        ).strip()

def _sanitize_export_filename_component(value: str, fallback: str = "挖空题") -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or ""))
    text = re.sub(r"\s+", "_", text).strip("._ ")
    return (text or fallback)[:80]

def _build_question_image_tex(content: str) -> str:
    body = _strip_label_data_for_export(content)

    def _inline_input_file(match):
        input_path = (match.group(1) or "").strip()
        if not input_path:
            return match.group(0)
        candidate = input_path if os.path.isabs(input_path) else os.path.join(BASE_DIR, input_path)
        if not candidate.endswith(".tex"):
            candidate += ".tex"
        if not os.path.exists(candidate):
            return match.group(0)
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                return "\n" + f.read() + "\n"
        except Exception:
            return match.group(0)

    body = re.sub(r"\\input\{([^}]+)\}", _inline_input_file, body)
    preamble = r"""\documentclass[12pt]{ctexart}
\usepackage[a4paper,margin=1.35cm]{geometry}
\usepackage{amsmath,amssymb,mathtools}
\usepackage{xparse}
\usepackage{xcolor}
\usepackage{tikz}
\usepackage{pgfplots}
\usepackage{tasks}
\usepackage{enumitem}
\usepackage{array,booktabs,graphicx,float,caption}
\pgfplotsset{compat=1.16}
\usetikzlibrary{patterns,calc,positioning,intersections,arrows,arrows.meta,quotes,angles,3d,trees,decorations.pathreplacing,decorations.markings,decorations.pathmorphing,shapes.geometric,through,shapes.symbols,shapes.arrows,automata,shadows,shapes.callouts}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0.65em}
\settasks{label=\Alph*.}
\NewDocumentEnvironment{problem}{ m m m m m +b }{
  \par\noindent\textbf{【#1~~#3，#4】}\par
  #6
  \par\vspace{0.3em}
}{}
\NewDocumentEnvironment{answer}{ O{【答案】} O{} O{} +b }{
  \par\noindent\textbf{#1}\quad #4\par
}{}
\NewDocumentEnvironment{solutions}{ O{【解答】} O{} O{} +b }{
  \par\noindent\textbf{#1}\quad #4\par
}{}
\NewDocumentEnvironment{solution}{ O{【解答】} O{} O{} +b }{
  \par\noindent\textbf{#1}\quad #4\par
}{}
\NewDocumentEnvironment{choices}{ O{2} }{\begin{tasks}(#1)}{\end{tasks}}
\NewDocumentCommand{\choice}{m}{\task #1}
\newcommand{\circled}[1]{\tikz[baseline=(char.base)]{\node[shape=circle,draw,inner sep=1pt](char){#1};}}
\newcommand{\jc}[1]{\textbf{#1}}
\newcommand{\bj}[1]{\textbf{#1}}
\newcommand{\questionasset}[1]{\par\noindent\fbox{\scriptsize image: #1}\par}
\begin{document}
"""
    return preamble + "\n" + body + "\n" + r"\end{document}" + "\n"

def generate_question_png_from_latex(content: str, filename_hint: str = "挖空题", cloze_type: str = "") -> dict:
    if not (content or "").strip():
        return {"ok": False, "error": "当前内容为空，无法生成图片。"}

    xelatex = shutil.which("xelatex")
    if not xelatex:
        return {"ok": False, "error": "未检测到 xelatex，无法将 LaTeX 编译为图片。"}

    try:
        import fitz
        from PIL import Image
    except ImportError as e:
        return {"ok": False, "error": f"缺少图片导出依赖：{e}"}

    export_dir = os.path.join(BASE_DIR, "cloze_exports")
    compile_dir = os.path.join(export_dir, "_compile")
    ensure_dir(export_dir)
    ensure_dir(compile_dir)

    unique_id = uuid.uuid4().hex
    tex_name = f"{unique_id}.tex"
    tex_path = os.path.join(compile_dir, tex_name)
    pdf_path = os.path.join(compile_dir, f"{unique_id}.pdf")
    tex_content = _build_question_image_tex(content)
    last_output = ""

    try:
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_content)

        completed = subprocess.run(
            [
                xelatex,
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-file-line-error",
                tex_name,
            ],
            cwd=compile_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
        last_output = completed.stdout or ""
        if completed.returncode != 0 or not os.path.exists(pdf_path):
            return {
                "ok": False,
                "error": "LaTeX 编译失败，暂未生成图片。",
                "log": last_output[-3000:],
            }

        doc = fitz.open(pdf_path)
        page_images = []
        try:
            for page in doc:
                pix = page.get_pixmap(dpi=180, alpha=False)
                page_images.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
        finally:
            doc.close()

        if not page_images:
            return {"ok": False, "error": "PDF 中没有可导出的页面。"}

        width = max(img.width for img in page_images)
        height = sum(img.height for img in page_images)
        combined = Image.new("RGB", (width, height), "white")
        y = 0
        for img in page_images:
            x = (width - img.width) // 2
            combined.paste(img, (x, y))
            y += img.height

        buffer = io.BytesIO()
        combined.save(buffer, format="PNG", optimize=True)
        png_bytes = buffer.getvalue()

        safe_hint = _sanitize_export_filename_component(filename_hint, "挖空题")
        safe_type = _sanitize_export_filename_component(cloze_type, "当前题目")
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        out_name = f"{safe_hint}-{safe_type}-{timestamp}-{unique_id[:6]}.png"
        out_path = os.path.join(export_dir, out_name)
        with open(out_path, "wb") as f:
            f.write(png_bytes)

        return {"ok": True, "path": out_path, "filename": out_name, "bytes": png_bytes}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "LaTeX 编译超时，暂未生成图片。", "log": last_output[-3000:]}
    except Exception as e:
        return {"ok": False, "error": f"图片生成失败：{e}", "log": last_output[-3000:]}
    finally:
        for ext in (".tex", ".aux", ".log", ".out", ".pdf", ".xdv"):
            temp_path = os.path.join(compile_dir, f"{unique_id}{ext}")
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass

def _replace_first_env_or_insert_after_problem(tex: str, env_name: str, new_block: str) -> str:
    new_block = (new_block or "").strip()
    if not new_block:
        return tex
    pat = re.compile(rf"\\begin\{{{re.escape(env_name)}\}}[\s\S]*?\\end\{{{re.escape(env_name)}\}}")
    if pat.search(tex):
        return pat.sub(lambda m: new_block, tex, count=1)
    if "\\end{problem}" in tex:
        return tex.replace("\\end{problem}", "\\end{problem}\n\n" + new_block, 1)
    return tex.rstrip() + "\n\n" + new_block + "\n"

def _insert_block_after(tex: str, anchor_pat: str, new_block: str) -> str:
    m = re.search(anchor_pat, tex)
    if not m:
        return tex.rstrip() + "\n\n" + new_block.strip() + "\n"
    insert_pos = m.end()
    prefix = tex[:insert_pos]
    suffix = tex[insert_pos:]
    return prefix + "\n\n" + new_block.strip() + suffix

def _insert_block_before(tex: str, anchor_pat: str, new_block: str) -> str:
    m = re.search(anchor_pat, tex)
    if not m:
        return new_block.strip() + "\n\n" + tex.lstrip()
    insert_pos = m.start()
    prefix = tex[:insert_pos]
    suffix = tex[insert_pos:]
    return prefix.rstrip() + "\n\n" + new_block.strip() + "\n\n" + suffix.lstrip()

def _replace_or_insert_answer_solutions(tex: str, new_answer: str, new_solutions: str) -> str:
    answer_pat = re.compile(r"\\begin\{answer\}[\s\S]*?\\end\{answer\}")
    sol_pat = re.compile(r"\\begin\{solutions\}[\s\S]*?\\end\{solutions\}")
    has_answer = answer_pat.search(tex) is not None
    has_sol = sol_pat.search(tex) is not None

    if has_answer and has_sol:
        updated = answer_pat.sub(lambda m: new_answer.strip(), tex, count=1)
        updated = sol_pat.sub(lambda m: new_solutions.strip(), updated, count=1)
        return updated

    if has_answer and not has_sol:
        updated = answer_pat.sub(lambda m: new_answer.strip(), tex, count=1)
        return _insert_block_after(updated, r"\\end\{answer\}", new_solutions)

    if not has_answer and has_sol:
        updated = sol_pat.sub(lambda m: new_solutions.strip(), tex, count=1)
        return _insert_block_before(updated, r"\\begin\{solutions\}", new_answer)

    if "\\end{problem}" in tex:
        return _insert_block_after(tex, r"\\end\{problem\}", (new_answer.strip() + "\n\n" + new_solutions.strip()).strip())
    return (tex.rstrip() + "\n\n" + new_answer.strip() + "\n\n" + new_solutions.strip() + "\n").strip() + "\n"

def _extract_solutions_inner(new_solutions_block: str) -> str:
    m = re.search(r"\\begin\{solutions\}(?:\[[^\]]*\])?([\s\S]*?)\\end\{solutions\}", new_solutions_block or "")
    if not m:
        return ""
    return (m.group(1) or "").strip()

def _append_alt_solutions_after_last_solutions(tex: str, new_solutions_block: str, alt_label: str) -> str:
    inner = _extract_solutions_inner(new_solutions_block)
    if not inner:
        raise ValueError("empty solutions")

    label = (alt_label or "").strip()
    if label:
        alt_block = f"\\begin{{solutions}}[{label}]\n{inner}\n\\end{{solutions}}"
    else:
        alt_block = f"\\begin{{solutions}}\n{inner}\n\\end{{solutions}}"

    matches = list(re.finditer(r"\\end\{solutions\}", tex))
    if matches:
        last = matches[-1]
        insert_pos = last.end()
        return tex[:insert_pos] + "\n\n" + alt_block + tex[insert_pos:]

    if "\\end{answer}" in tex:
        return _insert_block_after(tex, r"\\end\{answer\}", alt_block)
    if "\\end{problem}" in tex:
        return _insert_block_after(tex, r"\\end\{problem\}", alt_block)
    return tex.rstrip() + "\n\n" + alt_block + "\n"

def _prepend_line_after_begin(block: str, env_name: str, line: str) -> str:
    block = (block or "").strip()
    if not block:
        return block
    begin = f"\\begin{{{env_name}}}"
    if begin not in block:
        return block
    return block.replace(begin, begin + "\n" + line, 1)

def _split_answer_solutions_from_text(text: str):
    ans = _extract_env_block(text, "answer")
    sol = _extract_env_block(text, "solutions")
    return ans, sol

def _repair_latex_from_json_escapes(text: str) -> str:
    s = text or ""
    s = s.replace("\x08", r"\b")
    s = s.replace("\x0c", r"\f")
    s = s.replace("\x09", r"\t")
    s = s.replace("\x0d", r"\r")
    s = s.replace("\x1b", "\\")
    s = re.sub(r"\n(?=eq\b)", r"\\n", s)
    s = re.sub(r"\n(?=abla\b)", r"\\n", s)

    keep_cmds = {
        "nabla",
        "neq",
        "nexists",
        "nmid",
        "not",
        "notin",
        "nu",
        "nparallel",
        "nsubseteq",
        "nsupseteq",
        "nRightarrow",
        "nrightarrow",
        "nLeftarrow",
        "nleftarrow",
        "nLeftrightarrow",
        "nleftrightarrow",
        "nVdash",
        "nvDash",
        "nvdash",
        "nVDash",
    }

    out = []
    i = 0
    while i < len(s):
        if i + 1 < len(s) and s[i] == "\\" and s[i + 1] == "n":
            j = i + 2
            if j < len(s) and s[j].isalpha():
                k = j
                while k < len(s) and s[k].isalpha():
                    k += 1
                cmd = "n" + s[j:k]
                if cmd in keep_cmds:
                    out.append("\\" + cmd)
                else:
                    out.append("\n" + s[j:k])
                i = k
                continue
            out.append("\n")
            i += 2
            continue
        out.append(s[i])
        i += 1
    s = "".join(out)
    return s

def _normalize_ai_generated_tex_for_preview(text: str) -> str:
    s = _repair_latex_from_json_escapes(text or "")
    s = s.replace("```json", "").replace("```latex", "").replace("```", "")
    s = s.replace("`", "")
    s = re.sub(r"\$\$\s*([\s\S]*?)\s*\$\$", lambda m: "$$\n" + m.group(1).strip() + "\n$$", s)
    s = re.sub(r"(?<!\$)\$([^$\n]*?)\$(?!\$)", lambda m: "$" + m.group(1).strip() + "$", s)
    s = re.sub(r"(\$|\$\$)\s*。", r"\1.", s)
    s = re.sub(r"(\$|\$\$)\s*，", r"\1,", s)
    s = re.sub(r"(\$|\$\$)\s*；", r"\1;", s)
    s = re.sub(r"\$\$\s*([。．\.，,；;])", r"$$\n\1", s)
    s = re.sub(r"([。．\.，,；;])\s*\$\$", r"\1\n$$", s)
    s = re.sub(r"[ \t]*\$\$[ \t]*", "$$", s)
    s = re.sub(r"(?<!\n)\$\$", r"\n$$", s)
    s = re.sub(r"\$\$(?!\n)", r"$$\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)

    def _fix_answer_env(m):
        inner = (m.group(1) or "").strip()
        if not inner:
            fixed_inner = ""
        else:
            fixed_inner = re.sub(r"\\frac(?=\{)", r"\\dfrac", inner)
            has_dollar = ("$" in fixed_inner) or ("$$" in fixed_inner)
            if not has_dollar:
                fixed_inner = "$" + fixed_inner.strip() + "$"
        return "\\begin{answer}\n" + fixed_inner + "\n\\end{answer}"

    s = re.sub(r"\\begin\{answer\}\s*([\s\S]*?)\s*\\end\{answer\}", _fix_answer_env, s)
    s = re.sub(r"\\begin\{solutions\}\s*", lambda _m: "\\begin{solutions}\n", s)
    s = re.sub(r"\s*\\end\{solutions\}", lambda _m: "\n\\end{solutions}", s)
    return s.strip()


CLOZE_BLANK_TEX = r"\underline{\hspace{4em}}"
CLOZE_GENERATION_RULES = {
    "简单定义基础计算挖空": "只挖定义、直接使用的公式、基础计算结果与最终数值。保留关键推导结构，通常设置 $6$ 至 $10$ 个空。",
    "基础推导与题意读取提炼挖空": "挖已知条件的关键转述、核心公式、必要的等价变形和中间结果。通常设置 $5$ 至 $8$ 个空，要求学生能完成完整推导。",
    "关键思路抽象推导挖空": "挖方法选择、关键定理、核心转化、结论衔接和决定性推导。通常设置 $6$ 至 $8$ 个空，但不能把同一行或同一公式挖得无法作答。",
}


def _normalize_cloze_blank_markup(tex: str) -> str:
    """Use one stable blank form so generated cloze questions render consistently."""
    return re.sub(
        r"\\underline\s*\{\s*\\hspace\*?\s*\{[^}]*\}\s*\}",
        lambda _m: CLOZE_BLANK_TEX,
        tex or "",
    )


def _normalize_cloze_generated_tex(text: str) -> str:
    """Clean transport artifacts without changing the answer-key layout."""
    tex = _repair_latex_from_json_escapes(text or "")
    tex = tex.replace("```json", "").replace("```latex", "").replace("```", "").replace("`", "")
    tex = re.sub(r"\\begin\{(problem|answer|solutions)\}\s*", lambda m: f"\\begin{{{m.group(1)}}}\n", tex)
    tex = re.sub(r"\s*\\end\{(problem|answer|solutions)\}", lambda m: f"\n\\end{{{m.group(1)}}}", tex)
    tex = re.sub(r"\n{3,}", "\n\n", tex)
    return _normalize_cloze_blank_markup(tex.strip())


def call_ai_for_cloze_question(source_tex: str, cloze_type: str) -> dict:
    """Generate an editable student cloze version plus its answer and completed solution."""
    load_dotenv(_root_env_path(), override=True)
    api_key = os.getenv("AI_API_KEY")
    base_url = os.getenv("AI_BASE_URL")
    model_name = os.getenv("AI_SOLVER_MODEL_NAME") or os.getenv("AI_MODEL_NAME")

    if not api_key or not base_url or not model_name:
        return {"error": "AI 配置不完整，请检查 .env 文件"}

    source_tex = _strip_label_data_for_export(source_tex)
    if not source_tex or not _extract_problem_env(source_tex):
        return {"error": "来源题目缺少完整的 problem 环境"}

    rule = CLOZE_GENERATION_RULES.get(cloze_type, CLOZE_GENERATION_RULES["简单定义基础计算挖空"])
    prompt = fr"""你是一名高中数学教研专家。请把下面的原题制作成可供学生练习的 LaTeX 挖空题。

本次挖空类型：{cloze_type}
具体要求：{rule}

必须严格输出 JSON，且只包含一个字段 cloze_tex。cloze_tex 必须是完整的 LaTeX 题目，依次包含：
1. 一个完整的 \\begin{{problem}}{{年份}}{{WK}}{{试卷名称}}{{题号}}{{知识板块}} ... \\end{{problem}}。题干必须保留原题的已知条件、小问、TikZ 图和其他必要排版；随后在 problem 内加入“解答过程：”，写出供学生填写的分步解答。
2. 一个完整的 \\begin{{answer}} ... \\end{{answer}}，按空格出现顺序给出每个空对应的内容，并保留原题最终答案。
3. 一个完整的 \\begin{{solutions}} ... \\end{{solutions}}，给出无挖空、完整且可核对的解答过程。

强制规则：
- 每一个空都必须且只能写为 `{CLOZE_BLANK_TEX}`，不得使用其他长度、\_\_\_、\verb|\blank|、\verb|\fillin| 等形式。
- 不能只挖最终答案；空格要覆盖与本次类型相符的关键学习步骤。
- 学生版的 problem 至少包含一个空，且解答过程应能独立作答。
- solutions 中不得保留空格，必须写出完整内容。
- 原题含有 TikZ、wrapfigure 或其他图形代码时，必须逐字保留原图代码，不能删改坐标、标注、样式或图形位置。
- 不得输出 Markdown、反引号或 JSON 以外的说明。
- LaTeX 命令在 JSON 字符串中必须正确转义，使用真实换行，不要输出文字 \\n。

原题：
{source_tex}"""

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "You are a JSON output bot. You only output valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 5600,
        "response_format": {"type": "json_object"} if "gpt" in model_name.lower() or "qwen" in model_name.lower() else None,
    }

    try:
        response, _ = post_chat_completion(base_url, headers, payload, timeout=(10, 180))
        if response.status_code != 200:
            return {"error": f"API 请求失败: {response.status_code}\n{response.text[:500]}"}
        result = response.json()
        if "choices" not in result or not result["choices"]:
            return {"error": "AI 未返回有效内容"}
        try:
            data = _extract_json_obj_from_text(result["choices"][0]["message"]["content"])
        except Exception:
            return {"error": "AI 返回格式解析失败（非 JSON）"}

        cloze_tex = _normalize_cloze_generated_tex(str(data.get("cloze_tex", "")))
        problem_tex = _extract_problem_env(cloze_tex)
        answer_tex = _extract_env_block(cloze_tex, "answer")
        solutions_tex = _extract_env_block(cloze_tex, "solutions")
        if not problem_tex or not answer_tex or not solutions_tex:
            return {"error": "AI 返回内容缺少完整的 problem、answer 或 solutions 环境"}
        if CLOZE_BLANK_TEX not in problem_tex:
            return {"error": "AI 未在学生版题目中生成统一格式的挖空"}
        if CLOZE_BLANK_TEX in solutions_tex:
            return {"error": "AI 在完整解析中保留了挖空，请重试"}
        return {"cloze_tex": cloze_tex}
    except requests.exceptions.Timeout:
        return {"error": f"请求超时（模型：{model_name}），请重试"}
    except Exception as e:
        return {"error": f"请求发生异常: {str(e)}"}


def _cloze_source_row_matches(row: dict, field: str, query: str) -> bool:
    query = (query or "").strip()
    if not query:
        return True
    values = {
        "题目ID": row.get("题目ID", ""),
        "题目类型": row.get("题型", ""),
        "题目内容": row.get("题干", ""),
        "解答内容": row.get("解析", ""),
        "难度星级": row.get("难度星级", ""),
        "标签": row.get("标签", ""),
        "备注": row.get("备注", ""),
    }
    if field == "全文内容":
        value = "\n".join(str(row.get(key, "") or "") for key in ("题干", "答案", "解析", "标签", "备注", "试卷名称", "知识板块"))
    else:
        value = values.get(field, "")
    return query in str(value or "")


def _cloze_source_label(row: dict) -> str:
    question_id = (row.get("题目ID", "") or "").strip() or "未分配 ID"
    year = (row.get("年份", "") or "").strip()
    paper = (row.get("试卷名称", "") or "").strip()
    number = (row.get("原卷题号", "") or "").strip()
    subject = (row.get("知识板块", "") or "").strip()
    return f"[{question_id}] {year} {paper} 第{number}题 | {subject}"


def _cloze_source_sort_key(row: dict) -> int:
    try:
        return int(str(row.get("题目ID", "") or "").strip())
    except (TypeError, ValueError):
        return -1


def _load_cloze_source_row(row: dict) -> str:
    rel_path = (row.get("相对文件路径", "") or "").strip()
    source_path = os.path.join(CHAPTERS_DIR, rel_path) if rel_path else ""
    if not source_path or not os.path.exists(source_path):
        raise FileNotFoundError("来源题目文件不存在，请先重建题库索引")
    with open(source_path, "r", encoding="utf-8") as f:
        source_tex = _strip_label_data_for_export(f.read())

    fields = extract_problem_header_fields(source_tex) or {}
    year = fields.get("year") or (row.get("年份", "") or "").strip()
    paper = fields.get("paper") or (row.get("试卷名称", "") or "").strip()
    number = fields.get("number") or (row.get("原卷题号", "") or "").strip()
    subject_str = fields.get("subject_str") or (row.get("知识板块", "") or "").strip()
    draft_tex = replace_problem_header(source_tex, year, "WK", paper, number, subject_str)

    st.session_state["cloze_source_tex"] = source_tex
    st.session_state["cloze_source_path"] = source_path
    st.session_state["cloze_source_label"] = _cloze_source_label(row)
    st.session_state["cloze_source_question_id"] = str(row.get("题目ID", "") or "")
    st.session_state["entry_year"] = year
    st.session_state["entry_p_type"] = "WK"
    st.session_state["entry_paper_name"] = paper
    st.session_state["entry_number"] = number
    st.session_state["entry_subject_multi"] = [item.strip() for item in subject_str.split("，") if item.strip() in SUBJECTS]
    st.session_state["entry_subject_user_locked"] = True
    st.session_state["entry_content"] = draft_tex
    st.session_state["cloze_image_result"] = None
    return draft_tex


def render_cloze_source_picker():
    """Three-condition lookup limited to ordinary questions, then load a source into the draft."""
    search_fields = ["全文内容", "题目ID", "题目类型", "题目内容", "解答内容", "难度星级", "标签", "备注"]
    query_specs = []

    with st.expander("选择来源原题", expanded=False):
        search_cols = st.columns(3)
        for index, column in enumerate(search_cols, start=1):
            with column:
                field = st.selectbox("检索字段", search_fields, key=f"cloze_source_field_{index}")
                if field == "题目类型":
                    query = st.selectbox("检索内容", ["", "选择题", "填空题", "解答题"], key=f"cloze_source_query_type_{index}")
                else:
                    query = st.text_input("检索内容", key=f"cloze_source_query_{index}")
                query_specs.append((field, query))

        try:
            from utils.csv_ops import read_csv_index
            source_rows = [
                row for row in read_csv_index()
                if (row.get("试卷类型", "") or "").strip() != "WK"
                and _cloze_source_row_matches(row, query_specs[0][0], query_specs[0][1])
                and _cloze_source_row_matches(row, query_specs[1][0], query_specs[1][1])
                and _cloze_source_row_matches(row, query_specs[2][0], query_specs[2][1])
            ]
        except Exception as e:
            st.error(f"读取来源题目索引失败：{e}")
            source_rows = []

        source_rows.sort(key=_cloze_source_sort_key, reverse=True)
        source_rows = source_rows[:100]
        if source_rows:
            options_by_path = {}
            for row in source_rows:
                rel_path = (row.get("相对文件路径", "") or "").strip()
                if rel_path:
                    options_by_path[rel_path] = row
            option_paths = list(options_by_path)
            if not option_paths:
                st.warning("匹配题目缺少文件路径，请先重建题库索引")
                return
            selected_key = "cloze_source_candidate_path"
            if st.session_state.get(selected_key) not in option_paths:
                st.session_state.pop(selected_key, None)
            selected_path = st.selectbox(
                "候选原题",
                options=option_paths,
                format_func=lambda path: _cloze_source_label(options_by_path[path]),
                key=selected_key,
            )
            if st.button("载入原题", key="btn_load_cloze_source", use_container_width=True):
                try:
                    _load_cloze_source_row(options_by_path[selected_path])
                    st.toast("已载入来源原题", icon="✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"载入来源原题失败：{e}")
        else:
            st.info("没有找到匹配的普通题目")

    source_tex = st.session_state.get("cloze_source_tex", "")
    if not source_tex:
        return

    st.caption(f"来源原题：{st.session_state.get('cloze_source_label', '')}")
    generate_col, clear_col = st.columns([3, 1])
    with generate_col:
        if st.button("✨ 生成挖空题", key="btn_generate_cloze", type="primary", use_container_width=True):
            cloze_type = st.session_state.get("cloze_generation_type", "简单定义基础计算挖空")
            with st.spinner("AI 正在生成挖空题..."):
                result = call_ai_for_cloze_question(source_tex, cloze_type)
            if result.get("error"):
                st.error(result["error"])
            else:
                fields = extract_problem_header_fields(source_tex) or {}
                generated_tex = replace_problem_header(
                    result["cloze_tex"],
                    fields.get("year") or st.session_state.get("entry_year", ""),
                    "WK",
                    fields.get("paper") or st.session_state.get("entry_paper_name", ""),
                    fields.get("number") or st.session_state.get("entry_number", ""),
                    fields.get("subject_str") or "，".join(st.session_state.get("entry_subject_multi", [])),
                )
                st.session_state["entry_content"] = generated_tex
                st.session_state["cloze_image_result"] = None
                st.session_state["cloze_generated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st.toast("挖空题已生成，可继续人工修改", icon="✅")
                st.rerun()
    with clear_col:
        if st.button("清除来源", key="btn_clear_cloze_source", use_container_width=True):
            for key in ("cloze_source_tex", "cloze_source_path", "cloze_source_label", "cloze_source_question_id", "cloze_generated_at"):
                st.session_state.pop(key, None)
            st.rerun()

def call_ai_for_answer_solutions(problem_tex: str, fast: bool = True) -> dict:
    load_dotenv(_root_env_path(), override=True)
    api_key = os.getenv("AI_API_KEY")
    base_url = os.getenv("AI_BASE_URL")
    model_name = os.getenv("AI_SOLVER_MODEL_NAME") or "qwen3.6-flash"

    if not api_key or not base_url or not model_name:
        return {"error": "AI 配置不完整，请检查 .env 文件"}

    problem_tex = (problem_tex or "").strip()
    if not problem_tex:
        return {"error": "未识别到 \\begin{problem}...\\end{problem}，无法生成解答"}

    def _build_prompt() -> str:
        if fast:
            return f"""请为下面的 LaTeX problem 生成答案与解析。

严格输出 JSON，且只包含两个字段：answer_tex 与 solutions_tex。
answer_tex 必须是完整的 \\begin{{answer}}...\\end{{answer}} 环境（只写最终答案）。
solutions_tex 必须是完整的 \\begin{{solutions}}...\\end{{solutions}} 环境（步骤尽量精简，关键式子即可）。
禁止输出反引号 ` 或 Markdown 代码块。

problem_tex：
{problem_tex}"""
        return f"""你是一名资深高中数学教研专家。请为下面的 LaTeX problem 生成对应的答案与解析。

要求：
1) 严格输出 JSON 格式，包含两个字段：answer_tex 与 solutions_tex。不要输出多余解释。
2) answer_tex 必须用 \\begin{{answer}}...\\end{{answer}} 包裹，且这两句一定要单独一行，中间内容仅输出最终答案（如选项字母、数值或集合）。
3) solutions_tex 必须用 \\begin{{solutions}}...\\end{{solutions}} 包裹，且这两句一定要单独一行。
4) **解析要求极简高效**：请给出关键公式和核心推导步骤，不需要过多啰嗦的文字描述。优先采用公式表达，且因为所以采用中文，不采用数学符号做这种连接，同时避免长篇大论。
5) 保持 LaTeX 书写规范（如下），注意数学符号排版，最终结论可以使用 \\boxed{{}}；\\boxed{{}} 外面不需要打 $，内部内容涉及到公式时再单独打 $。
6) 禁止输出任何反引号 ` 或 Markdown 代码块标记。
7) solutions_tex 中每个逻辑步骤单独成段，段落之间空一行（用两个换行）。
8) 重要：你输出的是 JSON 字符串。所有 LaTeX 命令的反斜杠必须写成双反斜杠，例如 \\\\frac、\\\\boxed、\\\\neq、\\\\text、\\\\right、\\\\left、\\\\displaystyle。
9) 重要：禁止输出 $\\boxed{...}$ 或 $$\\boxed{...}$$，只能输出 \\boxed{...}。
10) 重要：换行请直接使用真实换行，不要输出 \\n 字符串来表示换行。

排版与符号规范：
- 【公式环境】行内公式用 $ 包裹，居中行间公式用 $$ 包裹。要求：$$ 必须单独占一行（不要写成 $$ 公式 $$），公式本体单独占一行。绝对禁止使用 \\(\\) 或 \\[\\]。
- 【符号规范】遇到分式、求和、累乘等公式（包含行内公式），内部必须强制加 \\displaystyle 指令！数学括号必须使用 \\left( \\right)、\\left[ \\right] 等自适应大小指令！平行用 \\mathop{{//}}。带圈数字（如①、②、③、④等）必须无条件使用 \\circled{{1}}、\\circled{{2}} 格式，绝对禁止直接输出特殊字符①②③！
- 【独立数字/字母】单独的阿拉伯数字(1, 2)或英文字母(A, a)必须、无条件用 $ $ 包裹(如 $1$, $A$)！
- 【标点与空格规范】纯中文句子的结尾正常使用中文句号 。；但紧跟在数学公式或表达式后面的句号，必须严格使用英文句号 .！
- 【文字与公式间距】数学公式与前后的中文文字之间建议加一个空格（例如：已知函数 $f(x)$ 的定义域）。但 $ 与公式内容之间严禁留空格，必须写成 $f(x)$，不要写成 $ f(x) $。每一个完整的话（或段落）之间必须空一空行！题目小问直接写（1）（2）或（a），禁止使用 {{enumerate}} 环境。

problem_tex：
{problem_tex}"""

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "You are a JSON output bot. You only output valid JSON."},
            {"role": "user", "content": _build_prompt()},
        ],
        "temperature": 0.1,
        "max_tokens": 1600 if fast else 2600,
        "response_format": {"type": "json_object"} if "gpt" in model_name.lower() or "qwen" in model_name.lower() else None,
    }

    try:
        response, _ = post_chat_completion(base_url, headers, payload, timeout=(10, 90 if fast else 150))
        if response.status_code != 200:
            return {"error": f"API 请求失败: {response.status_code}\n{response.text[:500]}"}
        result = response.json()
        if "choices" not in result or not result["choices"]:
            return {"error": "AI 未返回有效内容"}
        reply = result["choices"][0]["message"]["content"]
        try:
            data = _extract_json_obj_from_text(reply)
        except Exception:
            return {"error": "AI 返回格式解析失败（非 JSON）"}

        answer_tex = str(data.get("answer_tex", "")).strip()
        solutions_tex = str(data.get("solutions_tex", "")).strip()
        answer_tex = _repair_latex_from_json_escapes(answer_tex)
        solutions_tex = _repair_latex_from_json_escapes(solutions_tex)
        if not answer_tex or not solutions_tex:
            return {"error": "AI 返回 JSON 缺少 answer_tex / solutions_tex"}
        if "\\begin{answer}" not in answer_tex or "\\end{answer}" not in answer_tex:
            return {"error": "answer_tex 不是完整的 answer 环境"}
        if "\\begin{solutions}" not in solutions_tex or "\\end{solutions}" not in solutions_tex:
            return {"error": "solutions_tex 不是完整的 solutions 环境"}
        return {"answer_tex": answer_tex, "solutions_tex": solutions_tex}
    except requests.exceptions.Timeout:
        return {"error": f"请求超时（模型：{model_name}）。可重试或切换更快模型。"}
    except Exception as e:
        return {"error": f"请求发生异常: {str(e)}"}

def _update_csv_index_for_content_change(fpath: str, new_content: str):
    try:
        from utils.csv_ops import update_csv_index_for_edit
        basename = os.path.basename(fpath).replace(".tex", "")
        parts = basename.split("-")
        if len(parts) >= 5:
            update_csv_index_for_edit(fpath, fpath, new_content, parts[0], parts[1], parts[2], parts[3], parts[4])
    except Exception:
        return

def _save_tex_from_widget(fpath: str, widget_key: str, edit_mode_key: str = "", toast_msg: str = "文件已保存！"):
    raw = st.session_state.get(widget_key, "")
    if not _duplicate_save_confirmation(fpath, raw, scope=widget_key):
        return False
    final_content = save_modified_tex_file(fpath, raw)
    _update_csv_index_for_content_change(fpath, final_content)
    _clear_advanced_search_result_cache()
    st.session_state[widget_key] = final_content
    if edit_mode_key:
        st.session_state[edit_mode_key] = False
    st.session_state["last_saved"] = time.time()
    st.toast(toast_msg, icon="✅")

def _apply_generated_answer_solutions_to_file(fpath: str, new_answer: str, new_solutions: str, mode: str, alt_label: str = ""):
    with open(fpath, "r", encoding="utf-8") as f:
        old_tex = f.read()

    new_answer = _normalize_ai_generated_tex_for_preview((new_answer or "").strip())
    new_solutions = _normalize_ai_generated_tex_for_preview((new_solutions or "").strip())
    if mode == "replace":
        if not new_answer or not new_solutions:
            raise ValueError("empty answer/solutions")
    else:
        if not new_solutions:
            raise ValueError("empty solutions")

    if mode == "replace":
        updated = _replace_or_insert_answer_solutions(old_tex, new_answer, new_solutions)
    elif mode == "append":
        updated = _append_alt_solutions_after_last_solutions(old_tex, new_solutions, alt_label)
    else:
        raise ValueError("invalid mode")

    final_content = save_modified_tex_file(fpath, updated)
    _update_csv_index_for_content_change(fpath, final_content)
    _clear_advanced_search_result_cache()
    clear_statistics_cache()
    return final_content

def _ai_sol_keys(fpath: str, key_prefix: str):
    import hashlib
    fhash = hashlib.md5(f"{key_prefix}:{fpath}".encode()).hexdigest()[:10]
    data_key = f"ai_sol_data_{fhash}"
    editor_key = f"ai_sol_editor_{fhash}"
    return fhash, data_key, editor_key

def render_ai_solution_generate_button(
    fpath: str,
    current_content: str,
    key_prefix: str,
    use_container_width: bool = True,
    compact: bool = False,
    action_columns=None,
):
    fhash, data_key, editor_key = _ai_sol_keys(fpath, key_prefix)
    do = None
    upload_open_key = f"ai_sol_upload_open_{fhash}"

    if compact:
        if action_columns:
            c_ai, c_img = action_columns
            with c_ai:
                if st.button("\U0001f916 AI\u751f\u6210\u89e3\u7b54", key=f"ai_sol_gen_{fhash}", type="primary", use_container_width=use_container_width):
                    do = "ai"
            with c_img:
                if st.button("\U0001f5bc\ufe0f \u89e3\u7b54\u56fe\u7247\u8bc6\u522b", key=f"ai_sol_img_toggle_{fhash}", type="secondary", use_container_width=use_container_width):
                    st.session_state[upload_open_key] = not st.session_state.get(upload_open_key, False)
        else:
            if st.button("\U0001f916 AI\u751f\u6210\u89e3\u7b54", key=f"ai_sol_gen_{fhash}", type="primary", use_container_width=use_container_width):
                do = "ai"
            if st.button("\U0001f5bc\ufe0f \u89e3\u7b54\u56fe\u7247\u8bc6\u522b", key=f"ai_sol_img_toggle_{fhash}", type="secondary", use_container_width=use_container_width):
                st.session_state[upload_open_key] = not st.session_state.get(upload_open_key, False)
    else:
        c_ai, c_img = st.columns([1, 1])
        with c_ai:
            if st.button("🤖 AI生成解答", key=f"ai_sol_gen_{fhash}", type="primary", use_container_width=use_container_width):
                do = "ai"
        with c_img:
            if st.button("🖼️ 解答图片识别", key=f"ai_sol_img_toggle_{fhash}", type="secondary", use_container_width=use_container_width):
                st.session_state[upload_open_key] = not st.session_state.get(upload_open_key, False)

    if do:
        problem_tex = _extract_problem_env(current_content)
        with st.spinner("🤖 AI 正在生成解答..."):
            res = call_ai_for_answer_solutions(problem_tex, fast=False)
        if "error" in res:
            st.toast(res["error"], icon="❌")
        else:
            combined = _normalize_ai_generated_tex_for_preview(res["answer_tex"].strip() + "\n\n" + res["solutions_tex"].strip())
            st.session_state[data_key] = {"answer_tex": res["answer_tex"], "solutions_tex": res["solutions_tex"]}
            st.session_state[editor_key] = combined
            st.toast("已生成解答（未写回文件）", icon="🪄")
            st.rerun()

def render_ai_solution_image_ocr_section(fpath: str, key_prefix: str, max_images: int = 5, compact: bool = False):
    fhash, data_key, editor_key = _ai_sol_keys(fpath, key_prefix)
    upload_open_key = f"ai_sol_upload_open_{fhash}"
    if not st.session_state.get(upload_open_key, False):
        return

    st.markdown('<hr style="border-top: 1px solid #e1e4e8; margin: 8px 0 12px 0;">', unsafe_allow_html=True)

    try:
        from PIL import Image
    except Exception:
        st.toast("缺少 pillow，无法读取图片", icon="❌")
        return

    queue_key = f"ai_sol_img_queue_{fhash}"
    prev_ids_key = f"ai_sol_img_uploader_prev_{fhash}"
    if queue_key not in st.session_state:
        st.session_state[queue_key] = []
    if prev_ids_key not in st.session_state:
        st.session_state[prev_ids_key] = []

    upload_targets = [st.container(), st.container()] if compact else st.columns([1, 1])
    with upload_targets[0]:
        if st.button("📋 粘贴剪贴板图片", key=f"ai_sol_img_paste_{fhash}", use_container_width=True):
            if not ImageGrab:
                st.toast("缺少 ImageGrab，无法读取剪贴板", icon="❌")
            else:
                try:
                    clip = ImageGrab.grabclipboard()
                    new_imgs = []
                    if isinstance(clip, Image.Image):
                        new_imgs.append(clip)
                    elif isinstance(clip, list):
                        for item in clip:
                            if isinstance(item, str) and os.path.isfile(item):
                                try:
                                    img = Image.open(item)
                                    img.load()
                                    new_imgs.append(img)
                                except Exception:
                                    continue
                    if not new_imgs:
                        st.toast("剪贴板中没有可用图片", icon="⚠️")
                    else:
                        room = max(0, max_images - len(st.session_state[queue_key]))
                        if room <= 0:
                            st.toast(f"队列已满（最多 {max_images} 张）", icon="⚠️")
                        else:
                            st.session_state[queue_key].extend(new_imgs[:room])
                            st.toast(f"已添加 {min(len(new_imgs), room)} 张图片", icon="✅")
                            st.rerun()
                except Exception as e:
                    st.toast(f"剪贴板读取失败: {e}", icon="❌")

    with upload_targets[1]:
        uploaded_files = st.file_uploader("📂 本地上传", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key=f"ai_sol_img_uploader_{fhash}")
        if uploaded_files:
            current_ids = [f"{f.name}_{f.size}" for f in uploaded_files]
            prev_ids = st.session_state.get(prev_ids_key, [])
            room = max(0, max_images - len(st.session_state[queue_key]))
            added = 0
            for uf in uploaded_files:
                if room <= 0:
                    break
                fid = f"{uf.name}_{uf.size}"
                if fid in prev_ids:
                    continue
                try:
                    img = Image.open(uf)
                    img.load()
                    st.session_state[queue_key].append(img)
                    added += 1
                    room -= 1
                except Exception:
                    continue
            st.session_state[prev_ids_key] = current_ids
            if added > 0:
                st.toast(f"已添加 {added} 张图片", icon="✅")
                st.rerun()

    imgs = st.session_state.get(queue_key, []) or []
    c_status, c_clear = ([st.container(), st.container()] if compact else st.columns([3, 1]))
    with c_status:
        st.caption(f"当前队列：{len(imgs)}/{max_images} 张")
    with c_clear:
        if st.button("清空", key=f"ai_sol_img_clear_{fhash}", use_container_width=True):
            st.session_state[queue_key] = []
            st.session_state[prev_ids_key] = []
            st.rerun()

    if imgs:
        cols = [st.container() for _ in imgs] if compact else st.columns(min(max_images, len(imgs)))
        for i, img in enumerate(list(imgs)):
            with cols[i % len(cols)]:
                st.image(img, use_column_width=True)
                if st.button("🗑️ 删除", key=f"ai_sol_img_del_{fhash}_{i}", use_container_width=True):
                    try:
                        st.session_state[queue_key].pop(i)
                    except Exception:
                        pass
                    st.rerun()

    if imgs:
        if st.button(f"开始识别（{len(imgs)} 张）", key=f"ai_sol_img_run_{fhash}", type="primary", use_container_width=True):
            with st.spinner("🤖 AI 正在识别解答图片..."):
                res = ocr_solution_images_to_answer_solutions(images=imgs[:max_images])
            if "error" in res:
                st.toast(res["error"], icon="❌")
            else:
                combined = _normalize_ai_generated_tex_for_preview((res.get("answer_tex") or "").strip() + "\n\n" + (res.get("solutions_tex") or "").strip())
                st.session_state[data_key] = {"answer_tex": res.get("answer_tex") or "", "solutions_tex": res.get("solutions_tex") or ""}
                st.session_state[editor_key] = combined
                st.toast("已识别解答（未写回文件）", icon="🪄")
                st.rerun()

def render_ai_solution_panel(fpath: str, q_label: str, key_prefix: str):
    fhash, data_key, editor_key = _ai_sol_keys(fpath, key_prefix)
    if data_key not in st.session_state:
        return

    st.markdown(f"### {q_label} <span style='color: #1E90FF;'>问题的新生成解答</span>", unsafe_allow_html=True)

    col_close, _ = st.columns([0.15, 0.85])
    with col_close:
        if st.button("✖ 关闭面板", key=f"close_ai_panel_{fhash}", use_container_width=True):
            del st.session_state[data_key]
            st.rerun()

    c_left, c_right = st.columns([1, 1])
    with c_left:
        gen_text = st.text_area("解答源码", key=editor_key, height=320)
    with c_right:
        try:
            preview_text = _normalize_ai_generated_tex_for_preview(gen_text)
            st.markdown(latex_to_markdown(preview_text, show_title=False), unsafe_allow_html=True)
        except Exception as e:
            st.error(f"渲染错误: {e}")

    ans, sol = _split_answer_solutions_from_text(gen_text)
    if not sol:
        st.warning("解答源码中未检测到 solutions 环境，暂无法写回。")
        return

    opt_c1, opt_c2 = st.columns([1, 1])
    with opt_c1:
        if st.button("✅ 替换原本的解答与答案", key=f"ai_sol_apply_replace_{fhash}", type="primary", use_container_width=True):
            if not ans:
                st.toast("缺少 answer 环境，无法执行替换。", icon="❌")
                return
            try:
                _apply_generated_answer_solutions_to_file(fpath, ans, sol, mode="replace")
                st.toast("已替换并保存", icon="✅")
                del st.session_state[data_key]
                st.rerun()
            except Exception as e:
                st.toast(f"保存失败: {e}", icon="❌")
    with opt_c2:
        st.markdown("**保存为（另解/解法）**", unsafe_allow_html=True)
        alt_label = st.text_input("保存为（另解/解法）", value="另解", key=f"ai_sol_alt_label_{fhash}", label_visibility="collapsed")
        if st.button("💾 保存为另解/解法", key=f"ai_sol_apply_append_{fhash}", use_container_width=True):
            try:
                _apply_generated_answer_solutions_to_file(fpath, ans, sol, mode="append", alt_label=alt_label)
                st.toast("已追加并保存", icon="✅")
                del st.session_state[data_key]
                st.rerun()
            except Exception as e:
                st.toast(f"保存失败: {e}", icon="❌")

def call_ai_for_polish(intent_text: str) -> str:
    """调用 AI 润色用户的组卷意图"""
    api_key = os.getenv("AI_API_KEY")
    base_url = os.getenv("AI_BASE_URL")
    model_name = os.getenv("AI_MODEL_NAME")

    if not api_key or not base_url or not model_name:
        return "❌ AI 配置不完整，请检查 .env 文件"

    prompt = f"""你是一个资深的高中数学教研专家。请帮我润色以下组卷意图，使其更加专业、明确、富有条理。
润色后的文本将用于指导后续的 AI 抽题算法。
要求：
1. 保持原意不变，但语言更精准。
2. 直接输出润色后的文本，不要带有任何“好的”、“没问题”等废话。

原想法：
{intent_text}"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    try:
        response, _ = post_chat_completion(base_url, headers, payload, timeout=20)
        if response.status_code == 200:
            result = response.json()
            if 'choices' in result and len(result['choices']) > 0:
                return result['choices'][0]['message']['content'].strip()
            else:
                return "❌ AI 未返回有效内容"
        else:
            return f"❌ API 请求失败: {response.status_code}"
    except Exception as e:
        return f"❌ 请求发生异常: {str(e)}"

def process_ocr_result(ocr_result, mode):
    """处理识别结果并更新界面"""
    if "❌" in ocr_result:
        st.error(ocr_result)
    else:
        st.success("识别成功！")

        if mode == "单题录入":
            st.session_state["entry_content"] = ""
            st.session_state["entry_custom_tags"] = ""
            st.session_state["entry_remark"] = ""
            st.session_state["entry_difficulty"] = 0.0
            st.session_state["entry_subject_user_locked"] = False

            parsed = _parse_single_ocr_result(
                ocr_result,
                paper_types=PAPER_TYPES,
                valid_subjects=SUBJECTS,
            )
            if parsed.header:
                st.session_state["entry_year"] = parsed.header.year
                st.session_state["entry_p_type"] = parsed.header.type
                st.session_state["entry_paper_name"] = parsed.header.paper
                st.session_state["entry_number"] = parsed.header.number
                if parsed.subject_list:
                    st.session_state["entry_subject_multi"] = parsed.subject_list
                    st.session_state["entry_subject_user_locked"] = True
                st.session_state["_ai_override_subjects"] = True
                st.session_state["entry_content"] = parsed.normalized_text
                st.rerun()
            else:
                st.warning(parsed.warning or "识别内容未包含标准 problem 结构，已自动进行结构重组。")
                st.session_state["entry_content"] = parsed.normalized_text
                st.rerun()

        else: # 批量模式（包括同卷试题录入和批量试题录入）
            # 智能解析批量OCR结果，支持多问题识别
            processed_result = process_batch_ocr_result(ocr_result, mode)

            # 第二次识别直接覆盖，不追加（避免内容重复）
            st.session_state["batch_content"] = processed_result
            st.session_state["batch_items_src_hash"] = None
            st.rerun()

def normalize_single_problem_structure(text, s_year="?", s_type="?", s_paper="?", s_num="?", s_subj="?"):
    r"""安全提取并重组单题的 LaTeX 结构，确保 \begin{problem}...\end{problem} 包裹正确，并预留答案和解析。"""
    return _service_normalize_single_problem_structure(text, s_year, s_type, s_paper, s_num, s_subj)

def fix_problem_format(text):
    """修复 \begin{problem} 的非标准格式，统一转为 {年份}{类别}{试卷}{题号}{板块} 格式"""
    return _service_fix_problem_format(text)

def _increment_question_number(number: str, offset: int = 1) -> str:
    """Increment numeric question numbers while keeping non-numeric labels editable."""
    return _service_increment_question_number(number, offset)

def _split_problem_block_by_choices(problem_block: str) -> list[str]:
    """Split an OCR block only when repeated choice environments give clear boundaries."""
    return _service_split_problem_block_by_choices(problem_block)

def process_batch_ocr_result(ocr_result, mode):
    """Normalize OCR output into one independently editable block per problem."""
    from utils.csv_ops import get_next_id

    parsed = _service_process_batch_ocr_result(ocr_result, start_id=get_next_id(), filename_builder=generate_filename)
    if parsed.first_info:
        update_batch_form_from_ocr(parsed.first_info)
    return parsed.normalized_text

def extract_info_to_form(ocr_result):
    """从单个OCR结果中提取信息并更新到表单"""
    info = _extract_batch_info_from_ocr(ocr_result)
    if info:
        update_batch_form_from_ocr(info)

def update_batch_form_from_ocr(info):
    """更新同卷试题录入表单中的统一信息"""
    try:
        # 更新年份
        if info.get('year') and info['year'].isdigit():
            st.session_state["u_batch_year"] = info['year']

        # 更新类别
        if info.get('type'):
            t_clean = info['type'].split('(')[0].split('（')[0].strip()
            for k, v in PAPER_TYPES.items():
                if k == t_clean or v == t_clean or k == info['type'] or v == info['type']:
                    st.session_state["u_batch_type"] = k
                    break

        # 更新试卷名称
        if info.get('paper'):
            st.session_state["u_batch_paper"] = info['paper']

        st.toast("✅ 已自动提取并填入年份和试卷信息", icon="📝")
    except Exception as e:
        print(f"更新表单信息时出错: {e}")


def _sqlite_draft_split_text_list(value: str) -> list[str]:
    return _service_split_text_list(value)


def _sqlite_draft_parse_asset_lines(value: str) -> list[dict]:
    return _service_parse_asset_lines(value)


def _sqlite_asset_caption_from_source_path(source_path: str) -> str:
    return _service_asset_caption_from_source_path(source_path)


def _sqlite_draft_review_reset_page():
    st.session_state["sqlite_draft_review_page"] = 1
    st.session_state["sqlite_draft_review_page_select"] = 1
    st.session_state["sqlite_draft_selected_id"] = ""


def _sqlite_draft_review_apply_page_select():
    try:
        selected_page = int(st.session_state.get("sqlite_draft_review_page_select", 1) or 1)
    except (TypeError, ValueError):
        selected_page = 1
    st.session_state["sqlite_draft_review_page"] = max(1, selected_page)
    st.session_state["sqlite_draft_selected_id"] = ""


def _sqlite_draft_review_change_page(delta, page_count):
    try:
        current_page = int(st.session_state.get("sqlite_draft_review_page", 1) or 1)
    except (TypeError, ValueError):
        current_page = 1
    upper_bound = max(1, int(page_count or 1))
    next_page = min(upper_bound, max(1, current_page + int(delta)))
    st.session_state["sqlite_draft_review_page"] = next_page
    st.session_state["sqlite_draft_review_page_select"] = next_page
    st.session_state["sqlite_draft_selected_id"] = ""


def _sqlite_draft_json_list_text(value: str, separator: str = "\n") -> str:
    return _service_json_list_text(value, separator=separator)


def _sqlite_draft_extra_dict(value: str) -> dict:
    return _service_extra_dict(value)


def _sqlite_draft_edit_hash(draft_id: str) -> str:
    return _question_key("sqlite_draft_edit", draft_id)


def _sqlite_draft_edit_field_key(draft_id: str, field: str) -> str:
    return f"sqlite_draft_review_edit_{_sqlite_draft_edit_hash(draft_id)}_{field}"


def _sqlite_draft_review_choice_editor_scope_key(draft_id: str) -> str:
    return _sqlite_draft_edit_field_key(draft_id, "choice_editor")


def _sqlite_manual_draft_choice_editor_scope_key() -> str:
    return "sqlite_manual_draft_choice_editor"


def _sqlite_draft_collect_manual_choices_text() -> str:
    scope_key = _sqlite_manual_draft_choice_editor_scope_key()
    count_key = _structured_choice_editor_key(scope_key, "choice_count")
    choices_text = st.session_state.get("sqlite_draft_choices_text", "")
    if count_key in st.session_state:
        choices_text = _structured_choice_editor_collect_text(scope_key)
        st.session_state["sqlite_draft_choices_text"] = choices_text
    return choices_text


def _sqlite_draft_asset_field_key(draft_asset_id: str, field: str) -> str:
    return f"sqlite_draft_asset_{_question_key('sqlite_draft_asset', draft_asset_id)}_{field}"


def _sqlite_draft_edit_form_token(form_values: dict) -> str:
    encoded = json.dumps(form_values, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:14]


def _sqlite_draft_prepare_edit_form_state(draft_id: str, form_values: dict):
    token_key = _sqlite_draft_edit_field_key(draft_id, "_token")
    next_token = _sqlite_draft_edit_form_token(form_values)
    if st.session_state.get(token_key) == next_token:
        return
    for field, value in form_values.items():
        st.session_state[_sqlite_draft_edit_field_key(draft_id, field)] = value
    st.session_state[token_key] = next_token


def _sqlite_draft_collect_edit_form_values(draft_id: str) -> dict:
    choices_text_key = _sqlite_draft_edit_field_key(draft_id, "choices_text")
    choice_scope_key = _sqlite_draft_review_choice_editor_scope_key(draft_id)
    choice_count_key = _structured_choice_editor_key(choice_scope_key, "choice_count")
    choices_text = st.session_state.get(choices_text_key)
    if choice_count_key in st.session_state:
        choices_text = _structured_choice_editor_collect_text(choice_scope_key)
        st.session_state[choices_text_key] = choices_text
    fields = [
        "source_label",
        "proposed_action",
        "target_question_id",
        "source_kind",
        "detected_year",
        "paper_series",
        "detected_source",
        "detected_question_number",
        "sub_number",
        "detected_topic",
        "question_type_id",
        "difficulty",
        "official_flag",
        "stem_tex",
        "choices_text",
        "answer_tex",
        "solution_tex",
        "tags_text",
        "note",
    ]
    values = {field: st.session_state.get(_sqlite_draft_edit_field_key(draft_id, field)) for field in fields}
    values["choices_text"] = choices_text
    return values


def _sqlite_draft_preview_question_from_state() -> dict:
    tags = _sqlite_draft_split_text_list(st.session_state.get("sqlite_draft_tags_text", ""))
    choices = _db_preview_split_choice_lines(_sqlite_draft_collect_manual_choices_text())
    difficulty = st.session_state.get("sqlite_draft_difficulty")
    if difficulty == "未设置":
        difficulty = None
    return {
        "question_id": "DRAFT",
        "legacy_id": "DRAFT",
        "detected_year": st.session_state.get("sqlite_draft_year", ""),
        "paper_series": st.session_state.get("sqlite_draft_paper_series", "G"),
        "detected_source": st.session_state.get("sqlite_draft_source_name", ""),
        "detected_question_number": st.session_state.get("sqlite_draft_question_number", ""),
        "detected_topic": st.session_state.get("sqlite_draft_topic", ""),
        "stem_tex": st.session_state.get("sqlite_draft_stem_tex", ""),
        "choices_json": json.dumps(choices, ensure_ascii=False),
        "answer_tex": st.session_state.get("sqlite_draft_answer_tex", ""),
        "solution_tex": st.session_state.get("sqlite_draft_solution_tex", ""),
        "difficulty": difficulty,
        "tags_json": json.dumps(tags, ensure_ascii=False),
        "note": st.session_state.get("sqlite_draft_note", ""),
        "usage_count": 0,
    }


SQLITE_DRAFT_ENTRY_MODES = ["单题录入", "批量试题录入", "同卷试题录入", "同书试题录入"]


def _sqlite_draft_read_balanced_argument(text: str, start_brace: int) -> tuple[str | None, int]:
    return _service_read_balanced_argument(text, start_brace)


def _sqlite_draft_extract_choice_items(choices_inner: str) -> list[str]:
    return _service_extract_choice_items(choices_inner)


def _sqlite_draft_extract_choices_from_stem(stem_tex: str) -> tuple[str, list[str]]:
    return _service_extract_choices_from_stem(stem_tex)


def _sqlite_draft_strip_problem_body(tex: str) -> tuple[dict, str, list[str], str, str]:
    return _service_strip_problem_body(tex, paper_types=PAPER_TYPES)


def _sqlite_draft_split_input_items(text: str) -> list[dict[str, str]]:
    return _service_split_input_items(text)


def _sqlite_draft_source_label(source_kind: str, year: str, source_name: str, question_number: str, fallback: str = "") -> str:
    return _service_source_label(source_kind, year, source_name, question_number, fallback)


def _sqlite_draft_join_number_and_sub_number(number: str, sub_number: str) -> str:
    return _service_join_number_and_sub_number(number, sub_number)


def _structured_choice_editor_write_text(scope_key: str, choices_text: str):
    raw_choices = _db_preview_split_choice_lines(choices_text)
    display_choices = [_db_preview_unwrap_choice_value(choice) for choice in raw_choices]
    count_key = _structured_choice_editor_key(scope_key, "choice_count")
    st.session_state[count_key] = min(len(display_choices), 8)
    for index in range(8):
        st.session_state[_structured_choice_editor_key(scope_key, f"choice_item_{index}")] = (
            display_choices[index] if index < len(display_choices) else ""
        )
    st.session_state[_structured_choice_editor_key(scope_key, "token")] = _db_preview_form_token({"choices": raw_choices})


def _sqlite_draft_preview_question_from_payload(payload: dict) -> dict:
    extra = payload.get("extra") or {}
    choices = payload.get("choices") or []
    tags = payload.get("tags") or []
    return {
        "question_id": "DRAFT",
        "legacy_id": "DRAFT",
        "detected_year": extra.get("detected_year", ""),
        "paper_series": extra.get("paper_series", "G"),
        "detected_source": extra.get("detected_source", payload.get("source_label", "")),
        "detected_question_number": extra.get("detected_question_number", ""),
        "detected_topic": extra.get("detected_topic", ""),
        "stem_tex": payload.get("stem_tex", ""),
        "choices_json": json.dumps(choices, ensure_ascii=False),
        "answer_tex": payload.get("answer_tex", ""),
        "solution_tex": payload.get("solution_tex", ""),
        "difficulty": payload.get("difficulty"),
        "tags_json": json.dumps(tags, ensure_ascii=False),
        "note": payload.get("note", ""),
        "usage_count": 0,
    }


def _sqlite_draft_target_filename(payload: dict) -> str:
    extra = payload.get("extra") or {}
    year = str(extra.get("detected_year") or "").strip() or "年份"
    paper_series = str(extra.get("paper_series") or "").strip() or "G"
    source = str(extra.get("detected_source") or payload.get("source_label") or "").strip() or "来源"
    number = str(extra.get("detected_question_number") or "").strip() or "题号"
    topic = str(extra.get("detected_topic") or "").strip() or "未分类"
    try:
        return generate_filename(year, paper_series, source, number, topic)
    except Exception:
        return f"{year}-{paper_series}-{source}-{number}-{topic}.tex"


def _sqlite_draft_problem_body_preview_tex(payload: dict) -> str:
    stem = str(payload.get("stem_tex") or "").strip()
    choices = [choice for choice in (payload.get("choices") or []) if str(choice or "").strip()]
    if not choices:
        return stem
    choice_lines = ["\\begin{choices}"]
    for choice in choices:
        wrapped_choice = _db_preview_wrap_choice_value(choice)
        if wrapped_choice:
            choice_lines.append(f"\\choice{{{wrapped_choice}}}")
    choice_lines.append("\\end{choices}")
    choices_tex = "\n".join(choice_lines)
    return f"{stem}\n{choices_tex}" if stem else choices_tex


def _sqlite_draft_preview_fragment_markdown(tex: str) -> str:
    text = str(tex or "").strip()
    if not text:
        return ""
    return _cached_latex_to_markdown(text, show_title=False)


def _render_sqlite_draft_preview_section(title: str, markdown_text: str):
    st.markdown(f"<div class='mc-sqlite-entry-preview-box-title'>{html.escape(title)}</div>", unsafe_allow_html=True)
    if str(markdown_text or "").strip():
        st.markdown(markdown_text, unsafe_allow_html=True)


def _sqlite_draft_payload_from_state(question_to_legacy_tex_func) -> dict:
    difficulty_value = st.session_state.get("sqlite_draft_difficulty")
    if difficulty_value == "未设置":
        difficulty_value = None
    source_kind = st.session_state.get("sqlite_draft_source_kind", "")
    year_value = st.session_state.get("sqlite_draft_year", "")
    source_name = st.session_state.get("sqlite_draft_source_name", "")
    question_number = st.session_state.get("sqlite_draft_question_number", "")
    sub_number = st.session_state.get("sqlite_draft_sub_number", "") if st.session_state.get("sqlite_draft_show_sub_number") else ""
    display_question_number = _sqlite_draft_join_number_and_sub_number(question_number, sub_number) if sub_number else question_number
    topic_multi = st.session_state.get("sqlite_draft_topic_multi") or []
    topic_value = "，".join(topic_multi) if topic_multi else st.session_state.get("sqlite_draft_topic", "")
    source_label = _sqlite_draft_source_label(
        source_kind,
        year_value,
        source_name,
        display_question_number,
        "",
    )
    payload = {
        "source_item_id": source_label,
        "source_label": source_label,
        "proposed_action": "insert",
        "target_question_id": "",
        "review_status": "ready",
        "question_type_id": st.session_state.get("sqlite_draft_question_type_id"),
        "stem_tex": st.session_state.get("sqlite_draft_stem_tex", ""),
        "choices": _db_preview_split_choice_lines(_sqlite_draft_collect_manual_choices_text()),
        "answer_tex": st.session_state.get("sqlite_draft_answer_tex", ""),
        "solution_tex": st.session_state.get("sqlite_draft_solution_tex", ""),
        "difficulty": difficulty_value,
        "tags": _sqlite_draft_split_text_list(st.session_state.get("sqlite_draft_tags_text", "")),
        "note": st.session_state.get("sqlite_draft_note", ""),
        "official_flag": False,
        "raw_source_text": st.session_state.get("sqlite_draft_stem_tex", ""),
        "assets": _sqlite_draft_parse_asset_lines(st.session_state.get("sqlite_draft_asset_lines", "")),
        "extra": {
            "source_kind": source_kind,
            "detected_year": year_value,
            "paper_series": st.session_state.get("sqlite_draft_paper_series", ""),
            "detected_source": source_name,
            "detected_question_number": display_question_number,
            "detected_topic": topic_value,
            "sub_number": sub_number,
            "track": st.session_state.get("sqlite_draft_track", ""),
        },
    }
    payload["normalized_tex"] = question_to_legacy_tex_func(_sqlite_draft_preview_question_from_payload(payload))
    return payload


def _sqlite_draft_batch_preview_state_key(mode: str) -> str:
    snapshot = {
        "mode": mode,
        "text": st.session_state.get("sqlite_draft_batch_text", ""),
        "source_kind": st.session_state.get("sqlite_draft_batch_source_kind", ""),
        "year": st.session_state.get("sqlite_draft_batch_year", ""),
        "paper_series": st.session_state.get("sqlite_draft_batch_paper_series", ""),
        "source_name": st.session_state.get("sqlite_draft_batch_source_name", ""),
        "topic": st.session_state.get("sqlite_draft_batch_topic", ""),
        "tags": st.session_state.get("sqlite_draft_batch_tags_text", ""),
        "note": st.session_state.get("sqlite_draft_batch_note", ""),
        "assets": st.session_state.get("sqlite_draft_batch_asset_lines", ""),
        "question_type_id": st.session_state.get("sqlite_draft_batch_question_type_id"),
        "difficulty": st.session_state.get("sqlite_draft_batch_difficulty"),
        "allow_ready": st.session_state.get("sqlite_draft_batch_allow_ready", False),
        "track": st.session_state.get("sqlite_draft_batch_track", ""),
        "book_page": st.session_state.get("sqlite_draft_batch_book_page", ""),
        "book_column": st.session_state.get("sqlite_draft_batch_book_column", ""),
        "book_exercise": st.session_state.get("sqlite_draft_batch_book_exercise", ""),
    }
    raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()


def _sqlite_draft_batch_payloads_from_state(mode: str, question_to_legacy_tex_func, include_normalized_tex: bool = True) -> list[dict]:
    raw_items = _sqlite_draft_split_input_items(st.session_state.get("sqlite_draft_batch_text", ""))
    difficulty_value = st.session_state.get("sqlite_draft_batch_difficulty")
    if difficulty_value == "未设置":
        difficulty_value = None
    common_kind = st.session_state.get("sqlite_draft_batch_source_kind", "试卷")
    if mode == "同卷试题录入":
        common_kind = "试卷"
    elif mode == "同书试题录入":
        common_kind = "教材"
    common_year = st.session_state.get("sqlite_draft_batch_year", "")
    common_series = st.session_state.get("sqlite_draft_batch_paper_series", "G")
    common_source = st.session_state.get("sqlite_draft_batch_source_name", "")
    common_topic = st.session_state.get("sqlite_draft_batch_topic", "")
    common_tags = _sqlite_draft_split_text_list(st.session_state.get("sqlite_draft_batch_tags_text", ""))
    common_note = st.session_state.get("sqlite_draft_batch_note", "")
    common_assets = _sqlite_draft_parse_asset_lines(st.session_state.get("sqlite_draft_batch_asset_lines", ""))
    payloads = []
    for index, item in enumerate(raw_items, start=1):
        fields, stem_tex, choices, answer_tex, solution_tex = _sqlite_draft_strip_problem_body(item.get("tex", ""))
        detected_year = fields.get("year") or common_year
        paper_series = fields.get("p_type") or common_series
        detected_source = fields.get("paper") or common_source
        question_number = fields.get("number") or str(index)
        topic = fields.get("subject_str") or common_topic
        if mode == "同书试题录入":
            paper_series = "BK"
            detected_source = common_source
            page_number = st.session_state.get("sqlite_draft_batch_book_page", "")
            column_name = st.session_state.get("sqlite_draft_batch_book_column", "")
            exercise_number = fields.get("number") or st.session_state.get("sqlite_draft_batch_book_exercise", "") or str(index)
            question_number = " · ".join(part for part in [f"p{page_number}" if page_number else "", column_name, exercise_number] if part)
            topic = column_name or topic
        elif mode == "同卷试题录入":
            paper_series = common_series
            detected_source = common_source
            detected_year = common_year
        source_label = _sqlite_draft_source_label(
            common_kind,
            detected_year,
            detected_source,
            question_number,
            "",
        )
        payload = {
            "source_item_id": f"{source_label} · {item.get('label', index)}",
            "source_label": source_label,
            "proposed_action": "insert",
            "target_question_id": "",
            "review_status": "ready" if st.session_state.get("sqlite_draft_batch_allow_ready") else "needs_review",
            "question_type_id": st.session_state.get("sqlite_draft_batch_question_type_id"),
            "stem_tex": stem_tex,
            "choices": choices,
            "answer_tex": answer_tex,
            "solution_tex": solution_tex,
            "difficulty": difficulty_value,
            "tags": common_tags,
            "note": common_note,
            "official_flag": False,
            "raw_source_text": item.get("tex", ""),
            "assets": common_assets,
            "extra": {
                "source_kind": common_kind,
                "entry_mode": mode,
                "detected_year": detected_year,
                "paper_series": paper_series,
                "detected_source": detected_source,
                "detected_question_number": question_number,
                "detected_topic": topic,
                "track": st.session_state.get("sqlite_draft_batch_track", ""),
                "book_page_number": st.session_state.get("sqlite_draft_batch_book_page", ""),
                "book_column_name": st.session_state.get("sqlite_draft_batch_book_column", ""),
            },
        }
        if include_normalized_tex:
            payload["normalized_tex"] = question_to_legacy_tex_func(_sqlite_draft_preview_question_from_payload(payload))
        payloads.append(payload)
    return payloads


def _sqlite_draft_apply_tex_to_single_state(tex: str):
    items = _sqlite_draft_split_input_items(tex)
    source = items[0]["tex"] if items else tex
    fields, stem_tex, choices, answer_tex, solution_tex = _sqlite_draft_strip_problem_body(source)
    if fields.get("year"):
        st.session_state["sqlite_draft_year"] = fields["year"]
    if fields.get("p_type"):
        st.session_state["sqlite_draft_paper_series"] = fields["p_type"]
    if fields.get("paper"):
        st.session_state["sqlite_draft_source_name"] = fields["paper"]
    if fields.get("number"):
        st.session_state["sqlite_draft_question_number"] = fields["number"]
    if fields.get("subject_str"):
        topic_text = fields["subject_str"]
        st.session_state["sqlite_draft_topic"] = topic_text
        topic_items = [item.strip() for item in topic_text.split("，") if item.strip() in SUBJECTS]
        st.session_state["sqlite_draft_topic_multi"] = topic_items
    if stem_tex:
        st.session_state["sqlite_draft_stem_tex"] = stem_tex
    if choices:
        choices_text = "\n".join(choices)
        st.session_state["sqlite_draft_choices_text"] = choices_text
        _structured_choice_editor_write_text(_sqlite_manual_draft_choice_editor_scope_key(), choices_text)
    if answer_tex:
        st.session_state["sqlite_draft_answer_tex"] = answer_tex
    if solution_tex:
        st.session_state["sqlite_draft_solution_tex"] = solution_tex


def _sqlite_draft_append_batch_text(tex: str, label: str = "AI-OCR"):
    current = st.session_state.get("sqlite_draft_batch_text", "")
    separator = "\n\n" if current.strip() else ""
    st.session_state["sqlite_draft_batch_text"] = f"{current.rstrip()}{separator}---{label}.tex---\n{(tex or '').strip()}".strip()


def _render_png_clipboard_button(png_bytes: bytes, key: str):
    if not png_bytes:
        return
    data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    safe_data_url = json.dumps(data_url)
    safe_key = re.sub(r"[^A-Za-z0-9_-]+", "_", key)
    components.html(
        f"""
        <button id="{safe_key}" style="
            width:100%;
            min-height:34px;
            border:1px solid rgba(109,40,217,.22);
            border-radius:8px;
            background:#f5f3ff;
            color:#4c1d95;
            font-weight:700;
            cursor:pointer;
        ">复制本题图片</button>
        <script>
        const button = document.getElementById({json.dumps(safe_key)});
        button.addEventListener("click", async () => {{
            try {{
                if (!navigator.clipboard || !window.ClipboardItem) {{
                    throw new Error("当前浏览器不支持图片剪贴板");
                }}
                const response = await fetch({safe_data_url});
                const blob = await response.blob();
                await navigator.clipboard.write([new ClipboardItem({{"image/png": blob}})]);
                button.textContent = "已复制图片";
            }} catch (error) {{
                button.textContent = "复制受限，请下载图片";
            }}
        }});
        </script>
        """,
        height=42,
    )


def _render_text_clipboard_button(text: str, label: str, key: str, *, height: int = 40):
    text = str(text or "")
    if not text:
        return
    safe_text = json.dumps(text)
    safe_key = re.sub(r"[^A-Za-z0-9_-]+", "_", key)
    safe_label = html.escape(label)
    components.html(
        f"""
        <button id="{safe_key}" type="button" style="
            width:100%;
            min-height:{height}px;
            border:1px solid rgba(109,40,217,.22);
            border-radius:999px;
            background:#f5f3ff;
            color:#4c1d95;
            font-weight:700;
            cursor:pointer;
        ">{safe_label}</button>
        <script>
        const button = document.getElementById({json.dumps(safe_key)});
        button.addEventListener("click", async () => {{
            try {{
                if (!navigator.clipboard || !navigator.clipboard.writeText) {{
                    throw new Error("clipboard unavailable");
                }}
                await navigator.clipboard.writeText({safe_text});
                button.textContent = "已复制";
            }} catch (error) {{
                button.textContent = "复制受限";
            }}
        }});
        </script>
        """,
        height=height + 8,
    )


def _render_sqlite_entry_ai_recognition_panel(entry_mode: str):
    st.markdown("##### 🖼️ AI 图片 / PDF 识别")
    st.caption("识别结果会自动填入当前录入方式：单题填字段，批量/同卷/同书填入批量 TeX。")
    uploaded_files = st.file_uploader(
        "上传图片或 PDF",
        type=["pdf", "png", "jpg", "jpeg"],
        key="sqlite_entry_ocr_uploader",
        accept_multiple_files=True,
        help="为控制延迟，单次最多识别 5 张图片或 PDF 前 5 页。",
    )
    st.session_state.setdefault("sqlite_entry_clipboard_images", [])
    paste_col, clear_col = st.columns([1.3, 0.7], gap="small")
    with paste_col:
        if st.button("📋 粘贴剪贴板首张图片", key="sqlite_entry_paste_clipboard", use_container_width=True):
            if not ImageGrab:
                st.warning("当前环境不支持读取剪贴板图片。")
            else:
                try:
                    from PIL import Image
                    clipboard_content = ImageGrab.grabclipboard()
                    if isinstance(clipboard_content, Image.Image):
                        st.session_state["sqlite_entry_clipboard_images"].append(clipboard_content.copy())
                        st.toast("已添加剪贴板图片", icon="✅")
                        st.rerun()
                    elif isinstance(clipboard_content, list):
                        added = False
                        for item in clipboard_content:
                            if isinstance(item, str) and os.path.isfile(item):
                                try:
                                    image = Image.open(item)
                                    image.load()
                                    st.session_state["sqlite_entry_clipboard_images"].append(image.convert("RGB").copy())
                                    added = True
                                    break
                                except Exception:
                                    pass
                        if added:
                            st.toast("已从剪贴板文件添加图片", icon="✅")
                            st.rerun()
                        else:
                            st.warning("剪贴板中没有可读取的图片。")
                    else:
                        st.warning("剪贴板中没有图片。")
                except Exception as exc:
                    st.warning(f"剪贴板读取失败：{exc}")
    with clear_col:
        if st.button("清空", key="sqlite_entry_clear_clipboard", use_container_width=True):
            st.session_state["sqlite_entry_clipboard_images"] = []
            st.rerun()
    clipboard_count = len(st.session_state.get("sqlite_entry_clipboard_images") or [])
    file_count = len(uploaded_files or [])
    if clipboard_count or file_count:
        st.caption(f"待识别：上传文件 {file_count} 个，剪贴板图片 {clipboard_count} 张。")
    else:
        st.info("请添加图片或 PDF 进行识别")

    if st.button("🚀 识别并填入", key="sqlite_entry_run_ocr", type="primary", use_container_width=True):
        try:
            from PIL import Image
        except ImportError:
            st.error("缺少 PIL 库，请安装 pillow。")
            return
        images = list(st.session_state.get("sqlite_entry_clipboard_images") or [])
        for uploaded_file in uploaded_files or []:
            if len(images) >= 5:
                break
            extension = os.path.splitext(uploaded_file.name)[1].lower()
            if extension == ".pdf":
                try:
                    import fitz
                    pdf_bytes = uploaded_file.getvalue()
                    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf_doc:
                        page_count = min(pdf_doc.page_count, 5 - len(images))
                    if page_count > 0:
                        pdf_images, render_error = render_pdf_pages_to_images(pdf_bytes, range(1, page_count + 1))
                        if render_error:
                            st.warning(f"{uploaded_file.name} 渲染失败：{render_error}")
                        else:
                            images.extend(pdf_images[: 5 - len(images)])
                except Exception as exc:
                    st.warning(f"{uploaded_file.name} 读取失败：{exc}")
            else:
                try:
                    image = Image.open(uploaded_file)
                    image.load()
                    images.append(image.convert("RGB").copy())
                except Exception as exc:
                    st.warning(f"{uploaded_file.name} 读取失败：{exc}")
        images = images[:5]
        if not images:
            st.warning("没有可识别的图片或 PDF 页面。")
            return
        result = ocr_image_to_latex(
            images=images,
            max_image_size=1600,
            max_tokens=8192,
            spinner_text=f"🤖 AI 正在识别 {len(images)} 张图片/页面...",
        )
        if result.startswith("❌"):
            st.error(result)
            return
        st.session_state["sqlite_entry_ocr_last_text"] = result.strip()
        if entry_mode == "单题录入":
            _sqlite_draft_apply_tex_to_single_state(result)
            st.toast("识别结果已填入单题字段", icon="✅")
        else:
            stamp = datetime.datetime.now().strftime("%H%M%S")
            _sqlite_draft_append_batch_text(result, label=f"{entry_mode}-{stamp}")
            st.toast("识别结果已追加到批量 TeX", icon="✅")
        st.rerun()
    if st.session_state.get("sqlite_entry_ocr_last_text"):
        with st.expander("查看最近识别原文", expanded=False):
            st.code(st.session_state.get("sqlite_entry_ocr_last_text", ""), language="latex")


def render_sqlite_manual_draft_entry():
    from services.database_service import DEFAULT_DATABASE_PATH
    from services.export_service import question_to_legacy_tex
    from services.import_service import create_manual_entry_draft, create_manual_entry_drafts
    from services.question_db_service import list_question_filter_options

    db_path = DEFAULT_DATABASE_PATH
    st.markdown(
        """
        <style>
        body:has(.mc-sqlite-draft-entry-anchor) .block-container {
            padding-top: 0.35rem !important;
        }
        .mc-sqlite-entry-hero {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 1rem;
            margin: 0 0 0.8rem;
            padding: 0.72rem 0.82rem;
            border-radius: 16px;
            background: linear-gradient(135deg, #f5f3ff 0%, #eef6ff 100%);
            border: 1px solid rgba(109, 40, 217, 0.14);
        }
        .mc-sqlite-entry-hero h1 {
            margin: 0;
            color: #312e81;
            font-size: 1.55rem;
            line-height: 1.2;
            font-weight: 860;
            letter-spacing: -0.02em;
        }
        .mc-sqlite-entry-hero p {
            margin: 0.22rem 0 0;
            color: #475569;
            font-size: 0.9rem;
            line-height: 1.45;
        }
        body:has(.mc-sqlite-draft-entry-anchor) div[data-testid="stForm"] {
            border: 0 !important;
            border-radius: 0 !important;
            background: transparent !important;
            padding: 0.22rem 0 !important;
            box-shadow: none !important;
        }
        body:has(.mc-sqlite-draft-entry-anchor) div[data-testid="column"]:has(.mc-sqlite-entry-rail-anchor) {
            position: sticky;
            top: 0.7rem;
            align-self: flex-start;
            z-index: 8;
        }
        body:has(.mc-sqlite-draft-entry-anchor) div[data-testid="stVerticalBlock"]:has(.mc-sqlite-entry-rail-anchor) {
            padding: 0.48rem 0.14rem 0.48rem 0;
            background: transparent;
            border: 0;
            box-shadow: none;
        }
        body:has(.mc-sqlite-draft-entry-anchor) div[data-testid="column"]:has(.mc-sqlite-entry-preview-anchor) > div[data-testid="stVerticalBlock"] {
            position: sticky;
            top: 0.7rem;
            padding: 0.14rem 0 0.14rem 0.12rem;
            border-radius: 0;
            background: transparent;
            border: 0;
            box-shadow: none;
        }
        body:has(.mc-sqlite-draft-entry-anchor) div[data-testid="column"]:has(.mc-sqlite-entry-rail-anchor),
        body:has(.mc-sqlite-draft-entry-anchor) div[data-testid="column"]:has(.mc-sqlite-entry-preview-anchor) {
            overflow: visible !important;
        }
        body:has(.mc-sqlite-draft-entry-anchor) div[data-testid="column"]:has(.mc-sqlite-entry-rail-anchor) > div,
        body:has(.mc-sqlite-draft-entry-anchor) div[data-testid="column"]:has(.mc-sqlite-entry-preview-anchor) > div {
            max-height: none !important;
            overflow: visible !important;
        }
        .mc-sqlite-entry-section {
            margin: 0.76rem 0 0.46rem;
            color: #1f2937;
            font-size: 1rem;
            line-height: 1.35;
            font-weight: 820;
        }
        .mc-sqlite-entry-help {
            margin: 0.35rem 0 0.68rem;
            color: #64748b;
            font-size: 0.82rem;
            line-height: 1.5;
        }
        .mc-sqlite-draft-note {
            margin: 0.25rem 0 0.85rem;
            padding: 0.62rem 0.72rem;
            border: 1px solid rgba(14, 165, 233, 0.18);
            border-radius: 12px;
            background: #f0f9ff;
            color: #075985;
            font-size: 0.86rem;
            line-height: 1.5;
        }
        .mc-sqlite-entry-batch-actions {
            margin-top: 0.48rem;
        }
        .mc-sqlite-draft-result {
            margin: 0.55rem 0 0.85rem;
            padding: 0.24rem 0;
            border-radius: 0;
            background: transparent;
            color: #334155;
            font-size: 0.86rem;
            line-height: 1.5;
        }
        .mc-sqlite-entry-option-head {
            display: flex;
            align-items: baseline;
            gap: 0.62rem;
            margin: 0.56rem 0 0.18rem;
        }
        .mc-sqlite-entry-option-head strong {
            color: #1f2937;
            font-size: 0.98rem;
            font-weight: 820;
        }
        .mc-sqlite-entry-option-head span {
            color: #64748b;
            font-size: 0.82rem;
            line-height: 1.35;
        }
        .mc-sqlite-entry-option-count-label {
            min-height: 2.38rem;
            display: flex;
            align-items: center;
            color: #475569;
            font-size: 0.88rem;
            font-weight: 720;
        }
        .mc-sqlite-entry-asset-toggle-note {
            margin: 0.28rem 0 0.32rem;
            color: #64748b;
            font-size: 0.8rem;
            line-height: 1.45;
        }
        .mc-sqlite-entry-preview-file {
            display: flex;
            align-items: flex-start;
            gap: 0.45rem;
            margin: 0.08rem 0 0.48rem;
            padding: 0.12rem 0;
            border-radius: 0;
            background: transparent;
            color: #1e3a8a;
            font-size: 0.82rem;
            line-height: 1.45;
        }
        .mc-sqlite-entry-preview-file strong {
            display: inline;
            margin-bottom: 0;
            color: #1e40af;
            font-size: 0.78rem;
            font-weight: 820;
            white-space: nowrap;
        }
        .mc-sqlite-entry-preview-file code {
            display: inline;
            white-space: normal;
            word-break: break-all;
            overflow-wrap: anywhere;
            background: transparent;
            color: #172554;
            font-size: 0.82rem;
            line-height: 1.4;
        }
        .mc-sqlite-entry-preview-box {
            margin: 0 0 0.46rem;
            padding: 0.2rem 0 0.2rem;
            border-radius: 13px;
            background: transparent;
            border: 0;
        }
        .mc-sqlite-entry-preview-box-title {
            margin: 0 0 0.2rem;
            color: #5b21b6;
            font-size: 0.9rem;
            font-weight: 840;
            letter-spacing: -0.01em;
        }
        .mc-sqlite-entry-preview-box-body {
            color: #111827;
            font-size: 0.94rem;
            line-height: 1.62;
        }
        .mc-sqlite-entry-preview-box-body p {
            margin: 0.28rem 0;
        }
        .mc-sqlite-entry-preview-empty-text {
            color: #94a3b8;
            font-size: 0.86rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<span class="mc-sqlite-draft-entry-anchor"></span>', unsafe_allow_html=True)

    if not os.path.exists(db_path):
        st.warning(f"未找到正式数据库：{db_path}")
        return

    st.markdown(
        """
        <div class="mc-sqlite-entry-hero">
            <div>
                <h1>✍️ 录入问题</h1>
                <p>面向新版 SQLite 题库的草稿录入工作台；先进入待审核草稿，不直接改正式题库，也不改旧 .tex 文件。</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    try:
        options = list_question_filter_options(db_path)
    except Exception as exc:
        st.error(f"读取 SQLite 选项失败：{exc}")
        return

    question_types = options.get("question_types", [])
    type_options = [item.get("question_type_id") for item in question_types]
    if 5 not in type_options:
        type_options.append(5)
    type_name_by_id = {item.get("question_type_id"): item.get("name") or item.get("code") or str(item.get("question_type_id")) for item in question_types}
    type_name_by_id.setdefault(5, "其他")

    defaults = {
        "sqlite_draft_entry_mode": "单题录入",
        "sqlite_draft_source_kind": "试卷",
        "sqlite_draft_year": str(datetime.datetime.now().year),
        "sqlite_draft_paper_series": "G",
        "sqlite_draft_track": "新高考",
        "sqlite_draft_source_name": "",
        "sqlite_draft_question_number": "",
        "sqlite_draft_sub_number": "",
        "sqlite_draft_show_sub_number": False,
        "sqlite_draft_topic": "",
        "sqlite_draft_topic_multi": [],
        "sqlite_draft_source_label": "",
        "sqlite_draft_proposed_action": "insert",
        "sqlite_draft_target_question_id": "",
        "sqlite_draft_question_type_id": 5,
        "sqlite_draft_difficulty": "未设置",
        "sqlite_draft_stem_tex": "",
        "sqlite_draft_choices_text": "",
        "sqlite_draft_answer_tex": "",
        "sqlite_draft_solution_tex": "",
        "sqlite_draft_tags_text": "",
        "sqlite_draft_note": "",
        "sqlite_draft_asset_lines": "",
        "sqlite_draft_show_assets_panel": False,
        "sqlite_draft_official_flag": False,
        "sqlite_draft_allow_ready": False,
        "sqlite_draft_batch_source_kind": "试卷",
        "sqlite_draft_batch_year": str(datetime.datetime.now().year),
        "sqlite_draft_batch_paper_series": "G",
        "sqlite_draft_batch_track": "新高考",
        "sqlite_draft_batch_source_name": "",
        "sqlite_draft_batch_topic": "",
        "sqlite_draft_batch_book_page": "",
        "sqlite_draft_batch_book_column": "",
        "sqlite_draft_batch_book_exercise": "",
        "sqlite_draft_batch_question_type_id": 5,
        "sqlite_draft_batch_difficulty": "未设置",
        "sqlite_draft_batch_tags_text": "",
        "sqlite_draft_batch_note": "",
        "sqlite_draft_batch_asset_lines": "",
        "sqlite_draft_batch_show_assets_panel": False,
        "sqlite_draft_batch_official_flag": False,
        "sqlite_draft_batch_allow_ready": False,
        "sqlite_draft_batch_text": "",
        "sqlite_draft_batch_proposed_action": "insert",
        "sqlite_draft_batch_preview_index": 1,
        "sqlite_draft_show_review_workspace": False,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)
    if not st.session_state.get("sqlite_draft_topic_multi") and st.session_state.get("sqlite_draft_topic"):
        topic_items = [item.strip() for item in str(st.session_state.get("sqlite_draft_topic") or "").split("，") if item.strip() in SUBJECTS]
        if topic_items:
            st.session_state["sqlite_draft_topic_multi"] = topic_items
    if st.session_state.get("sqlite_draft_entry_mode") not in SQLITE_DRAFT_ENTRY_MODES:
        st.session_state["sqlite_draft_entry_mode"] = "单题录入"

    left_col, form_col, preview_col = st.columns([1.08, 1.56, 0.96], gap="medium")
    with left_col:
        st.markdown('<span class="mc-sqlite-entry-rail-anchor"></span>', unsafe_allow_html=True)
        st.markdown("##### 录入方式")
        entry_mode = st.radio(
            "录入方式",
            SQLITE_DRAFT_ENTRY_MODES,
            key="sqlite_draft_entry_mode",
            label_visibility="collapsed",
        )
        mode_help = {
            "单题录入": "适合人工校订一题，字段最完整，右侧实时预览。",
            "批量试题录入": "适合粘贴多题 TeX；优先识别分隔符或 problem 环境。",
            "同卷试题录入": "多题共享同一试卷来源，题号优先从 problem 头读取。",
            "同书试题录入": "多题共享同一教材、页码和栏目，后续可转为教材来源关系。",
        }
        st.caption(mode_help.get(entry_mode, ""))
        st.divider()
        _render_sqlite_entry_ai_recognition_panel(entry_mode)
        if entry_mode == "单题录入":
            st.divider()
            st.toggle(
                "显示草稿审核与入库",
                key="sqlite_draft_show_review_workspace",
                help="单题保存后可在这里打开审核区，确认 ready/approved 后再写入正式 SQLite。",
            )
        else:
            st.caption("批量、同卷、同书模式会在下方显示草稿审核区。")

    submitted = False
    batch_submitted = False
    with form_col:
        if entry_mode == "单题录入":
            st.markdown("### 📝 单题详情")
            top_year_col, top_topic_col, top_series_col = st.columns([0.78, 1.65, 1.1], gap="small")
            with top_year_col:
                st.text_input("年份", key="sqlite_draft_year")
            with top_topic_col:
                valid_topics = [item for item in st.session_state.get("sqlite_draft_topic_multi", []) if item in SUBJECTS]
                if valid_topics != st.session_state.get("sqlite_draft_topic_multi"):
                    st.session_state["sqlite_draft_topic_multi"] = valid_topics
                st.multiselect("知识板块 (首个为主)", options=SUBJECTS, key="sqlite_draft_topic_multi")
            with top_series_col:
                series_options = _editable_paper_type_options()
                current_series = st.session_state.get("sqlite_draft_paper_series", "G")
                if current_series not in series_options:
                    st.session_state["sqlite_draft_paper_series"] = "G" if "G" in series_options else series_options[0]
                st.selectbox("试卷类别", series_options, key="sqlite_draft_paper_series", format_func=lambda value: f"{value} ({PAPER_TYPES.get(value, value)})")

            paper_col, number_col, sub_toggle_col = st.columns([2.35, 0.82, 0.54], gap="small")
            with paper_col:
                st.text_input("试卷 / 教材 / 专题名称", key="sqlite_draft_source_name")
            with number_col:
                st.text_input("题号 / 页码", key="sqlite_draft_question_number")
            with sub_toggle_col:
                st.write("")
                st.checkbox("小题", key="sqlite_draft_show_sub_number")
            if st.session_state.get("sqlite_draft_show_sub_number"):
                st.text_input("小题编号", key="sqlite_draft_sub_number", placeholder="可选，例如：1、Ⅰ、a")

            extra_col_1, extra_col_2, extra_col_3, extra_col_4 = st.columns([1.05, 1.05, 1.18, 0.88], gap="small")
            with extra_col_1:
                st.selectbox("来源类型", ["试卷", "教材", "专题", "其他"], key="sqlite_draft_source_kind")
            with extra_col_2:
                st.selectbox("文理 / 新高考", ["新高考", "文科", "理科", "不区分"], key="sqlite_draft_track")
            with extra_col_3:
                st.selectbox(
                    "题型",
                    type_options,
                    key="sqlite_draft_question_type_id",
                    format_func=lambda value: type_name_by_id.get(value, str(value)),
                )
            with extra_col_4:
                st.selectbox("难度", ["未设置", 1, 2, 3, 4, 5], key="sqlite_draft_difficulty")

            st.markdown("##### 🏷️ 附加属性")
            tag_col, remark_col, ai_col = st.columns([1.35, 1.35, 0.9], gap="small")
            with tag_col:
                st.text_input("标签（逗号或换行分隔）", key="sqlite_draft_tags_text", placeholder="例如：压轴题，易错点")
            with remark_col:
                st.text_input("备注", key="sqlite_draft_note", placeholder="例如：2025 新高考题型")
            with ai_col:
                st.write("")
                if st.button("🪄 AI 自动打标签", key="sqlite_draft_ai_tag_single", use_container_width=True):
                    content_for_ai = "\n".join(
                        part
                        for part in [
                            st.session_state.get("sqlite_draft_stem_tex", ""),
                            _sqlite_draft_collect_manual_choices_text(),
                            st.session_state.get("sqlite_draft_answer_tex", ""),
                            st.session_state.get("sqlite_draft_solution_tex", ""),
                        ]
                        if str(part or "").strip()
                    )
                    if not content_for_ai.strip():
                        st.toast("题目内容为空，无法进行 AI 分析", icon="⚠️")
                    else:
                        ai_result = call_ai_for_tags(content_for_ai)
                        if "error" in ai_result:
                            st.toast(ai_result["error"], icon="❌")
                        else:
                            try:
                                st.session_state["sqlite_draft_difficulty"] = max(1, min(5, int(round(float(ai_result.get("difficulty") or 0)))))
                            except Exception:
                                pass
                            ai_tags = str(ai_result.get("tags") or "").strip()
                            if ai_tags:
                                current_tags = str(st.session_state.get("sqlite_draft_tags_text") or "").strip()
                                st.session_state["sqlite_draft_tags_text"] = "，".join(
                                    dict.fromkeys([item.strip() for item in f"{current_tags}，{ai_tags}".split("，") if item.strip()])
                                )
                            st.toast("AI 标签与难度评级成功", icon="🪄")
                            st.rerun()

            st.markdown("##### 📝 题目内容 (LaTeX)")
            st.text_area("题干 TeX", key="sqlite_draft_stem_tex", height=170, placeholder="在此粘贴题干源码；不要手动写 problem 头。")
            _render_structured_choice_editor(
                _sqlite_manual_draft_choice_editor_scope_key(),
                st.session_state.get("sqlite_draft_choices_text", ""),
                show_step_buttons=False,
                use_grid_layout=False,
            )
            st.text_area("答案 TeX", key="sqlite_draft_answer_tex", height=64)
            st.text_area("解析 TeX", key="sqlite_draft_solution_tex", height=124)
            show_asset_panel = st.toggle("添加图片 / 附件草稿路径", key="sqlite_draft_show_assets_panel")
            if show_asset_panel:
                st.markdown(
                    "<div class='mc-sqlite-entry-asset-toggle-note'>每行格式：<code>role | 文件路径 | 命名 | 说明</code>；role 可用 problem / answer / solution / source / thumbnail。命名会在后续审核区继续保留，说明可补充用途、页码或裁剪信息。</div>",
                    unsafe_allow_html=True,
                )
                st.text_area("资源路径", key="sqlite_draft_asset_lines", height=82, label_visibility="collapsed")
            submitted = st.button("保存为 SQLite 草稿", key="sqlite_draft_single_submit", type="primary", use_container_width=True)
        else:
            st.markdown('<div class="mc-sqlite-entry-section">共同来源</div>', unsafe_allow_html=True)
            if entry_mode == "批量试题录入":
                source_kind_col, batch_year_col = st.columns([1.1, 1.0], gap="small")
                with source_kind_col:
                    st.selectbox("来源类型", ["试卷", "教材", "专题", "其他"], key="sqlite_draft_batch_source_kind")
                with batch_year_col:
                    st.text_input("年份 / 册次", key="sqlite_draft_batch_year")
            else:
                st.markdown(
                    "<div class='mc-sqlite-entry-help'>"
                    + (
                        "本模式下来源类型固定为试卷，多题共享年份、卷别和试卷名称。"
                        if entry_mode == "同卷试题录入"
                        else "本模式下来源类型固定为教材，多题共享教材名称、页码和栏目。"
                    )
                    + "</div>",
                    unsafe_allow_html=True,
                )
                st.text_input("年份 / 册次", key="sqlite_draft_batch_year")
            if entry_mode != "同书试题录入":
                series_options = _editable_paper_type_options()
                current_series = st.session_state.get("sqlite_draft_batch_paper_series", "G")
                if current_series not in series_options:
                    st.session_state["sqlite_draft_batch_paper_series"] = "G" if "G" in series_options else series_options[0]
                source_row_1, source_row_2, source_row_3 = st.columns([0.95, 0.95, 1.3], gap="small")
                with source_row_1:
                    st.selectbox("卷别代码", series_options, key="sqlite_draft_batch_paper_series", format_func=lambda value: f"{value} ({PAPER_TYPES.get(value, value)})")
                with source_row_2:
                    st.selectbox("文理 / 新高考", ["新高考", "文科", "理科", "不区分"], key="sqlite_draft_batch_track")
                with source_row_3:
                    st.text_input("试卷 / 来源名称", key="sqlite_draft_batch_source_name")
                st.text_input("知识板块", key="sqlite_draft_batch_topic")
            else:
                book_name_col, book_page_col = st.columns([1.45, 0.7], gap="small")
                with book_name_col:
                    st.text_input("教材名称", key="sqlite_draft_batch_source_name")
                with book_page_col:
                    st.text_input("页码", key="sqlite_draft_batch_book_page")
                book_column_col, book_exercise_col = st.columns([1.2, 0.95], gap="small")
                with book_column_col:
                    st.text_input("栏目", key="sqlite_draft_batch_book_column", placeholder="例如：习题、例题、复习题")
                with book_exercise_col:
                    st.text_input("起始题号", key="sqlite_draft_batch_book_exercise", placeholder="可选")

            st.markdown('<div class="mc-sqlite-entry-section">批量字段</div>', unsafe_allow_html=True)
            default_type_col, default_diff_col = st.columns([1.25, 0.9], gap="small")
            with default_type_col:
                st.selectbox(
                    "默认题型",
                    type_options,
                    key="sqlite_draft_batch_question_type_id",
                    format_func=lambda value: type_name_by_id.get(value, str(value)),
                )
            with default_diff_col:
                st.selectbox("默认难度", ["未设置", 1, 2, 3, 4, 5], key="sqlite_draft_batch_difficulty")
            st.text_input("默认标签（逗号或换行分隔）", key="sqlite_draft_batch_tags_text")
            st.text_area("默认备注", key="sqlite_draft_batch_note", height=62)
            show_batch_asset_panel = st.toggle("添加图片 / 附件草稿路径", key="sqlite_draft_batch_show_assets_panel")
            if show_batch_asset_panel:
                st.markdown(
                    "<div class='mc-sqlite-entry-asset-toggle-note'>批量模式下这里作为共同附件草稿；逐题图片建议后续在审核区补录。每行同样支持 <code>role | 文件路径 | 命名 | 说明</code>。</div>",
                    unsafe_allow_html=True,
                )
                st.text_area("资源路径", key="sqlite_draft_batch_asset_lines", height=82, label_visibility="collapsed")
            st.markdown('<div class="mc-sqlite-entry-section">TeX 内容</div>', unsafe_allow_html=True)
            st.text_area(
                "批量 TeX 内容",
                key="sqlite_draft_batch_text",
                height=320,
                placeholder="可粘贴多个完整 problem；也支持 ---xxx.tex--- 分隔格式。",
            )
            ready_col, save_col = st.columns([1.25, 1.0], gap="small")
            with ready_col:
                st.checkbox("字段完整且无警告时标记为 ready", key="sqlite_draft_batch_allow_ready")
            with save_col:
                st.markdown('<div class="mc-sqlite-entry-batch-actions"></div>', unsafe_allow_html=True)
                batch_submitted = st.button("批量保存为 SQLite 待审核草稿", key="sqlite_draft_batch_submit", type="primary", use_container_width=True)

    if submitted:
        try:
            payload = _sqlite_draft_payload_from_state(question_to_legacy_tex)
            result = create_manual_entry_draft(
                db_path,
                payload,
                source_path=f"streamlit/manual-entry/{payload.get('extra', {}).get('source_kind', 'manual')}",
            )
            st.session_state["sqlite_draft_last_result"] = result
            if result.get("draft_id"):
                st.session_state["sqlite_draft_selected_id"] = result["draft_id"]
            st.toast(f"草稿已保存：{result['draft_id']}", icon="✅")
        except Exception as exc:
            st.error(f"保存草稿失败：{exc}")
    if batch_submitted:
        try:
            payloads = _sqlite_draft_batch_payloads_from_state(entry_mode, question_to_legacy_tex)
            if not payloads:
                st.warning("没有解析到可保存的题目。")
            elif len(payloads) > 60:
                st.warning("一次最多建议保存 60 题；请拆分后再保存。")
            else:
                result = create_manual_entry_drafts(
                    db_path,
                    payloads,
                    source_path=f"streamlit/manual-entry/{entry_mode}",
                    mode=entry_mode,
                    summary=f"{entry_mode} · {len(payloads)} 题",
                )
                st.session_state["sqlite_draft_last_result"] = result
                st.toast(f"已保存 {result['draft_count']} 条草稿", icon="✅")
        except Exception as exc:
            st.error(f"批量保存草稿失败：{exc}")

    with preview_col:
        st.markdown('<span class="mc-sqlite-entry-preview-anchor"></span>', unsafe_allow_html=True)
        st.markdown("##### 实时预览")
        last_result = st.session_state.get("sqlite_draft_last_result") or {}
        if last_result:
            draft = last_result.get("draft") or {}
            validation = last_result.get("validation") or {}
            if last_result.get("draft_count"):
                result_label = f"{last_result.get('draft_count')} 条草稿"
                result_status = last_result.get("status_counts") or {}
            else:
                result_label = str(last_result.get("draft_id") or "")
                result_status = draft.get("review_status") or validation.get("status") or ""
            st.markdown(
                f"""
                <div class="mc-sqlite-draft-result">
                    <strong>最近保存：</strong>{html.escape(result_label)}<br>
                    <strong>状态：</strong>{html.escape(str(result_status))}<br>
                    <strong>批次：</strong>{html.escape(str(last_result.get('batch_id') or ''))}
                </div>
                """,
                unsafe_allow_html=True,
            )
            if not last_result.get("draft_count") and last_result.get("draft_id"):
                if st.button("打开草稿审核与入库", key="sqlite_draft_open_review_after_save", use_container_width=True):
                    st.session_state["sqlite_draft_show_review_workspace"] = True
                    st.session_state["sqlite_draft_selected_id"] = str(last_result.get("draft_id") or "")
                    st.rerun()
        try:
            preview_payload = None
            preview_payloads = []
            if entry_mode == "单题录入":
                preview_payload = _sqlite_draft_payload_from_state(question_to_legacy_tex)
                preview_tex = question_to_legacy_tex(_sqlite_draft_preview_question_from_payload(preview_payload))
            else:
                batch_preview_cache_key = _sqlite_draft_batch_preview_state_key(entry_mode)
                batch_preview_cache = st.session_state.get("sqlite_draft_batch_preview_cache") or {}
                if batch_preview_cache.get("key") == batch_preview_cache_key:
                    preview_payloads = batch_preview_cache.get("payloads") or []
                else:
                    preview_payloads = _sqlite_draft_batch_payloads_from_state(
                        entry_mode,
                        question_to_legacy_tex,
                        include_normalized_tex=False,
                    )
                    st.session_state["sqlite_draft_batch_preview_cache"] = {
                        "key": batch_preview_cache_key,
                        "payloads": preview_payloads,
                    }
                st.caption(f"当前解析到 {len(preview_payloads)} 题。")
                preview_tex = ""
            if entry_mode == "单题录入" and preview_payload:
                st.markdown(
                    f"""
                    <div class="mc-sqlite-entry-preview-file">
                        <strong>参考保存文件名</strong>
                        <code>{html.escape(_sqlite_draft_target_filename(preview_payload))}</code>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            if entry_mode == "单题录入" and preview_tex.strip():
                preview_image_token = hashlib.md5(preview_tex.encode("utf-8", errors="ignore")).hexdigest()
                if st.session_state.get("sqlite_draft_preview_image_token") != preview_image_token:
                    st.session_state["sqlite_draft_preview_image_token"] = preview_image_token
                    st.session_state["sqlite_draft_preview_image_result"] = {}
                if st.button("生成本题图片", key="sqlite_draft_generate_preview_png", use_container_width=True):
                    with st.spinner("正在渲染完整题图..."):
                        image_result = generate_question_png_from_latex(
                            preview_tex,
                            filename_hint="SQLite录入草稿",
                            cloze_type="完整题图",
                        )
                    st.session_state["sqlite_draft_preview_image_result"] = image_result
                    if image_result.get("ok"):
                        st.toast("题图已生成", icon="✅")
                    else:
                        st.warning(image_result.get("error") or "题图生成失败")
                image_result = st.session_state.get("sqlite_draft_preview_image_result") or {}
                if image_result.get("ok") and image_result.get("bytes"):
                    st.image(io.BytesIO(image_result["bytes"]), caption="当前草稿完整题图")
                    _render_png_clipboard_button(image_result["bytes"], "sqlite-draft-preview-copy-image")
                    st.download_button(
                        "下载本题图片",
                        data=image_result["bytes"],
                        file_name=image_result.get("filename") or "sqlite_manual_draft_preview.png",
                        mime="image/png",
                        use_container_width=True,
                    )
                if entry_mode == "单题录入" and preview_payload:
                    _render_sqlite_draft_preview_section(
                        "题干",
                        _sqlite_draft_preview_fragment_markdown(
                            _sqlite_draft_problem_body_preview_tex(preview_payload)
                        ),
                    )
                    _render_sqlite_draft_preview_section(
                        "答案",
                        _sqlite_draft_preview_fragment_markdown(preview_payload.get("answer_tex", "")),
                    )
                    _render_sqlite_draft_preview_section(
                        "解答",
                        _sqlite_draft_preview_fragment_markdown(preview_payload.get("solution_tex", "")),
                    )
                else:
                    if preview_payloads:
                        st.markdown(
                            f"<div class='mc-sqlite-entry-preview-file'><strong>批量统一预览</strong>共 {len(preview_payloads)} 题</div>",
                            unsafe_allow_html=True,
                        )
                        for index, item_payload in enumerate(preview_payloads, start=1):
                            st.markdown(
                                f"<div class='mc-sqlite-entry-preview-file'><strong>第 {index} 题</strong><code>{html.escape(_sqlite_draft_target_filename(item_payload))}</code></div>",
                                unsafe_allow_html=True,
                            )
                            _render_sqlite_draft_preview_section(
                                "题干",
                                _sqlite_draft_preview_fragment_markdown(
                                    _sqlite_draft_problem_body_preview_tex(item_payload)
                                ),
                            )
                            _render_sqlite_draft_preview_section(
                                "答案",
                                _sqlite_draft_preview_fragment_markdown(item_payload.get("answer_tex", "")),
                            )
                            _render_sqlite_draft_preview_section(
                                "解答",
                                _sqlite_draft_preview_fragment_markdown(item_payload.get("solution_tex", "")),
                            )
            else:
                st.info("填写或粘贴 TeX 后，这里会显示当前草稿预览。")
        except Exception as exc:
            st.warning(f"草稿预览失败：{exc}")

    if entry_mode != "单题录入" or st.session_state.get("sqlite_draft_show_review_workspace"):
        st.divider()
        render_sqlite_draft_review_workspace(db_path)


def render_sqlite_draft_review_workspace(db_path: str):
    from services.export_service import question_to_legacy_tex
    from services.import_service import (
        commit_draft_to_question,
        count_draft_questions,
        add_draft_asset,
        delete_draft_asset,
        draft_to_preview_question,
        get_draft_question,
        list_draft_questions,
        list_import_batches,
        update_draft_asset_fields,
        update_draft_question_fields,
        update_draft_review_status,
    )
    from services.asset_service import collect_asset_reference_issues
    from services.question_db_service import get_question, list_question_filter_options

    st.markdown(
        """
        <style>
        .mc-sqlite-review-shell {
            margin: 0.25rem 0 0.85rem;
            padding: 0.28rem 0 0.3rem;
            border-radius: 0;
            background: transparent;
            color: #4b5563;
            font-size: 0.86rem;
            line-height: 1.5;
        }
        .mc-sqlite-review-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 0.24rem 0.34rem;
            margin: 0.34rem 0 0.58rem;
        }
        .mc-sqlite-review-pill {
            display: inline-flex;
            align-items: center;
            max-width: 100%;
            padding: 0.1rem 0.38rem;
            border-radius: 999px;
            background: #f1f5f9;
            color: #334155;
            font-size: 0.76rem;
            line-height: 1.35;
            font-weight: 700;
            overflow-wrap: anywhere;
        }
        .mc-sqlite-review-pill.ready,
        .mc-sqlite-review-pill.approved {
            background: #dcfce7;
            color: #166534;
        }
        .mc-sqlite-review-pill.blocked,
        .mc-sqlite-review-pill.rejected {
            background: #fee2e2;
            color: #991b1b;
        }
        .mc-sqlite-review-pill.needs_review {
            background: #fef3c7;
            color: #92400e;
        }
        .mc-sqlite-review-list-label {
            margin: 0.65rem 0 0.35rem;
            color: #1f2328;
            font-size: 0.98rem;
            font-weight: 800;
        }
        .mc-sqlite-review-detail-title {
            margin: 0 0 0.2rem;
            color: #111827;
            font-size: 1.06rem;
            line-height: 1.35;
            font-weight: 820;
            text-wrap: balance;
        }
        .mc-sqlite-review-danger {
            margin: 0.65rem 0 0.55rem;
            padding: 0.62rem 0.72rem;
            border-radius: 12px;
            background: #fff7ed;
            color: #9a3412;
            border: 1px solid rgba(234, 88, 12, 0.18);
            font-size: 0.84rem;
            line-height: 1.45;
        }
        .mc-sqlite-review-form-note {
            margin: 0.18rem 0 0.62rem;
            color: #64748b;
            font-size: 0.82rem;
            line-height: 1.45;
        }
        .mc-sqlite-review-edit-subtitle {
            margin: 0.05rem 0 0.42rem;
            color: #312e81;
            font-size: 0.92rem;
            line-height: 1.35;
            font-weight: 820;
            letter-spacing: -0.01em;
        }
        body:has(.mc-sqlite-draft-entry-anchor) div[data-testid="stVerticalBlock"]:has(.mc-sqlite-review-left-anchor) {
            padding: 0.5rem 0.2rem 0.5rem 0;
            border: 0;
            border-radius: 14px;
            background: transparent;
            max-height: none;
            overflow: visible;
        }
        body:has(.mc-sqlite-draft-entry-anchor) div[data-testid="column"]:has(.mc-sqlite-review-left-anchor) {
            position: sticky;
            top: 0.75rem;
            align-self: flex-start;
            z-index: 7;
        }
        body:has(.mc-sqlite-draft-entry-anchor) div[data-testid="column"]:has(.mc-sqlite-review-left-anchor),
        body:has(.mc-sqlite-draft-entry-anchor) div[data-testid="column"]:has(.mc-sqlite-review-left-anchor) > div,
        body:has(.mc-sqlite-draft-entry-anchor) div[data-testid="column"]:has(.mc-sqlite-review-left-anchor) > div > div {
            overflow: visible !important;
            max-height: none !important;
        }
        body:has(.mc-sqlite-draft-entry-anchor) div[data-testid="stExpander"] {
            background: transparent !important;
            border: 1px solid rgba(109, 40, 217, 0.12) !important;
            border-radius: 12px !important;
            box-shadow: none !important;
            overflow: hidden !important;
        }
        body:has(.mc-sqlite-draft-entry-anchor) div[data-testid="stExpander"] summary {
            padding: 0.22rem 0.4rem !important;
            background: transparent !important;
        }
        body:has(.mc-sqlite-draft-entry-anchor) div[data-testid="stExpander"] summary:hover {
            background: rgba(109, 40, 217, 0.04) !important;
        }
        body:has(.mc-sqlite-draft-entry-anchor) div[data-testid="stExpander"] > div {
            background: transparent !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.subheader("🧾 草稿审核与确认入库")
    st.markdown(
        "<div class='mc-sqlite-review-shell'>审核区可以修改草稿状态；只有 ready/approved 草稿在用户勾选确认并输入 COMMIT 后，才会写入正式题库。</div>",
        unsafe_allow_html=True,
    )

    status_options = ["全部状态", "needs_review", "ready", "blocked", "approved", "committed", "rejected", "sample"]
    for key, value in [
        ("sqlite_draft_review_status_filter", "全部状态"),
        ("sqlite_draft_review_batch_filter", "全部批次"),
        ("sqlite_draft_review_page_size", 5),
        ("sqlite_draft_review_page", 1),
        ("sqlite_draft_review_page_select", 1),
        ("sqlite_draft_selected_id", ""),
    ]:
        st.session_state.setdefault(key, value)

    batches = list_import_batches(db_path, limit=50)
    batch_options = ["全部批次"] + [str(item.get("batch_id") or "") for item in batches if item.get("batch_id")]
    batch_labels = {"全部批次": "全部批次"}
    for item in batches:
        batch_id = str(item.get("batch_id") or "")
        if batch_id:
            batch_labels[batch_id] = f"{item.get('import_type') or 'batch'} · {item.get('draft_count') or 0} 条 · {batch_id}"
    if st.session_state.get("sqlite_draft_review_batch_filter") not in batch_options:
        st.session_state["sqlite_draft_review_batch_filter"] = "全部批次"
    if st.session_state.get("sqlite_draft_review_status_filter") not in status_options:
        st.session_state["sqlite_draft_review_status_filter"] = "全部状态"
    if st.session_state.get("sqlite_draft_review_page_size") not in [5, 10, 15, 20]:
        st.session_state["sqlite_draft_review_page_size"] = 5

    left_col, right_col = st.columns([0.94, 2.22], gap="medium")
    with left_col:
        st.markdown('<span class="mc-sqlite-review-left-anchor"></span>', unsafe_allow_html=True)
        st.markdown("##### 审核筛选")
        status_filter = st.selectbox(
            "草稿状态",
            status_options,
            key="sqlite_draft_review_status_filter",
            on_change=_sqlite_draft_review_reset_page,
        )
        batch_filter = st.selectbox(
            "导入批次",
            batch_options,
            key="sqlite_draft_review_batch_filter",
            format_func=lambda value: batch_labels.get(value, value),
            on_change=_sqlite_draft_review_reset_page,
        )
        page_size = st.selectbox(
            "每页显示",
            [5, 10, 15, 20],
            key="sqlite_draft_review_page_size",
            on_change=_sqlite_draft_review_reset_page,
        )

    batch_id = "" if batch_filter == "全部批次" else batch_filter
    review_status = "" if status_filter == "全部状态" else status_filter
    page_size_int = int(page_size or 5)
    total = count_draft_questions(db_path, batch_id=batch_id, review_status=review_status)
    page_count = (total + page_size_int - 1) // page_size_int if total else 0
    current_page = max(1, min(int(st.session_state.get("sqlite_draft_review_page", 1) or 1), max(1, page_count)))
    if current_page != st.session_state.get("sqlite_draft_review_page"):
        st.session_state["sqlite_draft_review_page"] = current_page
        st.session_state["sqlite_draft_review_page_select"] = current_page
    drafts = list_draft_questions(
        db_path,
        batch_id=batch_id,
        review_status=review_status,
        limit=page_size_int,
        offset=(current_page - 1) * page_size_int,
    )

    with left_col:
        st.markdown(
            f"""
            <div class="mc-db-result-summary">
                <strong>查找结果</strong>
                <span>找到 {total} 条草稿 · 第 {current_page if page_count else 0}/{page_count} 页 · 每页 {page_size_int} 条</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        page_options = list(range(1, page_count + 1)) if page_count else [1]
        if st.session_state.get("sqlite_draft_review_page_select") not in page_options:
            st.session_state["sqlite_draft_review_page_select"] = current_page if current_page in page_options else 1
        pager_left, pager_mid, pager_right = st.columns([0.95, 1.2, 0.95], gap="small")
        with pager_left:
            st.button(
                "上一页",
                key="sqlite_draft_review_prev_page",
                disabled=current_page <= 1,
                use_container_width=True,
                on_click=_sqlite_draft_review_change_page,
                args=(-1, page_count),
            )
        with pager_mid:
            st.selectbox(
                "页码",
                page_options,
                key="sqlite_draft_review_page_select",
                label_visibility="collapsed",
                format_func=lambda value: f"{value}/{page_count or 0}",
                on_change=_sqlite_draft_review_apply_page_select,
            )
        with pager_right:
            st.button(
                "下一页",
                key="sqlite_draft_review_next_page",
                disabled=not page_count or current_page >= page_count,
                use_container_width=True,
                on_click=_sqlite_draft_review_change_page,
                args=(1, page_count),
            )
        if drafts:
            st.markdown('<div class="mc-sqlite-review-list-label">选择草稿</div>', unsafe_allow_html=True)
            draft_options = [str(item.get("draft_id") or "") for item in drafts if item.get("draft_id")]
            if st.session_state.get("sqlite_draft_selected_id") not in draft_options:
                st.session_state["sqlite_draft_selected_id"] = draft_options[0]
            draft_label_map = {
                str(item.get("draft_id") or ""): (
                    f"{item.get('review_status') or ''} · {item.get('source_label') or item.get('draft_id')} · "
                    f"{str(item.get('stem_preview') or '')[:34]}"
                )
                for item in drafts
            }
            selected_draft_id = st.selectbox(
                "草稿",
                draft_options,
                key="sqlite_draft_selected_id",
                format_func=lambda value: draft_label_map.get(value, value),
                label_visibility="collapsed",
            )
        else:
            selected_draft_id = ""
            st.info("没有匹配的草稿。")

    with right_col:
        if not selected_draft_id:
            st.markdown('<div class="mc-db-browse-empty">请选择左侧草稿。</div>', unsafe_allow_html=True)
            return

        draft = get_draft_question(db_path, selected_draft_id)
        if not draft:
            st.error(f"草稿不存在：{selected_draft_id}")
            return
        status = str(draft.get("review_status") or "")
        action = str(draft.get("proposed_action") or "insert")
        target_question_id = str(draft.get("target_question_id") or "")
        st.markdown(f"<div class='mc-sqlite-review-detail-title'>{html.escape(draft.get('source_label') or selected_draft_id)}</div>", unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class="mc-sqlite-review-meta">
                <span class="mc-sqlite-review-pill {html.escape(status)}">{html.escape(status)}</span>
                <span class="mc-sqlite-review-pill">动作：{html.escape(action)}</span>
                <span class="mc-sqlite-review-pill">题型：{html.escape(str(draft.get('question_type_id') or '未设置'))}</span>
                <span class="mc-sqlite-review-pill">难度：{html.escape(str(draft.get('difficulty') if draft.get('difficulty') is not None else '未设置'))}</span>
                <span class="mc-sqlite-review-pill">附件草稿：{len(draft.get('assets') or [])}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if draft.get("review_reason"):
            st.caption(f"审核说明：{draft.get('review_reason')}")

        asset_reference_issues = collect_asset_reference_issues(
            draft,
            draft.get("assets") or [],
            project_root=APP_ROOT,
        )
        issue_count = (
            len(asset_reference_issues.get("missing_includegraphics") or [])
            + len(asset_reference_issues.get("unresolved_questionasset") or [])
            + len(asset_reference_issues.get("missing_asset_files") or [])
        )
        has_asset_reference_context = bool(
            asset_reference_issues.get("questionasset_refs")
            or asset_reference_issues.get("includegraphics_refs")
            or asset_reference_issues.get("missing_includegraphics")
            or asset_reference_issues.get("unresolved_questionasset")
            or asset_reference_issues.get("missing_asset_files")
            or asset_reference_issues.get("unreferenced_assets")
            or draft.get("assets")
        )
        if issue_count:
            st.warning(
                "图片引用检查发现 "
                f"{issue_count} 个需要处理的问题：缺失 includegraphics / 未登记 questionasset / 附件文件缺失。"
            )
        elif has_asset_reference_context:
            st.success("图片引用检查通过。")

        if has_asset_reference_context:
            with st.expander("图片引用检查详情", expanded=bool(issue_count)):
                st.write(
                    {
                        "includegraphics_refs": asset_reference_issues.get("includegraphics_refs") or [],
                        "questionasset_refs": asset_reference_issues.get("questionasset_refs") or [],
                        "missing_includegraphics": asset_reference_issues.get("missing_includegraphics") or [],
                        "unresolved_questionasset": asset_reference_issues.get("unresolved_questionasset") or [],
                        "missing_asset_files": asset_reference_issues.get("missing_asset_files") or [],
                        "unreferenced_assets": asset_reference_issues.get("unreferenced_assets") or [],
                    }
                )

        try:
            filter_options = list_question_filter_options(db_path)
        except Exception:
            filter_options = {"question_types": []}
        question_types = filter_options.get("question_types", []) or []
        type_options = [item.get("question_type_id") for item in question_types]
        type_labels = {item.get("question_type_id"): item.get("name") or item.get("code") or str(item.get("question_type_id")) for item in question_types}
        current_type = draft.get("question_type_id")
        if current_type not in type_options:
            type_options.append(current_type)
        type_labels.setdefault(current_type, "未设置" if current_type is None else str(current_type))

        extra = _sqlite_draft_extra_dict(draft.get("extra_json"))
        source_kind_options = ["试卷", "教材", "专题", "其他"]
        current_source_kind = extra.get("source_kind") or "其他"
        if current_source_kind not in source_kind_options:
            source_kind_options.append(current_source_kind)
        paper_series_options = _editable_paper_type_options()
        current_paper_series = extra.get("paper_series") or "G"
        if current_paper_series not in paper_series_options:
            paper_series_options.append(current_paper_series)
        difficulty_options = ["未设置", 1, 2, 3, 4, 5]
        current_difficulty = draft.get("difficulty") if draft.get("difficulty") is not None else "未设置"
        if current_difficulty not in difficulty_options:
            difficulty_options.append(current_difficulty)

        draft_edit_values = {
            "source_label": draft.get("source_label") or "",
            "proposed_action": action if action in ["insert", "update", "skip"] else "insert",
            "target_question_id": target_question_id,
            "source_kind": current_source_kind,
            "detected_year": extra.get("detected_year") or "",
            "paper_series": current_paper_series,
            "detected_source": extra.get("detected_source") or "",
            "detected_question_number": extra.get("detected_question_number") or "",
            "sub_number": extra.get("sub_number") or "",
            "detected_topic": extra.get("detected_topic") or "",
            "question_type_id": current_type,
            "difficulty": current_difficulty,
            "official_flag": bool(draft.get("official_flag")),
            "stem_tex": draft.get("stem_tex") or "",
            "choices_text": _sqlite_draft_json_list_text(draft.get("choices_json")),
            "answer_tex": draft.get("answer_tex") or "",
            "solution_tex": draft.get("solution_tex") or "",
            "tags_text": _sqlite_draft_json_list_text(draft.get("tags_json"), separator="，"),
            "note": draft.get("note") or "",
        }
        _sqlite_draft_prepare_edit_form_state(selected_draft_id, draft_edit_values)
        with st.expander("入库前字段校订", expanded=False):
            if status == "committed":
                st.info("该草稿已经入库，字段校订已锁定。")
            else:
                last_update = st.session_state.get("sqlite_draft_review_last_update") or {}
                if last_update.get("draft_id") == selected_draft_id:
                    st.success(f"草稿已更新：{', '.join(last_update.get('changed_fields') or []) or '字段无变化'}")
                st.markdown(
                    "<div class='mc-sqlite-review-form-note'>只校订入库必要字段；正式写库仍需要下方审核状态与 COMMIT 二次确认。</div>",
                    unsafe_allow_html=True,
                )
                with st.form(key=f"sqlite_draft_review_edit_form_{_sqlite_draft_edit_hash(selected_draft_id)}", clear_on_submit=False):
                    meta_edit_col, tex_edit_col = st.columns([0.92, 1.48], gap="large")
                    with meta_edit_col:
                        st.markdown("<div class='mc-sqlite-review-edit-subtitle'>来源与入库动作</div>", unsafe_allow_html=True)
                        st.text_input("来源标签", key=_sqlite_draft_edit_field_key(selected_draft_id, "source_label"))
                        action_col, target_col = st.columns([0.74, 1.08], gap="small")
                        with action_col:
                            st.selectbox("动作", ["insert", "update", "skip"], key=_sqlite_draft_edit_field_key(selected_draft_id, "proposed_action"))
                        with target_col:
                            st.text_input("目标题号", key=_sqlite_draft_edit_field_key(selected_draft_id, "target_question_id"), placeholder="update 时填写")

                        source_col, year_col = st.columns([1.1, 0.8], gap="small")
                        with source_col:
                            st.selectbox("来源类型", source_kind_options, key=_sqlite_draft_edit_field_key(selected_draft_id, "source_kind"))
                        with year_col:
                            st.text_input("年份/册次", key=_sqlite_draft_edit_field_key(selected_draft_id, "detected_year"))
                        st.selectbox(
                            "卷别代码",
                            paper_series_options,
                            key=_sqlite_draft_edit_field_key(selected_draft_id, "paper_series"),
                            format_func=lambda value: f"{value} ({PAPER_TYPES.get(value, value)})",
                        )

                        st.text_input("试卷/教材/专题名称", key=_sqlite_draft_edit_field_key(selected_draft_id, "detected_source"))
                        number_col, sub_col = st.columns([1, 0.78], gap="small")
                        with number_col:
                            st.text_input("题号/页码", key=_sqlite_draft_edit_field_key(selected_draft_id, "detected_question_number"))
                        with sub_col:
                            st.text_input("小题", key=_sqlite_draft_edit_field_key(selected_draft_id, "sub_number"))
                        st.text_input("知识板块/栏目", key=_sqlite_draft_edit_field_key(selected_draft_id, "detected_topic"))

                        type_col, diff_col = st.columns([1.18, 0.82], gap="small")
                        with type_col:
                            st.selectbox(
                                "题型",
                                type_options,
                                format_func=lambda value: type_labels.get(value, "未设置"),
                                key=_sqlite_draft_edit_field_key(selected_draft_id, "question_type_id"),
                            )
                        with diff_col:
                            st.selectbox("难度", difficulty_options, key=_sqlite_draft_edit_field_key(selected_draft_id, "difficulty"))
                        st.checkbox("官方来源", key=_sqlite_draft_edit_field_key(selected_draft_id, "official_flag"))
                        st.text_input("标签", key=_sqlite_draft_edit_field_key(selected_draft_id, "tags_text"), help="支持逗号或换行分隔。")
                        st.text_area("备注", key=_sqlite_draft_edit_field_key(selected_draft_id, "note"), height=78)

                    with tex_edit_col:
                        st.markdown("<div class='mc-sqlite-review-edit-subtitle'>TeX 内容</div>", unsafe_allow_html=True)
                        st.text_area("题干 TeX", key=_sqlite_draft_edit_field_key(selected_draft_id, "stem_tex"), height=156)
                        _render_structured_choice_editor(
                            _sqlite_draft_review_choice_editor_scope_key(selected_draft_id),
                            draft_edit_values.get("choices_text", ""),
                            show_step_buttons=False,
                        )
                        answer_col, solution_col = st.columns([0.78, 1.22], gap="small")
                        with answer_col:
                            st.text_area("答案 TeX", key=_sqlite_draft_edit_field_key(selected_draft_id, "answer_tex"), height=118)
                        with solution_col:
                            st.text_area("解析 TeX", key=_sqlite_draft_edit_field_key(selected_draft_id, "solution_tex"), height=118)
                        draft_edit_submitted = st.form_submit_button("保存草稿字段", type="primary", use_container_width=True)

                if draft_edit_submitted:
                    form_values = _sqlite_draft_collect_edit_form_values(selected_draft_id)
                    difficulty_value = form_values.get("difficulty")
                    if difficulty_value == "未设置":
                        difficulty_value = None
                    next_extra = dict(extra)
                    next_extra.update(
                        {
                            "source_kind": form_values.get("source_kind") or "",
                            "detected_year": form_values.get("detected_year") or "",
                            "paper_series": form_values.get("paper_series") or "",
                            "detected_source": form_values.get("detected_source") or "",
                            "detected_question_number": form_values.get("detected_question_number") or "",
                            "sub_number": form_values.get("sub_number") or "",
                            "detected_topic": form_values.get("detected_topic") or "",
                        }
                    )
                    try:
                        update_result = update_draft_question_fields(
                            db_path,
                            selected_draft_id,
                            {
                                "source_label": form_values.get("source_label") or "",
                                "proposed_action": form_values.get("proposed_action") or "insert",
                                "target_question_id": form_values.get("target_question_id") or "",
                                "question_type_id": form_values.get("question_type_id"),
                                "stem_tex": form_values.get("stem_tex") or "",
                                "choices": _db_preview_split_choice_lines(form_values.get("choices_text") or ""),
                                "answer_tex": form_values.get("answer_tex") or "",
                                "solution_tex": form_values.get("solution_tex") or "",
                                "difficulty": difficulty_value,
                                "tags": _sqlite_draft_split_text_list(form_values.get("tags_text") or ""),
                                "note": form_values.get("note") or "",
                                "official_flag": form_values.get("official_flag"),
                                "raw_source_text": form_values.get("stem_tex") or "",
                                "extra": next_extra,
                            },
                            operator="streamlit_ui",
                        )
                        st.session_state["sqlite_draft_review_last_update"] = update_result
                        st.toast("草稿字段已保存", icon="✅")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"保存草稿字段失败：{exc}")

        state_col, commit_col = st.columns([1.05, 1], gap="large")
        with state_col:
            st.markdown("##### 审核状态")
            status_edit_key = f"sqlite_draft_review_status_edit_{_question_key('draft_status', selected_draft_id)}"
            reason_edit_key = f"sqlite_draft_review_reason_edit_{_question_key('draft_reason', selected_draft_id)}"
            allowed_status = ["needs_review", "ready", "blocked", "approved", "rejected"]
            if st.session_state.get(status_edit_key) not in allowed_status:
                st.session_state[status_edit_key] = status if status in allowed_status else "needs_review"
            if reason_edit_key not in st.session_state:
                st.session_state[reason_edit_key] = draft.get("review_reason") or ""
            st.selectbox("新状态", allowed_status, key=status_edit_key)
            st.text_area("审核说明", key=reason_edit_key, height=80)
            if st.button("保存审核状态", key=f"sqlite_draft_save_status_{_question_key('draft_save', selected_draft_id)}", use_container_width=True):
                try:
                    update_draft_review_status(
                        db_path,
                        selected_draft_id,
                        st.session_state.get(status_edit_key),
                        st.session_state.get(reason_edit_key, ""),
                    )
                    st.toast("草稿状态已保存", icon="✅")
                    st.rerun()
                except Exception as exc:
                    st.error(f"保存审核状态失败：{exc}")

        with commit_col:
            st.markdown("##### 确认入库")
            st.markdown(
                "<div class='mc-sqlite-review-danger'>该操作会写入正式 SQLite 题目表、关系表和修订记录；不会修改旧 .tex 文件。</div>",
                unsafe_allow_html=True,
            )
            ready_for_commit = status in {"ready", "approved"}
            confirm_key = f"sqlite_draft_commit_confirm_{_question_key('draft_commit_confirm', selected_draft_id)}"
            text_key = f"sqlite_draft_commit_text_{_question_key('draft_commit_text', selected_draft_id)}"
            st.checkbox("我确认写入正式题库", key=confirm_key, disabled=not ready_for_commit)
            st.text_input("输入 COMMIT 确认", key=text_key, disabled=not ready_for_commit)
            can_commit = ready_for_commit and st.session_state.get(confirm_key) and st.session_state.get(text_key) == "COMMIT"
            if st.button(
                "提交为正式题",
                key=f"sqlite_draft_commit_{_question_key('draft_commit', selected_draft_id)}",
                type="primary",
                disabled=not can_commit,
                use_container_width=True,
            ):
                try:
                    result = commit_draft_to_question(db_path, selected_draft_id, operator="streamlit_ui")
                    _db_preview_clear_question_payload_cache()
                    st.session_state["sqlite_draft_review_last_commit"] = result
                    st.toast(result.get("message", "草稿已提交"), icon="✅")
                    st.rerun()
                except Exception as exc:
                    st.error(f"提交失败：{exc}")
            last_commit = st.session_state.get("sqlite_draft_review_last_commit") or {}
            if last_commit.get("draft_id") == selected_draft_id:
                st.success(last_commit.get("message", "已提交"))
                st.caption(f"正式题号：{last_commit.get('question_id')} · revision：{last_commit.get('revision_id')}")

        st.markdown("##### 草稿内容")
        draft_question = draft_to_preview_question(draft)
        draft_tex = question_to_legacy_tex(draft_question)
        if action == "update" and target_question_id:
            target_question = get_question(db_path, target_question_id)
            compare_left, compare_right = st.columns(2, gap="large")
            with compare_left:
                st.markdown(f"**目标题 {target_question_id}**")
                if target_question:
                    st.code(question_to_legacy_tex(target_question), language="latex")
                else:
                    st.warning("目标题不存在。")
            with compare_right:
                st.markdown("**草稿版本**")
                st.code(draft_tex, language="latex")
        else:
            code_col, preview_col = st.columns([0.98, 1.02], gap="medium")
            with code_col:
                st.markdown("**草稿 TeX**")
                st.code(draft_tex, language="latex")
            with preview_col:
                st.markdown("**草稿渲染**")
                render_question_preview(draft_tex, show_title=False)

        with st.expander("图片/附件草稿管理", expanded=False):
            asset_role_options = ["problem", "answer", "solution", "source", "thumbnail"]
            asset_status_options = ["needs_review", "ready", "blocked", "approved", "rejected"]
            st.caption("资源按顺序字段从小到大排列；命名会保留为可解析别名，默认占位符仍优先稳定文件名主干；说明用于补充页码、裁剪、用途等信息。")
            if status == "committed":
                st.info("该草稿已经入库，附件草稿只读。")

            assets = draft.get("assets") or []
            if not assets:
                st.caption("当前草稿暂无图片/附件。")
            for asset in assets:
                draft_asset_id = str(asset.get("draft_asset_id") or "")
                if not draft_asset_id:
                    continue
                st.markdown(f"**{asset.get('role') or 'problem'} · {asset.get('original_file_name') or asset.get('source_path') or draft_asset_id}**")
                if status == "committed":
                    summary_bits = [
                        str(asset.get("review_status") or "needs_review"),
                        str(asset.get("source_path") or ""),
                        str(asset.get("planned_file_path") or ""),
                        str(asset.get("caption") or ""),
                        str(asset.get("note") or ""),
                    ]
                    st.caption(" · ".join(bit for bit in summary_bits if bit))
                    continue
                role_options = list(asset_role_options)
                if asset.get("role") not in role_options:
                    role_options.append(asset.get("role"))
                status_options_for_asset = list(asset_status_options)
                if asset.get("review_status") not in status_options_for_asset:
                    status_options_for_asset.append(asset.get("review_status"))
                with st.form(key=f"sqlite_draft_asset_form_{_question_key('draft_asset_form', draft_asset_id)}", clear_on_submit=False):
                    role_col, status_col, order_col = st.columns([0.85, 0.9, 0.55], gap="small")
                    with role_col:
                        st.selectbox(
                            "位置",
                            role_options,
                            index=role_options.index(asset.get("role")) if asset.get("role") in role_options else 0,
                            key=_sqlite_draft_asset_field_key(draft_asset_id, "role"),
                        )
                    with status_col:
                        st.selectbox(
                            "状态",
                            status_options_for_asset,
                            index=status_options_for_asset.index(asset.get("review_status")) if asset.get("review_status") in status_options_for_asset else 0,
                            key=_sqlite_draft_asset_field_key(draft_asset_id, "review_status"),
                        )
                    with order_col:
                        st.number_input(
                            "序号",
                            min_value=1,
                            step=1,
                            value=int(asset.get("sort_order") or 1),
                            key=_sqlite_draft_asset_field_key(draft_asset_id, "sort_order"),
                        )
                    path_col, planned_col = st.columns([1.45, 1.05], gap="small")
                    with path_col:
                        st.text_input(
                            "源文件路径",
                            value=asset.get("source_path") or "",
                            key=_sqlite_draft_asset_field_key(draft_asset_id, "source_path"),
                        )
                    with planned_col:
                        st.text_input(
                            "计划路径",
                            value=asset.get("planned_file_path") or "",
                            key=_sqlite_draft_asset_field_key(draft_asset_id, "planned_file_path"),
                        )
                    name_col, note_col = st.columns([1.05, 1.4], gap="small")
                    with name_col:
                        st.text_input(
                            "命名",
                            value=asset.get("caption") or "",
                            key=_sqlite_draft_asset_field_key(draft_asset_id, "caption"),
                        )
                    with note_col:
                        st.text_area(
                            "说明",
                            value=asset.get("note") or "",
                            height=60,
                            key=_sqlite_draft_asset_field_key(draft_asset_id, "note"),
                        )
                    save_asset_col, remove_asset_col = st.columns(2, gap="small")
                    with save_asset_col:
                        save_asset = st.form_submit_button("保存资源", use_container_width=True)
                    with remove_asset_col:
                        remove_asset = st.form_submit_button("移除资源", use_container_width=True)
                if save_asset:
                    try:
                        update_draft_asset_fields(
                            db_path,
                            draft_asset_id,
                            {
                                "role": st.session_state.get(_sqlite_draft_asset_field_key(draft_asset_id, "role")),
                                "review_status": st.session_state.get(_sqlite_draft_asset_field_key(draft_asset_id, "review_status")),
                                "sort_order": st.session_state.get(_sqlite_draft_asset_field_key(draft_asset_id, "sort_order")),
                                "source_path": st.session_state.get(_sqlite_draft_asset_field_key(draft_asset_id, "source_path")),
                                "planned_file_path": st.session_state.get(_sqlite_draft_asset_field_key(draft_asset_id, "planned_file_path")),
                                "caption": (
                                    st.session_state.get(_sqlite_draft_asset_field_key(draft_asset_id, "caption"))
                                    or _sqlite_asset_caption_from_source_path(
                                        st.session_state.get(_sqlite_draft_asset_field_key(draft_asset_id, "source_path"))
                                    )
                                ),
                                "note": st.session_state.get(_sqlite_draft_asset_field_key(draft_asset_id, "note")),
                            },
                        )
                        st.toast("草稿资源已保存", icon="✅")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"保存草稿资源失败：{exc}")
                if remove_asset:
                    try:
                        delete_draft_asset(db_path, draft_asset_id)
                        st.toast("草稿资源已移除；源文件未删除", icon="✅")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"移除草稿资源失败：{exc}")

            if status != "committed":
                st.markdown("**新增图片/附件草稿**")
                with st.form(key=f"sqlite_draft_asset_add_form_{_sqlite_draft_edit_hash(selected_draft_id)}", clear_on_submit=False):
                    add_role_col, add_status_col, add_order_col = st.columns([0.85, 0.9, 0.55], gap="small")
                    with add_role_col:
                        add_role = st.selectbox("位置", asset_role_options, key=_sqlite_draft_asset_field_key(selected_draft_id, "add_role"))
                    with add_status_col:
                        add_status = st.selectbox("状态", asset_status_options, key=_sqlite_draft_asset_field_key(selected_draft_id, "add_review_status"))
                    with add_order_col:
                        add_sort_order = st.number_input(
                            "序号",
                            min_value=0,
                            step=1,
                            value=0,
                            help="填 0 时自动排到最后。",
                            key=_sqlite_draft_asset_field_key(selected_draft_id, "add_sort_order"),
                        )
                    add_path_col, add_planned_col = st.columns([1.45, 1.05], gap="small")
                    with add_path_col:
                        add_source_path = st.text_input("源文件路径", key=_sqlite_draft_asset_field_key(selected_draft_id, "add_source_path"))
                    with add_planned_col:
                        st.text_input("计划路径", key=_sqlite_draft_asset_field_key(selected_draft_id, "add_planned_file_path"))
                    add_name_col, add_note_col = st.columns([1.05, 1.4], gap="small")
                    with add_name_col:
                        add_caption = st.text_input("命名", key=_sqlite_draft_asset_field_key(selected_draft_id, "add_caption"))
                    with add_note_col:
                        add_note = st.text_area("说明", height=60, key=_sqlite_draft_asset_field_key(selected_draft_id, "add_note"))
                    st.caption("命名会被保留为 `\\questionasset{...}` 的可解析别名；若留空，则会回落到文件名主干。")
                    add_asset_submitted = st.form_submit_button("添加资源草稿", type="primary", use_container_width=True)
                if add_asset_submitted:
                    try:
                        add_draft_asset(
                            db_path,
                            selected_draft_id,
                            {
                                "role": add_role,
                                "review_status": add_status,
                                "sort_order": add_sort_order,
                                "source_path": add_source_path,
                                "planned_file_path": st.session_state.get(_sqlite_draft_asset_field_key(selected_draft_id, "add_planned_file_path")) or "",
                                "caption": add_caption or _sqlite_asset_caption_from_source_path(add_source_path),
                                "note": add_note,
                            },
                        )
                        st.toast("资源草稿已添加", icon="✅")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"添加资源草稿失败：{exc}")


# ================= 页面：新题录入 =================
def page_entry(force_single_mode: bool = False, cloze_mode: bool = False):
    st.markdown('<span id="mc-entry-page-anchor"></span>', unsafe_allow_html=True)
    st.header("🧩 挖空题生成" if cloze_mode else "📝 录入新题")
    
    # 初始化 Session State
    if "entry_year" not in st.session_state: st.session_state["entry_year"] = "2024"
    if "entry_p_type" not in st.session_state: st.session_state["entry_p_type"] = "G"
    if "entry_subject_multi" not in st.session_state: st.session_state["entry_subject_multi"] = []
    if "entry_number" not in st.session_state: st.session_state["entry_number"] = "1"
    if "entry_paper_name" not in st.session_state: st.session_state["entry_paper_name"] = "新高考I卷"
    if "entry_content" not in st.session_state: st.session_state["entry_content"] = ""
    if "batch_content" not in st.session_state: st.session_state["batch_content"] = ""
    if "entry_subject_user_locked" not in st.session_state: st.session_state["entry_subject_user_locked"] = False

    if force_single_mode:
        mode = "单题录入"
        if cloze_mode:
            st.session_state["entry_p_type"] = "WK"
            cloze_options = ["简单定义基础计算挖空", "基础推导与题意读取提炼挖空", "关键思路抽象推导挖空"]
            if st.session_state.get("cloze_generation_type") not in cloze_options:
                st.session_state["cloze_generation_type"] = cloze_options[0]
            st.markdown("""
            <style>
            div[class*="st-key-btn_open_cloze_library"] button {
                min-height: 48px !important;
                font-size: 16px !important;
                font-weight: 700 !important;
                white-space: nowrap !important;
            }
            </style>
            """, unsafe_allow_html=True)
            cloze_mode_col, cloze_library_col = st.columns([3, 1.4])
            with cloze_mode_col:
                st.radio("挖空要求", cloze_options, key="cloze_generation_type", horizontal=True)
            with cloze_library_col:
                if st.button("📚 挖空题库", key="btn_open_cloze_library", use_container_width=True):
                    st.session_state["tools_subpage"] = "cloze_library"
                    st.session_state["adv_search_active"] = False
                    for key in ("paper_type", "paper_year", "paper_name", "selected_q_idx"):
                        st.session_state.pop(key, None)
                    _clear_advanced_search_result_cache()
                    st.rerun()
            render_cloze_source_picker()
            st.caption("选择普通题库中的原题后生成挖空版本；生成结果可在下方继续人工修改、预览与保存。")
    else:
        mode = st.radio("录入模式", ["单题录入", "批量试题录入", "同卷试题录入"], horizontal=True)
    
    if mode == "单题录入":
        col_left, col_mid, col_right = st.columns([1.5, 2, 2])
    else:
        col_left, col_mid, col_right = st.columns([1.5, 4, 0.01])
    
    # === 左侧：AI 识别区 ===
    with col_left:
        st.subheader("🖼️ AI 图片 / PDF 识别")
        inject_custom_css() # 注入样式
        
        # 确保 Image 模块可用
        try:
            from PIL import Image
        except ImportError:
            st.error("缺少 PIL 库，请安装 pillow")
            return

        # 初始化上传队列
        if "ocr_queue" not in st.session_state:
            st.session_state["ocr_queue"] = []
        if "pdf_queue" not in st.session_state:
            st.session_state["pdf_queue"] = []
        if "entry_upload_prev_files" not in st.session_state:
            st.session_state["entry_upload_prev_files"] = []

        max_pdf_files = 3
        max_image_files = 5
        pdf_ocr_batch_size = 2

        def _upload_file_id(file_obj):
            return f"{file_obj.name}_{file_obj.size}"

        def _format_upload_size(size_bytes):
            if size_bytes >= 1024 * 1024:
                return f"{size_bytes / (1024 * 1024):.2f} MB"
            return f"{size_bytes / 1024:.1f} KB"

        def _get_pdf_page_count(pdf_bytes):
            try:
                import fitz
                with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf_doc:
                    return pdf_doc.page_count
            except Exception:
                return None

        # 1. 统一文件上传区域：支持 PDF 与图片
        st.markdown("##### 添加文件")
        uploaded_files = st.file_uploader(
            "📁 上传图片或 PDF",
            type=["pdf", "png", "jpg", "jpeg"],
            key="entry_file_uploader",
            accept_multiple_files=True,
            help="拖拽文件到此处或点击选择。图片最多 5 张，PDF 最多 3 个。"
        )
        st.caption("支持 PDF、PNG、JPG、JPEG；图片最多 5 张，PDF 最多 3 个。")

        if uploaded_files:
            current_file_ids = [_upload_file_id(f) for f in uploaded_files]
            prev_file_ids = st.session_state["entry_upload_prev_files"]
            queued_pdf_ids = {item["id"] for item in st.session_state["pdf_queue"]}
            ignored_pdf_count = 0
            ignored_image_count = 0
            added_pdf_count = 0
            added_image_count = 0

            for uploaded_file in uploaded_files:
                file_id = _upload_file_id(uploaded_file)
                if file_id in prev_file_ids:
                    continue

                extension = os.path.splitext(uploaded_file.name)[1].lower()
                if extension == ".pdf":
                    if file_id in queued_pdf_ids or len(st.session_state["pdf_queue"]) >= max_pdf_files:
                        ignored_pdf_count += 1
                        continue
                    pdf_bytes = uploaded_file.getvalue()
                    page_count = _get_pdf_page_count(pdf_bytes)
                    st.session_state["pdf_queue"].append({
                        "id": file_id,
                        "name": uploaded_file.name,
                        "size": uploaded_file.size,
                        "bytes": pdf_bytes,
                        "page_count": page_count,
                        "page_start": 1 if page_count else None,
                        "page_end": page_count,
                        "page_range": f"1-{page_count}" if page_count else "",
                    })
                    queued_pdf_ids.add(file_id)
                    added_pdf_count += 1
                else:
                    if len(st.session_state["ocr_queue"]) >= max_image_files:
                        ignored_image_count += 1
                        continue
                    try:
                        img = Image.open(uploaded_file)
                        img.load()
                        st.session_state["ocr_queue"].append(img.copy())
                        added_image_count += 1
                    except Exception as e:
                        st.error(f"图片 {uploaded_file.name} 读取失败: {e}")

            st.session_state["entry_upload_prev_files"] = current_file_ids
            if added_pdf_count or added_image_count:
                added_parts = []
                if added_image_count:
                    added_parts.append(f"{added_image_count} 张图片")
                if added_pdf_count:
                    added_parts.append(f"{added_pdf_count} 个 PDF")
                st.toast(f"已添加 {'、'.join(added_parts)}", icon="✅")
            if ignored_image_count:
                st.warning(f"图片最多上传 {max_image_files} 张，已忽略 {ignored_image_count} 张图片。")
            if ignored_pdf_count:
                st.warning(f"PDF 最多上传 {max_pdf_files} 个，已忽略 {ignored_pdf_count} 个文件。")
        else:
            st.session_state["entry_upload_prev_files"] = []

        if st.session_state["pdf_queue"]:
            c_pdf_header, c_pdf_clear = st.columns([3, 1])
            with c_pdf_header:
                st.write(f"当前 PDF: {len(st.session_state['pdf_queue'])}/{max_pdf_files} 个")
            with c_pdf_clear:
                if st.button("🗑️ 清空", key="clear_pdf_queue", use_container_width=True):
                    st.session_state["pdf_queue"] = []
                    st.rerun()

            for i, pdf_item in enumerate(st.session_state["pdf_queue"]):
                st.caption(f"{i + 1}. {pdf_item['name']} · {_format_upload_size(pdf_item['size'])}")
                page_count = pdf_item.get("page_count")
                if page_count:
                    default_start = pdf_item.get("page_start") or 1
                    default_end = pdf_item.get("page_end") or page_count
                    c_range_label, c_page_start, c_range_separator, c_page_end, c_page_count, c_pdf_del = st.columns([1.5, 1, 0.3, 1, 0.7, 0.8])
                    with c_range_label:
                        st.caption("扫描页面范围")
                    with c_page_start:
                        page_start = st.number_input(
                            "起始页",
                            min_value=1,
                            max_value=page_count,
                            value=min(max(default_start, 1), page_count),
                            step=1,
                            key=f"pdf_page_start_{pdf_item['id']}",
                            label_visibility="collapsed",
                        )
                    with c_range_separator:
                        st.markdown(
                            "<div style='height: 2.35rem; display: flex; align-items: center; justify-content: center; font-size: 18px; color: #4b5563;'>—</div>",
                            unsafe_allow_html=True,
                        )
                    with c_page_end:
                        page_end = st.number_input(
                            "结束页",
                            min_value=1,
                            max_value=page_count,
                            value=min(max(default_end, 1), page_count),
                            step=1,
                            key=f"pdf_page_end_{pdf_item['id']}",
                            label_visibility="collapsed",
                        )
                    with c_page_count:
                        st.caption(f"最大 {page_count} 页")
                    with c_pdf_del:
                        delete_pdf = st.button("删除", key=f"del_pdf_{i}", use_container_width=True)
                    if page_start > page_end:
                        st.warning("起始页不能大于结束页。")
                    else:
                        pdf_item["page_start"] = page_start
                        pdf_item["page_end"] = page_end
                        pdf_item["page_range"] = f"{page_start}-{page_end}"
                else:
                    st.caption("未能读取 PDF 页数，后续可重新上传该文件。")
                    delete_pdf = st.button("删除", key=f"del_pdf_{i}")

                if delete_pdf:
                    st.session_state["pdf_queue"].pop(i)
                    st.rerun()

        c_clipboard, _ = st.columns([1, 1])
        with c_clipboard:
            def _read_clipboard_image_candidates():
                if not ImageGrab:
                    st.error("缺少 PIL 库")
                    return []
                clipboard_content = ImageGrab.grabclipboard()
                candidates = []
                if isinstance(clipboard_content, Image.Image):
                    candidates.append({"label": "剪贴板图片 1", "image": clipboard_content.copy()})
                elif isinstance(clipboard_content, list):
                    for item in clipboard_content:
                        if isinstance(item, str) and os.path.isfile(item):
                            try:
                                img = Image.open(item)
                                img.load()
                                candidates.append({"label": os.path.basename(item), "image": img.copy()})
                            except Exception:
                                pass
                return candidates

            def _append_clipboard_first_image():
                try:
                    candidates = _read_clipboard_image_candidates()
                except Exception as e:
                    st.error(f"剪贴板读取失败: {e}")
                    return
                if not candidates:
                    st.warning("剪贴板中没有图片或支持的图片文件")
                    return
                if len(st.session_state["ocr_queue"]) >= max_image_files:
                    st.warning(f"图片最多上传 {max_image_files} 张。")
                    return
                st.session_state["ocr_queue"].append(candidates[0]["image"])
                st.toast("已从剪贴板添加 1 张图片", icon="✅")
                st.rerun()

            if st.button("📋 粘贴剪贴板首张图片", use_container_width=True):
                _append_clipboard_first_image()

        st.divider()

        # 3. 图片队列展示与管理
        if st.session_state["ocr_queue"]:
            c_q_header, c_q_clear = st.columns([3, 1])
            with c_q_header:
                st.write(f"当前队列: {len(st.session_state['ocr_queue'])}/5 张")
            with c_q_clear:
                if st.button("🗑️ 清空", key="clear_queue", use_container_width=True):
                    st.session_state["ocr_queue"] = []
                    st.rerun()
            
            for i, img in enumerate(st.session_state["ocr_queue"]):
                st.caption(f"图片 {i+1}")
                st.image(img, width=190)
                # 当前区域已位于 col_left 中，操作按钮只再嵌套一层列。
                c_btn1, c_btn2, c_btn3, c_btn4 = st.columns(4)
                with c_btn1:
                    if i > 0:
                        if st.button("⬆️", key=f"mv_up_{i}", help="前移"):
                            st.session_state["ocr_queue"][i], st.session_state["ocr_queue"][i-1] = st.session_state["ocr_queue"][i-1], st.session_state["ocr_queue"][i]
                            st.rerun()
                with c_btn2:
                    if i < len(st.session_state["ocr_queue"]) - 1:
                        if st.button("⬇️", key=f"mv_down_{i}", help="后移"):
                            st.session_state["ocr_queue"][i], st.session_state["ocr_queue"][i+1] = st.session_state["ocr_queue"][i+1], st.session_state["ocr_queue"][i]
                            st.rerun()
                with c_btn3:
                    if st.button("🗑️", key=f"del_{i}", help="删除"):
                        st.session_state["ocr_queue"].pop(i)
                        st.rerun()
                with c_btn4:
                    if st.button("🔍", key=f"zoom_{i}", help="放大"):
                        zoom_image(img)
            
        if st.session_state["ocr_queue"] or st.session_state["pdf_queue"]:
            st.divider()

            image_count = len(st.session_state["ocr_queue"])
            pdf_page_count = sum(
                max(0, (item.get("page_end") or 0) - (item.get("page_start") or 0) + 1)
                for item in st.session_state["pdf_queue"]
                if item.get("page_count") and (item.get("page_start") or 0) <= (item.get("page_end") or 0)
            )
            action_label = "🚀 识别已选图片和 PDF 页面" if image_count and pdf_page_count else (
                "🚀 识别所有图片" if image_count else "🚀 识别所选 PDF 页面"
            )
            batch_hint = "单题模式会合并识别；批量模式每 2 页分批识别。"
            st.caption(f"本次将识别 {image_count} 张图片、{pdf_page_count} 页 PDF；{batch_hint}")

            if st.button(action_label, type="primary", use_container_width=True):
                total_source_pages = image_count + pdf_page_count
                if mode == "单题录入" and total_source_pages > max_image_files:
                    st.warning("单题录入一次最多识别 5 张图片或页面；多页 PDF 请切换到“批量试题录入”或“同卷试题录入”。")
                    st.stop()

                ocr_batches = []
                batch_labels = []
                single_mode_images = []

                if st.session_state["ocr_queue"]:
                    if mode == "单题录入":
                        single_mode_images.extend(st.session_state["ocr_queue"])
                    else:
                        ocr_batches.append(list(st.session_state["ocr_queue"]))
                        batch_labels.append(f"图片 1-{image_count}")

                for pdf_item in st.session_state["pdf_queue"]:
                    page_start = pdf_item.get("page_start")
                    page_end = pdf_item.get("page_end")
                    if not pdf_item.get("page_count"):
                        st.error(f"PDF {pdf_item['name']} 无法读取页数，不能识别。")
                        continue
                    if not page_start or not page_end or page_start > page_end:
                        st.error(f"PDF {pdf_item['name']} 的扫描页面范围无效。")
                        continue

                    selected_pages = range(page_start, page_end + 1)
                    with st.spinner(f"正在渲染 PDF：{pdf_item['name']}（第 {page_start}-{page_end} 页）..."):
                        pdf_images, render_error = render_pdf_pages_to_images(pdf_item["bytes"], selected_pages)
                    if render_error:
                        st.error(f"PDF {pdf_item['name']}：{render_error}")
                        continue

                    if mode == "单题录入":
                        single_mode_images.extend(pdf_images)
                    else:
                        for offset in range(0, len(pdf_images), pdf_ocr_batch_size):
                            page_batch = pdf_images[offset:offset + pdf_ocr_batch_size]
                            first_page = page_start + offset
                            last_page = first_page + len(page_batch) - 1
                            ocr_batches.append(page_batch)
                            batch_labels.append(f"{pdf_item['name']} 第 {first_page}-{last_page} 页")

                if mode == "单题录入" and single_mode_images:
                    ocr_batches.append(single_mode_images)
                    batch_labels.append(f"已选图片与 PDF 页面（共 {len(single_mode_images)} 页/张）")

                if not ocr_batches:
                    st.warning("没有可识别的图片或有效 PDF 页面。")
                else:
                    ocr_results = []
                    progress = st.progress(0)
                    status = st.empty()
                    total_batches = len(ocr_batches)

                    for batch_index, (image_batch, batch_label) in enumerate(zip(ocr_batches, batch_labels), start=1):
                        status.text(f"正在识别 {batch_label}（{batch_index}/{total_batches}）")
                        result = ocr_image_to_latex(
                            images=image_batch,
                            max_image_size=1600,
                            max_tokens=8192,
                            spinner_text=f"🤖 AI 正在识别 {batch_label}...",
                        )
                        if result.startswith("❌"):
                            status.empty()
                            progress.empty()
                            st.error(f"{batch_label} 识别失败：{result}")
                            break
                        ocr_results.append(result.strip())
                        progress.progress(batch_index / total_batches)
                    else:
                        status.empty()
                        progress.empty()
                        process_ocr_result("\n\n".join(ocr_results), mode)
        else:
            st.info("请添加图片或 PDF 进行识别")

        # 增加手动中断提示
        st.caption("提示: 如果 AI 响应时间过长，请直接刷新页面以中断。")
    # === 中间：录入/批量区 ===
    with col_mid:
        if mode == "单题录入":
            st.subheader("📝 单题详情")
            
            def update_content_wrapper():
                """根据表单字段更新 entry_content 中的 problem 包裹"""
                content = st.session_state.get("entry_content", "")
                year = st.session_state.get("entry_year", "")
                p_type = st.session_state.get("entry_p_type", "G")
                paper = st.session_state.get("entry_paper_name", "")
                number = st.session_state.get("entry_number", "")
                subj_list = st.session_state.get("entry_subject_multi", [])
                subj = "，".join(subj_list) if subj_list else ""
                
                # 尝试匹配现有的 problem 包裹
                prob_match = re.search(r'(\\begin\{problem\})\{.*?\}\{.*?\}\{.*?\}\{.*?\}\{.*?\}', content, re.DOTALL)
                if prob_match:
                    # 替换现有的参数
                    new_header = f"\\begin{{problem}}{{{year}}}{{{p_type}}}{{{paper}}}{{{number}}}{{{subj}}}"
                    content = content[:prob_match.start()] + new_header + content[prob_match.end():]
                    st.session_state["entry_content"] = content
                elif year and p_type and paper and number:
                    # 没有 problem 包裹，添加一个
                    content = f"\\begin{{problem}}{{{year}}}{{{p_type}}}{{{paper}}}{{{number}}}{{{subj}}}\n{content}\n\\end{{problem}}"
                    st.session_state["entry_content"] = content
            
            c_r1_1, c_r1_2, c_r1_3 = st.columns([1, 2, 1.5])
            with c_r1_1:
                year = st.text_input("年份", key="entry_year", on_change=update_content_wrapper)
            with c_r1_2:
                # 知识板块推断与选择逻辑优化
                current_content = st.session_state.get("entry_content", "")
                last_inferred_content = st.session_state.get("_last_inferred_content", None)
                
                if st.session_state.get("_ai_override_subjects", False):
                    st.session_state["_ai_override_subjects"] = False
                    st.session_state["_last_inferred_content"] = current_content
                elif (not st.session_state.get("entry_subject_user_locked", False)) and current_content != last_inferred_content and current_content.strip() != "":
                    inferred_subjects = []
                    for s in SUBJECTS:
                        if len(s) > 1 and s in current_content:
                            inferred_subjects.append(s)
                    if inferred_subjects:
                        st.session_state["entry_subject_multi"] = inferred_subjects
                    st.session_state["_last_inferred_content"] = current_content

                current_multi = st.session_state.get("entry_subject_multi", [])
                valid_current_multi = [s for s in current_multi if s in SUBJECTS]
                    
                if st.session_state.get("entry_subject_multi") != valid_current_multi:
                    st.session_state["entry_subject_multi"] = valid_current_multi
                def _on_subject_change():
                    st.session_state["entry_subject_user_locked"] = True
                    update_content_wrapper()
                st.multiselect("知识板块 (首个为主)", options=SUBJECTS, key="entry_subject_multi", on_change=_on_subject_change)
                subjects = st.session_state.get("entry_subject_multi") or []
                subject = "，".join(subjects) if subjects else ""
            with c_r1_3:
                type_opts = _editable_paper_type_options("WK" if cloze_mode else None)
                current_p_type = st.session_state.get("entry_p_type", "G")
                if current_p_type not in type_opts:
                    current_p_type = type_opts[0]
                    st.session_state["entry_p_type"] = current_p_type
                default_type_idx = type_opts.index(current_p_type)

                if cloze_mode:
                    st.selectbox("试卷类别", options=type_opts, index=default_type_idx, format_func=lambda x: f"{x} ({PAPER_TYPES[x]})", key="entry_p_type", disabled=True)
                else:
                    st.selectbox("试卷类别", options=type_opts, index=default_type_idx, format_func=lambda x: f"{x} ({PAPER_TYPES[x]})", key="entry_p_type", on_change=update_content_wrapper)
                p_type_code = st.session_state.get("entry_p_type", "G")

            c_r2_1, c_r2_2 = st.columns([3, 1])
            with c_r2_1:
                paper_name = st.text_input("试卷名称", key="entry_paper_name", on_change=update_content_wrapper)
            with c_r2_2:
                number = st.text_input("题号", key="entry_number", on_change=update_content_wrapper)
            
            st.markdown("##### 🏷️ 附加属性")
            c_attr1, c_attr2, c_attr3 = st.columns([1.2, 2, 2])
            with c_attr1:
                st.markdown("<div style='font-size: 14px; color: #31333F; margin-bottom: 5px;'><b>难度星级</b></div>", unsafe_allow_html=True)
                from utils.star_rating import st_star_rating
                s_difficulty_val = st_star_rating(label="", value=st.session_state.get("entry_difficulty", 0.0), max_stars=6, key="star_entry_difficulty")
                if s_difficulty_val != st.session_state.get("entry_difficulty", 0.0):
                    st.session_state["entry_difficulty"] = s_difficulty_val
            with c_attr2:
                st.markdown("<div style='font-size: 14px; color: #31333F; margin-bottom: 5px;'><b>标签 (用逗号“，”分隔)</b></div>", unsafe_allow_html=True)
                s_tags = st.text_input("标签", placeholder="例如: 压轴题, 易错点", key="entry_custom_tags", label_visibility="collapsed")
            with c_attr3:
                st.markdown("<div style='font-size: 14px; color: #31333F; margin-bottom: 5px;'><b>备注</b></div>", unsafe_allow_html=True)
                s_remark = st.text_input("备注", placeholder="例如: 2025新高考题型", key="entry_remark", label_visibility="collapsed")
            
            c_content_lbl, c_ai_btn = st.columns([3, 1], vertical_alignment="bottom")
            with c_content_lbl:
                st.markdown("##### 📝 题目内容 (LaTeX)")
            with c_ai_btn:
                def on_ai_analyze_click():
                    content = st.session_state.get("entry_content", "").strip()
                    if not content:
                        st.toast("题目内容为空，无法进行 AI 分析", icon="⚠️")
                        return
                    
                    res = call_ai_for_tags(content)
                    if "error" in res:
                        st.toast(res["error"], icon="❌")
                    else:
                        diff = res["difficulty"]
                        tags = res["tags"]
                        
                        if 0.0 <= diff <= 6.0:
                            st.session_state["entry_difficulty"] = diff
                        if tags:
                            old_tags = st.session_state.get("entry_custom_tags", "").strip()
                            if old_tags:
                                all_tags = set([t.strip() for t in old_tags.split("，") if t.strip()] + [t.strip() for t in tags.split("，") if t.strip()])
                                st.session_state["entry_custom_tags"] = "，".join(all_tags)
                            else:
                                st.session_state["entry_custom_tags"] = tags
                                
                        st.toast("AI 标签与难度评级成功！", icon="🪄")

                st.button("🪄 AI 自动打标签", on_click=on_ai_analyze_click, use_container_width=True)

        # 所有模式共用的查找替换
        def _normalize_circled_digits(text: str) -> str:
            if not text:
                return text
            mapping = {
                "①": r"\circled{1}",
                "②": r"\circled{2}",
                "③": r"\circled{3}",
                "④": r"\circled{4}",
                "⑤": r"\circled{5}",
            }
            for k, v in mapping.items():
                text = text.replace(k, v)
            return text

        def render_find_replace(target_key):
            with st.expander("🔍 查找与替换", expanded=False):
                c_f_1, c_f_2, c_f_3, c_f_4 = st.columns([2, 2, 1, 1])
                with c_f_1: f_str = st.text_input("查找", key=f"entry_find_{target_key}")
                with c_f_2: r_str = st.text_input("替换", key=f"entry_replace_{target_key}")
                with c_f_3:
                    st.write("")
                    st.write("")
                    if st.button("替换", key=f"btn_entry_replace_{target_key}"):
                        if st.session_state.get(target_key, "") and f_str:
                            st.session_state[target_key] = st.session_state[target_key].replace(f_str, r_str)
                            st.toast("替换完成", icon="✅")
                            st.rerun()
                with c_f_4:
                    st.write("")
                    st.write("")
                    if st.button("圈号→LaTeX", key=f"btn_entry_circled_{target_key}"):
                        cur = st.session_state.get(target_key, "") or ""
                        st.session_state[target_key] = _normalize_circled_digits(cur)
                        st.toast("已替换圈号 ①②③④⑤", icon="✅")
                        st.rerun()

        if mode == "单题录入":
            st.markdown("##### ⚙️ 录入配置")
            auto_solve_label = "如果识别内容缺少解答，则保存时 AI 生成解答" if cloze_mode else "本次录入同时生成解答"
            auto_solve_default = True if cloze_mode else False
            auto_solve_key = "cloze_auto_solve" if cloze_mode else "entry_auto_solve"
            auto_solve_enabled = st.checkbox(auto_solve_label, key=auto_solve_key, value=auto_solve_default)

            render_find_replace("entry_content")
            
            def on_content_change():
                """当用户编辑源码框时，同步回表单字段"""
                content = st.session_state.get("entry_content", "")
                if not content:
                    return
                
                fields = extract_problem_header_fields(content)
                if fields:
                    sy = fields["year"]
                    st_type = fields["p_type"]
                    sp = fields["paper"]
                    sn = fields["number"]
                    ss = fields["subject_str"]
                    if sy:
                        st.session_state["entry_year"] = sy
                    if st_type:
                        st.session_state["entry_p_type"] = st_type
                    if sp:
                        st.session_state["entry_paper_name"] = sp
                    if sn:
                        st.session_state["entry_number"] = sn
                    extracted_subjs = [s.strip() for s in (ss or "").split("，") if s.strip()]
                    valid_subjs = [s for s in extracted_subjs if s in SUBJECTS]
                    if valid_subjs:
                        st.session_state["entry_subject_multi"] = valid_subjs
                        st.session_state["entry_subject_user_locked"] = True
            
            content = st.text_area("题目内容 (LaTeX)", height=400, placeholder="在此粘贴题目内容...", key="entry_content", label_visibility="collapsed", on_change=on_content_change)
            
        elif mode in ["批量试题录入", "同卷试题录入"]:
            def _split_batch_text_to_items(text: str):
                text = text or ""
                parts = re.split(r'---(.+\.tex)---\s*', text)
                items = []
                for i in range(1, len(parts), 2):
                    if i + 1 < len(parts):
                        fname = (parts[i] or "").strip()
                        body = (parts[i + 1] or "").lstrip()
                        if fname:
                            items.append({"filename": fname, "content": body})
                return items
            
            def _join_batch_items(items):
                out = []
                for it in items or []:
                    fname = (it.get("filename") or "").strip()
                    if fname.startswith("---") and fname.endswith("---"):
                        fname = fname[3:-3].strip()
                    fname = fname.replace("\n", " ").replace("\r", " ").strip()
                    if fname and not fname.lower().endswith(".tex"):
                        fname += ".tex"
                    body = (it.get("content") or "").rstrip()
                    if not fname:
                        continue
                    out.append(f"---{fname}---\n{body}".rstrip())
                return "\n\n".join(out).strip()

            def _write_batch_items_state(items, src_hash=None):
                old_count = int(st.session_state.get("batch_item_count") or 0)
                items = items or []
                st.session_state["batch_item_count"] = len(items)
                if src_hash is not None:
                    st.session_state["batch_items_src_hash"] = src_hash
                for idx, it in enumerate(items):
                    st.session_state[f"batch_item_name_{idx}"] = it.get("filename", "")
                    st.session_state[f"batch_item_text_{idx}"] = it.get("content", "")
                for idx in range(len(items), old_count):
                    st.session_state.pop(f"batch_item_name_{idx}", None)
                    st.session_state.pop(f"batch_item_text_{idx}", None)
             
            def _ensure_batch_items_state():
                src = st.session_state.get("batch_content", "") or ""
                src_hash = hashlib.md5(src.encode("utf-8", errors="ignore")).hexdigest()
                if st.session_state.get("batch_items_src_hash") == src_hash and st.session_state.get("batch_item_count") is not None:
                    return
                items = _split_batch_text_to_items(src)
                _write_batch_items_state(items, src_hash)
            
            def _current_items_from_state():
                n = int(st.session_state.get("batch_item_count") or 0)
                items = []
                for idx in range(n):
                    fname = st.session_state.get(f"batch_item_name_{idx}", "")
                    body = st.session_state.get(f"batch_item_text_{idx}", "")
                    items.append({"filename": fname, "content": body})
                return items

            def _set_batch_content_and_hash(new_text: str):
                new_text = (new_text or "").strip()
                st.session_state["batch_content"] = new_text
                st.session_state["batch_items_src_hash"] = hashlib.md5(new_text.encode("utf-8", errors="ignore")).hexdigest()

            def _sync_batch_content_from_items():
                _set_batch_content_and_hash(_join_batch_items(_current_items_from_state()))

            def _manual_split_candidates(content):
                lines = (content or "").splitlines()
                substantive = []
                previous_nonempty = ""
                for line_index, raw_line in enumerate(lines):
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    excluded = (
                        stripped.startswith("%")
                        or stripped.startswith(r"\begin{")
                        or stripped.startswith(r"\end{")
                        or stripped.startswith(r"\choice")
                        or stripped.startswith("---")
                    )
                    if not excluded:
                        substantive.append((line_index, stripped, previous_nonempty))
                    previous_nonempty = stripped

                # The first substantive line is the current question stem, not a split point.
                candidates = substantive[1:]
                strong = []
                remaining = []
                for line_index, text, previous in candidates:
                    item = (line_index, text[:90])
                    if previous in {r"\end{choices}", r"\end{problem}", r"\end{answer}", r"\end{solutions}"}:
                        strong.append(item)
                    else:
                        remaining.append(item)
                return strong + remaining

            def _split_batch_item_at_line(item_index, line_index):
                from utils.csv_ops import get_next_id
                from utils.latex_ops import inject_meta_data, parse_meta_data

                current_items = _current_items_from_state()
                if not (0 <= item_index < len(current_items)):
                    return False, "未找到需要拆分的题目。"

                source_item = current_items[item_index]
                source_content = source_item.get("content") or ""
                source_lines = source_content.splitlines()
                if not (0 < line_index < len(source_lines)):
                    return False, "拆分位置无效。"

                head_raw = "\n".join(source_lines[:line_index]).strip()
                tail_raw = "\n".join(source_lines[line_index:]).strip()
                original_meta, clean_source = parse_meta_data(source_content)
                _, clean_head = parse_meta_data(head_raw)
                _, clean_tail = parse_meta_data(tail_raw)
                if not clean_head.strip() or not clean_tail.strip():
                    return False, "拆分位置前后都必须有题目内容。"

                fields = extract_problem_header_fields(clean_source) or {}
                filename = os.path.basename(source_item.get("filename") or "").removesuffix(".tex")
                filename_parts = filename.split("-")
                fallback = {
                    "year": filename_parts[0] if len(filename_parts) >= 5 else "?",
                    "p_type": filename_parts[1] if len(filename_parts) >= 5 else "?",
                    "paper": filename_parts[2] if len(filename_parts) >= 5 else "?",
                    "number": filename_parts[3] if len(filename_parts) >= 5 else "?",
                    "subject_str": "-".join(filename_parts[4:]) if len(filename_parts) >= 5 else "未分类",
                }
                year = fields.get("year") or fallback["year"]
                p_type = fields.get("p_type") or fallback["p_type"]
                paper = fields.get("paper") or fallback["paper"]
                number = fields.get("number") or fallback["number"]
                subject = fields.get("subject_str") or fallback["subject_str"] or "未分类"

                used_numbers = set()
                used_ids = set()
                for current_item in current_items:
                    current_name = os.path.basename(current_item.get("filename") or "").removesuffix(".tex")
                    current_parts = current_name.split("-")
                    if len(current_parts) >= 5:
                        used_numbers.add(current_parts[3])
                    current_meta, _ = parse_meta_data(current_item.get("content") or "")
                    current_id = str(current_meta.get("ID", "")).strip()
                    if current_id.isdigit():
                        used_ids.add(int(current_id))

                next_number = _increment_question_number(number)
                while next_number in used_numbers:
                    next_number = _increment_question_number(next_number)

                next_id = get_next_id()
                while next_id in used_ids:
                    next_id += 1

                head_content = normalize_single_problem_structure(clean_head, year, p_type, paper, number, subject)
                tail_content = normalize_single_problem_structure(clean_tail, year, p_type, paper, next_number, subject)
                head_meta = {
                    "ID": original_meta.get("ID") or str(next_id),
                    "难度星级": original_meta.get("难度星级", ""),
                    "标签": original_meta.get("标签", ""),
                    "备注": original_meta.get("备注", ""),
                    "组卷引用次数": original_meta.get("组卷引用次数", "0"),
                }
                if not original_meta.get("ID"):
                    used_ids.add(next_id)
                    next_id += 1
                    while next_id in used_ids:
                        next_id += 1
                tail_meta = {
                    "ID": str(next_id),
                    "难度星级": "",
                    "标签": "",
                    "备注": "",
                    "组卷引用次数": "0",
                }

                current_items[item_index] = {
                    "filename": generate_filename(year, p_type, paper, number, subject),
                    "content": inject_meta_data(head_content, head_meta),
                }
                current_items.insert(item_index + 1, {
                    "filename": generate_filename(year, p_type, paper, next_number, subject),
                    "content": inject_meta_data(tail_content, tail_meta),
                })
                new_text = _join_batch_items(current_items)
                _set_batch_content_and_hash(new_text)
                _write_batch_items_state(current_items, st.session_state["batch_items_src_hash"])
                return True, f"已拆分为两题，新题暂定为第 {next_number} 题。"

            def _apply_same_paper_meta_to_items(items, year, p_type, paper):
                synced = []
                for it in items or []:
                    fname = (it.get("filename") or "").strip()
                    content = it.get("content") or ""
                    name_body = fname.replace(".tex", "")
                    segments = name_body.split("-")
                    if len(segments) >= 2:
                        q_num = segments[-2]
                        q_subj = segments[-1]
                    else:
                        q_num = "?"
                        q_subj = "未分类"

                    synced_name = generate_filename(year, p_type, paper, q_num, q_subj)
                    if content.strip():
                        if "\\begin{problem}" in content:
                            synced_content = replace_problem_header(content, year, p_type, paper, q_num, q_subj)
                        else:
                            synced_content = normalize_single_problem_structure(content.strip(), year, p_type, paper, q_num, q_subj)
                    else:
                        synced_content = content
                    synced.append({"filename": synced_name, "content": synced_content})
                return synced
            
            _ensure_batch_items_state()
            
            c_title, c_ai_btn = st.columns([3, 1], vertical_alignment="bottom")
            with c_title:
                st.markdown(f"### 📚 {mode}")
            with c_ai_btn:
                def on_batch_ai_click():
                    batch_text = _join_batch_items(_current_items_from_state())
                    if not batch_text.strip():
                        st.warning("内容为空，无法进行 AI 分析")
                        return
                    
                    # Split by `---filename---`
                    parts = re.split(r'(---.+\.tex---\s*)', batch_text)
                    new_batch_text = ""
                    if len(parts) > 1:
                        new_batch_text = parts[0]
                        from utils.latex_ops import parse_meta_data
                        
                        progress_text = "🤖 正在批量调用 AI..."
                        my_bar = st.progress(0, text=progress_text)
                        total_q = len(parts) // 2
                        
                        for i in range(1, len(parts), 2):
                            current_q = i // 2 + 1
                            my_bar.progress(current_q / total_q, text=f"{progress_text} ({current_q}/{total_q})")
                            
                            header = parts[i]
                            content = parts[i+1]
                            existing_meta, clean_content = parse_meta_data(content)
                            
                            # 调用 AI
                            ai_res = call_ai_for_tags(clean_content)
                            if "error" not in ai_res:
                                diff = ai_res["difficulty"]
                                existing_meta["难度星级"] = str(diff) if diff > 0 else ""
                                existing_meta["标签"] = ai_res["tags"]
                            else:
                                st.toast(f"第 {current_q} 题 AI 分析出错: {ai_res['error']}", icon="❌")
                                
                            meta_str = "% === Begin Label Data ===\n"
                            meta_str += f"% ID: {existing_meta.get('ID', '')}\n"
                            meta_str += f"% 难度星级: {existing_meta.get('难度星级', '')}\n"
                            meta_str += f"% 标签: {existing_meta.get('标签', '')}\n"
                            meta_str += f"% 备注: {existing_meta.get('备注', '')}\n"
                            meta_str += f"% 组卷引用次数: {existing_meta.get('组卷引用次数', '0')}\n"
                            meta_str += "% === End  Label Data ===\n\n"
                            
                            new_batch_text += header + meta_str + clean_content.lstrip()
                            
                        my_bar.empty()
                        _set_batch_content_and_hash(new_batch_text)
                        st.toast("批量 AI 自动打标签完成！", icon="🪄")
                    else:
                        st.warning("未检测到有效的分隔线格式，请确保内容符合 `---xxx.tex---` 格式")

                st.button("🪄 AI 自动打标签", key="btn_batch_ai", on_click=on_batch_ai_click, use_container_width=True)
            
            # 如果是同卷录入，提供试卷头部信息输入
            if mode == "同卷试题录入":
                st.info("💡 **同卷模式**：下方填写的【年份】【试卷名称】等信息，将自动应用到所有识别出的题目中。")
                if "u_batch_year" not in st.session_state:
                    st.session_state["u_batch_year"] = "2024"
                if "u_batch_paper" not in st.session_state:
                    st.session_state["u_batch_paper"] = "新高考I卷"
                if "u_batch_type" not in st.session_state:
                    st.session_state["u_batch_type"] = "G"
                    
                c1, c2, c3, c4 = st.columns([1.5, 2, 1.5, 1])
                batch_year = c1.text_input("统一年份", key="u_batch_year")
                batch_pname = c2.text_input("统一试卷名称", key="u_batch_paper")
                type_opts = _editable_paper_type_options()
                batch_ptype = c3.selectbox("统一试卷类别", options=type_opts, format_func=lambda x: f"{x} ({PAPER_TYPES[x]})", key="u_batch_type")
                
                with c4:
                    st.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)
                    def on_sync_click():
                        s_y = st.session_state.get("u_batch_year", "")
                        s_t = st.session_state.get("u_batch_type", "G")
                        s_p = st.session_state.get("u_batch_paper", "")
                        
                        if s_y and s_p:
                            items = _apply_same_paper_meta_to_items(_current_items_from_state(), s_y, s_t, s_p)
                            new_text = _join_batch_items(items)
                            
                            # 自动匹配并分配空的 ID
                            from utils.csv_ops import get_next_id
                            current_id = get_next_id()
                            def repl_id(m):
                                nonlocal current_id
                                val = m.group(1).strip()
                                if not val:  # 只有为空时才分配新ID，防止重复点击浪费ID
                                    val = str(current_id)
                                    current_id += 1
                                return f"% ID: {val}"
                            # 修复正则：匹配末尾可能的空格或换行符
                            new_text = re.sub(r'% ID:\s*(.*?)(?=\n|$)', repl_id, new_text)
                            _set_batch_content_and_hash(new_text)
                            _write_batch_items_state(_split_batch_text_to_items(new_text), st.session_state["batch_items_src_hash"])
                            
                    if st.button("🔄 同步更新", help="将上方填写的年份、类别和试卷名称，一键替换下方所有源码中的 problem 标签", on_click=on_sync_click, use_container_width=True, type="secondary"):
                        st.toast("已同步更新所有 problem 标签及预分配ID！", icon="✅")

            with st.expander("🔍 查找与替换", expanded=False):
                c_f_1, c_f_2, c_f_3, c_f_4 = st.columns([2, 2, 1, 1])
                with c_f_1:
                    f_str = st.text_input("查找", key="batch_find_all")
                with c_f_2:
                    r_str = st.text_input("替换", key="batch_replace_all")
                with c_f_3:
                    st.write("")
                    st.write("")
                    def _apply_batch_replace():
                        if not f_str:
                            return
                        items = _current_items_from_state()
                        for idx, it in enumerate(items):
                            # 同时替换文件名和正文内容
                            fname = (it.get("filename") or "").replace(f_str, r_str)
                            content = (it.get("content") or "").replace(f_str, r_str)
                            st.session_state[f"batch_item_name_{idx}"] = fname
                            st.session_state[f"batch_item_text_{idx}"] = content
                        _sync_batch_content_from_items()
                    if st.button("替换", key="btn_batch_replace_all", on_click=_apply_batch_replace):
                        st.toast("替换完成（含标题）", icon="✅")
                with c_f_4:
                    st.write("")
                    st.write("")
                    def _apply_batch_circled():
                        items = _current_items_from_state()
                        for idx, it in enumerate(items):
                            st.session_state[f"batch_item_text_{idx}"] = _normalize_circled_digits(it.get("content") or "")
                        _sync_batch_content_from_items()
                    if st.button("圈号→LaTeX", key="btn_batch_circled_all", on_click=_apply_batch_circled):
                        st.toast("已替换圈号 ①②③④⑤", icon="✅")

            st.markdown("##### 📝 题目内容 (LaTeX)")
            items = _current_items_from_state()
            if not items:
                st.text_area("批量内容编辑", height=260, key="batch_content_fallback", label_visibility="collapsed")
            else:
                st.markdown("""
<style>
button[kind="secondary"][data-testid="stBaseButton-secondary"][aria-label="放弃本题×"] {
    color: #dc3545 !important;
    border-color: #dc3545 !important;
}
button[kind="secondary"][data-testid="stBaseButton-secondary"][aria-label="放弃本题×"]:hover {
    color: #fff !important;
    background-color: #dc3545 !important;
    border-color: #dc3545 !important;
}
</style>
                """, unsafe_allow_html=True)
                for idx, it in enumerate(items):
                    st.markdown('<hr style="border-top: 1px solid #e1e4e8; margin-top: 14px; margin-bottom: 14px;">', unsafe_allow_html=True)
                    def _apply_batch_fname():
                        _sync_batch_content_from_items()
                        st.toast("已应用文件名修改", icon="✅")
                        st.rerun()

                    def _discard_batch_item(_idx=idx):
                        # 从 batch_content 中移除该题目
                        current_items = _current_items_from_state()
                        if 0 <= _idx < len(current_items):
                            current_items.pop(_idx)
                            new_text = _join_batch_items(current_items)
                            _set_batch_content_and_hash(new_text)
                            _write_batch_items_state(current_items, st.session_state["batch_items_src_hash"])
                            st.toast("已放弃该题目")
                        st.rerun()

                    # 文件名操作栏与源码/预览栏平级，兼容 Streamlit 1.37 的列嵌套限制。
                    c_fn_1, c_btn_1, c_btn_2 = st.columns([3, 1, 1], vertical_alignment="bottom")
                    with c_fn_1:
                        st.text_input("文件名", key=f"batch_item_name_{idx}", on_change=_sync_batch_content_from_items)
                    with c_btn_1:
                        st.button("应用标题", key=f"batch_apply_fname_{idx}", use_container_width=True, on_click=_apply_batch_fname)
                    with c_btn_2:
                        st.button("放弃本题×", key=f"batch_discard_fname_{idx}", use_container_width=True, on_click=_discard_batch_item, type="secondary")

                    c_src, c_prev = st.columns([1, 1])
                    with c_src:
                        st.text_area("题目源码", height=240, key=f"batch_item_text_{idx}", label_visibility="collapsed", on_change=_sync_batch_content_from_items)
                        st.caption("提示：编辑后点击空白处或按 Ctrl+Enter 以应用更新。")
                    with c_prev:
                        fname = (st.session_state.get(f"batch_item_name_{idx}", "") or "").strip()
                        st.markdown(f"### 📄 {fname}")
                        try:
                            preview_src = st.session_state.get(f"batch_item_text_{idx}", "") or ""
                            st.markdown(latex_to_markdown(preview_src, show_title=False), unsafe_allow_html=True)
                        except Exception as e:
                            st.error(f"预览渲染出错: {e}")

                    split_source = st.session_state.get(f"batch_item_text_{idx}", it.get("content") or "") or ""
                    split_candidates = _manual_split_candidates(split_source)
                    if split_candidates:
                        with st.expander("✂️ 手动拆题", expanded=False):
                            candidate_lines = [line_index for line_index, _ in split_candidates]
                            candidate_labels = {line_index: preview for line_index, preview in split_candidates}
                            selected_line = st.selectbox(
                                "下一题起始行",
                                options=candidate_lines,
                                format_func=lambda line_index: f"第 {line_index + 1} 行 · {candidate_labels[line_index]}",
                                key=f"batch_split_line_{idx}_{hashlib.md5(split_source.encode('utf-8', errors='ignore')).hexdigest()[:8]}",
                                help="选择下一道题题干开始的那一行。明确边界会优先显示。",
                            )
                            if st.button("从选中行拆分", key=f"batch_split_apply_{idx}", type="primary"):
                                split_ok, split_message = _split_batch_item_at_line(idx, selected_line)
                                if split_ok:
                                    st.toast(split_message, icon="✂️")
                                    st.rerun()
                                else:
                                    st.error(split_message)
                _sync_batch_content_from_items()

            st.markdown('<hr style="border-top: 1px solid #e1e4e8; margin-top: 12px; margin-bottom: 16px;">', unsafe_allow_html=True)
            if mode == "同卷试题录入":
                c_same_title, c_same_btn = st.columns([2, 1])
                with c_same_title:
                    st.markdown("### 📚 同卷试题批量处理状态")
                with c_same_btn:
                    if st.button("💾 同卷提取并保存", type="primary", use_container_width=True, key="same_paper_save_btn"):
                        st.session_state["_run_same_paper_batch"] = True
                        st.session_state["_run_ai_tagging_batch"] = st.session_state.get("batch_enable_ai_flag", False)
                        st.session_state["batch_enable_ai_flag"] = False
                        st.rerun()
                st.info("同卷试题批量录入的处理结果会在此显示。")
                
                if st.session_state.get("_run_same_paper_batch", False):
                    st.session_state["_run_same_paper_batch"] = False
                    batch_text = st.session_state.get("batch_content", "")
                    u_year = st.session_state.get("u_batch_year", "")
                    u_paper = st.session_state.get("u_batch_paper", "")
                    u_type = st.session_state.get("u_batch_type", "G")
                    
                    if not batch_text.strip():
                        st.warning("请输入内容")
                    elif not (u_year and u_paper):
                        st.error("请完善年份和试卷名称信息")
                    else:
                        parts = re.split(r'---(.+\.tex)---\s*', batch_text)
                        count = 0
                        log_msg = []
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        total_files = len(parts) // 2
                        for i in range(1, len(parts), 2):
                            current_idx = i // 2 + 1
                            if i + 1 < len(parts):
                                raw_fname = parts[i].strip()
                                file_content = parts[i+1].strip()
                                status_text.text(f"正在处理: {raw_fname} ({current_idx}/{total_files})")
                                name_body = raw_fname.replace('.tex', '')
                                segments = name_body.split('-')
                                if len(segments) >= 2:
                                    q_num = segments[-2]
                                    q_subj = segments[-1]
                                    final_filename = generate_filename(u_year, u_type, u_paper, q_num, q_subj)
                                    primary_subj = q_subj.split("，")[0]
                                    save_dir = os.path.join(CHAPTERS_DIR, primary_subj, str(u_year))
                                    ensure_dir(save_dir)
                                    file_path = os.path.join(save_dir, final_filename)
                                    if "\\begin{problem}" in file_content:
                                        file_content = replace_problem_header(file_content, str(u_year), u_type, u_paper, q_num, q_subj)
                                    else:
                                        file_content = normalize_single_problem_structure(file_content, str(u_year), u_type, u_paper, q_num, q_subj)
                                    file_content = extract_and_replace_tikz(file_content, final_filename, save_dir)
                                    from utils.latex_ops import parse_meta_data, inject_meta_data
                                    existing_meta, clean_content = parse_meta_data(file_content)
                                    q_id = existing_meta.get("ID", "")
                                    if not q_id:
                                        from utils.csv_ops import get_next_id
                                        q_id = get_next_id()
                                    meta_dict = {"ID": q_id, "难度星级": existing_meta.get("难度星级", ""), "标签": existing_meta.get("标签", ""), "备注": existing_meta.get("备注", ""), "组卷引用次数": existing_meta.get("组卷引用次数", "0")}
                                    file_content = inject_meta_data(file_content, meta_dict)
                                    try:
                                        duplicate_matches = []
                                        saved = _save_batch_question_if_new(
                                            file_path,
                                            file_content,
                                            str(u_year),
                                            u_type,
                                            u_paper,
                                            q_num,
                                            q_subj,
                                            duplicate_matches_out=duplicate_matches,
                                        )
                                        if not saved:
                                            log_msg.append({
                                                "status": "skip",
                                                "file": final_filename,
                                                "msg": (
                                                    f"检测到完全相同题干，已跳过（已有：{duplicate_matches[0].get('name', '')}）"
                                                    if duplicate_matches
                                                    else "检测到同名旧题目，已保留旧题并跳过新的识别结果"
                                                ),
                                            })
                                            progress_bar.progress(current_idx / total_files)
                                            continue
                                        count += 1
                                        ai_str = ""
                                        if meta_dict['难度星级'] or meta_dict['标签']:
                                            ai_str = f" [AI自动提取: 星级={meta_dict['难度星级'] or '无'} | 标签={meta_dict['标签'] or '无'}]"
                                        log_msg.append({"status": "success", "file": final_filename, "path": file_path, "ai_info": ai_str})
                                    except Exception as e:
                                        log_msg.append({"status": "error", "file": final_filename, "msg": str(e)})
                                else:
                                    log_msg.append({"status": "skip", "file": raw_fname, "msg": "文件名格式不足 (需至少包含 题号-板块)"})
                            progress_bar.progress(current_idx / total_files)
                        status_text.empty()
                        c_msg, c_jump = st.columns([3, 1])
                        c_msg.success(f"处理完成，共保存 {count} 个文件")
                        def _jump_to_browse_same_paper():
                            st.session_state["main_sidebar_radio"] = "🔍\n全局浏览\n与编辑"
                            st.session_state["adv_search_active"] = False
                            st.session_state["recent_saved_active"] = True
                            st.session_state["recent_saved_paths"] = [log.get("path") for log in log_msg if log.get("status") == "success" and log.get("path")]
                        c_jump.button("跳转至全局浏览查看 ↗", use_container_width=True, type="primary", key="jump_to_browse_same_paper", on_click=_jump_to_browse_same_paper)
                        st.toast(f"同卷处理完成！共保存 {count} 个文件", icon="✅")
                        with st.expander("查看处理日志", expanded=True):
                            for log_index, log in enumerate(log_msg):
                                if log["status"] == "success":
                                    c1, c2 = st.columns([4, 1])
                                    ai_str = log.get('ai_info', '')
                                    c1.success(f"✅ {log['file']}{ai_str}")
                                    log_key = hashlib.md5(
                                        str(log.get("path") or log.get("file") or log_index).encode("utf-8", errors="ignore")
                                    ).hexdigest()[:10]
                                    if c2.button("📂 打开", key=f"open_log_u_{log_index}_{log_key}"):
                                        try:
                                            os.startfile(log['path'])
                                        except Exception as e:
                                            st.error(f"无法打开: {e}")
                                elif log["status"] == "error":
                                    st.error(f"❌ {log['file']}: {log['msg']}")
                                else:
                                    st.warning(f"⚠️ {log['file']}: {log['msg']}")

            elif mode == "批量试题录入":
                c_batch_title, c_batch_btn = st.columns([2, 1])
                with c_batch_title:
                    st.markdown("### 🗃️ 批量处理状态")
                with c_batch_btn:
                    if st.button("💾 批量提取并保存", type="primary", use_container_width=True, key="batch_save_btn"):
                        st.session_state["_run_batch_mode"] = True
                        st.session_state["_run_ai_tagging_global_batch"] = st.session_state.get("batch_enable_ai_flag", False)
                        st.session_state["batch_enable_ai_flag"] = False
                        st.rerun()
                st.info("批量录入的处理结果会在此显示。")
                if st.session_state.get("_run_batch_mode", False):
                    st.session_state["_run_batch_mode"] = False
                    batch_text = st.session_state.get("batch_content", "")
                    if not batch_text.strip():
                        st.warning("请输入内容")
                    else:
                        parts = re.split(r'---(.+\.tex)---\s*', batch_text)
                        count = 0
                        log_msg = []
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        total_files = len(parts) // 2
                        for i in range(1, len(parts), 2):
                            current_idx = i // 2 + 1
                            if i + 1 < len(parts):
                                filename = parts[i].strip()
                                file_content = parts[i+1].strip()
                                status_text.text(f"正在处理: {filename} ({current_idx}/{total_files})")
                                name_body = filename.replace('.tex', '')
                                segments = name_body.split('-')
                                if len(segments) >= 5:
                                    year_seg = segments[0]
                                    topic_seg = segments[-1]
                                    primary_topic = topic_seg.split("，")[0]
                                    save_dir = os.path.join(CHAPTERS_DIR, primary_topic, str(year_seg))
                                    ensure_dir(save_dir)
                                    file_path = os.path.join(save_dir, filename)
                                    file_content = extract_and_replace_tikz(file_content, filename, save_dir)
                                    from utils.latex_ops import parse_meta_data, inject_meta_data
                                    existing_meta, clean_content = parse_meta_data(file_content)
                                    q_id = existing_meta.get("ID", "")
                                    if not q_id:
                                        from utils.csv_ops import get_next_id
                                        q_id = get_next_id()
                                    meta_dict = {"ID": q_id, "难度星级": existing_meta.get("难度星级", ""), "标签": existing_meta.get("标签", ""), "备注": existing_meta.get("备注", ""), "组卷引用次数": existing_meta.get("组卷引用次数", "0")}
                                    file_content = inject_meta_data(file_content, meta_dict)
                                    try:
                                        duplicate_matches = []
                                        saved = _save_batch_question_if_new(
                                            file_path,
                                            file_content,
                                            segments[0],
                                            segments[1],
                                            segments[2],
                                            segments[3],
                                            segments[4],
                                            duplicate_matches_out=duplicate_matches,
                                        )
                                        if not saved:
                                            log_msg.append({
                                                "status": "skip",
                                                "file": filename,
                                                "msg": (
                                                    f"检测到完全相同题干，已跳过（已有：{duplicate_matches[0].get('name', '')}）"
                                                    if duplicate_matches
                                                    else "检测到同名旧题目，已保留旧题并跳过新的识别结果"
                                                ),
                                            })
                                            progress_bar.progress(current_idx / total_files)
                                            continue
                                        count += 1
                                        ai_str = ""
                                        if meta_dict['难度星级'] or meta_dict['标签']:
                                            ai_str = f" [AI自动提取: 星级={meta_dict['难度星级'] or '无'} | 标签={meta_dict['标签'] or '无'}]"
                                        log_msg.append({"status": "success", "file": filename, "path": file_path, "id": q_id, "ai_info": ai_str})
                                    except Exception as e:
                                        log_msg.append({"status": "error", "file": filename, "msg": str(e)})
                                else:
                                    log_msg.append({"status": "skip", "file": filename, "msg": "文件名格式错误"})
                            progress_bar.progress(current_idx / total_files)
                        status_text.empty()
                        c_msg, c_jump = st.columns([3, 1])
                        c_msg.success(f"处理完成，共保存 {count} 个文件")
                        def _jump_to_browse_batch():
                            st.session_state["main_sidebar_radio"] = "🔍\n全局浏览\n与编辑"
                            st.session_state["adv_search_active"] = False
                            st.session_state["recent_saved_active"] = True
                            st.session_state["recent_saved_paths"] = [log.get("path") for log in log_msg if log.get("status") == "success" and log.get("path")]
                        c_jump.button("跳转至全局浏览查看 ↗", use_container_width=True, type="primary", key="jump_to_browse_batch", on_click=_jump_to_browse_batch)
                        clear_statistics_cache()
                        st.toast(f"批量处理完成！共保存 {count} 个文件", icon="✅")
                        with st.expander("查看处理日志", expanded=True):
                            for log_index, log in enumerate(log_msg):
                                if log["status"] == "success":
                                    c1, c2 = st.columns([4, 1])
                                    ai_str = log.get('ai_info', '')
                                    c1.success(f"✅ {log['file']}{ai_str}")
                                    log_key = hashlib.md5(
                                        str(log.get("path") or log.get("file") or log_index).encode("utf-8", errors="ignore")
                                    ).hexdigest()[:10]
                                    if c2.button("📂 打开", key=f"open_log_{log_index}_{log_key}"):
                                        try:
                                            os.startfile(log['path'])
                                        except Exception as e:
                                            st.error(f"无法打开: {e}")
                                elif log["status"] == "error":
                                    st.error(f"❌ {log['file']}: {log['msg']}")
                                else:
                                    st.warning(f"⚠️ {log['file']}: {log['msg']}")
            
    # === 右侧：实时预览与保存（仅单题模式） ===
    with col_right:
        if mode == "单题录入":
            if cloze_mode:
                c_preview_title, c_img_btn, c_save_btn = st.columns([2, 1, 1])
            else:
                c_preview_title, c_save_btn = st.columns([2, 1])
            with c_preview_title:
                st.subheader("👁️ 实时预览与保存")
            if cloze_mode:
                with c_img_btn:
                    def on_generate_cloze_image():
                        current = st.session_state.get("entry_content", "").strip()
                        fields = extract_problem_header_fields(current)
                        hint = "挖空题"
                        if fields:
                            hint = generate_filename(
                                fields.get("year") or st.session_state.get("entry_year", ""),
                                fields.get("p_type") or st.session_state.get("entry_p_type", ""),
                                fields.get("paper") or st.session_state.get("entry_paper_name", ""),
                                fields.get("number") or st.session_state.get("entry_number", ""),
                                fields.get("subject_str") or "未分类",
                            ).replace(".tex", "")
                        with st.spinner("正在生成当前挖空题图片..."):
                            res = generate_question_png_from_latex(
                                current,
                                filename_hint=hint,
                                cloze_type=st.session_state.get("cloze_generation_type", "挖空题"),
                            )
                        st.session_state["cloze_image_result"] = res
                        if res.get("ok"):
                            st.toast("挖空题图片已生成", icon="✅")
                        else:
                            st.toast(res.get("error", "图片生成失败"), icon="❌")
                    st.button("🖼️ 生成图片", on_click=on_generate_cloze_image, use_container_width=True)
            with c_save_btn:
                def on_save_entry():
                    s_content = st.session_state.get("entry_content", "")
                    if cloze_mode:
                        s_content = _normalize_cloze_blank_markup(s_content)
                        st.session_state["entry_content"] = s_content
                    fields = extract_problem_header_fields(s_content)
                    s_year = (fields.get("year") if fields else "") or st.session_state.get("entry_year", "")
                    s_type = "WK" if cloze_mode else ((fields.get("p_type") if fields else "") or st.session_state.get("entry_p_type", ""))
                    s_paper = (fields.get("paper") if fields else "") or st.session_state.get("entry_paper_name", "")
                    s_num = (fields.get("number") if fields else "") or st.session_state.get("entry_number", "")
                    s_subj_from_state = "，".join(st.session_state.get("entry_subject_multi", []) or []).strip()
                    s_subj_str = ((fields.get("subject_str") if fields else "") or s_subj_from_state).strip()
                    s_subj = s_subj_str if s_subj_str else "未分类"
                    s_diff_raw = st.session_state.get("entry_difficulty", 0.0)
                    s_diff = "" if s_diff_raw == 0.0 else str(s_diff_raw)
                    s_tag = st.session_state.get("entry_custom_tags", "")
                    s_rem = st.session_state.get("entry_remark", "")
                    if not s_content:
                        st.toast("题目内容不能为空", icon="⚠️")
                        return
                    if cloze_mode and CLOZE_BLANK_TEX not in _extract_problem_env(s_content):
                        st.toast("挖空题至少需要包含一个统一格式的挖空后才能保存", icon="⚠️")
                        return
                    if cloze_mode:
                        cloze_type = st.session_state.get("cloze_generation_type", "挖空题")
                        if cloze_type and cloze_type not in s_paper:
                            s_paper = f"{s_paper}（{cloze_type}）"
                    full_text = normalize_single_problem_structure(s_content.strip(), s_year, s_type, s_paper, s_num, s_subj)
                    s_filename = generate_filename(s_year, s_type, s_paper, s_num, s_subj)
                    primary_subj = s_subj.split("，")[0]
                    s_save_dir = os.path.join(CHAPTERS_DIR, primary_subj, s_year)
                    ensure_dir(s_save_dir)
                    s_file_path = os.path.join(s_save_dir, s_filename)
                    if os.path.exists(s_file_path):
                        st.toast("目标题目文件已存在，请修改题号或试卷信息后再保存", icon="⚠️")
                        return
                    duplicate_matches = find_duplicate_matches(
                        full_text,
                        exclude_path=s_file_path,
                        similarity_threshold=0.88,
                        max_results=5,
                    )
                    duplicate_fingerprint = question_fingerprint(full_text)
                    pending_duplicate = st.session_state.get("entry_duplicate_warning") or {}
                    if duplicate_matches and pending_duplicate.get("fingerprint") != duplicate_fingerprint:
                        st.session_state["entry_duplicate_warning"] = {
                            "fingerprint": duplicate_fingerprint,
                            "matches": duplicate_matches,
                        }
                        st.toast("发现可能重复的题目，请确认后再次点击保存", icon="⚠️")
                        return
                    allow_duplicate = bool(duplicate_matches)
                    st.session_state.pop("entry_duplicate_warning", None)
                    full_text = extract_and_replace_tikz(full_text, s_filename, s_save_dir)
                    from utils.csv_ops import get_next_id
                    new_id = get_next_id()
                    meta_dict = {"ID": new_id, "难度星级": s_diff, "标签": s_tag, "备注": s_rem, "组卷引用次数": 0}
                    if cloze_mode:
                        meta_dict.update({
                            "来源题目ID": st.session_state.get("cloze_source_question_id", ""),
                            "挖空类型": st.session_state.get("cloze_generation_type", ""),
                            "生成时间": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        })
                    from utils.latex_ops import inject_meta_data
                    full_text = inject_meta_data(full_text, meta_dict)
                    try:
                        new_id = create_question_file(
                            s_file_path,
                            full_text,
                            s_year,
                            s_type,
                            s_paper,
                            s_num,
                            s_subj,
                            allow_duplicate=allow_duplicate,
                        )
                        solve_key = "cloze_auto_solve" if cloze_mode else "entry_auto_solve"
                        should_auto_solve = st.session_state.get(solve_key, False)
                        if cloze_mode:
                            should_auto_solve = should_auto_solve and not _has_nonempty_answer_and_solution(full_text)
                        if should_auto_solve:
                            problem_tex = _extract_problem_env(full_text)
                            with st.spinner("🤖 AI 正在生成解答..."):
                                res = call_ai_for_answer_solutions(problem_tex, fast=False)
                            if "error" in res:
                                st.toast(f"自动生成解答失败: {res['error']}", icon="❌")
                            else:
                                try:
                                    _apply_generated_answer_solutions_to_file(s_file_path, res["answer_tex"], res["solutions_tex"], mode="replace")
                                    st.toast("已自动生成并写回解答", icon="🪄")
                                except Exception as e:
                                    st.toast(f"写回解答失败: {e}", icon="❌")
                        st.toast(f"成功保存到: {s_filename} (分配ID: {new_id})", icon="✅")
                        clear_statistics_cache()
                        st.session_state["entry_year"] = s_year
                        st.session_state["entry_p_type"] = s_type
                        st.session_state["entry_paper_name"] = s_paper
                        st.session_state["entry_number"] = s_num
                        st.session_state["entry_subject_multi"] = [s.strip() for s in (s_subj or "").split("，") if s.strip() and s.strip() in SUBJECTS]
                        st.session_state["entry_subject_user_locked"] = True
                        st.session_state["entry_content"] = ""
                        st.session_state["entry_difficulty"] = 0.0
                        st.session_state["entry_custom_tags"] = ""
                        st.session_state["entry_remark"] = ""
                        st.session_state["entry_number"] = ""
                    except Exception as e:
                        st.toast(f"保存失败: {e}", icon="❌")
                pending_duplicate = st.session_state.get("entry_duplicate_warning") or {}
                if pending_duplicate.get("matches"):
                    st.warning("检测到相同或高度相似题目。再次点击保存将保留当前题目。")
                    for match in pending_duplicate["matches"][:3]:
                        st.caption(
                            f"{'完全重复' if match.get('kind') == 'exact' else '相似'} "
                            f"{match.get('score', 0) * 100:.1f}%：{match.get('name') or match.get('relative_path')}"
                        )
                save_label = "⚠️ 确认仍然保存" if pending_duplicate.get("matches") else "💾 保存题目"
                st.markdown('<span id="entry-save-button-anchor"></span>', unsafe_allow_html=True)
                st.button(save_label, type="primary", on_click=on_save_entry, use_container_width=True)
            filename = generate_filename(year, p_type_code, paper_name, number, subject or "未分类")
            st.info(f"目标文件名: `{filename}`")
            if cloze_mode:
                img_res = st.session_state.get("cloze_image_result")
                if img_res:
                    if img_res.get("ok"):
                        st.success(f"图片已生成：{img_res.get('path')}")
                        st.download_button(
                            "下载当前图片",
                            data=img_res.get("bytes") or b"",
                            file_name=img_res.get("filename") or "挖空题.png",
                            mime="image/png",
                            use_container_width=True,
                            key="cloze_download_current_image",
                        )
                    else:
                        st.warning(img_res.get("error", "图片生成失败"))
                        if img_res.get("log"):
                            with st.expander("查看 LaTeX 编译日志", expanded=False):
                                st.code(img_res["log"])
            if content.strip():
                st.markdown("---")
                try:
                    md_preview = latex_to_markdown(content, show_title=True)
                    st.markdown(md_preview, unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"预览渲染出错: {e}")
        else:
            st.empty()
                             

def _topic_collection_key(*parts) -> str:
    raw = "_".join(str(part or "empty") for part in parts)
    return "topic_collection_" + re.sub(r"[^0-9a-zA-Z_]+", "_", raw)[:120]


def _topic_collection_label(topic: dict) -> str:
    module = str(topic.get("module_name") or "未分类专题").strip()
    name = str(topic.get("name") or topic.get("topic_id") or "未命名专题").strip()
    count = int(topic.get("question_link_count") or 0)
    return f"{module} · {name} · {count} 题"


def _topic_collection_question_source(row: dict) -> str:
    bits = []
    year = row.get("detected_year")
    if year not in (None, ""):
        bits.append(str(year))
    source = str(row.get("detected_source") or "").strip()
    number = str(row.get("detected_question_number") or "").strip()
    chapter = str(row.get("detected_chapter") or "").strip()
    if source:
        bits.append(source)
    if number:
        bits.append(f"第{number}题")
    if chapter:
        bits.append(chapter)
    return " ".join(bits) or str(row.get("legacy_file_path") or "").strip() or "来源未登记"


def _topic_collection_group_value(value: str) -> str:
    cleaned = str(value or "").strip()
    return "" if cleaned in {"默认分组", "无分组"} else cleaned


def _topic_collection_add_result_message(result: dict):
    added_count = int(result.get("added_count") or 0)
    skipped_count = int(result.get("skipped_count") or 0)
    if added_count:
        st.success(f"已收录 {added_count} 道题。")
    if skipped_count:
        skipped = result.get("skipped") or []
        preview = "；".join(f"{item.get('question_id')}：{item.get('reason')}" for item in skipped[:6])
        st.warning(f"跳过 {skipped_count} 道题。{preview}")
    if not added_count and not skipped_count:
        st.info("没有可收录的题目。")


def _topic_collection_intro_preview(title: str, tex: str):
    st.markdown(f"**{title}预览**")
    if not str(tex or "").strip():
        st.info(f"{title}为空。")
        return
    try:
        render_question_preview(str(tex), show_title=False)
    except Exception as exc:
        st.warning(f"预览失败：{exc}")
        st.code(str(tex), language="latex")


@st.dialog("编辑专题引言", width="large")
def _topic_collection_intro_dialog(topic_id: str, field: str):
    from services.database_service import DEFAULT_DATABASE_PATH
    from services.topic_service import get_topic, update_topic_intro

    topic = get_topic(DEFAULT_DATABASE_PATH, topic_id)
    if not topic:
        st.error("专题不存在，无法编辑引言。")
        return

    field = field if field in {"problem_intro_tex", "answer_intro_tex"} else "problem_intro_tex"
    title = "试题引言" if field == "problem_intro_tex" else "答案引言"
    state_key = _topic_collection_key("intro", topic_id, field)
    if state_key not in st.session_state:
        st.session_state[state_key] = topic.get(field) or ""

    st.markdown(f"#### {html.escape(topic.get('name') or '')} · {title}", unsafe_allow_html=True)
    left, right = st.columns([1, 1], gap="large")
    with left:
        value = st.text_area(
            f"{title} TeX",
            key=state_key,
            height=520,
            help="这里保存为专题级 TeX 片段，导出专题时会插入到对应位置。",
        )
    with right:
        _topic_collection_intro_preview(title, value)

    c_save, c_close = st.columns([1, 1], gap="small")
    with c_save:
        if st.button("保存引言", key=_topic_collection_key("save_intro", topic_id, field), type="primary", use_container_width=True):
            try:
                if field == "problem_intro_tex":
                    update_topic_intro(DEFAULT_DATABASE_PATH, topic_id, problem_intro_tex=value)
                else:
                    update_topic_intro(DEFAULT_DATABASE_PATH, topic_id, answer_intro_tex=value)
                record_operation("topic_collection_intro_update", details=f"{topic_id}:{field}")
                st.session_state.pop(_topic_collection_key("topic_cache_token"), None)
                st.toast("专题引言已保存", icon="✅")
                st.rerun()
            except Exception as exc:
                st.error(f"保存失败：{exc}")
    with c_close:
        if st.button("关闭", key=_topic_collection_key("close_intro", topic_id, field), use_container_width=True):
            st.rerun()


@st.dialog("三级搜索添加题目", width="large")
def _topic_collection_three_level_dialog(topic_id: str, target_group: str, target_note: str):
    from services.database_service import DEFAULT_DATABASE_PATH
    from services.question_db_service import QuestionListFilters, list_question_filter_options, list_questions_page
    from services.topic_service import add_questions_to_topic

    db_path = DEFAULT_DATABASE_PATH
    st.markdown(
        "<div class='mc-topic-dialog-title'>按“知识板块 → 年份 → 题目”定位，并在右侧即时预览。</div>",
        unsafe_allow_html=True,
    )
    keyword = st.text_input(
        "关键词",
        key=_topic_collection_key("three_level_keyword", topic_id),
        placeholder="可选；支持用 / 分隔多个必须同时匹配的词",
    )

    try:
        base_options = list_question_filter_options(db_path, QuestionListFilters(keyword=keyword.strip()))
        chapter_options = ["全部板块"] + list(base_options.get("chapters") or [])
    except Exception as exc:
        st.error(f"读取筛选项失败：{exc}")
        return

    filter_col_1, filter_col_2, filter_col_3, filter_col_4 = st.columns([1.18, 0.82, 0.72, 0.72], gap="small")
    with filter_col_1:
        chapter_pick = st.selectbox("1级：知识板块", chapter_options, key=_topic_collection_key("three_level_chapter", topic_id))
    chapter = "" if chapter_pick == "全部板块" else str(chapter_pick)

    try:
        staged_options = list_question_filter_options(db_path, QuestionListFilters(keyword=keyword.strip(), chapter=chapter))
        year_options = ["全部年份"] + [str(year) for year in staged_options.get("years") or []]
    except Exception as exc:
        st.error(f"读取年份失败：{exc}")
        return

    with filter_col_2:
        year_pick = st.selectbox("2级：年份", year_options, key=_topic_collection_key("three_level_year", topic_id))
    year = None if year_pick == "全部年份" else int(year_pick)
    with filter_col_3:
        page_size = st.selectbox("每页", [5, 10, 15, 20], index=1, key=_topic_collection_key("three_level_size", topic_id))

    first_page = list_questions_page(
        db_path,
        QuestionListFilters(keyword=keyword.strip(), chapter=chapter, year=year, limit=int(page_size), offset=0),
    )
    total = int(first_page.get("total") or 0)
    page_count = max(1, int(first_page.get("page_count") or 1))
    page_key = _topic_collection_key("three_level_page", topic_id)
    if int(st.session_state.get(page_key, 1) or 1) > page_count:
        st.session_state[page_key] = page_count
    with filter_col_4:
        page_number = st.number_input("页码", min_value=1, max_value=page_count, value=int(st.session_state.get(page_key, 1) or 1), step=1, key=page_key)

    page = (
        first_page
        if int(page_number) == 1
        else list_questions_page(
            db_path,
            QuestionListFilters(
                keyword=keyword.strip(),
                chapter=chapter,
                year=year,
                limit=int(page_size),
                offset=(int(page_number) - 1) * int(page_size),
            ),
        )
    )
    rows = list(page.get("items") or [])
    st.markdown(
        f"<div class='mc-topic-search-meta'>找到 <strong>{total}</strong> 道匹配题目 · 第 {int(page_number)}/{page_count} 页</div>",
        unsafe_allow_html=True,
    )
    if not rows:
        st.info("当前筛选下没有题目。")
        return

    row_by_id = {str(row.get("question_id")): row for row in rows}

    def _format_question_option(question_id: str) -> str:
        row = row_by_id.get(str(question_id), {})
        source = _topic_collection_question_source(row)
        stem = str(row.get("stem_tex") or "").replace("\n", " ").strip()
        return f"{question_id} · {source} · {stem[:52]}"

    selected_key = _topic_collection_key("three_level_selected", topic_id)
    question_ids = list(row_by_id.keys())
    if st.session_state.get(selected_key) not in question_ids:
        st.session_state[selected_key] = question_ids[0]

    choose_col, preview_col = st.columns([0.92, 1.35], gap="large")
    with choose_col:
        selected_question_id = st.selectbox(
            "3级：题目",
            question_ids,
            key=selected_key,
            format_func=_format_question_option,
        )
        selected_row = row_by_id.get(str(selected_question_id), {})
        st.markdown(
            f"""
            <div class="mc-topic-dialog-card">
                <span class="mc-topic-pill purple">{html.escape(str(selected_row.get('detected_chapter') or '未登记板块'))}</span>
                <span class="mc-topic-pill blue">{html.escape(str(selected_row.get('detected_year') or '未登记年份'))}</span>
                <span class="mc-topic-pill">{html.escape(str(selected_row.get('detected_source') or '未登记来源'))}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        add_col_1, add_col_2 = st.columns([1, 1], gap="small")
        with add_col_1:
            if st.button("加入选中题目", key=_topic_collection_key("three_level_add_one", topic_id), type="primary", use_container_width=True):
                try:
                    result = add_questions_to_topic(
                        db_path,
                        topic_id,
                        [str(selected_question_id)],
                        group_name=target_group,
                        topic_note=target_note,
                    )
                    record_operation("topic_collection_add_questions", details=f"{topic_id}: three_level={selected_question_id}")
                    _topic_collection_add_result_message(result)
                    st.session_state["topic_collection_preview_question_id"] = str(selected_question_id)
                    st.rerun()
                except Exception as exc:
                    st.error(f"加入失败：{exc}")
        with add_col_2:
            if st.button("加入当前页", key=_topic_collection_key("three_level_add_page", topic_id), use_container_width=True):
                try:
                    result = add_questions_to_topic(
                        db_path,
                        topic_id,
                        question_ids,
                        group_name=target_group,
                        topic_note=target_note,
                    )
                    record_operation("topic_collection_add_questions", details=f"{topic_id}: three_level_page={len(question_ids)}")
                    _topic_collection_add_result_message(result)
                    st.rerun()
                except Exception as exc:
                    st.error(f"加入失败：{exc}")

    with preview_col:
        st.markdown("<div class='mc-topic-dialog-preview-title'>题目预览</div>", unsafe_allow_html=True)
        try:
            db_mtime = os.path.getmtime(db_path)
            payload = _db_preview_question_payload(db_path, str(selected_question_id), db_mtime)
            with st.expander("TeX 源码", expanded=False):
                st.code(payload.get("legacy_tex") or "", language="latex")
            render_question_preview(payload.get("legacy_tex") or "", show_title=False, prepared_markdown=payload.get("preview_markdown"))
        except Exception as exc:
            st.error(f"题目预览失败：{exc}")


def _topic_collection_render_css():
    st.markdown(
        """
        <style>
        .mc-topic-page-anchor,
        .mc-topic-sidebar-anchor {
            display: none !important;
        }
        body:has(.mc-topic-page-anchor) .main .block-container {
            padding-top: 1.05rem !important;
        }
        div[data-testid="stHorizontalBlock"]:has(> div[data-testid="column"] .mc-topic-sidebar-anchor) {
            align-items: flex-start !important;
            gap: 1rem !important;
        }
        div[data-testid="stHorizontalBlock"]:has(> div[data-testid="column"] .mc-topic-sidebar-anchor) > div:first-child {
            flex: 0 0 22rem !important;
            max-width: 22rem !important;
            min-width: 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(> div[data-testid="column"] .mc-topic-sidebar-anchor) > div:last-child {
            min-width: 0 !important;
        }
        div[data-testid="column"]:has(.mc-topic-sidebar-anchor) {
            position: sticky !important;
            top: 0.72rem !important;
            align-self: flex-start !important;
            z-index: 8 !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mc-topic-sidebar-anchor) {
            padding: 0.95rem !important;
            border: 1px solid rgba(109, 40, 217, 0.14) !important;
            border-radius: 16px !important;
            background: #ffffff !important;
            box-shadow: 0 10px 28px rgba(15, 23, 42, 0.055) !important;
            max-height: calc(100vh - 1.45rem) !important;
            overflow-y: auto !important;
            overflow-x: hidden !important;
        }
        .mc-topic-title {
            margin: 0.1rem 0 0.18rem;
            color: #111827;
            font-size: clamp(1.55rem, 2.2vw, 2.05rem);
            line-height: 1.18;
            font-weight: 830;
            letter-spacing: -0.025em;
        }
        .mc-topic-subtitle {
            margin: 0 0 0.85rem;
            color: #6b7280;
            font-size: 0.92rem;
            line-height: 1.55;
        }
        .mc-topic-panel-title {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.8rem;
            margin-bottom: 0.66rem;
            color: #1f2937;
            font-size: 1.05rem;
            line-height: 1.25;
            font-weight: 820;
        }
        .mc-topic-panel-title span {
            color: #6d28d9;
            font-size: 0.82rem;
            font-weight: 760;
            text-align: right;
        }
        .mc-topic-kv-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
            margin: 0.34rem 0 0.76rem;
        }
        .mc-topic-pill {
            display: inline-flex;
            align-items: center;
            max-width: 100%;
            padding: 0.18rem 0.52rem;
            border-radius: 999px;
            background: #f3f4f6;
            color: #374151;
            font-size: 0.8rem;
            font-weight: 680;
            line-height: 1.35;
            overflow-wrap: anywhere;
        }
        .mc-topic-pill.purple {
            background: #f3e8ff;
            color: #6d28d9;
        }
        .mc-topic-pill.blue {
            background: #e0f2fe;
            color: #0369a1;
        }
        .mc-topic-pill.green {
            background: #dcfce7;
            color: #166534;
        }
        .mc-topic-empty {
            padding: 1.05rem;
            border: 1px dashed rgba(109, 40, 217, 0.28);
            border-radius: 14px;
            background: #faf5ff;
            color: #5b21b6;
            font-weight: 720;
        }
        .mc-topic-list-divider {
            height: 1px;
            margin: 1.05rem 0 0.82rem;
            background: linear-gradient(90deg, rgba(109, 40, 217, 0.22), rgba(14, 165, 233, 0.16), rgba(148, 163, 184, 0.04));
        }
        .mc-topic-dialog-title {
            margin: -0.2rem 0 0.7rem;
            color: #4b5563;
            font-size: 0.92rem;
            line-height: 1.55;
            font-weight: 680;
        }
        .mc-topic-search-meta {
            margin: 0.35rem 0 0.75rem;
            padding: 0.45rem 0.65rem;
            border-radius: 10px;
            background: #f8fafc;
            color: #475569;
            font-size: 0.86rem;
            font-weight: 680;
        }
        .mc-topic-search-meta strong {
            color: #6d28d9;
            font-weight: 820;
        }
        .mc-topic-dialog-card {
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem;
            margin: 0.45rem 0 0.8rem;
            padding: 0.6rem;
            border-radius: 12px;
            background: #fbfaff;
            border: 1px solid rgba(109, 40, 217, 0.12);
        }
        .mc-topic-dialog-preview-title {
            margin: 0.15rem 0 0.45rem;
            color: #1f2937;
            font-size: 1rem;
            font-weight: 820;
        }
        .mc-topic-table-head,
        .mc-topic-table-row {
            display: grid;
            grid-template-columns: 0.56fr 1fr 1.7fr minmax(0, 3.2fr) 1.1fr;
            gap: 0.5rem;
            align-items: start;
        }
        .mc-topic-table-head {
            padding: 0.5rem 0.62rem;
            border-radius: 10px;
            background: #f8fafc;
            color: #475569;
            font-size: 0.82rem;
            font-weight: 760;
        }
        .mc-topic-table-row {
            padding: 0.58rem 0.62rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.16);
            color: #334155;
            font-size: 0.86rem;
            line-height: 1.45;
        }
        .mc-topic-table-row strong {
            color: #111827;
        }
        .mc-topic-table-row span {
            color: #64748b;
            overflow-wrap: anywhere;
        }
        @media (max-width: 1100px) {
            div[data-testid="stHorizontalBlock"]:has(> div[data-testid="column"] .mc-topic-sidebar-anchor) > div:first-child {
                flex: 1 1 100% !important;
                max-width: 100% !important;
            }
            div[data-testid="column"]:has(.mc-topic-sidebar-anchor) {
                position: static !important;
            }
            .mc-topic-table-head,
            .mc-topic-table-row {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_topic_collection():
    from services.book_service import BookListFilters, list_book_questions, list_book_sections, list_books
    from services.database_service import DEFAULT_DATABASE_PATH
    from services.export_service import export_topic_to_tex, source_export_default_filename
    from services.paper_service import PaperListFilters, list_paper_questions, list_paper_years, list_papers
    from services.schema_migration_service import migration_status
    from services.topic_service import (
        TopicListFilters,
        add_questions_to_topic,
        count_topic_questions,
        delete_topic_question_link,
        get_topic,
        list_topic_groups,
        list_topic_modules,
        list_topic_questions,
        list_topics,
        resolve_question_lookups,
        update_topic_question_link,
        upsert_topic,
    )

    db_path = DEFAULT_DATABASE_PATH
    _topic_collection_render_css()
    st.markdown('<span class="mc-topic-page-anchor"></span><div class="mc-topic-title">📚 专题收录</div>', unsafe_allow_html=True)
    st.markdown(
        "<div class='mc-topic-subtitle'>建立专题、分组收录题目、维护导出引言，并从 SQLite 生成专题 TeX。</div>",
        unsafe_allow_html=True,
    )

    if not os.path.exists(db_path):
        st.error("未找到 SQLite 正式库。请先在工具箱 → 本地维护与升级中初始化本地数据库。")
        return

    try:
        schema_report = migration_status(db_path)
        if int(schema_report.get("current_version") or 0) < 2 and int(schema_report.get("target_version") or 0) >= 2:
            st.warning(
                "专题收录需要 SQLite schema version 2。当前正式库仍有 0002_topic_intro_fields 待迁移；"
                "可以先浏览目录，但新建专题、保存专题引言或导出前请到“工具箱 → 本地维护与升级”应用数据库升级。"
            )
    except Exception as exc:
        st.info(f"未能读取 schema 迁移状态：{exc}")

    try:
        modules = list_topic_modules(db_path)
    except Exception as exc:
        st.error(f"读取专题模块失败：{exc}")
        return

    left_col, right_col = st.columns([1.06, 2.7], gap="large")
    with left_col:
        st.markdown(
            '<span class="mc-topic-sidebar-anchor"></span><div class="mc-topic-panel-title">专题目录</div>',
            unsafe_allow_html=True,
        )
        if st.button("新建专题", key="topic_collection_new_topic", type="primary", use_container_width=True):
            st.session_state["topic_collection_selected_topic_id"] = ""
            st.session_state["topic_collection_new_mode"] = True
            st.rerun()

        module_options = ["全部模块"] + [str(item.get("module_id")) for item in modules]
        module_label = {"全部模块": "全部模块"}
        module_label.update({str(item.get("module_id")): f"{item.get('name') or '未命名'} · {item.get('question_link_count') or 0} 题" for item in modules})
        module_filter = st.selectbox(
            "筛选大专题",
            module_options,
            key="topic_collection_module_filter",
            format_func=lambda value: module_label.get(value, value),
        )
        keyword = st.text_input("搜索专题", key="topic_collection_keyword", placeholder="输入专题名称 / 文件名")
        filters = TopicListFilters(
            module_id="" if module_filter == "全部模块" else module_filter,
            keyword=keyword.strip(),
            limit=200,
            offset=0,
        )
        try:
            topics = list_topics(db_path, filters)
        except Exception as exc:
            st.error(f"读取专题失败：{exc}")
            topics = []

        topic_ids = [str(item.get("topic_id")) for item in topics if item.get("topic_id")]
        creating_new_topic = bool(st.session_state.get("topic_collection_new_mode"))
        if topic_ids and not st.session_state.get("topic_collection_selected_topic_id") and not creating_new_topic:
            st.session_state["topic_collection_selected_topic_id"] = topic_ids[0]
        if topic_ids and not creating_new_topic:
            selected = st.selectbox(
                "选择专题",
                topic_ids,
                key="topic_collection_selected_topic_id",
                format_func=lambda value: _topic_collection_label(next((item for item in topics if item.get("topic_id") == value), {"topic_id": value})),
            )
            st.session_state["topic_collection_new_mode"] = False
            selected_preview = next((item for item in topics if item.get("topic_id") == selected), {})
            st.markdown(
                f"""
                <div class="mc-topic-kv-row">
                    <span class="mc-topic-pill purple">{html.escape(str(selected_preview.get('module_name') or '未分类专题'))}</span>
                    <span class="mc-topic-pill blue">{int(selected_preview.get('question_link_count') or 0)} 题</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        elif creating_new_topic:
            st.markdown("<div class='mc-topic-empty'>正在新建专题。填写下方专题信息后保存。</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='mc-topic-empty'>暂无匹配专题。可以点击“新建专题”。</div>", unsafe_allow_html=True)

    selected_topic_id = str(st.session_state.get("topic_collection_selected_topic_id") or "")
    new_mode = bool(st.session_state.get("topic_collection_new_mode")) or not selected_topic_id
    selected_topic = {}
    if selected_topic_id and not new_mode:
        try:
            selected_topic = get_topic(db_path, selected_topic_id)
        except Exception as exc:
            st.error(f"载入专题失败：{exc}")
            selected_topic = {}

    with left_col:
        st.markdown(
            f"""
            <div class="mc-topic-panel-title">专题信息</div>
            """,
            unsafe_allow_html=True,
        )
        form_scope = "new" if new_mode else selected_topic_id
        with st.form(key=_topic_collection_key("topic_form", form_scope), clear_on_submit=False):
            top_a, top_b, top_c = st.columns([1.1, 1.25, 1.1], gap="small")
            with top_a:
                module_name = st.text_input(
                    "大专题",
                    value=str(selected_topic.get("module_name") or ""),
                    key=_topic_collection_key("module_name", form_scope),
                    placeholder="例如：函数 / 不等式 / 自定义专题目录",
                )
            with top_b:
                topic_name = st.text_input(
                    "专题名称",
                    value=str(selected_topic.get("name") or ""),
                    key=_topic_collection_key("topic_name", form_scope),
                    placeholder="例如：复习：不等式",
                )
            with top_c:
                topic_file_name = st.text_input(
                    "文件名称",
                    value=str(selected_topic.get("file_name") or ""),
                    key=_topic_collection_key("file_name", form_scope),
                    placeholder="例如：RV-Inequality.tex",
                )
            desc_col, note_col = st.columns([1.25, 1], gap="small")
            with desc_col:
                topic_description = st.text_input(
                    "说明",
                    value=str(selected_topic.get("description") or ""),
                    key=_topic_collection_key("description", form_scope),
                    placeholder="可选",
                )
            with note_col:
                export_note = st.text_input(
                    "导出备注",
                    value=str(selected_topic.get("export_note") or ""),
                    key=_topic_collection_key("export_note", form_scope),
                    placeholder="可选，写入专题元信息",
                )
            submitted = st.form_submit_button("保存专题信息", type="primary", use_container_width=True)
        if submitted:
            try:
                topic = upsert_topic(
                    db_path,
                    module_name=module_name,
                    name=topic_name,
                    file_name=topic_file_name,
                    description=topic_description,
                    problem_intro_tex=selected_topic.get("problem_intro_tex") or "",
                    answer_intro_tex=selected_topic.get("answer_intro_tex") or "",
                    export_note=export_note,
                )
                st.session_state["topic_collection_selected_topic_id"] = topic["topic_id"]
                st.session_state["topic_collection_new_mode"] = False
                record_operation("topic_collection_upsert", details=f"{topic.get('topic_id')} {topic.get('name')}")
                st.toast("专题信息已保存", icon="✅")
                st.rerun()
            except Exception as exc:
                st.error(f"保存专题失败：{exc}")

        if not selected_topic:
            st.markdown("<div class='mc-topic-empty'>保存专题后，右侧会显示添加题目入口。</div>", unsafe_allow_html=True)
        else:
            topic_id = str(selected_topic.get("topic_id") or "")
            groups = list_topic_groups(db_path, topic_id)
            total_questions = count_topic_questions(db_path, topic_id)
            st.markdown(
                f"""
                <div class="mc-topic-kv-row">
                    <span class="mc-topic-pill purple">{html.escape(str(selected_topic.get('module_name') or '未分类专题'))}</span>
                    <span class="mc-topic-pill blue">{html.escape(str(selected_topic.get('file_name') or '未设置文件名'))}</span>
                    <span class="mc-topic-pill green">{total_questions} 题</span>
                    <span class="mc-topic-pill">{len(groups)} 个分组</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            problem_intro_done = "已填写" if str(selected_topic.get("problem_intro_tex") or "").strip() else "未填写"
            answer_intro_done = "已填写" if str(selected_topic.get("answer_intro_tex") or "").strip() else "未填写"
            if st.button(f"编辑试题引言 · {problem_intro_done}", key=_topic_collection_key("problem_intro", topic_id), use_container_width=True):
                _topic_collection_intro_dialog(topic_id, "problem_intro_tex")
            if st.button(f"编辑答案引言 · {answer_intro_done}", key=_topic_collection_key("answer_intro", topic_id), use_container_width=True):
                _topic_collection_intro_dialog(topic_id, "answer_intro_tex")

            export_dir = os.path.join(BASE_DIR, "exports", "topic_collection_exports", datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
            if st.button("生成专题 TeX", key=_topic_collection_key("export", topic_id), type="primary", use_container_width=True):
                try:
                    ensure_dir(export_dir)
                    filename = source_export_default_filename("topic", selected_topic)
                    output_path = os.path.join(export_dir, filename)
                    result = export_topic_to_tex(db_path, topic_id, output_path, project_root=APP_ROOT, resolve_questionassets=True)
                    with open(output_path, "r", encoding="utf-8") as file_obj:
                        tex_data = file_obj.read()
                    result.update({"tex_data": tex_data, "file_name": filename, "output_path": output_path})
                    st.session_state[_topic_collection_key("last_export", topic_id)] = result
                    record_operation("topic_collection_export", details=_db_preview_relative_path(output_path))
                    st.toast("专题 TeX 已生成", icon="✅")
                except Exception as exc:
                    st.error(f"导出失败：{exc}")
            last_export = st.session_state.get(_topic_collection_key("last_export", topic_id)) or {}
            if last_export:
                st.success(f"已导出 {last_export.get('question_count') or 0} 题")
                st.download_button(
                    "下载专题 TeX",
                    data=last_export.get("tex_data") or "",
                    file_name=last_export.get("file_name") or "topic_export.tex",
                    mime="text/x-tex",
                    key=_topic_collection_key("download", topic_id, last_export.get("file_name")),
                    use_container_width=True,
                )

    if not selected_topic:
        with right_col:
            st.markdown("<div class='mc-topic-empty'>请先在左侧选择或新建并保存一个专题。</div>", unsafe_allow_html=True)
        return

    topic_id = str(selected_topic.get("topic_id") or "")
    groups = list_topic_groups(db_path, topic_id)
    total_questions = count_topic_questions(db_path, topic_id)
    with right_col:
        group_options = ["A组", "B组", "默认分组"] + [
            str(item.get("group_name") or "默认分组")
            for item in groups
            if str(item.get("group_name") or "默认分组") not in {"A组", "B组", "默认分组"}
        ]
        group_options = list(dict.fromkeys(group_options))
        st.markdown("<div class='mc-topic-panel-title'>添加题目<span>编号 / 三级搜索 / 试卷 / 教材</span></div>", unsafe_allow_html=True)
        target_group_col, target_note_col, target_search_col = st.columns([0.74, 1.18, 0.88], gap="small")
        with target_group_col:
            target_group_pick = st.selectbox("目标分组", group_options, key=_topic_collection_key("target_group", topic_id))
            target_group = _topic_collection_group_value(target_group_pick)
        with target_note_col:
            target_note = st.text_input("收录备注", key=_topic_collection_key("target_note", topic_id), placeholder="可选，写入每道题的专题备注")
        with target_search_col:
            st.markdown("<div style='height:1.78rem'></div>", unsafe_allow_html=True)
            if st.button("三级搜索选题", key=_topic_collection_key("three_level_open", topic_id), type="primary", use_container_width=True):
                _topic_collection_three_level_dialog(topic_id, target_group, target_note)

        add_tabs = st.tabs(["按编号", "按试卷", "按课本"])
        with add_tabs[0]:
            raw_qids = st.text_area(
                "题目编号 / qid",
                key=_topic_collection_key("raw_qids", topic_id),
                height=96,
                placeholder="支持 Q000001、旧数字 ID；多个编号用逗号、顿号或换行分隔。",
            )
            c_resolve, c_add = st.columns([1, 1], gap="small")
            with c_resolve:
                if st.button("检查编号", key=_topic_collection_key("resolve_qids", topic_id), use_container_width=True):
                    try:
                        lookup_report = resolve_question_lookups(db_path, raw_qids)
                        st.session_state[_topic_collection_key("lookup_report", topic_id)] = lookup_report
                    except Exception as exc:
                        st.error(f"检查失败：{exc}")
            with c_add:
                if st.button("加入专题", key=_topic_collection_key("add_qids", topic_id), type="primary", use_container_width=True):
                    try:
                        lookup_report = resolve_question_lookups(db_path, raw_qids)
                        qids = [item["question_id"] for item in lookup_report.get("resolved") or []]
                        result = add_questions_to_topic(db_path, topic_id, qids, group_name=target_group, topic_note=target_note)
                        record_operation("topic_collection_add_questions", details=f"{topic_id}: qids={len(qids)}")
                        _topic_collection_add_result_message(result)
                    except Exception as exc:
                        st.error(f"加入失败：{exc}")
            lookup_report = st.session_state.get(_topic_collection_key("lookup_report", topic_id)) or {}
            if lookup_report:
                st.caption(f"已识别 {len(lookup_report.get('resolved') or [])}/{lookup_report.get('input_count') or 0} 个编号。")
                if lookup_report.get("unresolved"):
                    st.warning("未找到：" + "，".join(lookup_report["unresolved"][:12]))

        with add_tabs[1]:
            years = ["全部年份"] + [str(year) for year in list_paper_years(db_path)]
            paper_filter_cols = st.columns([0.72, 1.28], gap="small")
            with paper_filter_cols[0]:
                paper_year_pick = st.selectbox("年份", years, key=_topic_collection_key("paper_year", topic_id))
            with paper_filter_cols[1]:
                paper_keyword = st.text_input("试卷关键词", key=_topic_collection_key("paper_keyword", topic_id), placeholder="卷名 / 来源")
            paper_filters = PaperListFilters(
                year=None if paper_year_pick == "全部年份" else int(paper_year_pick),
                keyword=paper_keyword.strip(),
                limit=120,
                offset=0,
            )
            papers = list_papers(db_path, paper_filters)
            paper_ids = [str(item.get("paper_id")) for item in papers if item.get("paper_id")]
            paper_label = {
                str(item.get("paper_id")): f"{item.get('year') or ''} {item.get('track') or ''} {item.get('paper_name') or item.get('source_name') or ''} · {item.get('question_count') or 0} 题"
                for item in papers
            }
            if paper_ids:
                selected_paper_id = st.selectbox("选择试卷", paper_ids, key=_topic_collection_key("paper_pick", topic_id), format_func=lambda value: paper_label.get(value, value))
                if st.button("加入选中试卷全部题目", key=_topic_collection_key("add_paper", topic_id), use_container_width=True):
                    try:
                        paper_questions = list_paper_questions(db_path, selected_paper_id)
                        qids = [row["question_id"] for row in paper_questions]
                        result = add_questions_to_topic(db_path, topic_id, qids, group_name=target_group, topic_note=target_note)
                        record_operation("topic_collection_add_questions", details=f"{topic_id}: paper={selected_paper_id} qids={len(qids)}")
                        _topic_collection_add_result_message(result)
                    except Exception as exc:
                        st.error(f"加入试卷失败：{exc}")
            else:
                st.info("没有匹配试卷。")

        with add_tabs[2]:
            book_keyword = st.text_input("教材关键词", key=_topic_collection_key("book_keyword", topic_id), placeholder="出版社 / 书名 / 册次")
            books = list_books(db_path, BookListFilters(keyword=book_keyword.strip(), limit=120, offset=0))
            book_ids = [str(item.get("book_id")) for item in books if item.get("book_id")]
            book_label = {
                str(item.get("book_id")): f"{item.get('title') or ''} {item.get('grade') or ''} {item.get('volume') or ''} · {item.get('question_link_count') or 0} 题"
                for item in books
            }
            if book_ids:
                selected_book_id = st.selectbox("选择教材", book_ids, key=_topic_collection_key("book_pick", topic_id), format_func=lambda value: book_label.get(value, value))
                sections = list_book_sections(db_path, selected_book_id)
                section_options = ["整本书"] + [str(item.get("section_id")) for item in sections if item.get("section_id")]
                section_label = {"整本书": "整本书"}
                section_label.update({str(item.get("section_id")): f"{item.get('title') or '未命名栏目'} · {item.get('question_link_count') or 0} 题" for item in sections})
                selected_section = st.selectbox("栏目", section_options, key=_topic_collection_key("book_section", topic_id), format_func=lambda value: section_label.get(value, value))
                if st.button("加入选中教材题目", key=_topic_collection_key("add_book", topic_id), use_container_width=True):
                    try:
                        book_questions = list_book_questions(
                            db_path,
                            selected_book_id,
                            "" if selected_section == "整本书" else selected_section,
                            limit=500,
                        )
                        qids = [row["question_id"] for row in book_questions]
                        result = add_questions_to_topic(db_path, topic_id, qids, group_name=target_group, topic_note=target_note)
                        record_operation("topic_collection_add_questions", details=f"{topic_id}: book={selected_book_id} qids={len(qids)}")
                        _topic_collection_add_result_message(result)
                    except Exception as exc:
                        st.error(f"加入教材失败：{exc}")
            else:
                st.info("没有匹配教材。")

    st.markdown("<div class='mc-topic-list-divider'></div>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='mc-topic-panel-title'>完整题目列表<span>{total_questions} 题</span></div>",
        unsafe_allow_html=True,
    )
    list_cols = st.columns([0.72, 0.72, 0.72, 0.72], gap="small")
    with list_cols[0]:
        group_filter_options = ["全部分组"] + group_options
        group_filter = st.selectbox("显示分组", group_filter_options, key=_topic_collection_key("group_filter", topic_id))
        query_group = "" if group_filter == "全部分组" else _topic_collection_group_value(group_filter)
    with list_cols[1]:
        page_size = st.selectbox("每页", [10, 20, 50, 100], index=1, key=_topic_collection_key("page_size", topic_id))
    visible_total = count_topic_questions(db_path, topic_id, query_group)
    page_count = max(1, (visible_total + int(page_size) - 1) // int(page_size))
    page_key = _topic_collection_key("page", topic_id)
    if int(st.session_state.get(page_key, 1) or 1) > page_count:
        st.session_state[page_key] = page_count
    with list_cols[2]:
        page_number = st.number_input("页码", min_value=1, max_value=page_count, value=int(st.session_state.get(page_key, 1) or 1), key=page_key)
    with list_cols[3]:
        st.markdown(f"<div style='height:1.9rem'></div><span class='mc-topic-pill blue'>第 {page_number}/{page_count} 页</span>", unsafe_allow_html=True)

    offset = (int(page_number) - 1) * int(page_size)
    question_rows = list_topic_questions(db_path, topic_id, query_group, limit=int(page_size), offset=offset)
    if not question_rows:
        st.markdown("<div class='mc-topic-empty'>当前专题还没有收录题目。</div>", unsafe_allow_html=True)
    else:
        st.markdown(
            "<div class='mc-topic-table-head'><div>#</div><div>题目编号</div><div>出处</div><div>题干</div><div>操作</div></div>",
            unsafe_allow_html=True,
        )
        for row_index, row in enumerate(question_rows, start=offset + 1):
            link_id = str(row.get("topic_question_id") or "")
            question_id = str(row.get("question_id") or "")
            source_label = _topic_collection_question_source(row)
            stem_preview = str(row.get("stem_preview") or "").replace("\n", " ").strip()
            st.markdown(
                f"""
                <div class="mc-topic-table-row">
                    <div><strong>{row_index}</strong></div>
                    <div><strong>{html.escape(question_id)}</strong><br><span>旧ID：{html.escape(str(row.get('legacy_id') or '无'))}</span></div>
                    <div><span>{html.escape(source_label)}</span></div>
                    <div>{html.escape(stem_preview[:220])}</div>
                    <div><span>{html.escape(str(row.get('group_name') or '默认分组'))} · {row.get('sort_order') or 0}</span></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            edit_cols = st.columns([0.75, 0.64, 1.5, 0.6, 0.6, 0.6], gap="small")
            with edit_cols[0]:
                row_group = st.text_input(
                    "分组",
                    value=str(row.get("group_name") or ""),
                    key=_topic_collection_key("row_group", link_id),
                    label_visibility="collapsed",
                    placeholder="分组",
                )
            with edit_cols[1]:
                row_order = st.number_input(
                    "排序",
                    value=int(row.get("sort_order") or 0),
                    min_value=0,
                    step=1,
                    key=_topic_collection_key("row_order", link_id),
                    label_visibility="collapsed",
                )
            with edit_cols[2]:
                row_note = st.text_input(
                    "备注",
                    value=str(row.get("topic_note") or ""),
                    key=_topic_collection_key("row_note", link_id),
                    label_visibility="collapsed",
                    placeholder="专题备注",
                )
            with edit_cols[3]:
                if st.button("保存", key=_topic_collection_key("save_row", link_id), use_container_width=True):
                    try:
                        update_topic_question_link(
                            db_path,
                            link_id,
                            group_name=row_group,
                            sort_order=row_order,
                            topic_note=row_note,
                        )
                        record_operation("topic_collection_update_row", question_id=question_id, details=link_id)
                        st.toast("题目收录信息已保存", icon="✅")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"保存失败：{exc}")
            with edit_cols[4]:
                if st.button("预览", key=_topic_collection_key("preview_row", link_id), use_container_width=True):
                    st.session_state["topic_collection_preview_question_id"] = question_id
            with edit_cols[5]:
                if st.button("删除", key=_topic_collection_key("delete_row", link_id), use_container_width=True):
                    try:
                        delete_topic_question_link(db_path, link_id)
                        record_operation("topic_collection_delete_link", question_id=question_id, details=link_id)
                        st.toast("已从专题移除", icon="✅")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"删除失败：{exc}")

    preview_question_id = str(st.session_state.get("topic_collection_preview_question_id") or "")
    if preview_question_id:
        with st.expander(f"题目预览 · {preview_question_id}", expanded=True):
            try:
                db_mtime = os.path.getmtime(db_path)
                payload = _db_preview_question_payload(db_path, preview_question_id, db_mtime)
                st.code(payload.get("legacy_tex") or "", language="latex")
                render_question_preview(payload.get("legacy_tex") or "", show_title=False, prepared_markdown=payload.get("preview_markdown"))
            except Exception as exc:
                st.error(f"题目预览失败：{exc}")


# ================= 组卷服务题目卡片 =================
def _toggle_exam_selection_path(fpath: str):
    selected_paths = list(st.session_state.setdefault("exam_selected_qs", []))
    if fpath in selected_paths:
        selected_paths = [p for p in selected_paths if p != fpath]
        if st.session_state.get("exam_expanded_q") == fpath:
            st.session_state["exam_expanded_q"] = selected_paths[0] if selected_paths else None
    else:
        selected_paths.append(fpath)
        st.session_state["exam_expanded_q"] = fpath
        st.session_state["exam_basket_open"] = True

    st.session_state["exam_selected_qs"] = selected_paths
    if "exam_blocks" in st.session_state:
        sync_exam_blocks_to_selected_order(selected_paths)
    if st.session_state.get("ai_exam_active"):
        st.session_state["ai_exam_modified"] = True


def _add_exam_selection_paths(paths):
    selected_paths = list(st.session_state.setdefault("exam_selected_qs", []))
    added_paths = []
    for fpath in paths or []:
        if fpath and os.path.exists(fpath) and fpath not in selected_paths:
            selected_paths.append(fpath)
            added_paths.append(fpath)

    if added_paths:
        st.session_state["exam_selected_qs"] = selected_paths
        st.session_state["exam_expanded_q"] = added_paths[-1]
        st.session_state["exam_basket_open"] = True
        if "exam_blocks" in st.session_state:
            sync_exam_blocks_to_selected_order(selected_paths)
        if st.session_state.get("ai_exam_active"):
            st.session_state["ai_exam_modified"] = True


def render_exam_question_card(q_label, content, fpath, action_key):
    """Render a focused, read-only question card for the exam-selection workflow."""
    from utils.latex_ops import parse_meta_data

    meta, _ = parse_meta_data(content)
    difficulty = (meta.get("难度星级", "") or "").strip() or "未设置"
    tags = (meta.get("标签", "") or "").strip() or "无标签"
    is_selected = fpath in st.session_state.get("exam_selected_qs", [])

    with st.container(border=True):
        st.markdown('<span class="mc-exam-card-anchor"></span>', unsafe_allow_html=True)
        title_col, action_col = st.columns([3.4, 1], gap="small", vertical_alignment="center")
        with title_col:
            state_label = "已加入组卷" if is_selected else "待选择"
            state_class = "selected" if is_selected else "available"
            st.markdown(
                f'<div class="mc-exam-card-title">{html.escape(q_label)}</div>'
                f'<span class="mc-exam-card-state {state_class}">{state_label}</span>',
                unsafe_allow_html=True,
            )
        with action_col:
            action_label = "移出组卷" if is_selected else "加入组卷"
            action_type = "primary" if is_selected else "secondary"
            st.button(action_label, key=action_key, type=action_type, use_container_width=True, on_click=_toggle_exam_selection_path, args=(fpath,))

        st.markdown(
            f'<div class="mc-exam-card-meta">'
            f'<span><strong>难度</strong> {html.escape(difficulty)}</span>'
            f'<span><strong>标签</strong> {html.escape(tags)}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="mc-exam-card-preview-label">问题预览</div>', unsafe_allow_html=True)
        try:
            st.markdown(_cached_latex_to_markdown(content), unsafe_allow_html=True)
        except Exception as e:
            st.error(f"渲染错误: {e}")


def _question_action_state_key(key_prefix, fhash):
    return f"{key_prefix}_pending_question_action_{fhash}"


def _set_pending_question_action(key_prefix, fhash, action):
    st.session_state[_question_action_state_key(key_prefix, fhash)] = action


def _pop_pending_question_action(key_prefix, fhash):
    return st.session_state.pop(_question_action_state_key(key_prefix, fhash), None)


def _render_native_question_actions(key_prefix, fhash, is_tag_editing, is_tex_editing):
    action = None
    st.markdown('<span class="mc-question-actions-grid-anchor"></span>', unsafe_allow_html=True)
    tex_label = "\U0001f4be \u4fdd\u5b58\u4fee\u6539" if is_tex_editing else "\u270f\ufe0f \u5f00\u59cb\u4fee\u6539tex\u5185\u5bb9"
    tex_action = "save_tex" if is_tex_editing else "start_tex_edit"
    tex_type = "primary" if is_tex_editing else "secondary"
    edit_label = "\u2705 \u4fdd\u5b58\u6587\u4ef6\u4fe1\u606f" if is_tag_editing else "\U0001f3f7\ufe0f \u4fee\u6539\u6587\u4ef6\u4fe1\u606f"
    edit_type = "primary" if is_tag_editing else "secondary"
    row1_col1, row1_col2, _ = st.columns([0.475, 0.475, 1.05], gap="small")
    row2_col1, row2_col2, _ = st.columns([0.475, 0.475, 1.05], gap="small")
    with row1_col1:
        if st.button(tex_label, key=f"{key_prefix}_tex_edit_{fhash}", type=tex_type, use_container_width=True, on_click=_set_pending_question_action, args=(key_prefix, fhash, tex_action)):
            action = tex_action
    with row1_col2:
        if st.button(edit_label, key=f"{key_prefix}_edit_meta_{fhash}", type=edit_type, use_container_width=True, on_click=_set_pending_question_action, args=(key_prefix, fhash, "edit_meta")):
            action = "edit_meta"
    with row2_col1:
        if st.button("\U0001f916 AI\u751f\u6210\u89e3\u7b54", key=f"{key_prefix}_ai_generate_{fhash}", use_container_width=True, on_click=_set_pending_question_action, args=(key_prefix, fhash, "ai_generate")):
            action = "ai_generate"
    with row2_col2:
        if st.button("\U0001f5bc\ufe0f \u89e3\u7b54\u56fe\u7247\u8bc6\u522b", key=f"{key_prefix}_image_ocr_{fhash}", use_container_width=True, on_click=_set_pending_question_action, args=(key_prefix, fhash, "image_ocr")):
            action = "image_ocr"
    return action


def render_browse_question_editor_card(q_label, content, fpath, key_prefix, paper_type_scope=None, extra_html_label="", rename_paths_key=None, prepared_assets=None, interactive_difficulty=True):
    prepared_assets = prepared_assets or {}
    render_question_header(
        q_label,
        content,
        fpath,
        extra_html_label=extra_html_label,
        compact=True,
        prepared_meta=prepared_assets.get("meta"),
        interactive_difficulty=interactive_difficulty,
    )

    tag_edit_key = f"{key_prefix}_tag_edit_mode_{_question_key('tag', fpath)}"
    tex_edit_key = f"{key_prefix}_tex_edit_mode_{_question_key('tex', fpath)}"
    text_area_key = f"{key_prefix}_edit_{_question_key('text', fpath)}"
    fhash = _question_key("meta", fpath)
    action = _pop_pending_question_action(key_prefix, fhash)
    is_tag_editing = st.session_state.get(tag_edit_key, False)
    is_tex_editing = st.session_state.get(tex_edit_key, False)
    if action == "start_tex_edit":
        st.session_state[tex_edit_key] = True
        st.session_state[text_area_key] = content
        is_tex_editing = True
    elif text_area_key not in st.session_state:
        st.session_state[text_area_key] = content
    current_content = st.session_state.get(text_area_key, content) if is_tex_editing else content
    if current_content == content and prepared_assets.get("editor_height") is not None:
        est_height = prepared_assets["editor_height"]
    else:
        est_height = _cached_editor_height(current_content)

    c_src, c_preview = st.columns([0.95, 1.05], gap="large")
    with c_src:
        if is_tex_editing:
            current_content = st.text_area("源码", height=est_height, key=text_area_key)
        else:
            st.text_area("源码", value=content, height=est_height, disabled=True, key=f"{text_area_key}_readonly")
            current_content = content

        if action == "save_tex":
            new_content = st.session_state.get(text_area_key, current_content)
            if not _duplicate_save_confirmation(fpath, new_content, scope=f"{key_prefix}:{fpath}"):
                st.rerun()
            final_content = save_modified_tex_file(fpath, new_content)
            _update_csv_index_for_content_change(fpath, final_content)
            _clear_advanced_search_result_cache()
            st.session_state[text_area_key] = final_content
            st.session_state[tex_edit_key] = False
            st.toast(f"{q_label} 已保存", icon="✅")
            time.sleep(0.5)
            st.rerun()

        if action == "edit_meta":
            if is_tag_editing:
                base = os.path.basename(fpath).replace(".tex", "")
                parts = base.split("-")
                if len(parts) >= 5:
                    old_year, old_ptype, old_pname, old_pnum, old_subj = parts[0], parts[1], parts[2], parts[3], parts[4]
                    new_year = st.session_state.get(f"{key_prefix}_meta_year_{fhash}", old_year)
                    new_type = st.session_state.get(f"{key_prefix}_meta_type_{fhash}", old_ptype)
                    new_name = st.session_state.get(f"{key_prefix}_meta_paper_{fhash}", old_pname)
                    new_num = st.session_state.get(f"{key_prefix}_meta_num_{fhash}", old_pnum)
                    new_subjects = st.session_state.get(f"{key_prefix}_tag_select_{fhash}", [old_subj])
                    new_subject_str = "，".join(new_subjects) if isinstance(new_subjects, list) else str(new_subjects or old_subj)
                    try:
                        rename_result = apply_meta_rename_and_update(fpath, str(new_year), str(new_type), str(new_name), str(new_num), new_subject_str)
                        new_path = rename_result[0] if isinstance(rename_result, tuple) else rename_result
                        if rename_paths_key and new_path:
                            old_list = st.session_state.get(rename_paths_key) or []
                            st.session_state[rename_paths_key] = [new_path if p == fpath else p for p in old_list]
                        if new_path and new_path != fpath:
                            new_text_key = f"{key_prefix}_edit_{_question_key('text', new_path)}"
                            st.session_state[new_text_key] = st.session_state.get(text_area_key, current_content)
                        st.session_state[tag_edit_key] = False
                        st.toast("修改成功！", icon="✅")
                        time.sleep(0.5)
                        st.rerun()
                    except Exception as e:
                        st.error(f"修改失败: {e}")
                else:
                    st.error("文件名格式不支持修改")
            else:
                st.session_state[tag_edit_key] = True
                st.rerun()

        if action == "ai_generate":
            problem_tex = _extract_problem_env(current_content)
            with st.spinner("🤖 AI 正在生成解答..."):
                res = call_ai_for_answer_solutions(problem_tex, fast=False)
            if "error" in res:
                st.toast(res["error"], icon="❌")
            else:
                combined = _normalize_ai_generated_tex_for_preview(res["answer_tex"].strip() + "\n\n" + res["solutions_tex"].strip())
                _, data_key, editor_key = _ai_sol_keys(fpath, "ai_solution_v1")
                st.session_state[data_key] = {"answer_tex": res["answer_tex"], "solutions_tex": res["solutions_tex"]}
                st.session_state[editor_key] = combined
                st.toast("已生成解答（未写回文件）", icon="🪄")
                st.rerun()

        if action == "image_ocr":
            ai_hash, _, _ = _ai_sol_keys(fpath, "ai_solution_v1")
            upload_open_key = f"ai_sol_upload_open_{ai_hash}"
            st.session_state[upload_open_key] = not st.session_state.get(upload_open_key, False)
            st.rerun()

        if is_tag_editing:
            base = os.path.basename(fpath).replace(".tex", "")
            parts = base.split("-")
            cur_year = parts[0] if len(parts) >= 5 else ""
            cur_type = parts[1] if len(parts) >= 5 else "G"
            cur_paper = parts[2] if len(parts) >= 5 else ""
            cur_num = parts[3] if len(parts) >= 5 else ""
            cur_subjects = (parts[4] if len(parts) >= 5 else "").split("，")
            valid_tags = [t for t in cur_subjects if t in SUBJECTS] or [SUBJECTS[0]]
            type_opts = _editable_paper_type_options(paper_type_scope)
            st.text_input("年份", value=str(cur_year), key=f"{key_prefix}_meta_year_{fhash}")
            if cur_type not in type_opts:
                cur_type = type_opts[0]
            st.selectbox("试卷类别", options=type_opts, index=type_opts.index(cur_type), format_func=lambda x: f"{x} ({PAPER_TYPES[x]})", key=f"{key_prefix}_meta_type_{fhash}")
            st.text_input("试卷名称", value=str(cur_paper), key=f"{key_prefix}_meta_paper_{fhash}")
            st.text_input("题号", value=str(cur_num), key=f"{key_prefix}_meta_num_{fhash}")
            st.multiselect("知识板块 (首个为主)", options=SUBJECTS, default=valid_tags, key=f"{key_prefix}_tag_select_{fhash}")

        render_ai_solution_image_ocr_section(fpath, key_prefix="ai_solution_v1", compact=True)

    with c_preview:
        try:
            prepared_markdown = None
            if current_content == content:
                prepared_markdown = prepared_assets.get("preview_markdown")
            render_question_preview(current_content, show_title=False, prepared_markdown=prepared_markdown)
        except Exception as e:
            st.error(f"渲染错误: {e}")

    _render_native_question_actions(key_prefix, fhash, is_tag_editing, is_tex_editing)

    render_ai_solution_panel(fpath, q_label, key_prefix="ai_solution_v1")


def sync_exam_blocks_to_selected_order(selected_paths):
    """Keep final typesetting order aligned with the floating basket order."""
    selected_paths = list(selected_paths or [])
    blocks = list(st.session_state.get("exam_blocks", []))
    existing_questions = {}
    for block in blocks:
        if block.get("type") == "question" and block.get("path") in selected_paths and block.get("path") not in existing_questions:
            existing_questions[block["path"]] = block

    ordered_questions = [
        existing_questions.get(path) or {"id": str(uuid.uuid4()), "type": "question", "path": path}
        for path in selected_paths
    ]
    ordered_iter = iter(ordered_questions)
    synced_blocks = []
    for block in blocks:
        if block.get("type") == "question":
            next_block = next(ordered_iter, None)
            if next_block is not None:
                synced_blocks.append(next_block)
        elif block.get("type") in ("chapter", "section", "subsection"):
            synced_blocks.append(block)
    synced_blocks.extend(list(ordered_iter))
    st.session_state["exam_blocks"] = synced_blocks


@st.fragment
def render_exam_floating_basket():
    selected_paths = st.session_state.setdefault("exam_selected_qs", [])
    selected_count = len(selected_paths)
    if "exam_basket_open" not in st.session_state:
        st.session_state["exam_basket_open"] = True
    if "exam_expanded_q" not in st.session_state:
        st.session_state["exam_expanded_q"] = selected_paths[0] if selected_paths else None
    if st.session_state.get("exam_expanded_q") not in selected_paths:
        st.session_state["exam_expanded_q"] = selected_paths[0] if selected_paths else None
    st.markdown(
        """
        <style>
        body:has(#mc-exam-page-anchor) div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-exam-floating-basket-anchor):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-exam-floating-basket-anchor)),
        .mc-exam-floating-basket-panel {
            position: fixed !important;
            right: 16px !important;
            left: auto !important;
            top: 104px !important;
            width: 560px !important;
            height: 150px !important;
            max-height: none !important;
            min-height: 150px !important;
            z-index: 1001 !important;
            overflow: auto !important;
            padding: 0.95rem !important;
            border: 1px solid rgba(119, 102, 142, 0.28) !important;
            border-radius: 12px !important;
            background: #faf8ff !important;
            background-color: #faf8ff !important;
            background-clip: padding-box !important;
            isolation: isolate !important;
            opacity: 1 !important;
            box-shadow: 0 18px 42px rgba(36, 28, 52, 0.20) !important;
        }
        body:has(#mc-exam-page-anchor) div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-exam-floating-basket-anchor):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-exam-floating-basket-anchor))::before,
        .mc-exam-floating-basket-panel::before {
            content: "";
            position: absolute;
            inset: 0;
            z-index: 0;
            border-radius: 12px;
            background: #faf8ff;
            pointer-events: none;
        }
        body:has(#mc-exam-page-anchor) div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-exam-floating-basket-anchor):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-exam-floating-basket-anchor)) > *,
        .mc-exam-floating-basket-panel > * {
            position: relative;
            z-index: 1;
        }
        .mc-exam-floating-basket-panel > div,
        .mc-exam-floating-basket-panel > div[data-testid="stVerticalBlock"],
        .mc-exam-floating-basket-panel div[data-testid="stVerticalBlock"],
        .mc-exam-floating-basket-panel div[data-testid="stHorizontalBlock"],
        .mc-exam-floating-basket-panel div[data-testid="column"],
        .mc-exam-floating-basket-panel div[data-testid="element-container"] {
            background: transparent !important;
            background-color: transparent !important;
            opacity: 1 !important;
        }
        .mc-exam-floating-basket-panel::after {
            content: "";
            position: absolute;
            right: 3px;
            bottom: 3px;
            width: 18px;
            height: 18px;
            background:
                linear-gradient(to right, transparent calc(100% - 2px), rgba(109, 40, 217, 0.50) calc(100% - 2px)),
                linear-gradient(to bottom, transparent calc(100% - 2px), rgba(109, 40, 217, 0.50) calc(100% - 2px));
            border-radius: 0 0 8px 0;
            cursor: nwse-resize;
            z-index: 3;
        }
        .mc-exam-floating-basket-collapsed-panel {
            position: fixed !important;
            right: 18px !important;
            top: 42vh !important;
            width: 142px !important;
            z-index: 1001 !important;
            padding: 0 !important;
            border: 0 !important;
            background: transparent !important;
            box-shadow: none !important;
        }
        .mc-exam-floating-basket-panel h4 {
            margin: 0 !important;
            cursor: move !important;
            user-select: none !important;
        }
        .mc-exam-floating-basket-panel div[data-testid="stHorizontalBlock"]:has(.mc-exam-basket-list-anchor) {
            gap: 1rem !important;
            align-items: start !important;
        }
        .mc-exam-floating-basket-panel div[data-testid="column"]:has(.mc-exam-basket-preview-anchor) {
            border-right: 1px solid rgba(119, 102, 142, 0.26) !important;
            padding-right: 1rem !important;
            max-height: calc(100vh - 270px) !important;
            overflow: auto !important;
        }
        .mc-exam-floating-basket-panel div[data-testid="column"]:has(.mc-exam-basket-list-anchor) {
            padding-left: 0.05rem !important;
        }
        .mc-exam-floating-basket-panel div[data-testid="stButton"] > button,
        .mc-exam-floating-basket-collapsed-panel div[data-testid="stButton"] > button {
            width: 100% !important;
            min-height: 2.35rem !important;
            border-radius: 9px !important;
            white-space: normal !important;
        }
        .mc-exam-floating-basket-collapsed-panel div[data-testid="stButton"] > button {
            border: 1px solid rgba(109, 40, 217, 0.30) !important;
            background: rgba(237, 229, 252, 0.98) !important;
            color: #4c1d95 !important;
            box-shadow: 0 12px 30px rgba(80, 60, 110, 0.18) !important;
            font-weight: 750 !important;
        }
        @media (max-width: 980px) {
            .mc-exam-floating-basket-panel {
                left: 72px !important;
                right: 12px !important;
                width: auto !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    components.html(
        """
        <script>
        (() => {
            const doc = window.parent.document;
            const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

            function findPanel() {
                const marker = doc.querySelector('.mc-exam-floating-basket-anchor');
                return marker ? marker.closest('div[data-testid="stVerticalBlockBorderWrapper"]') : null;
            }

            function markPanels() {
                doc.querySelectorAll('.mc-exam-floating-basket-panel').forEach((node) => {
                    if (!node.querySelector('.mc-exam-floating-basket-anchor')) {
                        node.classList.remove('mc-exam-floating-basket-panel');
                    }
                });
                doc.querySelectorAll('.mc-exam-floating-basket-collapsed-panel').forEach((node) => {
                    if (!node.querySelector('.mc-exam-floating-basket-collapsed-anchor')) {
                        node.classList.remove('mc-exam-floating-basket-collapsed-panel');
                    }
                });
                const panel = findPanel();
                if (panel) panel.classList.add('mc-exam-floating-basket-panel');
                const collapsedMarker = doc.querySelector('.mc-exam-floating-basket-collapsed-anchor');
                const collapsedPanel = collapsedMarker ? collapsedMarker.closest('div[data-testid="stVerticalBlockBorderWrapper"]') : null;
                if (collapsedPanel) collapsedPanel.classList.add('mc-exam-floating-basket-collapsed-panel');
                return panel;
            }

            function applyWidth(panel) {
                const sizeVersion = 'compact-v1';
                if (window.parent.localStorage.getItem('mcExamBasketSizeVersion') !== sizeVersion) {
                    window.parent.localStorage.removeItem('mcExamBasketWidth');
                    window.parent.localStorage.removeItem('mcExamBasketHeight');
                    window.parent.localStorage.setItem('mcExamBasketSizeVersion', sizeVersion);
                }
                const saved = Number(window.parent.localStorage.getItem('mcExamBasketWidth') || 0);
                if (saved > 0) {
                    panel.style.setProperty('width', `${clamp(saved, 560, Math.max(620, window.parent.innerWidth - 104))}px`, 'important');
                } else {
                    panel.style.setProperty('width', '560px', 'important');
                }
                const savedHeight = Number(window.parent.localStorage.getItem('mcExamBasketHeight') || 0);
                if (savedHeight > 0) {
                    panel.style.setProperty('height', `${clamp(savedHeight, 150, Math.max(180, window.parent.innerHeight - 116))}px`, 'important');
                    panel.style.setProperty('max-height', 'none', 'important');
                } else {
                    panel.style.setProperty('height', '150px', 'important');
                    panel.style.setProperty('max-height', 'none', 'important');
                }
            }

            function applyPosition(panel) {
                const savedX = Number(window.parent.localStorage.getItem('mcExamBasketX'));
                const savedY = Number(window.parent.localStorage.getItem('mcExamBasketY'));
                const hasSavedPosition = window.parent.localStorage.getItem('mcExamBasketPositionReady') === '1';
                if (hasSavedPosition && Number.isFinite(savedX) && Number.isFinite(savedY) && savedX >= 0 && savedY >= 0) {
                    const rect = panel.getBoundingClientRect();
                    const maxX = Math.max(72, window.parent.innerWidth - rect.width - 12);
                    const maxY = Math.max(12, window.parent.innerHeight - 90);
                    panel.style.setProperty('left', `${clamp(savedX, 72, maxX)}px`, 'important');
                    panel.style.setProperty('top', `${clamp(savedY, 12, maxY)}px`, 'important');
                    panel.style.setProperty('right', 'auto', 'important');
                } else {
                    panel.style.setProperty('left', 'auto', 'important');
                    panel.style.setProperty('right', '16px', 'important');
                    panel.style.setProperty('top', '104px', 'important');
                }
            }

            function bind() {
                const panel = markPanels();
                if (!panel || panel.dataset.mcResizeBound === '1') {
                    if (panel) {
                        applyWidth(panel);
                        applyPosition(panel);
                    }
                    return;
                }
                panel.dataset.mcResizeBound = '1';
                panel.style.setProperty('resize', 'none', 'important');
                panel.style.setProperty('min-width', '560px', 'important');
                panel.style.setProperty('max-width', 'calc(100vw - 104px)', 'important');
                panel.style.setProperty('min-height', '150px', 'important');
                applyWidth(panel);
                applyPosition(panel);

                let cornerResizing = false;
                let moving = false;
                let moveOffsetX = 0;
                let moveOffsetY = 0;
                let resizeStartX = 0;
                let resizeStartY = 0;
                let resizeStartWidth = 0;
                let resizeStartHeight = 0;
                panel.addEventListener('pointerdown', (event) => {
                    const rect = panel.getBoundingClientRect();
                    if (rect.right - event.clientX <= 22 && rect.bottom - event.clientY <= 22) {
                        cornerResizing = true;
                        resizeStartX = event.clientX;
                        resizeStartY = event.clientY;
                        resizeStartWidth = rect.width;
                        resizeStartHeight = rect.height;
                        panel.setPointerCapture(event.pointerId);
                        event.preventDefault();
                        return;
                    }
                    const heading = event.target.closest('h4');
                    if (!heading) return;
                    moving = true;
                    moveOffsetX = event.clientX - rect.left;
                    moveOffsetY = event.clientY - rect.top;
                    panel.setPointerCapture(event.pointerId);
                    event.preventDefault();
                });
                panel.addEventListener('pointermove', (event) => {
                    if (cornerResizing) {
                        const nextWidth = clamp(resizeStartWidth + event.clientX - resizeStartX, 560, Math.max(620, window.parent.innerWidth - panel.getBoundingClientRect().left - 12));
                        const nextHeight = clamp(resizeStartHeight + event.clientY - resizeStartY, 150, Math.max(180, window.parent.innerHeight - panel.getBoundingClientRect().top - 12));
                        panel.style.setProperty('width', `${nextWidth}px`, 'important');
                        panel.style.setProperty('height', `${nextHeight}px`, 'important');
                        panel.style.setProperty('max-height', 'none', 'important');
                        window.parent.localStorage.setItem('mcExamBasketWidth', String(nextWidth));
                        window.parent.localStorage.setItem('mcExamBasketHeight', String(nextHeight));
                        return;
                    }
                    if (!moving) return;
                    const rect = panel.getBoundingClientRect();
                    const nextX = clamp(event.clientX - moveOffsetX, 72, Math.max(72, window.parent.innerWidth - rect.width - 12));
                    const nextY = clamp(event.clientY - moveOffsetY, 12, Math.max(12, window.parent.innerHeight - 90));
                    panel.style.setProperty('left', `${nextX}px`, 'important');
                    panel.style.setProperty('top', `${nextY}px`, 'important');
                    panel.style.setProperty('right', 'auto', 'important');
                    window.parent.localStorage.setItem('mcExamBasketX', String(nextX));
                    window.parent.localStorage.setItem('mcExamBasketY', String(nextY));
                    window.parent.localStorage.setItem('mcExamBasketPositionReady', '1');
                });
                panel.addEventListener('pointerup', () => { cornerResizing = false; moving = false; });
                panel.addEventListener('pointercancel', () => { cornerResizing = false; moving = false; });
            }

            bind();
            window.parent.setTimeout(bind, 80);
            window.parent.setTimeout(bind, 300);
            if (window.parent.__mcExamBasketObserver) {
                window.parent.__mcExamBasketObserver.disconnect();
            }
            window.parent.__mcExamBasketObserver = new window.parent.MutationObserver(bind);
            window.parent.__mcExamBasketObserver.observe(doc.body, {childList: true, subtree: true});
        })();
        </script>
        """,
        height=0,
    )

    if not st.session_state["exam_basket_open"]:
        with st.container(border=True):
            st.markdown('<span class="mc-exam-floating-basket-collapsed-anchor"></span>', unsafe_allow_html=True)
            if st.button(f"🧺 试题篮 · {selected_count}", key="mc_exam_basket_open", use_container_width=True):
                st.session_state["exam_basket_open"] = True
                st.rerun(scope="fragment")
        return

    with st.container(border=True):
        st.markdown('<span class="mc-exam-floating-basket-anchor"></span>', unsafe_allow_html=True)
        h1, h2 = st.columns([5, 1], vertical_alignment="center")
        with h1:
            st.markdown(f"#### 🧺 试题篮 ({selected_count}/{st.session_state.get('exam_q_count_input', 10)})")
        with h2:
            if st.button("收起", key="mc_exam_basket_close", use_container_width=True):
                st.session_state["exam_basket_open"] = False
                st.rerun(scope="fragment")

        if selected_count <= 0:
            st.caption("暂未选择任何题目")
            return

        if st.button("✨ 选题完成，进入排版工作台", type="primary", key="mc_exam_basket_done", use_container_width=True):
            sync_exam_blocks_to_selected_order(selected_paths)
            st.session_state["exam_mode_stage"] = "typesetting"
            st.rerun()

        c_preview, c_list = st.columns([1.15, 1], gap="large")
        with c_preview:
            st.markdown('<span class="mc-exam-basket-preview-anchor"></span>', unsafe_allow_html=True)
            expanded_q = st.session_state.get("exam_expanded_q")
            if expanded_q and os.path.exists(expanded_q):
                st.caption("👁 已选问题预览")
                try:
                    with open(expanded_q, "r", encoding="utf-8") as f:
                        expanded_content = f.read()
                    st.markdown(latex_to_markdown(expanded_content), unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"无法读取文件: {e}")
            else:
                st.caption("选择右侧题目查看预览")

        with c_list:
            st.markdown('<span class="mc-exam-basket-list-anchor"></span>', unsafe_allow_html=True)
            items = [
                {"id": p, "label": f"{i + 1}. {os.path.basename(p).replace('.tex', '')}"}
                for i, p in enumerate(selected_paths)
            ]
            result = st_sortable_list(items, key="exam_basket_sortable")
            if isinstance(result, dict):
                removed = result.get("removed")
                order = result.get("order") or []
                selected = result.get("selected")
                if removed and removed in selected_paths:
                    st.session_state["exam_selected_qs"] = [p for p in selected_paths if p != removed]
                    sync_exam_blocks_to_selected_order(st.session_state["exam_selected_qs"])
                    if st.session_state.get("exam_expanded_q") == removed:
                        remaining = st.session_state["exam_selected_qs"]
                        st.session_state["exam_expanded_q"] = remaining[0] if remaining else None
                    if st.session_state.get("ai_exam_active"):
                        st.session_state["ai_exam_modified"] = True
                    st.rerun(scope="fragment")
                if order and order != selected_paths:
                    valid = [p for p in order if p in selected_paths]
                    missing = [p for p in selected_paths if p not in valid]
                    st.session_state["exam_selected_qs"] = valid + missing
                    sync_exam_blocks_to_selected_order(st.session_state["exam_selected_qs"])
                    if st.session_state.get("ai_exam_active"):
                        st.session_state["ai_exam_modified"] = True
                    st.rerun(scope="fragment")
                if selected and selected in selected_paths and selected != st.session_state.get("exam_expanded_q"):
                    st.session_state["exam_expanded_q"] = selected
                    st.rerun(scope="fragment")


def _db_preview_json_list(value):
    try:
        parsed = json.loads(value or "[]")
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _db_preview_label(question: dict) -> str:
    year = question.get("detected_year") or ""
    source = question.get("detected_source") or question.get("paper_name") or ""
    number = question.get("detected_question_number") or question.get("question_number") or ""
    chapter = question.get("detected_chapter") or question.get("detected_topic") or ""
    parts = [str(part) for part in [year, source, f"第{number}题" if number else "", chapter] if str(part).strip()]
    prefix = " · ".join(parts) if parts else question.get("question_id", "题目")
    return f"{prefix}（{question.get('question_id', '')}）"


def _db_preview_reset_page():
    st.session_state["db_browse_page"] = 1
    st.session_state["db_browse_page_select"] = 1
    st.session_state["db_browse_focus_question_id"] = ""
    st.session_state["db_browse_question_choice"] = "__all__"
    st.session_state["db_browse_editing_question_id"] = ""


def _db_preview_ensure_option(state_key, options, fallback):
    valid_options = list(options)
    if st.session_state.get(state_key) not in valid_options:
        st.session_state[state_key] = fallback
    return st.session_state[state_key]


def _db_preview_apply_search():
    keyword = (st.session_state.get("db_browse_keyword_input", "") or "").strip()
    st.session_state["db_browse_keyword"] = keyword
    st.session_state["db_browse_search_active"] = bool(keyword)
    _db_preview_reset_page()


def _db_preview_exit_search():
    st.session_state["db_browse_keyword_input"] = ""
    st.session_state["db_browse_keyword"] = ""
    st.session_state["db_browse_search_active"] = False
    _db_preview_reset_page()


def _db_preview_apply_page_select():
    try:
        selected_page = int(st.session_state.get("db_browse_page_select", 1) or 1)
    except (TypeError, ValueError):
        selected_page = 1
    st.session_state["db_browse_page"] = max(1, selected_page)
    st.session_state["db_browse_focus_question_id"] = ""
    st.session_state["db_browse_question_choice"] = "__all__"


def _db_preview_change_page(delta, page_count):
    try:
        current_page = int(st.session_state.get("db_browse_page", 1) or 1)
    except (TypeError, ValueError):
        current_page = 1
    upper_bound = max(1, int(page_count or 1))
    next_page = min(upper_bound, max(1, current_page + int(delta)))
    st.session_state["db_browse_page"] = next_page
    st.session_state["db_browse_page_select"] = next_page
    st.session_state["db_browse_focus_question_id"] = ""
    st.session_state["db_browse_question_choice"] = "__all__"
    st.session_state["db_browse_editing_question_id"] = ""


def _db_preview_edit_hash(question_id: str) -> str:
    return _question_key("db_edit", question_id)


def _db_preview_edit_field_key(question_id: str, field: str) -> str:
    return f"db_browse_edit_{_db_preview_edit_hash(question_id)}_{field}"


def _db_preview_meta_field_key(question_id: str, field: str) -> str:
    return f"db_browse_meta_{_db_preview_edit_hash(question_id)}_{field}"


def _db_preview_source_relation_key(question_id: str, field: str) -> str:
    return f"db_source_relation_{_db_preview_edit_hash(question_id)}_{field}"


def _db_preview_source_export_key(field: str) -> str:
    return f"db_source_export_{field}"


def _db_preview_source_export_id_key(source_kind: str) -> str:
    return _db_preview_source_export_key(f"{source_kind}_id")


def _db_preview_relative_path(path: str) -> str:
    try:
        return os.path.relpath(os.path.abspath(path), BASE_DIR)
    except Exception:
        return str(path or "")


def _db_preview_render_source_export_panel(db_path: str, filters=None, page=None):
    from services.export_service import (
        export_filtered_questions_to_tex,
        export_source_to_tex,
        filter_export_default_filename,
        get_source_export_bundle,
        list_source_export_options,
        source_export_default_filename,
    )

    source_kind_labels = {
        "paper": "试卷",
        "book": "教材",
        "topic": "专题",
    }
    st.session_state.setdefault(_db_preview_source_export_key("kind"), "paper")
    st.session_state.setdefault(_db_preview_source_export_key("copy_graphics"), False)
    st.session_state.setdefault(_db_preview_source_export_key("resolve_questionassets"), True)
    st.session_state.setdefault(_db_preview_source_export_key("last_result"), {})
    st.session_state.setdefault(_db_preview_source_export_key("filter_scope"), "当前页")
    st.session_state.setdefault(_db_preview_source_export_key("last_filter_result"), {})

    with st.expander("SQLite TeX 导出（只生成文件）", expanded=False):
        st.markdown('<span class="mc-db-source-export-anchor"></span>', unsafe_allow_html=True)
        st.markdown(
            """
            <div class="mc-db-source-export-help">
                <strong>这个导出只负责“从 SQLite 生成可用 TeX 文件”。</strong><br>
                来源导出：按一张试卷、一本教材或一个专题的关系顺序生成完整 TeX。<br>
                筛选导出：把当前左侧筛选结果合并生成 TeX，不做前端 LaTeX 渲染。<br>
                所有文件只写入 <code>exports/</code>，不会修改 SQLite，也不会覆盖旧 <code>.tex</code> 题库。
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("**来源导出**")
        source_kind = st.selectbox(
            "来源类型",
            list(source_kind_labels.keys()),
            key=_db_preview_source_export_key("kind"),
            format_func=lambda value: source_kind_labels.get(value, value),
        )
        try:
            source_options = list_source_export_options(db_path, source_kind, limit=1000)
        except Exception as exc:
            st.error(f"读取导出来源失败：{exc}")
            return

        if not source_options:
            st.info("当前没有可导出的来源关系。")
            return

        source_id_key = {"paper": "paper_id", "book": "book_id", "topic": "topic_id"}[source_kind]
        option_ids = [str(item.get(source_id_key) or "") for item in source_options if item.get(source_id_key)]
        label_by_id = {str(item.get(source_id_key) or ""): item.get("label") or str(item.get(source_id_key) or "") for item in source_options}
        selected_id_key = _db_preview_source_export_id_key(source_kind)
        if st.session_state.get(selected_id_key) not in option_ids:
            st.session_state[selected_id_key] = option_ids[0]
        selected_source_id = st.selectbox(
            "导出对象",
            option_ids,
            key=selected_id_key,
            format_func=lambda value: label_by_id.get(value, value),
        )
        copy_graphics = st.checkbox(
            "复制 includegraphics 图片",
            key=_db_preview_source_export_key("copy_graphics"),
        )
        resolve_questionassets = st.checkbox(
            "解析 questionasset 占位符",
            key=_db_preview_source_export_key("resolve_questionassets"),
        )

        if st.button("生成来源 TeX", key=_db_preview_source_export_key("submit"), type="primary", use_container_width=True):
            try:
                bundle = get_source_export_bundle(db_path, source_kind, selected_source_id)
                export_dir = os.path.join(
                    BASE_DIR,
                    "exports",
                    "sqlite_source_exports",
                    datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
                )
                ensure_dir(export_dir)
                filename = source_export_default_filename(source_kind, bundle["source"])
                output_path = os.path.join(export_dir, filename)
                result = export_source_to_tex(
                    db_path,
                    source_kind,
                    selected_source_id,
                    output_path,
                    project_root=APP_ROOT,
                    copy_graphics=copy_graphics,
                    resolve_questionassets=resolve_questionassets,
                )
                with open(output_path, "r", encoding="utf-8") as f:
                    tex_data = f.read()
                result.update(
                    {
                        "output_path": output_path,
                        "file_name": filename,
                        "tex_data": tex_data,
                    }
                )
                st.session_state[_db_preview_source_export_key("last_result")] = result
                st.toast(f"已生成 {result.get('question_count') or 0} 题 TeX", icon="✅")
            except Exception as exc:
                st.error(f"导出失败：{exc}")

        last_result = st.session_state.get(_db_preview_source_export_key("last_result")) or {}
        if last_result.get("source_kind") == source_kind and last_result.get("source_id") == selected_source_id:
            missing_count = sum(1 for item in last_result.get("graphics", []) if item.get("status") == "missing")
            st.success(
                f"已生成：{last_result.get('question_count') or 0} 题"
                + (f"；缺失图片 {missing_count} 处" if missing_count else "")
            )
            st.caption(_db_preview_relative_path(last_result.get("output_path", "")))
            st.download_button(
                "下载刚生成的 TeX",
                data=last_result.get("tex_data") or "",
                file_name=last_result.get("file_name") or "sqlite_source_export.tex",
                mime="text/x-tex",
                key=_db_preview_source_export_key(f"download_{source_kind}_{selected_source_id}"),
                use_container_width=True,
            )

        st.divider()
        st.markdown("**筛选导出**")
        st.caption("按当前左侧筛选条件合并导出；这里只拼接 TeX 源码，不触发大批量公式渲染。")
        filter_scope = st.selectbox(
            "筛选导出范围",
            ["当前页", "当前筛选全部", "前 100 题", "前 500 题"],
            key=_db_preview_source_export_key("filter_scope"),
        )
        filter_total = int((page or {}).get("total") or 0)
        st.caption(f"当前筛选匹配：{filter_total} 题")
        filter_token = hashlib.sha1(
            json.dumps(
                {
                    "keyword": getattr(filters, "keyword", ""),
                    "year": getattr(filters, "year", None),
                    "chapter": getattr(filters, "chapter", ""),
                    "source": getattr(filters, "source", ""),
                    "question_number": getattr(filters, "question_number", ""),
                    "question_type_id": getattr(filters, "question_type_id", None),
                    "difficulty": getattr(filters, "difficulty", None),
                    "limit": getattr(filters, "limit", None),
                    "offset": getattr(filters, "offset", None),
                    "scope": filter_scope,
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:14]

        if st.button(
            "生成筛选 TeX",
            key=_db_preview_source_export_key("filter_submit"),
            use_container_width=True,
            disabled=not filters or filter_total <= 0,
        ):
            try:
                if filter_scope == "当前页":
                    max_questions = int(getattr(filters, "limit", 20) or 20)
                    start_offset = int(getattr(filters, "offset", 0) or 0)
                elif filter_scope == "前 100 题":
                    max_questions = 100
                    start_offset = 0
                elif filter_scope == "前 500 题":
                    max_questions = 500
                    start_offset = 0
                else:
                    max_questions = 0
                    start_offset = 0

                export_dir = os.path.join(
                    BASE_DIR,
                    "exports",
                    "sqlite_filter_exports",
                    datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
                )
                ensure_dir(export_dir)
                filename = filter_export_default_filename(filters)
                output_path = os.path.join(export_dir, filename)
                result = export_filtered_questions_to_tex(
                    db_path,
                    filters,
                    output_path,
                    project_root=APP_ROOT,
                    max_questions=max_questions,
                    start_offset=start_offset,
                    copy_graphics=copy_graphics,
                    resolve_questionassets=resolve_questionassets,
                )
                with open(output_path, "r", encoding="utf-8") as f:
                    tex_data = f.read()
                result.update(
                    {
                        "output_path": output_path,
                        "file_name": filename,
                        "tex_data": tex_data,
                        "filter_token": filter_token,
                    }
                )
                st.session_state[_db_preview_source_export_key("last_filter_result")] = result
                st.toast(f"已生成筛选 TeX：{result.get('question_count') or 0} 题", icon="✅")
            except Exception as exc:
                st.error(f"筛选导出失败：{exc}")

        last_filter_result = st.session_state.get(_db_preview_source_export_key("last_filter_result")) or {}
        if last_filter_result.get("filter_token") == filter_token:
            missing_count = sum(1 for item in last_filter_result.get("graphics", []) if item.get("status") == "missing")
            st.success(
                f"筛选导出：{last_filter_result.get('question_count') or 0} 题"
                + (f"；缺失图片 {missing_count} 处" if missing_count else "")
            )
            st.caption(_db_preview_relative_path(last_filter_result.get("output_path", "")))
            st.download_button(
                "下载筛选 TeX",
                data=last_filter_result.get("tex_data") or "",
                file_name=last_filter_result.get("file_name") or "sqlite_filter_export.tex",
                mime="text/x-tex",
                key=_db_preview_source_export_key("filter_download"),
                use_container_width=True,
            )


def _db_preview_clear_edit_form_state(question_id: str):
    if not question_id:
        return
    prefix = f"db_browse_edit_{_db_preview_edit_hash(question_id)}_"
    for key in list(st.session_state.keys()):
        if str(key).startswith(prefix):
            st.session_state.pop(key, None)


def _db_preview_start_edit(question_id: str):
    previous_question_id = st.session_state.get("db_browse_editing_question_id", "")
    if previous_question_id and previous_question_id != question_id:
        _db_preview_clear_edit_form_state(previous_question_id)
    _db_preview_clear_edit_form_state(question_id)
    _db_preview_store_return_state(question_id)
    st.session_state["db_browse_editing_question_id"] = question_id


def _db_preview_cancel_edit(question_id: str, *, restore_browse: bool = False):
    _db_preview_clear_edit_form_state(question_id)
    if st.session_state.get("db_browse_editing_question_id") == question_id:
        st.session_state["db_browse_editing_question_id"] = ""
    if restore_browse:
        _db_preview_restore_browse_state()


def _db_preview_question_anchor_id(question_id: str) -> str:
    return f"db-browse-question-{_db_preview_edit_hash(question_id)}"


def _db_preview_store_return_state(question_id: str):
    try:
        current_page = int(st.session_state.get("db_browse_page", 1) or 1)
    except (TypeError, ValueError):
        current_page = 1
    try:
        current_page_select = int(st.session_state.get("db_browse_page_select", current_page) or current_page)
    except (TypeError, ValueError):
        current_page_select = current_page
    st.session_state["db_browse_return_page"] = max(1, current_page)
    st.session_state["db_browse_return_page_select"] = max(1, current_page_select)
    st.session_state["db_browse_return_question_choice"] = st.session_state.get("db_browse_question_choice", "__all__")
    st.session_state["db_browse_return_focus_question_id"] = st.session_state.get("db_browse_focus_question_id", "")
    st.session_state["db_browse_scroll_target_question_id"] = question_id


def _db_preview_restore_browse_state():
    try:
        restored_page = int(st.session_state.get("db_browse_return_page", 1) or 1)
    except (TypeError, ValueError):
        restored_page = 1
    try:
        restored_page_select = int(st.session_state.get("db_browse_return_page_select", restored_page) or restored_page)
    except (TypeError, ValueError):
        restored_page_select = restored_page
    restored_choice = st.session_state.get("db_browse_return_question_choice", "__all__") or "__all__"
    restored_focus = st.session_state.get("db_browse_return_focus_question_id", "") or ""
    st.session_state["db_browse_page"] = max(1, restored_page)
    st.session_state["db_browse_page_select"] = max(1, restored_page_select)
    st.session_state["db_browse_question_choice"] = restored_choice
    st.session_state["db_browse_focus_question_id"] = restored_focus
    for state_key in (
        "db_browse_return_page",
        "db_browse_return_page_select",
        "db_browse_return_question_choice",
        "db_browse_return_focus_question_id",
    ):
        st.session_state.pop(state_key, None)


def _db_preview_scroll_to_question(question_id: str):
    if not question_id:
        return
    anchor_id = _db_preview_question_anchor_id(question_id)
    components.html(
        f"""
        <script>
        (() => {{
            const doc = window.parent.document;
            const targetId = {json.dumps(anchor_id)};
            const scrollTarget = () => {{
                const target = doc.getElementById(targetId);
                if (!target) {{
                    return false;
                }}
                target.scrollIntoView({{ behavior: "auto", block: "start" }});
                return true;
            }};
            let attempts = 0;
            const timer = window.setInterval(() => {{
                attempts += 1;
                if (scrollTarget() || attempts >= 15) {{
                    window.clearInterval(timer);
                }}
            }}, 80);
        }})();
        </script>
        """,
        height=0,
    )
    st.session_state["db_browse_scroll_target_question_id"] = ""


def _db_preview_form_token(form_values: dict) -> str:
    encoded = json.dumps(form_values, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:14]


def _db_preview_prepare_edit_form_state(question_id: str, form_values: dict):
    token_key = _db_preview_edit_field_key(question_id, "_token")
    next_token = _db_preview_form_token(form_values)
    if st.session_state.get(token_key) == next_token:
        return

    for field, value in form_values.items():
        if field == "question_id":
            continue
        st.session_state[_db_preview_edit_field_key(question_id, field)] = value
    st.session_state[token_key] = next_token


def _db_preview_collect_edit_form_values(question_id: str) -> dict:
    choices_text_key = _db_preview_edit_field_key(question_id, "choices_text")
    choice_scope_key = _db_preview_choice_editor_scope_key(question_id)
    choice_count_key = _structured_choice_editor_key(choice_scope_key, "choice_count")
    choices_text = st.session_state.get(choices_text_key, "")
    if choice_count_key in st.session_state:
        choices_text = _structured_choice_editor_collect_text(choice_scope_key)
        st.session_state[choices_text_key] = choices_text
    return {
        "question_type_id": st.session_state.get(_db_preview_edit_field_key(question_id, "question_type_id")),
        "stem_tex": st.session_state.get(_db_preview_edit_field_key(question_id, "stem_tex"), ""),
        "choices_text": choices_text,
        "answer_tex": st.session_state.get(_db_preview_edit_field_key(question_id, "answer_tex"), ""),
        "solution_tex": st.session_state.get(_db_preview_edit_field_key(question_id, "solution_tex"), ""),
        "difficulty": st.session_state.get(_db_preview_edit_field_key(question_id, "difficulty")),
        "tags_text": st.session_state.get(_db_preview_edit_field_key(question_id, "tags_text"), ""),
        "note": st.session_state.get(_db_preview_edit_field_key(question_id, "note"), ""),
        "official_flag": st.session_state.get(_db_preview_edit_field_key(question_id, "official_flag"), False),
    }


def _db_preview_metadata_token(question: dict) -> str:
    payload = {
        "difficulty": question.get("difficulty"),
        "tags_json": question.get("tags_json") or "[]",
        "note": question.get("note") or "",
        "updated_at": question.get("updated_at") or "",
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:14]


def _db_preview_prepare_metadata_state(question_id: str, question: dict):
    token_key = _db_preview_meta_field_key(question_id, "_token")
    next_token = _db_preview_metadata_token(question)
    if st.session_state.get(token_key) == next_token:
        return

    difficulty = question.get("difficulty")
    if difficulty not in (None, 1, 2, 3, 4, 5):
        difficulty = None
    st.session_state[_db_preview_meta_field_key(question_id, "difficulty")] = difficulty
    st.session_state[_db_preview_meta_field_key(question_id, "tags_text")] = "，".join(
        _db_preview_json_list(question.get("tags_json", "[]"))
    )
    st.session_state[_db_preview_meta_field_key(question_id, "note")] = question.get("note") or ""
    st.session_state[token_key] = next_token


def _db_preview_collect_metadata_form_values(question_id: str, question: dict) -> dict:
    return {
        "question_type_id": question.get("question_type_id"),
        "stem_tex": question.get("stem_tex") or "",
        "choices_text": "\n".join(_db_preview_json_list(question.get("choices_json", "[]"))),
        "answer_tex": question.get("answer_tex") or "",
        "solution_tex": question.get("solution_tex") or "",
        "difficulty": st.session_state.get(_db_preview_meta_field_key(question_id, "difficulty")),
        "tags_text": st.session_state.get(_db_preview_meta_field_key(question_id, "tags_text"), ""),
        "note": st.session_state.get(_db_preview_meta_field_key(question_id, "note"), ""),
        "official_flag": bool(question.get("official_flag") or 0),
    }


@st.dialog("修改标签信息", width="small")
def _db_preview_metadata_dialog(db_path: str, question_id: str, question: dict):
    from services.question_edit_service import (
        edit_form_to_question_updates_with_canonical,
        normalize_question_updates,
        update_question_fields,
    )

    _db_preview_prepare_metadata_state(question_id, question)
    difficulty_options = [None, 1, 2, 3, 4, 5]
    st.markdown("**修改标签信息**")
    st.caption("只保存难度、标签、备注；不会修改题干、答案、解析或旧 `.tex` 文件。")
    st.selectbox(
        "难度星级",
        difficulty_options,
        format_func=lambda value: "未设置" if value is None else f"{value} 星",
        key=_db_preview_meta_field_key(question_id, "difficulty"),
    )
    st.text_input(
        "标签",
        key=_db_preview_meta_field_key(question_id, "tags_text"),
        placeholder="多个标签用中文逗号分隔",
    )
    st.text_area(
        "备注",
        key=_db_preview_meta_field_key(question_id, "note"),
        height=82,
        placeholder="补充这道题的人工说明",
    )
    if st.button(
        "保存标签信息",
        key=_db_preview_meta_field_key(question_id, "save"),
        type="primary",
        use_container_width=True,
    ):
        try:
            form_values = _db_preview_collect_metadata_form_values(question_id, question)
            raw_updates = edit_form_to_question_updates_with_canonical(question, form_values)
            metadata_updates = {
                field: raw_updates[field]
                for field in ("difficulty", "tags_json", "note")
                if field in raw_updates
            }
            current_metadata = normalize_question_updates(
                {field: question.get(field) for field in metadata_updates}
            )
            metadata_changed = [
                field
                for field, value in metadata_updates.items()
                if current_metadata.get(field) != value
            ]
            if metadata_changed and "canonical_tex" in raw_updates:
                metadata_updates["canonical_tex"] = raw_updates["canonical_tex"]

            update_result = update_question_fields(
                db_path,
                question_id,
                metadata_updates if metadata_changed else {},
                operator="streamlit_ui",
                note="SQLite 题卡标签信息快速编辑",
                change_source="metadata_quick_edit",
            )
            if update_result.get("changed_fields"):
                _db_preview_clear_question_payload_cache()
                st.toast(f"{question_id} 标签信息已保存", icon="✅")
                st.rerun()
            else:
                st.toast("没有检测到标签信息变更。", icon="ℹ️")
        except Exception as exc:
            st.error(f"保存标签信息失败：{exc}")


def _db_preview_render_metadata_popover(db_path: str, question_id: str, question: dict):
    st.markdown('<span class="mc-db-meta-action-anchor"></span>', unsafe_allow_html=True)
    if st.button(
        "标签信息 ▾",
        key=_db_preview_meta_field_key(question_id, "open"),
        help="修改难度、标签和备注",
    ):
        _db_preview_metadata_dialog(db_path, question_id, question)


def _db_preview_split_choice_lines(value: str) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def _db_preview_unwrap_choice_value(value: str) -> str:
    text = str(value or "").strip()
    if not text.startswith("{") or not text.endswith("}"):
        return text
    depth = 0
    for index, char in enumerate(text):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return text
            if depth == 0 and index != len(text) - 1:
                return text
    if depth != 0:
        return text
    return text[1:-1].strip()


def _db_preview_wrap_choice_value(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("{") and text.endswith("}") and _db_preview_unwrap_choice_value(text) != text:
        return text
    return "{" + text + "}"


def _structured_choice_editor_key(scope_key: str, field: str) -> str:
    return f"{scope_key}_{field}"


def _structured_choice_editor_prepare_state(scope_key: str, choices_text: str):
    raw_choices = _db_preview_split_choice_lines(choices_text)
    display_choices = [_db_preview_unwrap_choice_value(choice) for choice in raw_choices]
    token_key = _structured_choice_editor_key(scope_key, "token")
    count_key = _structured_choice_editor_key(scope_key, "choice_count")
    if token_key in st.session_state and count_key in st.session_state:
        return
    st.session_state[count_key] = len(display_choices)
    for index in range(8):
        item_key = _structured_choice_editor_key(scope_key, f"choice_item_{index}")
        st.session_state[item_key] = display_choices[index] if index < len(display_choices) else ""
    st.session_state[token_key] = _db_preview_form_token({"choices": raw_choices})


def _structured_choice_editor_collect_text(scope_key: str) -> str:
    try:
        choice_count = int(st.session_state.get(_structured_choice_editor_key(scope_key, "choice_count"), 0) or 0)
    except (TypeError, ValueError):
        choice_count = 0
    choice_count = max(0, min(choice_count, 8))
    wrapped_choices = []
    for index in range(choice_count):
        item = st.session_state.get(_structured_choice_editor_key(scope_key, f"choice_item_{index}"), "")
        wrapped_item = _db_preview_wrap_choice_value(item)
        if wrapped_item:
            wrapped_choices.append(wrapped_item)
    return "\n".join(wrapped_choices)


def _structured_choice_editor_adjust_count(scope_key: str, delta: int):
    count_key = _structured_choice_editor_key(scope_key, "choice_count")
    try:
        current_count = int(st.session_state.get(count_key, 0) or 0)
    except (TypeError, ValueError):
        current_count = 0
    st.session_state[count_key] = max(0, min(current_count + int(delta), 8))


def _render_structured_choice_editor(
    scope_key: str,
    choices_text: str,
    *,
    show_step_buttons: bool,
    use_grid_layout: bool = True,
):
    _structured_choice_editor_prepare_state(scope_key, choices_text)
    count_key = _structured_choice_editor_key(scope_key, "choice_count")
    if not use_grid_layout:
        st.markdown(
            """
            <div class="mc-sqlite-entry-option-head">
                <strong>选项</strong>
                <span>填写内部 TeX；保存和导出时自动生成 <code>\\choice{{...}}</code>，并插入题干之后。</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        count_label_col, count_input_col = st.columns([0.42, 0.58], gap="small")
        with count_label_col:
            st.markdown("<div class='mc-sqlite-entry-option-count-label'>选项数量</div>", unsafe_allow_html=True)
        with count_input_col:
            st.number_input(
                "选项数量",
                min_value=0,
                max_value=8,
                step=1,
                key=count_key,
                label_visibility="collapsed",
            )
        try:
            choice_count = int(st.session_state.get(count_key, 0) or 0)
        except (TypeError, ValueError):
            choice_count = 0
        choice_count = max(0, min(choice_count, 8))
        choice_labels = "ABCDEFGH"
        if choice_count <= 0:
            st.caption("当前没有选项；如需选择题选项，把数量改为 2～8。")
            return
        for row_start in range(0, choice_count, 3):
            row_cols = st.columns(3, gap="small")
            for offset, option_col in enumerate(row_cols):
                index = row_start + offset
                if index >= choice_count:
                    continue
                with option_col:
                    st.text_area(
                        f"{choice_labels[index]} 选项内部 TeX",
                        key=_structured_choice_editor_key(scope_key, f"choice_item_{index}"),
                        height=84,
                        placeholder=r"例如：$\dfrac{\pi}{4}$",
                    )
        return
    if show_step_buttons:
        title_col, count_col, minus_col, plus_col = st.columns([1.65, 0.8, 0.42, 0.42], gap="small")
    else:
        title_col, count_col = st.columns([1.85, 0.72], gap="small")
        minus_col = plus_col = None
    with title_col:
        st.markdown("**选项**")
        st.caption("填写内部 TeX；保存和导出时自动生成 `\\choice{{...}}`。")
    with count_col:
        st.number_input(
            "选项数量",
            min_value=0,
            max_value=8,
            step=1,
            key=count_key,
            label_visibility="collapsed",
            help="选择题通常为 4；非选择题可保持 0。",
        )
    if show_step_buttons and minus_col is not None and plus_col is not None:
        with minus_col:
            st.button(
                "−",
                key=_structured_choice_editor_key(scope_key, "choice_count_minus"),
                use_container_width=True,
                on_click=_structured_choice_editor_adjust_count,
                args=(scope_key, -1),
            )
        with plus_col:
            st.button(
                "+",
                key=_structured_choice_editor_key(scope_key, "choice_count_plus"),
                use_container_width=True,
                on_click=_structured_choice_editor_adjust_count,
                args=(scope_key, 1),
            )
    try:
        choice_count = int(st.session_state.get(count_key, 0) or 0)
    except (TypeError, ValueError):
        choice_count = 0
    choice_count = max(0, min(choice_count, 8))
    choice_labels = "ABCDEFGH"
    if choice_count <= 0:
        st.caption("当前没有选项；如需选择题选项，把数量改为 2～8。")
        return
    for row_start in range(0, choice_count, 2):
        row_cols = st.columns(2, gap="small")
        for offset, option_col in enumerate(row_cols):
            index = row_start + offset
            if index >= choice_count:
                continue
            with option_col:
                st.text_area(
                    f"{choice_labels[index]} 选项内部 TeX",
                    key=_structured_choice_editor_key(scope_key, f"choice_item_{index}"),
                    height=72,
                    placeholder=r"例如：$\dfrac{\pi}{4}$",
                )


def _db_preview_choice_editor_scope_key(question_id: str) -> str:
    return _db_preview_edit_field_key(question_id, "choice_editor")


def _db_preview_render_structured_choice_editor(question_id: str, choices_text: str):
    _render_structured_choice_editor(
        _db_preview_choice_editor_scope_key(question_id),
        choices_text,
        show_step_buttons=True,
        use_grid_layout=False,
    )


def _db_preview_clear_question_payload_cache():
    try:
        _db_preview_question_payload.clear()
    except Exception:
        pass


def _db_preview_insert_asset_placeholder(question_id: str, target_field: str, placeholder: str):
    allowed_fields = {"stem_tex", "answer_tex", "solution_tex"}
    if target_field not in allowed_fields or not placeholder:
        return
    field_key = _db_preview_edit_field_key(question_id, target_field)
    current_text = str(st.session_state.get(field_key, "") or "")
    separator = "\n" if current_text and not current_text.endswith("\n") else ""
    st.session_state[field_key] = f"{current_text}{separator}{placeholder}"


def _db_preview_asset_upload_item_key(question_id: str, upload_name: str, index: int, field: str) -> str:
    item_hash = _question_key("db_asset_upload_item", f"{question_id}:{index}:{upload_name}")
    return _db_preview_edit_field_key(question_id, f"asset_upload_{item_hash}_{field}")


def _db_preview_default_asset_alias(upload_name: str, role: str, index: int) -> str:
    from services.asset_service import normalize_asset_alias

    safe_name = _db_preview_safe_upload_name(upload_name)
    stem = os.path.splitext(safe_name)[0]
    return normalize_asset_alias(stem, fallback=f"{role}_{index:02d}")


def _db_preview_render_asset_upload_panel(db_path: str, question_id: str, *, compact_layout: bool = False):
    asset_role_options = ["problem", "answer", "solution", "source", "thumbnail"]
    asset_role_labels = {
        "problem": "题干图片",
        "answer": "答案图片",
        "solution": "解析图片",
        "source": "原始材料",
        "thumbnail": "缩略图",
    }
    target_field_options = ["__none__", "stem_tex", "answer_tex", "solution_tex"]
    target_field_labels = {
        "__none__": "仅登记，不改 TeX",
        "stem_tex": "插入题干 TeX",
        "answer_tex": "插入答案 TeX",
        "solution_tex": "插入解析 TeX",
    }

    panel_open_key = _db_preview_edit_field_key(question_id, "asset_panel_open")
    st.session_state.setdefault(panel_open_key, False)
    toggle_label = "收起图片插入面板" if st.session_state.get(panel_open_key) else "🖼️ 添加/管理图片"
    if st.button(toggle_label, key=_db_preview_edit_field_key(question_id, "asset_panel_toggle"), use_container_width=True):
        st.session_state[panel_open_key] = not bool(st.session_state.get(panel_open_key))
        st.rerun()
    if not st.session_state.get(panel_open_key):
        st.caption("图片面板默认收起；需要插入非 TikZ 图片时再打开。")
        return

    st.markdown(
        "<div class='mc-db-asset-upload-panel'><strong>图片插入入口</strong>"
        "上传后会复制到 <code>assets/questions/&lt;question_id&gt;/</code> 并登记到 SQLite。"
        "引用名会生成 <code>\\questionasset{引用名}</code>；选择“仅登记，不改 TeX”时不会自动改源码。"
        "</div>",
        unsafe_allow_html=True,
    )
    upload_key = _db_preview_edit_field_key(question_id, "asset_upload_batch")
    uploaded_assets = st.file_uploader(
        "拖入图片 / PDF（可多选）",
        type=["png", "jpg", "jpeg", "webp", "bmp", "svg", "pdf"],
        key=upload_key,
        accept_multiple_files=True,
    )
    uploaded_assets = list(uploaded_assets or [])
    if not uploaded_assets:
        st.caption("还没有选择文件。可一次拖入多张图，每张图会单独生成引用名。")
        return

    for index, uploaded_asset in enumerate(uploaded_assets, start=1):
        upload_name = getattr(uploaded_asset, "name", f"asset_{index}")
        role_key = _db_preview_asset_upload_item_key(question_id, upload_name, index, "role")
        alias_key = _db_preview_asset_upload_item_key(question_id, upload_name, index, "alias")
        target_key = _db_preview_asset_upload_item_key(question_id, upload_name, index, "target")
        caption_key = _db_preview_asset_upload_item_key(question_id, upload_name, index, "caption")
        st.session_state.setdefault(role_key, "problem")
        st.session_state.setdefault(alias_key, _db_preview_default_asset_alias(upload_name, st.session_state.get(role_key, "problem"), index))
        st.session_state.setdefault(target_key, "__none__")
        st.session_state.setdefault(caption_key, "")
        st.markdown(
            f"""
            <div class="mc-db-asset-upload-card">
                <strong>{index}. {html.escape(upload_name)}</strong>
                <span>登记后可用 <code>\\questionasset{{{html.escape(str(st.session_state.get(alias_key) or ''))}}}</code> 引用。</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        alias_value = str(st.session_state.get(alias_key) or "").strip()
        if alias_value:
            copy_col, copy_hint_col = st.columns([0.64, 1.36], gap="small")
            with copy_col:
                _render_text_clipboard_button(
                    f"\\questionasset{{{alias_value}}}",
                    "复制占位符",
                    f"sqlite_draft_asset_copy_{question_id}_{index}",
                    height=38,
                )
            with copy_hint_col:
                st.caption("复制后可直接粘贴到题干 / 答案 / 解析。")
        st.selectbox(
            "资源位置",
            asset_role_options,
            format_func=lambda value: asset_role_labels.get(value, value),
            key=role_key,
        )
        st.text_input(
            "引用名",
            key=alias_key,
            placeholder=f"例如：problem_{index:02d}",
            help="引用名会成为 \\questionasset{...} 的内容；建议使用英文、数字、下划线或短横线。",
        )
        st.selectbox(
            "插入到",
            target_field_options,
            format_func=lambda value: target_field_labels.get(value, value),
            key=target_key,
        )
        st.text_input(
            "图片说明",
            key=caption_key,
            placeholder="可选，例如：题干图 1",
        )

    if st.button("登记已上传图片", key=_db_preview_edit_field_key(question_id, "asset_submit_batch"), type="primary", use_container_width=True):
        if not uploaded_assets:
            st.warning("请先选择要登记的图片或 PDF。")
        else:
            registered = []
            inserted_count = 0
            try:
                for index, uploaded_asset in enumerate(uploaded_assets, start=1):
                    upload_name = getattr(uploaded_asset, "name", f"asset_{index}")
                    role_key = _db_preview_asset_upload_item_key(question_id, upload_name, index, "role")
                    alias_key = _db_preview_asset_upload_item_key(question_id, upload_name, index, "alias")
                    target_key = _db_preview_asset_upload_item_key(question_id, upload_name, index, "target")
                    caption_key = _db_preview_asset_upload_item_key(question_id, upload_name, index, "caption")
                    asset_result = _db_preview_attach_uploaded_asset(
                        db_path,
                        question_id,
                        uploaded_asset,
                        st.session_state.get(role_key, "problem"),
                        st.session_state.get(caption_key, ""),
                        alias=st.session_state.get(alias_key, ""),
                    )
                    registered.append(asset_result)
                    placeholder = str(asset_result.get("placeholder") or "")
                    asset_target = st.session_state.get(target_key, "__none__")
                    if asset_target != "__none__" and placeholder:
                        _db_preview_insert_asset_placeholder(question_id, asset_target, placeholder)
                        inserted_count += 1
                _db_preview_clear_question_payload_cache()
                st.session_state[_db_preview_edit_field_key(question_id, "asset_last_placeholder")] = "\n".join(
                    str(item.get("placeholder") or "") for item in registered if item.get("placeholder")
                )
                inserted_text = f"；已插入 {inserted_count} 处 TeX" if inserted_count else ""
                st.toast(
                    f"已登记 {len(registered)} 个图片/附件资源{inserted_text}",
                    icon="🖼️",
                )
                st.rerun()
            except Exception as exc:
                st.error(f"登记资源失败：{exc}")


def _db_preview_safe_upload_name(upload_name: str) -> str:
    safe_name = os.path.basename(str(upload_name or "").replace("\\", "/")).strip()
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", safe_name)
    return safe_name or f"uploaded_asset_{uuid.uuid4().hex[:8]}"


def _db_preview_attach_uploaded_asset(
    db_path: str,
    question_id: str,
    uploaded_file,
    role: str,
    caption: str,
    *,
    alias: str = "",
) -> dict:
    from services.asset_service import attach_asset_to_question

    safe_name = _db_preview_safe_upload_name(getattr(uploaded_file, "name", ""))
    with tempfile.TemporaryDirectory(prefix="mathcyclus_upload_") as tmp_dir:
        tmp_path = os.path.join(tmp_dir, safe_name)
        with open(tmp_path, "wb") as file:
            file.write(uploaded_file.getbuffer())
        return attach_asset_to_question(
            db_path,
            question_id,
            tmp_path,
            role=role,
            alias=alias,
            caption=caption,
            copy_file=True,
        )


def _db_preview_render_asset_management(db_path: str, question_id: str):
    from services.asset_service import asset_placeholder, delete_asset, list_assets, update_asset_fields

    assets = list_assets(db_path, question_id=question_id)
    role_options = ["problem", "answer", "solution", "source", "thumbnail"]
    role_labels = {
        "problem": "题干图片",
        "answer": "答案图片",
        "solution": "解析图片",
        "source": "原始材料",
        "thumbnail": "缩略图",
    }
    target_field_options = ["stem_tex", "answer_tex", "solution_tex"]
    target_field_labels = {
        "stem_tex": "题干 TeX",
        "answer_tex": "答案 TeX",
        "solution_tex": "解析 TeX",
    }
    last_placeholder_key = _db_preview_edit_field_key(question_id, "asset_last_placeholder")
    last_placeholder = st.session_state.pop(last_placeholder_key, "")
    if last_placeholder:
        st.success("资源已登记，可复制或插入下面的占位符。")
        st.code(last_placeholder, language="latex")

    if not assets:
        st.caption("当前题目还没有登记图片或附件。")
        return

    with st.expander(f"已登记资源（{len(assets)}）", expanded=True):
        for asset in assets:
            asset_id = str(asset.get("asset_id") or "")
            asset_key = _question_key("db_asset", asset_id)
            role_key = _db_preview_edit_field_key(question_id, f"asset_role_{asset_key}")
            caption_key = _db_preview_edit_field_key(question_id, f"asset_caption_{asset_key}")
            sort_key = _db_preview_edit_field_key(question_id, f"asset_sort_{asset_key}")
            token_key = _db_preview_edit_field_key(question_id, f"asset_token_{asset_key}")
            asset_token = json.dumps(
                {
                    "role": asset.get("role") or "problem",
                    "caption": asset.get("caption") or "",
                    "sort_order": int(asset.get("sort_order") or 0),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            if st.session_state.get(token_key) != asset_token:
                st.session_state[role_key] = asset.get("role") or "problem"
                st.session_state[caption_key] = asset.get("caption") or ""
                st.session_state[sort_key] = int(asset.get("sort_order") or 0)
                st.session_state[token_key] = asset_token

            try:
                placeholder = asset_placeholder(asset)
            except Exception:
                placeholder = ""

            st.markdown(
                f"""
                <div class="mc-db-asset-edit-card">
                    <strong>{html.escape(asset.get('original_file_name') or asset_id)}</strong>
                    <span>{html.escape(asset.get('file_path') or '')}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if placeholder:
                st.code(placeholder, language="latex")
                copy_col, copy_hint_col = st.columns([0.64, 1.36], gap="small")
                with copy_col:
                    _render_text_clipboard_button(
                        placeholder,
                        "复制占位符",
                        f"sqlite_asset_copy_{question_id}_{asset_key}",
                        height=38,
                    )
                with copy_hint_col:
                    st.caption("复制后可直接粘贴到题干 / 答案 / 解析。")
            insert_target_key = _db_preview_edit_field_key(question_id, f"asset_insert_target_{asset_key}")
            insert_col, update_col, delete_col = st.columns([1.15, 1, 0.95], gap="small")
            with insert_col:
                selected_target = st.selectbox(
                    "插入到",
                    target_field_options,
                    key=insert_target_key,
                    format_func=lambda value: target_field_labels.get(value, value),
                )
                st.button(
                    "插入占位符",
                    key=_db_preview_edit_field_key(question_id, f"asset_insert_{asset_key}"),
                    use_container_width=True,
                    disabled=not bool(placeholder),
                    on_click=_db_preview_insert_asset_placeholder,
                    args=(question_id, selected_target, placeholder),
                )
            with update_col:
                st.selectbox(
                    "资源位置",
                    role_options,
                    key=role_key,
                    format_func=lambda value: role_labels.get(value, value),
                )
                st.number_input(
                    "排序",
                    min_value=0,
                    step=1,
                    key=sort_key,
                )
            with delete_col:
                st.text_input("说明", key=caption_key)
                save_asset_col, remove_asset_col = st.columns(2, gap="small")
                with save_asset_col:
                    if st.button(
                        "保存",
                        key=_db_preview_edit_field_key(question_id, f"asset_save_{asset_key}"),
                        use_container_width=True,
                    ):
                        try:
                            result = update_asset_fields(
                                db_path,
                                asset_id,
                                {
                                    "role": st.session_state.get(role_key),
                                    "caption": st.session_state.get(caption_key),
                                    "sort_order": st.session_state.get(sort_key),
                                },
                                operator="streamlit_ui",
                            )
                            _db_preview_clear_question_payload_cache()
                            if result.get("changed_fields"):
                                st.toast("资源信息已保存", icon="✅")
                                st.rerun()
                            else:
                                st.info("资源信息没有变化。")
                        except Exception as exc:
                            st.error(f"保存资源失败：{exc}")
                with remove_asset_col:
                    if st.button(
                        "移除",
                        key=_db_preview_edit_field_key(question_id, f"asset_remove_{asset_key}"),
                        use_container_width=True,
                    ):
                        try:
                            delete_asset(db_path, asset_id, operator="streamlit_ui")
                            _db_preview_clear_question_payload_cache()
                            st.toast("已移除资源登记；文件未删除", icon="🧹")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"移除资源失败：{exc}")
            st.divider()


def _db_preview_source_relation_counts(db_path: str, question_id: str) -> dict[str, int]:
    counts = {"paper": 0, "book": 0, "topic": 0}
    try:
        from services.paper_service import list_question_paper_links

        counts["paper"] = len(list_question_paper_links(db_path, question_id) or [])
    except Exception:
        pass
    try:
        from services.book_service import list_question_book_links

        counts["book"] = len(list_question_book_links(db_path, question_id) or [])
    except Exception:
        pass
    try:
        from services.topic_service import list_question_topic_links

        counts["topic"] = len(list_question_topic_links(db_path, question_id) or [])
    except Exception:
        pass
    return counts


def _db_preview_render_source_relation_management(
    db_path: str,
    question_id: str,
    question: dict,
    *,
    outer_label: str | None = "来源关系管理（SQLite）",
    expanded: bool = False,
):
    from services.export_service import list_source_export_options
    from services.book_service import list_book_sections, list_question_book_links
    from services.paper_service import list_question_paper_links
    from services.source_relation_service import (
        delete_question_book_link,
        delete_question_paper_link,
        delete_question_topic_link,
        upsert_question_book_link,
        upsert_question_paper_link,
        upsert_question_topic_link,
    )
    from services.topic_service import list_question_topic_links, list_topic_groups

    def source_options(kind: str, id_key: str) -> tuple[list[str], dict[str, str], dict[str, dict]]:
        try:
            rows = list_source_export_options(db_path, kind, limit=1000)
        except Exception:
            rows = []
        ids = [str(row.get(id_key) or "") for row in rows if row.get(id_key)]
        labels = {"__manual__": "手动填写新来源"}
        by_id = {}
        for row in rows:
            row_id = str(row.get(id_key) or "")
            if not row_id:
                continue
            labels[row_id] = str(row.get("label") or row_id)
            by_id[row_id] = row
        return ["__manual__"] + ids, labels, by_id

    def filtered_source_ids(option_ids: list[str], labels: dict[str, str], search_text: str) -> list[str]:
        normalized = str(search_text or "").replace("／", "/").strip().lower()
        if not normalized:
            return option_ids
        terms = [term.strip() for term in normalized.split("/") if term.strip()]
        if not terms:
            return option_ids
        filtered = []
        for option_id in option_ids:
            if option_id == "__manual__":
                filtered.append(option_id)
                continue
            haystack = f"{labels.get(option_id, '')} {option_id}".lower()
            if all(term in haystack for term in terms):
                filtered.append(option_id)
        return filtered or ["__manual__"]

    def set_relation_state(field: str, value):
        st.session_state[_db_preview_source_relation_key(question_id, field)] = value

    source_shell = st.expander(outer_label, expanded=expanded) if outer_label else st.container()
    with source_shell:
        st.caption("只维护 SQLite 来源关系表并记录 revision；不会修改旧 TeX 文件。")
        st.markdown(
            """
            <style>
            .mc-db-relation-summary {
                margin: 0.15rem 0 0.35rem;
                padding: 0.34rem 0.62rem;
                border-radius: 10px;
                border: 1px solid rgba(91, 33, 182, 0.12);
                background: rgba(91, 33, 182, 0.05);
                color: #5b21b6;
                font-size: 0.86rem;
                line-height: 1.3;
                font-weight: 600;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        paper_links = list_question_paper_links(db_path, question_id)
        book_links = list_question_book_links(db_path, question_id)
        topic_links = list_question_topic_links(db_path, question_id)
        st.markdown(
            f"<div class='mc-db-relation-summary'>当前关系 · 试卷 {len(paper_links)} · 教材 {len(book_links)} · 专题 {len(topic_links)}</div>",
            unsafe_allow_html=True,
        )

        st.markdown("**已有试卷来源**")
        if paper_links:
            for link in paper_links:
                link_id = str(link.get("paper_question_id") or "")
                label = (
                    f"{link.get('year') or ''} · {link.get('paper_name') or ''} · "
                    f"{link.get('track') or ''} · 第{link.get('question_number') or ''}{link.get('sub_number') or ''}题"
                )
                row_col, action_col = st.columns([2.35, 0.65], gap="small")
                with row_col:
                    st.caption(label)
                with action_col:
                    if st.button("移除", key=_db_preview_source_relation_key(question_id, f"delete_paper_{link_id}"), use_container_width=True):
                        try:
                            delete_question_paper_link(db_path, link_id, operator="streamlit_ui")
                            _db_preview_clear_question_payload_cache()
                            st.toast("试卷来源关系已移除", icon="✅")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"移除试卷来源失败：{exc}")
        else:
            st.caption("暂无试卷来源关系。")

        paper_option_ids, paper_option_labels, papers_by_id = source_options("paper", "paper_id")
        paper_search_key = _db_preview_source_relation_key(question_id, "paper_existing_search")
        paper_search_col, paper_pick_col, paper_apply_col = st.columns([1.18, 1.42, 0.76], gap="small", vertical_alignment="bottom")
        with paper_search_col:
            paper_search_text = st.text_input(
                "搜索已有试卷",
                key=paper_search_key,
                placeholder="支持 / 分隔，例如：2025 / 全国II卷",
            )
        paper_filtered_ids = filtered_source_ids(paper_option_ids, paper_option_labels, paper_search_text)
        paper_pick_key = _db_preview_source_relation_key(question_id, "paper_existing_pick")
        if st.session_state.get(paper_pick_key) not in paper_filtered_ids:
            st.session_state[paper_pick_key] = "__manual__"
        with paper_pick_col:
            paper_pick = st.selectbox(
                "匹配结果",
                paper_filtered_ids,
                key=paper_pick_key,
                format_func=lambda value: paper_option_labels.get(value, value),
            )
        with paper_apply_col:
            if st.button(
                "填入",
                key=_db_preview_source_relation_key(question_id, "paper_apply_existing"),
                disabled=paper_pick == "__manual__",
                use_container_width=True,
            ):
                paper = papers_by_id.get(paper_pick, {})
                set_relation_state("paper_year", "" if paper.get("year") is None else str(paper.get("year")))
                set_relation_state("paper_series", str(paper.get("paper_series") or "G"))
                set_relation_state("paper_track", str(paper.get("track") or ""))
                set_relation_state("paper_name", str(paper.get("paper_name") or paper.get("source_name") or ""))
        if len(paper_filtered_ids) <= 1:
            st.caption("未找到匹配试卷，可直接手动填写。")

        with st.form(key=_db_preview_source_relation_key(question_id, "paper_form"), clear_on_submit=False):
            c1, c2, c3 = st.columns([0.65, 0.7, 0.75], gap="small")
            with c1:
                paper_year = st.text_input("年份", value=str(question.get("detected_year") or ""), key=_db_preview_source_relation_key(question_id, "paper_year"))
            with c2:
                paper_series = st.text_input("卷别代码", value=str(question.get("paper_series") or "G"), key=_db_preview_source_relation_key(question_id, "paper_series"))
            with c3:
                paper_track = st.text_input("文理/新高考", value=str(question.get("track") or ""), key=_db_preview_source_relation_key(question_id, "paper_track"))
            paper_name = st.text_input("试卷名称", value=str(question.get("paper_name") or question.get("detected_source") or ""), key=_db_preview_source_relation_key(question_id, "paper_name"))
            n1, n2, n3 = st.columns([0.75, 0.65, 0.7], gap="small")
            with n1:
                paper_number = st.text_input("题号", value=str(question.get("question_number") or question.get("detected_question_number") or ""), key=_db_preview_source_relation_key(question_id, "paper_number"))
            with n2:
                paper_sub_number = st.text_input("小题", value=str(question.get("sub_number") or ""), key=_db_preview_source_relation_key(question_id, "paper_sub_number"))
            with n3:
                paper_order = st.number_input("排序", min_value=0, step=1, value=0, key=_db_preview_source_relation_key(question_id, "paper_order"))
            paper_submit = st.form_submit_button("保存试卷来源", type="primary", use_container_width=True)
        if paper_submit:
            try:
                upsert_question_paper_link(
                    db_path,
                    question_id,
                    year=paper_year,
                    paper_series=paper_series,
                    track=paper_track,
                    paper_name=paper_name,
                    source_name=paper_name,
                    question_number=paper_number,
                    sub_number=paper_sub_number,
                    display_order=paper_order,
                    operator="streamlit_ui",
                )
                _db_preview_clear_question_payload_cache()
                st.toast("试卷来源已保存", icon="✅")
                st.rerun()
            except Exception as exc:
                st.error(f"保存试卷来源失败：{exc}")

        st.markdown("**已有教材来源**")
        if book_links:
            for link in book_links:
                link_id = str(link.get("book_exercise_question_id") or "")
                label = (
                    f"{link.get('title') or ''} · {link.get('section_title') or ''} · "
                    f"P{link.get('page_number') or ''} · {link.get('column_name') or ''} · {link.get('exercise_number') or ''}"
                )
                row_col, action_col = st.columns([2.35, 0.65], gap="small")
                with row_col:
                    st.caption(label)
                with action_col:
                    if link_id and st.button("移除", key=_db_preview_source_relation_key(question_id, f"delete_book_{link_id}"), use_container_width=True):
                        try:
                            delete_question_book_link(db_path, link_id, operator="streamlit_ui")
                            _db_preview_clear_question_payload_cache()
                            st.toast("教材来源关系已移除", icon="✅")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"移除教材来源失败：{exc}")
        else:
            st.caption("暂无教材来源关系。")

        book_option_ids, book_option_labels, books_by_id = source_options("book", "book_id")
        book_search_key = _db_preview_source_relation_key(question_id, "book_existing_search")
        book_search_col, book_pick_col, book_apply_col = st.columns([1.18, 1.42, 0.76], gap="small", vertical_alignment="bottom")
        with book_search_col:
            book_search_text = st.text_input(
                "搜索已有教材",
                key=book_search_key,
                placeholder="支持 / 分隔，例如：必修 / 数学",
            )
        book_filtered_ids = filtered_source_ids(book_option_ids, book_option_labels, book_search_text)
        book_pick_key = _db_preview_source_relation_key(question_id, "book_existing_pick")
        if st.session_state.get(book_pick_key) not in book_filtered_ids:
            st.session_state[book_pick_key] = "__manual__"
        with book_pick_col:
            book_pick = st.selectbox(
                "匹配结果",
                book_filtered_ids,
                key=book_pick_key,
                format_func=lambda value: book_option_labels.get(value, value),
            )
        with book_apply_col:
            if st.button(
                "填入",
                key=_db_preview_source_relation_key(question_id, "book_apply_existing"),
                disabled=book_pick == "__manual__",
                use_container_width=True,
            ):
                book = books_by_id.get(book_pick, {})
                set_relation_state("book_title", str(book.get("title") or ""))
                set_relation_state("book_publisher", str(book.get("publisher") or ""))
                set_relation_state("book_edition", str(book.get("edition") or ""))
                set_relation_state("book_grade", str(book.get("grade") or ""))
                set_relation_state("book_volume", str(book.get("volume") or ""))
                set_relation_state("book_curriculum", str(book.get("curriculum_version") or ""))

        if book_pick != "__manual__":
            try:
                section_rows = list_book_sections(db_path, book_pick)
            except Exception:
                section_rows = []
            if section_rows:
                section_ids = [str(row.get("section_id") or "") for row in section_rows if row.get("section_id")]
                section_labels = {
                    str(row.get("section_id") or ""): (
                        f"{row.get('title') or row.get('section_id')} · "
                        f"P{row.get('page_start') or ''}-{row.get('page_end') or ''} · "
                        f"{row.get('question_link_count') or 0} 题"
                    )
                    for row in section_rows
                    if row.get("section_id")
                }
                section_by_id = {str(row.get("section_id") or ""): row for row in section_rows if row.get("section_id")}
                section_pick_col, section_apply_col = st.columns([2.6, 0.76], gap="small", vertical_alignment="bottom")
                with section_pick_col:
                    selected_section_id = st.selectbox(
                        "从已有教材章节填入",
                        section_ids,
                        key=_db_preview_source_relation_key(question_id, "book_section_existing_pick"),
                        format_func=lambda value: section_labels.get(value, value),
                    )
                with section_apply_col:
                    if st.button(
                        "填入",
                        key=_db_preview_source_relation_key(question_id, "book_section_apply_existing"),
                        use_container_width=True,
                    ):
                        section = section_by_id.get(selected_section_id, {})
                        set_relation_state("book_section_title", str(section.get("title") or ""))
        if len(book_filtered_ids) <= 1:
            st.caption("未找到匹配教材，可直接手动填写。")

        with st.form(key=_db_preview_source_relation_key(question_id, "book_form"), clear_on_submit=False):
            book_title = st.text_input("教材名称", key=_db_preview_source_relation_key(question_id, "book_title"))
            b1, b2, b3 = st.columns([0.9, 0.7, 0.7], gap="small")
            with b1:
                book_publisher = st.text_input("出版社", key=_db_preview_source_relation_key(question_id, "book_publisher"))
            with b2:
                book_edition = st.text_input("版本", key=_db_preview_source_relation_key(question_id, "book_edition"))
            with b3:
                book_grade = st.text_input("年级", key=_db_preview_source_relation_key(question_id, "book_grade"))
            b4, b5 = st.columns(2, gap="small")
            with b4:
                book_volume = st.text_input("册次", key=_db_preview_source_relation_key(question_id, "book_volume"))
            with b5:
                book_curriculum = st.text_input("课标/体系", key=_db_preview_source_relation_key(question_id, "book_curriculum"))
            section_title = st.text_input("章节/栏目", key=_db_preview_source_relation_key(question_id, "book_section_title"))
            be1, be2, be3, be4 = st.columns([0.55, 0.7, 0.7, 0.55], gap="small")
            with be1:
                page_number = st.number_input("页码", min_value=0, step=1, value=0, key=_db_preview_source_relation_key(question_id, "book_page"))
            with be2:
                column_name = st.text_input("栏目", key=_db_preview_source_relation_key(question_id, "book_column"))
            with be3:
                exercise_number = st.text_input("题号", key=_db_preview_source_relation_key(question_id, "book_exercise"))
            with be4:
                book_sub_number = st.text_input("小题", key=_db_preview_source_relation_key(question_id, "book_sub"))
            book_note = st.text_input("来源备注", key=_db_preview_source_relation_key(question_id, "book_note"))
            book_submit = st.form_submit_button("保存教材来源", type="primary", use_container_width=True)
        if book_submit:
            try:
                upsert_question_book_link(
                    db_path,
                    question_id,
                    title=book_title,
                    publisher=book_publisher,
                    edition=book_edition,
                    grade=book_grade,
                    volume=book_volume,
                    curriculum_version=book_curriculum,
                    section_title=section_title,
                    page_number=page_number or None,
                    column_name=column_name,
                    exercise_number=exercise_number,
                    sub_number=book_sub_number,
                    source_note=book_note,
                    operator="streamlit_ui",
                )
                _db_preview_clear_question_payload_cache()
                st.toast("教材来源已保存", icon="✅")
                st.rerun()
            except Exception as exc:
                st.error(f"保存教材来源失败：{exc}")

        st.markdown("**已有专题来源**")
        if topic_links:
            for link in topic_links:
                link_id = str(link.get("topic_question_id") or "")
                label = f"{link.get('module_name') or ''} · {link.get('topic_name') or ''} · {link.get('group_name') or ''}"
                row_col, action_col = st.columns([2.35, 0.65], gap="small")
                with row_col:
                    st.caption(label)
                with action_col:
                    if link_id and st.button("移除", key=_db_preview_source_relation_key(question_id, f"delete_topic_{link_id}"), use_container_width=True):
                        try:
                            delete_question_topic_link(db_path, link_id, operator="streamlit_ui")
                            _db_preview_clear_question_payload_cache()
                            st.toast("专题来源关系已移除", icon="✅")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"移除专题来源失败：{exc}")
        else:
            st.caption("暂无专题来源关系。")

        topic_option_ids, topic_option_labels, topics_by_id = source_options("topic", "topic_id")
        topic_search_key = _db_preview_source_relation_key(question_id, "topic_existing_search")
        topic_search_col, topic_pick_col, topic_apply_col = st.columns([1.18, 1.42, 0.76], gap="small", vertical_alignment="bottom")
        with topic_search_col:
            topic_search_text = st.text_input(
                "搜索已有专题",
                key=topic_search_key,
                placeholder="支持 / 分隔，例如：函数 / 选择题",
            )
        topic_filtered_ids = filtered_source_ids(topic_option_ids, topic_option_labels, topic_search_text)
        topic_pick_key = _db_preview_source_relation_key(question_id, "topic_existing_pick")
        if st.session_state.get(topic_pick_key) not in topic_filtered_ids:
            st.session_state[topic_pick_key] = "__manual__"
        with topic_pick_col:
            topic_pick = st.selectbox(
                "匹配结果",
                topic_filtered_ids,
                key=topic_pick_key,
                format_func=lambda value: topic_option_labels.get(value, value),
            )
        with topic_apply_col:
            if st.button(
                "填入",
                key=_db_preview_source_relation_key(question_id, "topic_apply_existing"),
                disabled=topic_pick == "__manual__",
                use_container_width=True,
            ):
                topic = topics_by_id.get(topic_pick, {})
                set_relation_state("topic_module", str(topic.get("module_name") or ""))
                set_relation_state("topic_name", str(topic.get("name") or ""))
                set_relation_state("topic_file", str(topic.get("file_name") or ""))
        if len(topic_filtered_ids) <= 1:
            st.caption("未找到匹配专题，可直接手动填写。")

        if topic_pick != "__manual__":
            try:
                group_rows = list_topic_groups(db_path, topic_pick)
            except Exception:
                group_rows = []
            if group_rows:
                group_values = [str(row.get("group_name") or "") for row in group_rows]
                group_labels = {str(row.get("group_name") or ""): str(row.get("label") or "默认分组") for row in group_rows}
                group_by_value = {str(row.get("group_name") or ""): row for row in group_rows}
                group_pick_col, group_apply_col = st.columns([2.6, 0.76], gap="small", vertical_alignment="bottom")
                with group_pick_col:
                    selected_group = st.selectbox(
                        "从已有专题分组填入",
                        group_values,
                        key=_db_preview_source_relation_key(question_id, "topic_group_existing_pick"),
                        format_func=lambda value: group_labels.get(value, value or "默认分组"),
                    )
                with group_apply_col:
                    if st.button(
                        "填入",
                        key=_db_preview_source_relation_key(question_id, "topic_group_apply_existing"),
                        use_container_width=True,
                    ):
                        group = group_by_value.get(selected_group, {})
                        set_relation_state("topic_group", selected_group)
                        set_relation_state("topic_order", int(group.get("next_sort_order") or 0))

        with st.form(key=_db_preview_source_relation_key(question_id, "topic_form"), clear_on_submit=False):
            t1, t2 = st.columns([0.9, 1.1], gap="small")
            with t1:
                topic_module = st.text_input("专题模块", key=_db_preview_source_relation_key(question_id, "topic_module"))
            with t2:
                topic_name = st.text_input("专题名称", key=_db_preview_source_relation_key(question_id, "topic_name"))
            topic_file = st.text_input("专题 TeX 文件名", key=_db_preview_source_relation_key(question_id, "topic_file"))
            tg1, tg2 = st.columns([1, 0.55], gap="small")
            with tg1:
                topic_group = st.text_input("组名", key=_db_preview_source_relation_key(question_id, "topic_group"))
            with tg2:
                topic_order = st.number_input("排序", min_value=0, step=1, value=0, key=_db_preview_source_relation_key(question_id, "topic_order"))
            topic_note = st.text_input("专题备注", key=_db_preview_source_relation_key(question_id, "topic_note"))
            topic_submit = st.form_submit_button("保存专题来源", type="primary", use_container_width=True)
        if topic_submit:
            try:
                upsert_question_topic_link(
                    db_path,
                    question_id,
                    module_name=topic_module,
                    topic_name=topic_name,
                    topic_file_name=topic_file,
                    group_name=topic_group,
                    sort_order=topic_order,
                    topic_note=topic_note,
                    operator="streamlit_ui",
                )
                _db_preview_clear_question_payload_cache()
                st.toast("专题来源已保存", icon="✅")
                st.rerun()
            except Exception as exc:
                st.error(f"保存专题来源失败：{exc}")


def _db_preview_build_draft_tex(question: dict, form_values: dict) -> str:
    from services.export_service import question_to_legacy_tex
    from services.question_edit_service import edit_form_to_question_updates

    draft_question = dict(question)
    draft_question.update(edit_form_to_question_updates(form_values))
    return question_to_legacy_tex(draft_question)


def _db_preview_render_question_edit_form(
    db_path: str,
    question_id: str,
    question: dict,
    *,
    show_preview: bool = True,
    handle_save: bool = True,
    show_management_panels: bool = True,
):
    from services.question_edit_service import (
        edit_form_to_question_updates_with_canonical,
        get_question_edit_state,
        update_question_fields,
    )

    edit_state = get_question_edit_state(db_path, question_id, revision_limit=5)
    form_values = edit_state.get("form") or {}
    _db_preview_prepare_edit_form_state(question_id, form_values)

    question_types = edit_state.get("question_types") or []
    type_labels = {None: "未设置"}
    type_options = [None]
    for type_item in question_types:
        type_id = type_item.get("question_type_id")
        if type_id not in type_options:
            type_options.append(type_id)
        type_labels[type_id] = type_item.get("name") or type_item.get("code") or str(type_id)
    current_type = form_values.get("question_type_id")
    if current_type not in type_options:
        type_options.append(current_type)
        type_labels[current_type] = str(current_type)

    difficulty_options = [None, 1, 2, 3, 4, 5]
    current_difficulty = form_values.get("difficulty")
    if current_difficulty not in difficulty_options:
        difficulty_options.append(current_difficulty)

    edit_container = st.container()
    preview_container = st.container() if show_preview else None
    save_submitted = False
    with edit_container:
        st.markdown(
            """
            <div class="mc-db-edit-toolbar-title">TeX 编辑区</div>
            <div class="mc-db-edit-toolbar-caption">这里可以直接修改题干、选项、答案、解析、标签和备注。</div>
            """,
            unsafe_allow_html=True,
        )
        if st.button(
            "退出修改",
            key=f"db_browse_exit_edit_{_db_preview_edit_hash(question_id)}",
            use_container_width=True,
        ):
            _db_preview_cancel_edit(question_id, restore_browse=True)
            st.rerun()

        st.markdown('<span class="mc-db-edit-panel-anchor"></span>', unsafe_allow_html=True)
        st.markdown(
            "<div class='mc-db-edit-note'><strong>编辑态：</strong>保存只写入 SQLite，并自动记录 revision；不会修改旧 TeX 文件。</div>",
            unsafe_allow_html=True,
        )
        _db_preview_render_asset_upload_panel(db_path, question_id, compact_layout=True)
        st.selectbox(
            "题型",
            type_options,
            format_func=lambda value: type_labels.get(value, "未设置"),
            key=_db_preview_edit_field_key(question_id, "question_type_id"),
        )
        st.selectbox(
            "难度星级",
            difficulty_options,
            format_func=lambda value: "未设置" if value is None else f"{value} 星",
            key=_db_preview_edit_field_key(question_id, "difficulty"),
        )
        st.checkbox("官方", key=_db_preview_edit_field_key(question_id, "official_flag"))

        st.text_area("题干 TeX", key=_db_preview_edit_field_key(question_id, "stem_tex"), height=160)
        _db_preview_render_structured_choice_editor(question_id, form_values.get("choices_text", ""))
        st.text_area("答案 TeX", key=_db_preview_edit_field_key(question_id, "answer_tex"), height=90)
        st.text_area("解析 TeX", key=_db_preview_edit_field_key(question_id, "solution_tex"), height=170)
        st.text_input("标签（逗号或换行分隔）", key=_db_preview_edit_field_key(question_id, "tags_text"))
        st.text_area("备注", key=_db_preview_edit_field_key(question_id, "note"), height=70)

        st.markdown('<div class="mc-db-edit-actions"></div>', unsafe_allow_html=True)
        save_submitted = st.button(
            "💾 保存修改",
            key=f"db_browse_save_edit_{_db_preview_edit_hash(question_id)}",
            type="primary",
            use_container_width=True,
        )
        st.caption("如果不想保存，使用编辑区右上角的“退出修改”。")
        st.markdown(_db_preview_revision_details_html(edit_state.get("revisions") or []), unsafe_allow_html=True)

    form_current_values = _db_preview_collect_edit_form_values(question_id)
    if handle_save and save_submitted:
        try:
            updates = edit_form_to_question_updates_with_canonical(question, form_current_values)
            update_result = update_question_fields(
                db_path,
                question_id,
                updates,
                operator="streamlit_ui",
                note="SQLite 前端单题手动编辑",
                change_source="manual_edit",
            )
            if update_result.get("changed_fields"):
                _db_preview_cancel_edit(question_id, restore_browse=True)
                _db_preview_clear_question_payload_cache()
                st.toast(f"{question_id} 已保存，并记录 revision", icon="✅")
                st.rerun()
            else:
                _db_preview_cancel_edit(question_id, restore_browse=True)
                st.toast("没有检测到变更，已退出修改。", icon="ℹ️")
                st.rerun()
        except Exception as exc:
            st.error(f"保存失败：{exc}")

    if show_preview and preview_container is not None:
        with preview_container:
            st.markdown('<div class="mc-db-edit-toolbar-title">编辑草稿预览</div>', unsafe_allow_html=True)
            st.markdown(
                "<div class='mc-db-edit-preview-caption'>预览基于当前表单缓存；保存后会重新读取数据库并刷新。</div>",
                unsafe_allow_html=True,
            )
            try:
                draft_tex = _db_preview_build_draft_tex(question, form_current_values)
                st.download_button(
                    "下载草稿 TeX",
                    data=draft_tex,
                    file_name=f"{question_id}_draft.tex",
                    mime="text/x-tex",
                    key=f"db_browse_download_draft_{_db_preview_edit_hash(question_id)}",
                    use_container_width=True,
                )
                from services.asset_service import list_assets

                draft_markdown = _cached_latex_to_markdown(draft_tex, show_title=False)
                draft_markdown = _db_preview_apply_includegraphics_previews(draft_markdown, question)
                draft_markdown = _db_preview_apply_questionasset_previews(
                    draft_markdown,
                    list_assets(db_path, question_id=question_id),
                )
                render_question_preview(draft_tex, show_title=False, prepared_markdown=draft_markdown)
            except Exception as exc:
                st.warning(f"草稿渲染失败：{exc}")

    if show_management_panels:
        _db_preview_render_asset_management(db_path, question_id)
        _db_preview_render_source_relation_management(db_path, question_id, question)
    return save_submitted, form_current_values


def _db_preview_render_question_edit_workspace(db_path: str, question_id: str, question: dict):
    from services.question_edit_service import (
        edit_form_to_question_updates_with_canonical,
        get_question_edit_state,
        update_question_fields,
    )

    st.markdown('<span class="mc-db-edit-workspace-anchor"></span>', unsafe_allow_html=True)
    st.markdown(f"### {html.escape(_db_preview_label(question))}", unsafe_allow_html=True)
    st.caption(f"ID: {question_id} · 仅显示当前题目，保存或退出后会回到原来的位置。")

    edit_state = get_question_edit_state(db_path, question_id, revision_limit=5)
    form_values = edit_state.get("form") or {}
    _db_preview_prepare_edit_form_state(question_id, form_values)

    question_types = edit_state.get("question_types") or []
    type_labels = {None: "未设置"}
    type_options = [None]
    for type_item in question_types:
        type_id = type_item.get("question_type_id")
        if type_id not in type_options:
            type_options.append(type_id)
        type_labels[type_id] = type_item.get("name") or type_item.get("code") or str(type_id)
    current_type = form_values.get("question_type_id")
    if current_type not in type_options:
        type_options.append(current_type)
        type_labels[current_type] = str(current_type)

    difficulty_options = [None, 1, 2, 3, 4, 5]
    current_difficulty = form_values.get("difficulty")
    if current_difficulty not in difficulty_options:
        difficulty_options.append(current_difficulty)

    left_col, middle_col, preview_col = st.columns([1.02, 0.96, 1.12], gap="large")
    save_submitted = False
    with left_col:
        st.markdown(
            """
            <div class="mc-db-edit-toolbar-title">TeX 编辑区</div>
            <div class="mc-db-edit-toolbar-caption">题干、选项和基础信息放在这里。</div>
            """,
            unsafe_allow_html=True,
        )
        if st.button(
            "退出修改",
            key=f"db_browse_exit_edit_{_db_preview_edit_hash(question_id)}",
            use_container_width=True,
        ):
            _db_preview_cancel_edit(question_id, restore_browse=True)
            st.rerun()

        st.markdown('<span class="mc-db-edit-panel-anchor"></span>', unsafe_allow_html=True)
        st.markdown(
            "<div class='mc-db-edit-note'><strong>编辑态：</strong>保存只写入 SQLite，并自动记录 revision；不会修改旧 TeX 文件。</div>",
            unsafe_allow_html=True,
        )
        _db_preview_render_asset_upload_panel(db_path, question_id, compact_layout=True)
        st.selectbox(
            "题型",
            type_options,
            format_func=lambda value: type_labels.get(value, "未设置"),
            key=_db_preview_edit_field_key(question_id, "question_type_id"),
        )
        st.selectbox(
            "难度星级",
            difficulty_options,
            format_func=lambda value: "未设置" if value is None else f"{value} 星",
            key=_db_preview_edit_field_key(question_id, "difficulty"),
        )
        st.checkbox("官方", key=_db_preview_edit_field_key(question_id, "official_flag"))
        _db_preview_render_structured_choice_editor(question_id, form_values.get("choices_text", ""))
        st.markdown(_db_preview_revision_details_html(edit_state.get("revisions") or []), unsafe_allow_html=True)

    with middle_col:
        st.markdown('<span class="mc-db-edit-save-panel-anchor"></span>', unsafe_allow_html=True)
        st.markdown(
            """
            <div class="mc-db-edit-toolbar-title">答案与保存</div>
            <div class="mc-db-edit-toolbar-caption">答案、解析、标签、备注和保存操作。</div>
            """,
            unsafe_allow_html=True,
        )
        st.text_area("题干 TeX", key=_db_preview_edit_field_key(question_id, "stem_tex"), height=160)
        st.text_area("答案 TeX", key=_db_preview_edit_field_key(question_id, "answer_tex"), height=92)
        st.text_area("解析 TeX", key=_db_preview_edit_field_key(question_id, "solution_tex"), height=210)
        st.text_input("标签（逗号或换行分隔）", key=_db_preview_edit_field_key(question_id, "tags_text"))
        st.text_area("备注", key=_db_preview_edit_field_key(question_id, "note"), height=92)
        st.markdown('<div class="mc-db-edit-actions"></div>', unsafe_allow_html=True)
        save_submitted = st.button(
            "💾 保存修改",
            key=f"db_browse_save_edit_{_db_preview_edit_hash(question_id)}",
            type="primary",
            use_container_width=True,
        )
        st.caption("如果不想保存，使用左侧顶部的“退出修改”。")

    form_current_values = _db_preview_collect_edit_form_values(question_id)

    with preview_col:
        st.markdown('<span class="mc-db-edit-workspace-preview-anchor"></span>', unsafe_allow_html=True)
        st.markdown('<div class="mc-db-edit-toolbar-title">编辑草稿预览</div>', unsafe_allow_html=True)
        st.markdown(
            "<div class='mc-db-edit-preview-caption'>预览基于当前表单缓存；保存后会重新读取数据库并刷新。</div>",
            unsafe_allow_html=True,
        )
        try:
            from services.asset_service import list_assets

            preview_assets = list_assets(db_path, question_id=question_id)
        except Exception as exc:
            preview_assets = []
            st.caption(f"图片资源计数读取失败：{exc}")
        relation_counts = _db_preview_source_relation_counts(db_path, question_id)
        relation_total = sum(relation_counts.values())
        with st.popover(f"图片资源 · {len(preview_assets)}", use_container_width=True):
            _db_preview_render_asset_management(db_path, question_id)
        with st.popover(f"来源关系 · {relation_total}", use_container_width=True):
            st.caption(
                f"试卷 {relation_counts['paper']} · 教材 {relation_counts['book']} · 专题 {relation_counts['topic']}"
            )
            _db_preview_render_source_relation_management(
                db_path,
                question_id,
                question,
                outer_label=None,
            )
        try:
            draft_tex = _db_preview_build_draft_tex(question, form_current_values)
            st.download_button(
                "下载草稿 TeX",
                data=draft_tex,
                file_name=f"{question_id}_draft.tex",
                mime="text/x-tex",
                key=f"db_browse_download_draft_{_db_preview_edit_hash(question_id)}",
                use_container_width=True,
            )
            draft_markdown = _cached_latex_to_markdown(draft_tex, show_title=False)
            draft_markdown = _db_preview_apply_includegraphics_previews(draft_markdown, question)
            draft_markdown = _db_preview_apply_questionasset_previews(
                draft_markdown,
                preview_assets,
            )
            render_question_preview(draft_tex, show_title=False, prepared_markdown=draft_markdown)
        except Exception as exc:
            st.warning(f"草稿渲染失败：{exc}")

    if save_submitted:
        try:
            updates = edit_form_to_question_updates_with_canonical(question, form_current_values)
            update_result = update_question_fields(
                db_path,
                question_id,
                updates,
                operator="streamlit_ui",
                note="SQLite 前端单题手动编辑",
                change_source="manual_edit",
            )
            if update_result.get("changed_fields"):
                _db_preview_cancel_edit(question_id, restore_browse=True)
                _db_preview_clear_question_payload_cache()
                st.toast(f"{question_id} 已保存，并记录 revision", icon="✅")
                st.rerun()
            else:
                _db_preview_cancel_edit(question_id, restore_browse=True)
                st.toast("没有检测到变更，已退出修改。", icon="ℹ️")
                st.rerun()
        except Exception as exc:
            st.error(f"保存失败：{exc}")

    st.markdown("<div class='mc-db-edit-workspace-end'></div>", unsafe_allow_html=True)


@st.cache_data(show_spinner=False, max_entries=512)
def _db_preview_question_payload(db_path: str, question_id: str, db_mtime: float):
    from services.export_service import question_to_legacy_tex
    from services.question_db_service import get_question_bundle

    bundle = get_question_bundle(db_path, question_id)
    question = bundle.get("question") or {}
    legacy_tex = question_to_legacy_tex(question)
    preview_markdown = _cached_latex_to_markdown(legacy_tex, show_title=False)
    preview_markdown = _db_preview_apply_includegraphics_previews(preview_markdown, question)
    preview_markdown = _db_preview_apply_questionasset_previews(preview_markdown, bundle.get("assets") or [])
    return {
        "bundle": bundle,
        "question": question,
        "legacy_tex": legacy_tex,
        "preview_markdown": preview_markdown,
    }


def _db_preview_resolve_project_file(relative_path: str) -> str:
    if not relative_path:
        return ""
    root = os.path.abspath(APP_ROOT)
    candidate = os.path.abspath(os.path.join(root, relative_path))
    try:
        if os.path.commonpath([root, candidate]) != root:
            return ""
    except ValueError:
        return ""
    return candidate


@st.cache_data(show_spinner=False, max_entries=256)
def _db_preview_asset_data_uri(abs_path: str, mime_type: str, file_size: int, file_mtime: float) -> str:
    if not abs_path or not os.path.exists(abs_path):
        return ""
    if file_size > 2 * 1024 * 1024:
        return ""
    safe_mime = mime_type or "image/png"
    with open(abs_path, "rb") as file:
        encoded = base64.b64encode(file.read()).decode("ascii")
    return f"data:{safe_mime};base64,{encoded}"


def _db_preview_inline_asset_html(asset: dict, alias: str) -> str:
    file_path = str(asset.get("file_path") or "")
    abs_path = _db_preview_resolve_project_file(file_path)
    exists = bool(abs_path and os.path.exists(abs_path))
    mime_type = str(asset.get("mime_type") or "")
    caption = str(asset.get("caption") or asset.get("original_file_name") or alias)
    if exists and mime_type.startswith("image/"):
        file_size = os.path.getsize(abs_path)
        file_mtime = os.path.getmtime(abs_path)
        data_uri = _db_preview_asset_data_uri(abs_path, mime_type, file_size, file_mtime)
        if data_uri:
            return f"""
            <figure class="mc-db-inline-asset">
                <img src="{data_uri}" alt="{html.escape(caption)}" loading="lazy" />
                <figcaption>{html.escape(caption)} · {html.escape(alias)}</figcaption>
            </figure>
            """
    if exists:
        return f"""
        <span class="mc-db-inline-asset-file">
            附件：{html.escape(caption)} · {html.escape(file_path)}
        </span>
        """
    return f"""
    <span class="mc-db-inline-asset-missing">
        未找到图片资源：{html.escape(alias)}
    </span>
    """


def _db_preview_inline_file_html(abs_path: str, ref: str) -> str:
    import mimetypes

    mime_type = mimetypes.guess_type(abs_path)[0] or ""
    file_name = os.path.basename(abs_path)
    if mime_type.startswith("image/"):
        file_size = os.path.getsize(abs_path)
        file_mtime = os.path.getmtime(abs_path)
        data_uri = _db_preview_asset_data_uri(abs_path, mime_type, file_size, file_mtime)
        if data_uri:
            return f"""
            <figure class="mc-db-inline-asset">
                <img src="{data_uri}" alt="{html.escape(file_name)}" loading="lazy" />
                <figcaption>{html.escape(file_name)} · {html.escape(ref)}</figcaption>
            </figure>
            """
    return f"""
    <span class="mc-db-inline-asset-file">
        附件：{html.escape(file_name)} · {html.escape(ref)}
    </span>
    """


def _db_preview_apply_includegraphics_previews(markdown_text: str, question: dict) -> str:
    if not markdown_text or r"\includegraphics" not in markdown_text:
        return markdown_text

    from services.export_service import INCLUDE_GRAPHICS_PATTERN, resolve_graphics_ref

    source_file = question.get("legacy_file_path") or ""

    def replace(match) -> str:
        ref = match.group("path").strip()
        resolved = resolve_graphics_ref(ref, source_file, APP_ROOT)
        if not resolved:
            return f"<span class='mc-db-inline-asset-missing'>未找到 includegraphics 图片：{html.escape(ref)}</span>"
        return _db_preview_inline_file_html(str(resolved), ref)

    return INCLUDE_GRAPHICS_PATTERN.sub(replace, markdown_text)


def _db_preview_apply_questionasset_previews(markdown_text: str, assets: list[dict]) -> str:
    if not markdown_text or r"\questionasset" not in markdown_text:
        return markdown_text

    from services.export_service import QUESTION_ASSET_PATTERN, find_asset_by_alias

    safe_assets = assets or []

    def replace(match) -> str:
        alias = match.group("alias").strip()
        asset = find_asset_by_alias(safe_assets, alias)
        if not asset:
            return f"<span class='mc-db-inline-asset-missing'>未登记图片资源：{html.escape(alias)}</span>"
        return _db_preview_inline_asset_html(asset, alias)

    return QUESTION_ASSET_PATTERN.sub(replace, markdown_text)


def _db_preview_asset_card_html(asset: dict) -> str:
    from services.asset_service import asset_placeholder

    file_path = str(asset.get("file_path") or "")
    abs_path = _db_preview_resolve_project_file(file_path)
    exists = bool(abs_path and os.path.exists(abs_path))
    mime_type = str(asset.get("mime_type") or "")
    file_size = os.path.getsize(abs_path) if exists else 0
    file_mtime = os.path.getmtime(abs_path) if exists else 0
    data_uri = ""
    if exists and mime_type.startswith("image/"):
        data_uri = _db_preview_asset_data_uri(abs_path, mime_type, file_size, file_mtime)

    status_class = "ok" if exists else "missing"
    status_text = "可预览" if data_uri else ("已登记" if exists else "文件缺失")
    caption = str(asset.get("caption") or asset.get("original_file_name") or "")
    meta_bits = [
        str(asset.get("role") or "asset"),
        str(asset.get("asset_id") or ""),
        f"{round(file_size / 1024, 1)} KB" if file_size else "",
    ]
    meta = " · ".join(bit for bit in meta_bits if bit)
    try:
        placeholder_text = asset_placeholder(asset)
    except Exception:
        placeholder_text = ""
    preview = (
        f"<img src='{data_uri}' alt='{html.escape(caption or file_path)}' loading='lazy' />"
        if data_uri
        else "<div class='mc-db-asset-placeholder'>暂无缩略图</div>"
    )
    placeholder_html = (
        f"""
        <div class='mc-db-asset-placeholder-row'>
            <div class='mc-db-asset-placeholder-code'>{html.escape(placeholder_text)}</div>
            <button
                type='button'
                class='mc-db-asset-copy-btn'
                data-copy-text="{html.escape(placeholder_text, quote=True)}"
                onclick="navigator.clipboard.writeText(this.dataset.copyText).then(() => {{ this.textContent = '已复制'; }}).catch(() => {{ this.textContent = '复制失败'; }}); return false;"
            >复制占位符</button>
        </div>
        """
        if placeholder_text
        else ""
    )
    return f"""
    <article class="mc-db-asset-card">
        <div class="mc-db-asset-preview">{preview}</div>
        <div class="mc-db-asset-info">
            <div class="mc-db-asset-title">{html.escape(caption or os.path.basename(file_path) or "未命名资源")}</div>
            <div class="mc-db-asset-meta">{html.escape(meta)}</div>
            <div class="mc-db-asset-path">{html.escape(file_path)}</div>
            {placeholder_html}
        </div>
        <span class="mc-db-asset-status {status_class}">{html.escape(status_text)}</span>
    </article>
    """


def _db_preview_revision_details_html(revisions: list[dict]) -> str:
    rows = []
    for revision in revisions:
        raw_fields = revision.get("changed_fields_json") or "[]"
        try:
            fields = json.loads(raw_fields)
        except Exception:
            fields = []
        if not isinstance(fields, list):
            fields = []
        field_text = "，".join(str(field) for field in fields) or "未记录字段"
        rows.append(
            "<li>"
            f"<strong>{html.escape(str(revision.get('created_at') or ''))}</strong>"
            f"<span>{html.escape(str(revision.get('change_source') or ''))}</span>"
            f"<em>{html.escape(field_text)}</em>"
            "</li>"
        )
    content = f"<ul>{''.join(rows)}</ul>" if rows else "<p>暂无修订记录。</p>"
    return f"""
    <details class="mc-db-revision-details">
        <summary>最近修订记录</summary>
        <div class="mc-db-revision-details-body">{content}</div>
    </details>
    """


def _db_preview_material_drawer_html(bundle: dict) -> str:
    def list_section(title: str, rows: list[str]) -> str:
        if not rows:
            return (
                "<section class='mc-db-material-section'>"
                f"<div class='mc-db-material-section-title'>{html.escape(title)}</div>"
                "<p class='mc-db-material-empty'>暂无记录。</p>"
                "</section>"
            )
        return (
            "<section class='mc-db-material-section'>"
            f"<div class='mc-db-material-section-title'>{html.escape(title)}</div>"
            f"<ul class='mc-db-material-list'>{''.join(f'<li>{html.escape(row)}</li>' for row in rows)}</ul>"
            "</section>"
        )

    from services.traceback_service import build_question_traceback

    traceback = build_question_traceback(bundle, project_root=APP_ROOT)
    assets = traceback.get("assets") or []

    sections = [list_section("来源回溯", traceback.get("source_rows") or [])]
    if assets:
        sections.append(
            "<section class='mc-db-material-section'>"
            "<div class='mc-db-material-section-title'>图片资源</div>"
            f"<div class='mc-db-asset-grid'>{''.join(_db_preview_asset_card_html(asset) for asset in assets)}</div>"
            "</section>"
        )
    else:
        sections.append(list_section("图片资源", []))

    issue_rows = traceback.get("asset_issue_rows") or []
    sections.append(list_section("图片引用检查", issue_rows))
    summary_text = str(traceback.get("summary") or "暂无资料")

    return f"""
    <div class="mc-db-material-drawer-shell">
        <details class="mc-db-material-drawer">
            <summary><strong>题目回溯 / 图片资源</strong><span>{html.escape(summary_text)}</span></summary>
            <div class="mc-db-material-drawer-body">{''.join(sections)}</div>
        </details>
    </div>
    """


def render_sqlite_readonly_browse_preview(
    *,
    allow_edit: bool = True,
    allow_exam_basket: bool = True,
    show_export_panel: bool = True,
    right_heading: str | None = None,
    right_caption: str | None = None,
):
    from services.database_service import DEFAULT_DATABASE_PATH
    from services.question_db_service import (
        QuestionListFilters,
        list_question_filter_options,
        list_questions_page,
    )
    from services.sqlite_legacy_adapter import (
        list_resolved_legacy_card_paths,
        resolve_legacy_card_file_path,
        sqlite_bundle_to_legacy_card,
    )

    st.markdown('<span class="mc-db-browse-anchor"></span>', unsafe_allow_html=True)
    st.markdown("""
    <style>
    div[data-testid="stHorizontalBlock"]:has(> div[data-testid="column"] .mc-db-browse-left-anchor) {
        align-items: flex-start !important;
        gap: 1rem !important;
    }
    div[data-testid="stHorizontalBlock"]:has(> div[data-testid="column"] .mc-db-browse-left-anchor) > div {
        min-width: 0 !important;
        box-sizing: border-box !important;
    }
    div[data-testid="stHorizontalBlock"]:has(> div[data-testid="column"] .mc-db-browse-left-anchor) > div:first-child {
        min-width: 0 !important;
        flex: 0 0 clamp(18rem, 22vw, 21rem) !important;
        max-width: clamp(18rem, 22vw, 21rem) !important;
    }
    div[data-testid="stHorizontalBlock"]:has(> div[data-testid="column"] .mc-db-browse-left-anchor) > div:last-child {
        min-width: 0 !important;
        flex: 1 1 0% !important;
    }
    div[data-testid="column"]:has(> div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"] .mc-db-browse-left-anchor) {
        position: sticky !important;
        top: 0.75rem !important;
        align-self: flex-start !important;
        z-index: 8 !important;
        height: fit-content !important;
        max-height: calc(100vh - 1.5rem) !important;
        overflow: visible !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mc-db-browse-left-anchor) {
        gap: 0.42rem !important;
        padding: 0.95rem 0.95rem 1.05rem !important;
        border: 1px solid rgba(109, 40, 217, 0.14) !important;
        border-radius: 14px !important;
        background: #ffffff !important;
        box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06) !important;
        box-sizing: border-box !important;
        width: 100% !important;
        max-width: 100% !important;
        max-height: calc(100vh - 1.5rem) !important;
        overflow-x: hidden !important;
        overflow-y: auto !important;
        scrollbar-gutter: stable !important;
    }
    body:has(.mc-db-browse-anchor) div[data-testid="stVerticalBlockBorderWrapper"]:has(> div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"] .mc-db-browse-card-anchor) {
        border: 1px solid rgba(148, 163, 184, 0.22) !important;
        border-radius: 16px !important;
        background: #ffffff !important;
        background-color: #ffffff !important;
        background-clip: padding-box !important;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.035) !important;
    }
    body:has(.mc-db-browse-anchor) div[data-testid="stVerticalBlockBorderWrapper"]:has(> div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"] .mc-db-browse-card-anchor) > div[data-testid="stVerticalBlock"] {
        width: 100% !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
        border-radius: 16px !important;
        background: #ffffff !important;
        background-color: #ffffff !important;
        padding: 0.86rem 0.92rem 0.72rem !important;
    }
    body:has(.mc-db-browse-anchor) div[data-testid="stVerticalBlockBorderWrapper"]:has(> div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"] .mc-db-browse-card-anchor) div[data-testid="stElementContainer"],
    body:has(.mc-db-browse-anchor) div[data-testid="stVerticalBlockBorderWrapper"]:has(> div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"] .mc-db-browse-card-anchor) div[data-testid="stMarkdownContainer"] {
        background: transparent !important;
    }
    body:has(.mc-db-browse-anchor) div[data-testid="stVerticalBlockBorderWrapper"]:has(> div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"] .mc-db-browse-card-anchor) div[data-testid="stHorizontalBlock"] > div {
        min-width: 0 !important;
    }
    body:has(.mc-db-browse-anchor) div[data-testid="stElementContainer"]:has(.mc-db-meta-action-anchor) {
        display: none !important;
    }
    body:has(.mc-db-browse-anchor) div[data-testid="stElementContainer"]:has(.mc-db-meta-action-anchor) + div[data-testid="stElementContainer"],
    body:has(.mc-db-browse-anchor) div[data-testid="stElementContainer"]:has(.mc-db-meta-action-anchor) + div[data-testid="stElementContainer"] div[data-testid="stButton"] {
        width: max-content !important;
        max-width: max-content !important;
        min-width: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        background: transparent !important;
    }
    body:has(.mc-db-browse-anchor) div[data-testid="stElementContainer"]:has(.mc-db-meta-action-anchor) + div[data-testid="stElementContainer"] button {
        width: 82px !important;
        max-width: 82px !important;
        min-width: 0 !important;
        min-height: 1.36rem !important;
        height: 1.36rem !important;
        padding: 0 0.46rem !important;
        border: 1px solid rgba(109, 40, 217, 0.18) !important;
        border-radius: 999px !important;
        background: #ffffff !important;
        color: #6d28d9 !important;
        box-shadow: none !important;
        font-size: 0.68rem !important;
        line-height: 1.2 !important;
        font-weight: 720 !important;
        white-space: nowrap !important;
        word-break: keep-all !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    body:has(.mc-db-browse-anchor) div[data-testid="stElementContainer"]:has(.mc-db-meta-action-anchor) + div[data-testid="stElementContainer"] button p {
        font-size: 0.68rem !important;
        line-height: 1.1 !important;
        white-space: nowrap !important;
    }
    body:has(.mc-db-browse-anchor) div[data-testid="stElementContainer"]:has(.mc-db-meta-action-anchor) + div[data-testid="stElementContainer"] button:hover {
        background: #ede9fe !important;
        color: #5b21b6 !important;
    }
    body:has(.mc-db-browse-anchor) div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-db-browse-card-anchor):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-db-browse-card-anchor)) pre,
    body:has(.mc-db-browse-anchor) div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-db-browse-card-anchor):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-db-browse-card-anchor)) code {
        max-width: 100% !important;
        overflow-x: auto !important;
    }
    body:has(.mc-db-browse-anchor) div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-db-browse-card-anchor):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-db-browse-card-anchor)) .katex-display {
        overflow-x: auto !important;
        overflow-y: hidden !important;
    }
    .mc-db-browse-kicker {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.18rem 0.55rem;
        border-radius: 999px;
        background: #eef2ff;
        color: #5b21b6;
        font-size: 0.78rem;
        font-weight: 760;
        margin: 0 0 0.45rem;
    }
    .mc-db-browse-title {
        margin: 0 0 0.25rem;
        color: #111827;
        font-size: 1.05rem;
        line-height: 1.35;
        font-weight: 780;
    }
    .mc-db-browse-meta {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 0.38rem 0.55rem;
        margin: 0.25rem 0 0.75rem;
        color: #4b5563;
        font-size: 0.86rem;
        line-height: 1.45;
    }
    .mc-db-browse-pill {
        display: inline-flex;
        align-items: center;
        padding: 0.14rem 0.48rem;
        border-radius: 999px;
        background: #f3f4f6;
        color: #374151;
        font-weight: 650;
    }
    .mc-db-browse-pill.purple {
        background: #f3e8ff;
        color: #6d28d9;
    }
    .mc-db-browse-pill.blue {
        background: #e0f2fe;
        color: #0369a1;
    }
    .mc-db-browse-source {
        color: #6b7280;
        font-size: 0.8rem;
        line-height: 1.45;
        margin-top: -0.25rem;
        word-break: break-all;
    }
    .mc-db-meta-action-anchor,
    .mc-db-code-action-anchor {
        display: block;
        height: 0;
        margin: 0;
        padding: 0;
    }
    .mc-db-material-drawer-shell {
        position: relative;
        display: block;
        min-height: 2.25rem;
        margin: -0.1rem 0 0.72rem;
    }
    .mc-db-material-drawer {
        position: absolute;
        top: 0;
        right: 0;
        z-index: 28;
        width: min(31rem, 100%);
        color: #374151;
        font-size: 0.84rem;
        line-height: 1.45;
    }
    .mc-db-material-drawer summary {
        display: grid;
        grid-template-columns: auto minmax(0, 1fr) auto;
        align-items: center;
        gap: 0.5rem;
        min-height: 2.12rem;
        padding: 0.44rem 0.62rem 0.44rem 0.72rem;
        border: 1px solid rgba(109, 40, 217, 0.18);
        border-radius: 999px;
        background: #ffffff;
        color: #4c1d95;
        box-shadow: 0 10px 26px rgba(15, 23, 42, 0.08);
        cursor: pointer;
        list-style: none;
        outline: none;
    }
    .mc-db-material-drawer summary::-webkit-details-marker {
        display: none;
    }
    .mc-db-material-drawer summary::after {
        content: "▾";
        grid-column: 3;
        color: #8b5cf6;
        font-size: 0.82rem;
        line-height: 1;
        transition: transform 160ms ease;
    }
    .mc-db-material-drawer[open] summary {
        border-radius: 14px 14px 0 0;
        background: #f7f4ff;
        box-shadow: 0 12px 30px rgba(15, 23, 42, 0.1);
    }
    .mc-db-material-drawer[open] summary::after {
        transform: rotate(180deg);
    }
    .mc-db-material-drawer summary strong {
        color: #4c1d95;
        font-size: 0.88rem;
        font-weight: 800;
        line-height: 1.2;
        white-space: nowrap;
    }
    .mc-db-material-drawer summary span {
        min-width: 0;
        overflow: hidden;
        color: #6d28d9;
        font-size: 0.76rem;
        font-weight: 720;
        text-align: right;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .mc-db-material-drawer-body {
        max-height: min(68vh, 40rem);
        overflow: auto;
        padding: 0.72rem;
        border: 1px solid rgba(109, 40, 217, 0.18);
        border-top: 0;
        border-radius: 0 0 14px 14px;
        background: #ffffff;
        box-shadow: 0 18px 42px rgba(15, 23, 42, 0.12);
    }
    .mc-db-material-section {
        padding: 0.62rem 0;
        border-top: 1px solid rgba(148, 163, 184, 0.18);
    }
    .mc-db-material-section:first-child {
        padding-top: 0;
        border-top: 0;
    }
    .mc-db-material-section:last-child {
        padding-bottom: 0;
    }
    .mc-db-material-section-title {
        margin: 0 0 0.38rem;
        color: #111827;
        font-size: 0.88rem;
        line-height: 1.25;
        font-weight: 800;
    }
    .mc-db-material-list {
        margin: 0;
        padding-left: 1.05rem;
        color: #4b5563;
    }
    .mc-db-material-list li {
        margin: 0.16rem 0;
        overflow-wrap: anywhere;
    }
    .mc-db-material-empty {
        margin: 0;
        color: #8a8f98;
    }
    .mc-db-inline-asset {
        display: grid;
        justify-items: center;
        gap: 0.32rem;
        margin: 0.75rem auto;
        padding: 0.68rem;
        border-radius: 12px;
        background: #f8fafc;
        border: 1px solid rgba(148, 163, 184, 0.22);
        max-width: min(100%, 34rem);
    }
    .mc-db-inline-asset img {
        display: block;
        max-width: 100%;
        max-height: 24rem;
        object-fit: contain;
        border-radius: 8px;
        background: #ffffff;
    }
    .mc-db-inline-asset figcaption {
        color: #64748b;
        font-size: 0.78rem;
        line-height: 1.35;
        text-align: center;
    }
    .mc-db-inline-asset-file,
    .mc-db-inline-asset-missing {
        display: inline-flex;
        max-width: 100%;
        margin: 0.35rem 0;
        padding: 0.18rem 0.48rem;
        border-radius: 8px;
        font-size: 0.82rem;
        line-height: 1.4;
        overflow-wrap: anywhere;
    }
    .mc-db-inline-asset-file {
        color: #0369a1;
        background: #e0f2fe;
    }
    .mc-db-inline-asset-missing {
        color: #92400e;
        background: #fef3c7;
    }
    .mc-db-asset-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
        gap: 0.55rem;
    }
    .mc-db-asset-card {
        position: relative;
        display: grid;
        grid-template-columns: 4.75rem minmax(0, 1fr);
        gap: 0.62rem;
        align-items: center;
        min-width: 0;
        padding: 0.52rem;
        border: 1px solid rgba(15, 23, 42, 0.08);
        border-radius: 10px;
        background: #fbfdff;
    }
    .mc-db-asset-preview {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 4.75rem;
        height: 4.15rem;
        overflow: hidden;
        border-radius: 8px;
        background: #f8fafc;
        border: 1px solid rgba(148, 163, 184, 0.22);
    }
    .mc-db-asset-preview img {
        max-width: 100%;
        max-height: 100%;
        object-fit: contain;
        display: block;
    }
    .mc-db-asset-placeholder {
        color: #94a3b8;
        font-size: 0.74rem;
        font-weight: 680;
    }
    .mc-db-asset-info {
        min-width: 0;
        padding-right: 3.6rem;
    }
    .mc-db-asset-title {
        color: #1f2937;
        font-size: 0.84rem;
        line-height: 1.35;
        font-weight: 760;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .mc-db-asset-meta,
    .mc-db-asset-path {
        margin-top: 0.18rem;
        color: #64748b;
        font-size: 0.76rem;
        line-height: 1.35;
        overflow-wrap: anywhere;
    }
    .mc-db-asset-placeholder-code {
        display: inline-flex;
        max-width: 100%;
        margin-top: 0.28rem;
        padding: 0.12rem 0.36rem;
        border-radius: 6px;
        background: #f1f5f9;
        color: #334155;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 0.72rem;
        line-height: 1.35;
        overflow-wrap: anywhere;
    }
    .mc-db-asset-placeholder-row {
        display: flex;
        align-items: center;
        gap: 0.32rem;
        flex-wrap: wrap;
        margin-top: 0.28rem;
    }
    .mc-db-asset-copy-btn {
        appearance: none;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 1.42rem;
        padding: 0.15rem 0.5rem;
        border: 1px solid rgba(109, 40, 217, 0.22);
        border-radius: 999px;
        background: #f5f3ff;
        color: #4c1d95;
        font-size: 0.7rem;
        line-height: 1;
        font-weight: 760;
        cursor: pointer;
        transition: background 140ms ease, border-color 140ms ease, transform 140ms ease;
    }
    .mc-db-asset-copy-btn:hover {
        background: #ede9fe;
        border-color: rgba(109, 40, 217, 0.3);
    }
    .mc-db-asset-copy-btn:active {
        transform: translateY(1px);
    }
    .mc-db-asset-status {
        position: absolute;
        top: 0.42rem;
        right: 0.42rem;
        padding: 0.1rem 0.38rem;
        border-radius: 999px;
        font-size: 0.68rem;
        line-height: 1.2;
        font-weight: 760;
    }
    .mc-db-asset-status.ok {
        color: #047857;
        background: #d1fae5;
    }
    .mc-db-asset-status.missing {
        color: #b45309;
        background: #fef3c7;
    }
    .mc-db-revision-details {
        margin: 0.62rem 0 0;
        border: 1px solid rgba(148, 163, 184, 0.24);
        border-radius: 12px;
        background: #ffffff;
        overflow: hidden;
        color: #4b5563;
        font-size: 0.84rem;
        line-height: 1.45;
    }
    .mc-db-revision-details summary {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.55rem;
        min-height: 2.15rem;
        padding: 0.44rem 0.66rem;
        cursor: pointer;
        color: #334155;
        background: #f8fafc;
        font-weight: 730;
        list-style: none;
        outline: none;
    }
    .mc-db-revision-details summary::-webkit-details-marker {
        display: none;
    }
    .mc-db-revision-details summary::after {
        content: "⌄";
        color: #64748b;
        font-size: 0.9rem;
        line-height: 1;
        transition: transform 160ms ease;
    }
    .mc-db-revision-details[open] summary::after {
        transform: rotate(180deg);
    }
    .mc-db-revision-details-body {
        padding: 0.62rem 0.7rem 0.68rem;
        border-top: 1px solid rgba(148, 163, 184, 0.18);
        background: #ffffff;
    }
    .mc-db-revision-details-body ul {
        margin: 0;
        padding-left: 1rem;
    }
    .mc-db-revision-details-body li {
        margin: 0.16rem 0;
        color: #64748b;
        word-break: break-word;
    }
    .mc-db-revision-details-body strong,
    .mc-db-revision-details-body span,
    .mc-db-revision-details-body em {
        margin-right: 0.45rem;
        font-style: normal;
    }
    .mc-db-revision-details-body strong {
        color: #334155;
        font-weight: 760;
    }
    .mc-db-edit-note {
        margin: 0.78rem 0 0.72rem;
        padding: 0.62rem 0.72rem;
        border-radius: 12px;
        background: #f8fafc;
        color: #475569;
        font-size: 0.86rem;
        line-height: 1.5;
        border: 1px solid rgba(148, 163, 184, 0.2);
    }
    .mc-db-edit-note strong {
        color: #4c1d95;
        font-weight: 780;
    }
    .mc-db-edit-toolbar-title {
        color: #1f2328;
        font-size: 1.14rem;
        line-height: 1.25;
        font-weight: 820;
    }
    .mc-db-edit-toolbar-caption {
        margin-top: 0.1rem;
        color: #64748b;
        font-size: 0.82rem;
        line-height: 1.35;
    }
    .mc-db-edit-panel-anchor {
        display: none;
    }
    .mc-db-edit-workspace-anchor,
    .mc-db-edit-save-panel-anchor,
    .mc-db-edit-workspace-preview-anchor {
        display: none;
    }
    body:has(.mc-db-edit-workspace-anchor) div[data-testid="stHorizontalBlock"]:has(.mc-db-edit-panel-anchor):has(.mc-db-edit-workspace-preview-anchor) {
        align-items: flex-start !important;
        gap: 1.2rem !important;
    }
    body:has(.mc-db-edit-workspace-anchor) div[data-testid="column"]:has(.mc-db-edit-panel-anchor),
    body:has(.mc-db-edit-workspace-anchor) div[data-testid="column"]:has(.mc-db-edit-save-panel-anchor),
    body:has(.mc-db-edit-workspace-anchor) div[data-testid="column"]:has(.mc-db-edit-workspace-preview-anchor) {
        min-width: 0 !important;
    }
    body:has(.mc-db-edit-workspace-anchor) div[data-testid="column"]:has(.mc-db-edit-panel-anchor) textarea,
    body:has(.mc-db-edit-workspace-anchor) div[data-testid="column"]:has(.mc-db-edit-save-panel-anchor) textarea,
    body:has(.mc-db-edit-workspace-anchor) div[data-testid="column"]:has(.mc-db-edit-panel-anchor) input,
    body:has(.mc-db-edit-workspace-anchor) div[data-testid="column"]:has(.mc-db-edit-save-panel-anchor) input {
        background: #ffffff !important;
    }
    body:has(.mc-db-edit-workspace-anchor) div[data-testid="column"]:has(.mc-db-edit-workspace-preview-anchor) > div[data-testid="stVerticalBlock"] {
        position: sticky !important;
        top: 0.75rem !important;
        padding: 0.92rem 1rem !important;
        border: 1px solid rgba(148, 163, 184, 0.22) !important;
        border-radius: 16px !important;
        background: #ffffff !important;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.035) !important;
        max-height: calc(100vh - 1.5rem) !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
    }
    body:has(.mc-db-edit-workspace-anchor) div[data-testid="column"]:has(.mc-db-edit-workspace-preview-anchor) .katex-display {
        overflow-x: auto !important;
        overflow-y: hidden !important;
    }
    body:has(.mc-db-edit-workspace-anchor) div[class*="st-key-db_browse_exit_edit_"] button {
        background: #fff1f2 !important;
        border-color: rgba(244, 63, 94, 0.34) !important;
        color: #9f1239 !important;
        box-shadow: none !important;
    }
    body:has(.mc-db-edit-workspace-anchor) div[class*="st-key-db_browse_exit_edit_"] button:hover {
        background: #ffe4e6 !important;
        border-color: rgba(225, 29, 72, 0.48) !important;
        color: #881337 !important;
    }
    .mc-db-edit-actions {
        margin-top: 0.55rem;
    }
    body:has(.mc-db-browse-anchor) div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mc-db-edit-panel-anchor) {
        padding: 0.2rem 0 0 !important;
        gap: 0.45rem !important;
    }
    body:has(.mc-db-browse-anchor) div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mc-db-edit-panel-anchor) textarea,
    body:has(.mc-db-browse-anchor) div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mc-db-edit-panel-anchor) input {
        background: #ffffff !important;
    }
    .mc-db-edit-preview-caption {
        margin: 0.15rem 0 0.6rem;
        color: #6b7280;
        font-size: 0.84rem;
        line-height: 1.45;
    }
    .mc-db-source-export-help {
        margin: 0.15rem 0 0.75rem;
        padding: 0.62rem 0.72rem;
        border-radius: 12px;
        background: #f8fafc;
        border: 1px solid rgba(148, 163, 184, 0.18);
        color: #475569;
        font-size: 0.84rem;
        line-height: 1.5;
    }
    .mc-db-source-export-help strong {
        color: #4c1d95;
        font-weight: 780;
    }
    .mc-db-asset-upload-panel {
        margin: 0.72rem 0 0.52rem;
        padding: 0.62rem 0.72rem;
        border-radius: 12px;
        border: 1px solid rgba(109, 40, 217, 0.14);
        background: #fbfaff;
        color: #4b5563;
        font-size: 0.84rem;
        line-height: 1.45;
    }
    .mc-db-asset-upload-panel strong {
        display: block;
        margin-bottom: 0.16rem;
        color: #4c1d95;
        font-size: 0.9rem;
        font-weight: 780;
    }
    .mc-db-asset-upload-card {
        display: grid;
        gap: 0.14rem;
        margin: 0.72rem 0 0.34rem;
        padding: 0.58rem 0.66rem;
        border-radius: 10px;
        border: 1px solid rgba(148, 163, 184, 0.18);
        background: #ffffff;
        color: #334155;
    }
    .mc-db-asset-upload-card strong {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        color: #334155;
        font-size: 0.86rem;
        line-height: 1.3;
        font-weight: 780;
    }
    .mc-db-asset-upload-card span {
        color: #64748b;
        font-size: 0.76rem;
        line-height: 1.35;
        overflow-wrap: anywhere;
    }
    .mc-db-asset-edit-card {
        display: grid;
        gap: 0.18rem;
        margin: 0.18rem 0 0.42rem;
        padding: 0.58rem 0.66rem;
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: 10px;
        background: #ffffff;
        color: #334155;
    }
    .mc-db-asset-edit-card strong {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: 0.86rem;
        line-height: 1.3;
        font-weight: 780;
    }
    .mc-db-asset-edit-card span {
        color: #64748b;
        font-size: 0.76rem;
        line-height: 1.35;
        overflow-wrap: anywhere;
    }
    .mc-db-browse-empty {
        padding: 1.2rem;
        border: 1px dashed rgba(109, 40, 217, 0.25);
        border-radius: 14px;
        background: #faf5ff;
        color: #5b21b6;
        font-weight: 680;
    }
    .mc-db-sidebar-section-label {
        margin: 1.18rem 0 0.38rem;
        color: #1f2328;
        font-size: 1.18rem;
        line-height: 1.25;
        font-weight: 820;
    }
    .mc-db-sidebar-caption {
        color: #6b7280;
        font-size: 0.84rem;
        line-height: 1.45;
        margin: -0.08rem 0 0.62rem;
    }
    .mc-db-search-state {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.65rem;
        padding: 0.56rem 0.65rem;
        margin: 0.35rem 0 0.7rem;
        border-radius: 12px;
        background: #f5f3ff;
        color: #5b21b6;
        font-size: 0.88rem;
        font-weight: 760;
    }
    .mc-db-search-state span {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .mc-db-result-card {
        margin-top: 0.75rem;
        padding-top: 0.9rem;
        border-top: 1px solid rgba(109, 40, 217, 0.18);
    }
    .mc-db-result-summary {
        display: grid;
        grid-template-columns: auto minmax(0, 1fr);
        align-items: center;
        gap: 0.55rem;
        margin-bottom: 0.5rem;
        color: #1f2328;
        font-size: 1.08rem;
        line-height: 1.25;
        font-weight: 820;
    }
    .mc-db-result-summary span {
        color: #6d28d9;
        font-size: 0.82rem;
        font-weight: 760;
        text-align: right;
        min-width: 0;
        overflow-wrap: anywhere;
    }
    .mc-db-result-caption {
        margin: -0.15rem 0 0.55rem;
        color: #6b7280;
        font-size: 0.82rem;
        line-height: 1.35;
    }
    .mc-db-question-list-title {
        margin: 1rem 0 0.42rem;
        color: #1f2328;
        font-size: 1.02rem;
        font-weight: 780;
    }
    .mc-db-single-edit-heading {
        display: inline-flex;
        align-items: center;
        gap: 0.46rem;
        margin: 0.08rem 0 0.28rem;
        color: #5b21b6;
        font-size: 1.46rem;
        line-height: 1.22;
        font-weight: 860;
        letter-spacing: -0.025em;
    }
    .mc-db-single-edit-heading::before {
        content: "";
        width: 0.52rem;
        height: 1.55rem;
        border-radius: 999px;
        background: linear-gradient(180deg, #7c3aed, #a78bfa);
        box-shadow: 0 8px 18px rgba(124, 58, 237, 0.18);
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mc-db-browse-left-anchor) hr {
        margin: 0.78rem 0 !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mc-db-browse-left-anchor) label {
        margin-bottom: 0.12rem !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mc-db-browse-left-anchor) div[data-testid="stButton"] > button {
        width: 100% !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
        min-height: 2.25rem !important;
        border-color: rgba(109, 40, 217, 0.36) !important;
        border-radius: 8px !important;
        font-weight: 700 !important;
        line-height: 1.15 !important;
        white-space: normal !important;
        padding-left: 0.42rem !important;
        padding-right: 0.42rem !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mc-db-browse-left-anchor) div[data-testid="stDownloadButton"] > button {
        width: 100% !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
        white-space: normal !important;
        padding-left: 0.42rem !important;
        padding-right: 0.42rem !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mc-db-browse-left-anchor) div[data-testid="stButton"] > button[kind="primary"] {
        background: #d8c3fb !important;
        border-color: #b794f4 !important;
        color: #241238 !important;
        box-shadow: none !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mc-db-browse-left-anchor) div[data-testid="stButton"] > button:hover {
        border-color: #8b5cf6 !important;
        background: #f5f3ff !important;
        color: #4c1d95 !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mc-db-browse-left-anchor) [data-baseweb="select"] {
        min-width: 0 !important;
        width: 100% !important;
    }
    @media (max-width: 1180px) {
        div[data-testid="stHorizontalBlock"]:has(> div[data-testid="column"] .mc-db-browse-left-anchor) > div:first-child {
            flex-basis: 19.25rem !important;
            max-width: 19.25rem !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)

    db_path = DEFAULT_DATABASE_PATH
    if not os.path.exists(db_path):
        st.warning(f"未找到正式数据库：{db_path}")
        st.caption("请先运行数据库重建与提升流程，再使用 SQLite 只读预览。")
        return

    for state_key, fallback in [
        ("db_browse_editing_question_id", ""),
        ("db_browse_page", 1),
        ("db_browse_page_select", 1),
        ("db_browse_question_choice", "__all__"),
        ("db_browse_focus_question_id", ""),
        ("db_browse_return_page", 1),
        ("db_browse_return_page_select", 1),
        ("db_browse_return_question_choice", "__all__"),
        ("db_browse_return_focus_question_id", ""),
        ("db_browse_scroll_target_question_id", ""),
    ]:
        st.session_state.setdefault(state_key, fallback)
    editing_question_id = st.session_state.get("db_browse_editing_question_id", "")
    if allow_edit and editing_question_id:
        st.markdown('<div class="mc-db-single-edit-heading">单题 TeX 编辑</div>', unsafe_allow_html=True)
        st.caption("只显示当前题目；保存或退出后会返回原来的列表位置。")
        try:
            db_mtime = os.path.getmtime(db_path)
            payload = _db_preview_question_payload(db_path, editing_question_id, db_mtime)
            question = payload.get("question") or {}
        except Exception as exc:
            st.error(f"读取编辑题目失败：{exc}")
            if st.button(
                "退出修改",
                key=f"db_browse_exit_edit_missing_{_db_preview_edit_hash(editing_question_id)}",
                use_container_width=True,
            ):
                _db_preview_cancel_edit(editing_question_id, restore_browse=True)
                st.rerun()
            return

        if not question:
            st.error(f"未找到题目：{editing_question_id}")
            if st.button(
                "退出修改",
                key=f"db_browse_exit_edit_empty_{_db_preview_edit_hash(editing_question_id)}",
                use_container_width=True,
            ):
                _db_preview_cancel_edit(editing_question_id, restore_browse=True)
                st.rerun()
            return

        _db_preview_render_question_edit_workspace(db_path, editing_question_id, question)
        return

    try:
        base_options = list_question_filter_options(db_path)
    except Exception as exc:
        st.error(f"读取 SQLite 筛选项失败：{exc}")
        return

    left_col, right_col = st.columns([1.08, 3.42], gap="large")

    year_options = ["全部年份"] + [str(year) for year in base_options.get("years", [])]
    chapter_options = ["全部板块"] + base_options.get("chapters", [])
    page_size_options = list(base_options.get("page_size_options") or [5, 10, 15, 20])

    for state_key, fallback in [
        ("db_browse_chapter", "全部板块"),
        ("db_browse_year", "全部年份"),
        ("db_browse_source", "全部来源"),
        ("db_browse_difficulty", "全部难度"),
        ("db_browse_type_id", "__all__"),
        ("db_browse_page_size", 10),
        ("db_browse_page_select", 1),
        ("db_browse_question_choice", "__all__"),
        ("db_browse_editing_question_id", ""),
        ("db_browse_return_page", 1),
        ("db_browse_return_page_select", 1),
        ("db_browse_return_question_choice", "__all__"),
        ("db_browse_return_focus_question_id", ""),
        ("db_browse_scroll_target_question_id", ""),
    ]:
        st.session_state.setdefault(state_key, fallback)
    st.session_state.setdefault("db_browse_keyword", "")
    st.session_state.setdefault("db_browse_keyword_input", st.session_state.get("db_browse_keyword", ""))
    st.session_state.setdefault("db_browse_search_active", bool(st.session_state.get("db_browse_keyword", "")))
    st.session_state.setdefault("db_browse_focus_question_id", "")
    st.session_state.setdefault("db_browse_page", 1)

    _db_preview_ensure_option("db_browse_chapter", chapter_options, "全部板块")
    _db_preview_ensure_option("db_browse_year", year_options, "全部年份")
    _db_preview_ensure_option("db_browse_page_size", page_size_options, 10)

    search_active = bool(st.session_state.get("db_browse_search_active") and st.session_state.get("db_browse_keyword"))
    keyword = st.session_state.get("db_browse_keyword", "") if search_active else ""
    current_chapter = st.session_state.get("db_browse_chapter", "全部板块")
    current_year = st.session_state.get("db_browse_year", "全部年份")
    context_chapter = "" if current_chapter == "全部板块" else current_chapter
    context_year = None if current_year == "全部年份" else int(current_year)
    range_context = QuestionListFilters(
        chapter=context_chapter,
        year=context_year,
        limit=1,
    )
    try:
        source_context_options = list_question_filter_options(db_path, range_context)
    except Exception as exc:
        st.warning(f"读取来源联动筛选失败：{exc}")
        source_context_options = {"sources": []}
    source_options = ["全部来源"] + source_context_options.get("sources", [])
    _db_preview_ensure_option("db_browse_source", source_options, "全部来源")

    current_source = st.session_state.get("db_browse_source", "全部来源")
    type_context = QuestionListFilters(
        chapter=context_chapter,
        year=context_year,
        source="" if current_source == "全部来源" else current_source,
        limit=1,
    )
    try:
        type_context_options = list_question_filter_options(db_path, type_context)
    except Exception as exc:
        st.warning(f"读取题型联动筛选失败：{exc}")
        type_context_options = {"question_types": []}
    type_options = [{"question_type_id": "__all__", "name": "全部题型"}] + type_context_options.get("question_types", [])
    type_id_options = [item.get("question_type_id") for item in type_options]
    type_name_by_id = {
        item.get("question_type_id"): item.get("name", "全部题型")
        for item in type_options
    }
    if st.session_state.get("db_browse_type_id") is None:
        st.session_state["db_browse_type_id"] = "__all__"
    _db_preview_ensure_option("db_browse_type_id", type_id_options, "__all__")

    current_type = st.session_state.get("db_browse_type_id", "__all__")
    difficulty_context = QuestionListFilters(
        chapter=context_chapter,
        year=context_year,
        source="" if current_source == "全部来源" else current_source,
        question_type_id=None if current_type == "__all__" else current_type,
        limit=1,
    )
    try:
        difficulty_context_options = list_question_filter_options(db_path, difficulty_context)
    except Exception as exc:
        st.warning(f"读取难度联动筛选失败：{exc}")
        difficulty_context_options = {"difficulties": []}
    difficulty_options = ["全部难度"] + [str(item) for item in difficulty_context_options.get("difficulties", [])]
    _db_preview_ensure_option("db_browse_difficulty", difficulty_options, "全部难度")

    with left_col:
        st.markdown('<span class="mc-db-browse-left-anchor"></span>', unsafe_allow_html=True)
        st.markdown("### 🗃️ SQLite 筛选")
        if allow_edit:
            st.caption("默认只读；保存只写入 SQLite，不修改旧题目文件。")
        else:
            st.caption("组卷试用模式；SQLite 只负责筛选预览，试题篮复用旧 .tex 路径。")
        if allow_exam_basket:
            st.caption(f"当前试题篮：{len(st.session_state.get('exam_selected_qs', []))} 题")

        if search_active:
            st.markdown(
                f"<div class='mc-db-search-state'>检索模式<span>{html.escape(st.session_state.get('db_browse_keyword', ''))}</span></div>",
                unsafe_allow_html=True,
            )
            if st.button("退出检索", key="db_browse_exit_search", use_container_width=True, on_click=_db_preview_exit_search):
                pass

        st.markdown('<div class="mc-db-sidebar-section-label">精确搜索</div>', unsafe_allow_html=True)
        st.markdown('<div class="mc-db-sidebar-caption">支持用 <code>/</code> 分隔多个关键词，例如 <code>函数/导数</code>；多个词会同时命中才算结果。</div>', unsafe_allow_html=True)
        st.text_input(
            "关键词",
            key="db_browse_keyword_input",
            placeholder="例如：函数/导数、sin x",
            label_visibility="collapsed",
        )
        st.button(
            "再次搜索" if search_active else "开始搜索",
            key="db_browse_apply_search",
            type="primary",
            use_container_width=True,
            on_click=_db_preview_apply_search,
        )

        st.markdown('<div class="mc-db-sidebar-section-label">范围筛选</div>', unsafe_allow_html=True)
        range_chapter_col, range_year_col = st.columns([1.15, 0.85], gap="small")
        with range_chapter_col:
            selected_chapter = st.selectbox(
                "知识板块",
                chapter_options,
                key="db_browse_chapter",
                on_change=_db_preview_reset_page,
            )
        with range_year_col:
            selected_year = st.selectbox(
                "年份",
                year_options,
                key="db_browse_year",
                on_change=_db_preview_reset_page,
            )

        st.markdown('<div class="mc-db-sidebar-section-label">更多筛选</div>', unsafe_allow_html=True)
        st.markdown('<div class="mc-db-sidebar-caption">试卷来源、题型和难度会按当前知识板块与年份自动收窄。</div>', unsafe_allow_html=True)
        selected_source = st.selectbox("试卷来源", source_options, key="db_browse_source", on_change=_db_preview_reset_page)
        selected_type = st.selectbox(
            "题型",
            type_id_options,
            format_func=lambda type_id: type_name_by_id.get(type_id, "全部题型"),
            key="db_browse_type_id",
            on_change=_db_preview_reset_page,
        )
        selected_difficulty = st.selectbox("难度", difficulty_options, key="db_browse_difficulty", on_change=_db_preview_reset_page)
        page_size = int(st.session_state.get("db_browse_page_size", 10) or 10)

    filters = QuestionListFilters(
        keyword=(keyword or "").strip(),
        year=None if selected_year == "全部年份" else int(selected_year),
        chapter="" if selected_chapter == "全部板块" else selected_chapter,
        source="" if selected_source == "全部来源" else selected_source,
        question_type_id=None if selected_type == "__all__" else selected_type,
        difficulty=None if selected_difficulty == "全部难度" else int(selected_difficulty),
        limit=int(page_size),
        offset=(max(1, int(st.session_state.get("db_browse_page", 1) or 1)) - 1) * int(page_size),
    )

    try:
        page = list_questions_page(db_path, filters)
    except Exception as exc:
        st.error(f"读取 SQLite 题目失败：{exc}")
        return

    if page["page_count"] and st.session_state["db_browse_page"] > page["page_count"]:
        st.session_state["db_browse_page"] = page["page_count"]
        st.session_state["db_browse_page_select"] = page["page_count"]
        st.session_state["db_browse_question_choice"] = "__all__"
        st.session_state["db_browse_focus_question_id"] = ""
        st.rerun()

    if not page["page_count"] and st.session_state["db_browse_page"] != 1:
        st.session_state["db_browse_page"] = 1
        st.session_state["db_browse_page_select"] = 1
        st.session_state["db_browse_question_choice"] = "__all__"
        st.session_state["db_browse_focus_question_id"] = ""
        st.rerun()

    page_items = list(page["items"])
    page_item_ids = {item.get("question_id", "") for item in page_items}
    focus_question_id = st.session_state.get("db_browse_focus_question_id", "")
    if focus_question_id not in page_item_ids:
        focus_question_id = ""
        st.session_state["db_browse_focus_question_id"] = ""

    db_mtime = os.path.getmtime(db_path)
    page_exam_paths = []
    if allow_exam_basket and page_items:
        for item in page_items:
            exam_path = resolve_legacy_card_file_path({"path": item.get("legacy_file_path") or ""}, APP_ROOT)
            if exam_path and exam_path not in page_exam_paths:
                page_exam_paths.append(exam_path)

    with left_col:
        st.divider()
        page_count = int(page["page_count"] or 0)
        current_page = int(page["page"] or 1)
        page_options = list(range(1, page_count + 1)) if page_count else [1]
        if st.session_state.get("db_browse_page_select") not in page_options:
            st.session_state["db_browse_page_select"] = current_page if current_page in page_options else 1
        st.markdown(
            f"""
            <div class="mc-db-result-summary">
                <strong>查找结果</strong>
                <span>找到 {int(page['total'] or 0)} 题</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='mc-db-result-caption'>每页 {page['limit']} 道 · 当前第 {current_page if page_count else 0} / {page_count} 页</div>",
            unsafe_allow_html=True,
        )
        page_size_col, page_select_col = st.columns([0.92, 1.08], gap="small")
        with page_size_col:
            st.selectbox(
                "每页",
                page_size_options,
                key="db_browse_page_size",
                on_change=_db_preview_reset_page,
            )
        with page_select_col:
            st.selectbox(
                "页码",
                page_options,
                key="db_browse_page_select",
                format_func=lambda page_number: f"{page_number} / {page_count or 0}",
                on_change=_db_preview_apply_page_select,
            )
        prev_col, next_col = st.columns(2, gap="small")
        with prev_col:
            st.button(
                "上一页",
                key="db_browse_prev",
                disabled=current_page <= 1,
                use_container_width=True,
                on_click=_db_preview_change_page,
                args=(-1, page_count),
            )
        with next_col:
            st.button(
                "下一页",
                key="db_browse_next",
                disabled=not page_count or current_page >= page_count,
                use_container_width=True,
                on_click=_db_preview_change_page,
                args=(1, page_count),
            )
        if page_items:
            st.markdown('<div class="mc-db-question-list-title">题目显示</div>', unsafe_allow_html=True)
            question_choice_options = ["__all__"] + [item.get("question_id", "") for item in page_items if item.get("question_id", "")]
            question_choice_labels = {"__all__": "展示当前页全部题目"}
            for item_index, item in enumerate(page_items, start=1):
                question_id = item.get("question_id", "")
                if question_id:
                    question_choice_labels[question_id] = f"{item_index}. {_db_preview_label(item)}"
            if st.session_state.get("db_browse_question_choice") not in question_choice_options:
                st.session_state["db_browse_question_choice"] = "__all__"
            selected_question_choice = st.selectbox(
                "题目显示",
                question_choice_options,
                key="db_browse_question_choice",
                format_func=lambda value: question_choice_labels.get(value, value),
                label_visibility="collapsed",
            )
            focus_question_id = "" if selected_question_choice == "__all__" else selected_question_choice
            st.session_state["db_browse_focus_question_id"] = focus_question_id

        if allow_exam_basket:
            st.divider()
            st.markdown('<div class="mc-db-sidebar-section-label">试题篮操作</div>', unsafe_allow_html=True)
            selected_path_set = set(st.session_state.get("exam_selected_qs", []))
            available_to_add = [path for path in page_exam_paths if path not in selected_path_set]
            st.caption(f"当前页可组卷 {len(page_exam_paths)} 题；尚未加入 {len(available_to_add)} 题。")
            st.button(
                "加入当前页可组卷题",
                key=f"db_browse_add_page_to_exam_{current_page}_{page['limit']}_{len(page_exam_paths)}",
                type="primary",
                use_container_width=True,
                disabled=not available_to_add,
                on_click=_add_exam_selection_paths,
                args=(available_to_add,),
            )
            if not show_export_panel:
                target_count = max(1, int(st.session_state.get("exam_q_count_input", 10) or 10))
                remaining_count = max(0, target_count - len(selected_path_set))
                if st.button(
                    f"随机补足至 {target_count} 题",
                    key=f"db_browse_fill_exam_from_sqlite_{current_page}_{page['limit']}_{target_count}",
                    use_container_width=True,
                    disabled=remaining_count <= 0 or int(page.get("total") or 0) <= 0,
                    help="从当前 SQLite 筛选结果中随机补足，不会突破上方组卷数量。",
                ):
                    try:
                        import random

                        candidate_filters = QuestionListFilters(
                            keyword=filters.keyword,
                            year=filters.year,
                            chapter=filters.chapter,
                            source=filters.source,
                            question_number=filters.question_number,
                            question_type_id=filters.question_type_id,
                            difficulty=filters.difficulty,
                            limit=min(500, max(60, remaining_count * 8)),
                            offset=0,
                        )
                        candidate_paths = list_resolved_legacy_card_paths(db_path, candidate_filters, project_root=APP_ROOT)
                        candidate_paths = [path for path in candidate_paths if path not in selected_path_set]
                        random.shuffle(candidate_paths)
                        chosen_paths = candidate_paths[:remaining_count]
                        if chosen_paths:
                            _add_exam_selection_paths(chosen_paths)
                            st.toast(f"已补入 {len(chosen_paths)} 题", icon="✅")
                            st.rerun()
                        else:
                            st.warning("当前筛选下没有可继续加入的题目。")
                    except Exception as exc:
                        st.error(f"SQLite 随机补题失败：{exc}")

        if show_export_panel:
            st.divider()
            _db_preview_render_source_export_panel(db_path, filters=filters, page=page)

    if focus_question_id:
        display_items = [item for item in page_items if item.get("question_id") == focus_question_id]
    else:
        display_items = page_items

    with right_col:
        st.markdown(right_heading or ("### 检索结果预览" if keyword else "### SQLite 数据库题目预览"))
        if right_caption is not None:
            st.caption(right_caption)
        elif allow_edit:
            st.caption("当前入口默认只读；单题点击开始修改后才保存到 SQLite，旧文件编辑、AI 解答暂不接入这里。")
        else:
            st.caption("当前为 SQLite 试用选题；筛选不写库，最终生成仍沿用旧组卷引用次数逻辑。")

        if not display_items:
            st.markdown('<div class="mc-db-browse-empty">没有匹配题目。请调整左侧筛选条件。</div>', unsafe_allow_html=True)
            return

        for item in display_items:
            question_id = item.get("question_id", "")
            try:
                payload = _db_preview_question_payload(db_path, question_id, db_mtime)
                bundle = payload.get("bundle") or {}
                question = payload.get("question") or {}
                legacy_tex = payload.get("legacy_tex") or ""
                preview_markdown = payload.get("preview_markdown")
            except Exception as exc:
                st.error(f"{question_id} 读取失败：{exc}")
                continue

            tags = _db_preview_json_list(question.get("tags_json", "[]"))
            diff = question.get("difficulty")
            title = _db_preview_label(question)
            paper_bits = [
                str(bit)
                for bit in [question.get("detected_year"), question.get("detected_source"), question.get("detected_question_number")]
                if bit not in (None, "")
            ]
            source_text = " / ".join(paper_bits) or "未识别来源"
            tag_html = "".join(f"<span class='mc-db-browse-pill blue'>🏷️ {html.escape(tag)}</span>" for tag in tags) or "<span class='mc-db-browse-pill'>无标签</span>"
            note_text = question.get("note") or "无备注"

            is_editing = allow_edit and st.session_state.get("db_browse_editing_question_id") == question_id

            with st.container(border=True):
                st.markdown(
                    f'<span id="{_db_preview_question_anchor_id(question_id)}" class="mc-db-browse-card-anchor"></span>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    "<div class='mc-db-browse-kicker'>SQLite · 编辑中</div>" if is_editing else "<div class='mc-db-browse-kicker'>SQLite · 只读</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(f"<div class='mc-db-browse-title'>{html.escape(title)}</div>", unsafe_allow_html=True)
                meta_col, meta_action_col, _ = st.columns([1.72, 0.42, 1.88], gap="small", vertical_alignment="center")
                with meta_col:
                    st.markdown(
                        f"""
                        <div class="mc-db-browse-meta">
                            <span class="mc-db-browse-pill purple">ID：{html.escape(question_id)}</span>
                            <span class="mc-db-browse-pill">难度：{html.escape(str(diff)) if diff is not None else "未设置"}</span>
                            {tag_html}
                            <span class="mc-db-browse-pill">备注：{html.escape(note_text)}</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                with meta_action_col:
                    if allow_edit:
                        _db_preview_render_metadata_popover(db_path, question_id, question)
                st.markdown(
                    f"<div class='mc-db-browse-source'>来源：{html.escape(source_text)} · 文件：{html.escape(question.get('legacy_file_path') or '')}</div>",
                    unsafe_allow_html=True,
                )

                if is_editing and allow_edit:
                    _db_preview_render_question_edit_form(db_path, question_id, question)
                else:
                    st.markdown(_db_preview_material_drawer_html(bundle), unsafe_allow_html=True)
                    if not allow_edit and allow_exam_basket:
                        legacy_card = sqlite_bundle_to_legacy_card(bundle)
                        exam_path = resolve_legacy_card_file_path(legacy_card, APP_ROOT)
                        is_in_basket = bool(exam_path and exam_path in st.session_state.get("exam_selected_qs", []))
                        basket_action_col, download_action_col, _ = st.columns([0.82, 0.72, 2.28], gap="small")
                        with basket_action_col:
                            basket_label = "移出试题篮" if is_in_basket else "加入试题篮"
                            st.button(
                                basket_label,
                                key=f"db_browse_exam_basket_{_db_preview_edit_hash(question_id)}",
                                type="primary" if is_in_basket else "secondary",
                                use_container_width=True,
                                disabled=not exam_path,
                                on_click=_toggle_exam_selection_path,
                                args=(exam_path,),
                                help=None if exam_path else "该 SQLite 题目缺少可复用的旧 .tex 文件路径，暂不能进入旧组卷流程。",
                            )
                        with download_action_col:
                            st.download_button(
                                "下载 TeX",
                                data=legacy_tex,
                                file_name=f"{question_id}.tex",
                                mime="text/x-tex",
                                key=f"db_browse_download_{_db_preview_edit_hash(question_id)}",
                                use_container_width=True,
                            )

                    code_col, preview_col = st.columns([0.94, 1.32], gap="large")
                    with code_col:
                        st.markdown("**TeX 源码**")
                        if allow_edit:
                            st.markdown('<span class="mc-db-code-action-anchor"></span>', unsafe_allow_html=True)
                            if st.button(
                                "开始修改本题信息",
                                key=f"db_browse_start_edit_{_db_preview_edit_hash(question_id)}",
                                use_container_width=True,
                            ):
                                _db_preview_start_edit(question_id)
                                st.rerun()
                        st.code(legacy_tex, language="latex")
                    with preview_col:
                        st.markdown("**渲染预览**")
                        try:
                            render_question_preview(legacy_tex, show_title=False, prepared_markdown=preview_markdown)
                        except Exception as exc:
                            st.warning(f"渲染失败：{exc}")

        _db_preview_scroll_to_question(st.session_state.get("db_browse_scroll_target_question_id", ""))


# ================= 页面：浏览/编辑 =================
def page_browse(is_exam_mode=False, is_delete_mode=False, paper_type_scope=None, page_title=None):
    """Browse questions; default scope excludes WK, while the cloze library passes 'WK'."""
    is_cloze_library = paper_type_scope == "WK"
    page_title = page_title or ("🧩 挖空题库" if is_cloze_library else "🔍 全局浏览与编辑")
    st.markdown('<span class="mc-browse-page-anchor"></span>', unsafe_allow_html=True)
    if is_exam_mode:
        st.markdown("""
        <style>
        [data-testid="stVerticalBlockBorderWrapper"]:has(.mc-exam-card-anchor) {
            border-color: rgba(0, 0, 0, 0.10) !important;
            border-radius: 10px !important;
            background: transparent !important;
        }
        div[data-testid="stVerticalBlock"]:has(.mc-exam-card-anchor) {
            gap: 0.65rem !important;
        }
        div[data-testid="stVerticalBlock"]:has(.mc-exam-card-anchor) .mc-exam-card-title {
            color: #1d1d1f;
            font-size: 1.08rem;
            font-weight: 700;
            line-height: 1.35;
            margin: 0 0 0.2rem;
        }
        div[data-testid="stVerticalBlock"]:has(.mc-exam-card-anchor) .mc-exam-card-state {
            display: inline-flex;
            align-items: center;
            padding: 0.16rem 0.48rem;
            border-radius: 999px;
            font-size: 0.75rem;
            line-height: 1.25;
        }
        div[data-testid="stVerticalBlock"]:has(.mc-exam-card-anchor) .mc-exam-card-state.available {
            color: #5f6368;
            background: #f1f3f4;
        }
        div[data-testid="stVerticalBlock"]:has(.mc-exam-card-anchor) .mc-exam-card-state.selected {
            color: #075e54;
            background: #dff6ef;
        }
        div[data-testid="stVerticalBlock"]:has(.mc-exam-card-anchor) .mc-exam-card-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem 1.25rem;
            padding: 0.55rem 0.7rem;
            border-top: 1px solid rgba(0, 0, 0, 0.07);
            border-bottom: 1px solid rgba(0, 0, 0, 0.07);
            color: #6e6e73;
            font-size: 0.82rem;
            line-height: 1.4;
        }
        div[data-testid="stVerticalBlock"]:has(.mc-exam-card-anchor) .mc-exam-card-meta strong {
            color: #3f3f46;
            font-weight: 650;
        }
        div[data-testid="stVerticalBlock"]:has(.mc-exam-card-anchor) .mc-exam-card-preview-label {
            color: #5b21b6;
            font-size: 0.88rem;
            font-weight: 700;
            margin-top: 0.1rem;
        }
        div[data-testid="stVerticalBlock"]:has(.mc-exam-card-anchor) div[data-testid="stButton"] > button {
            min-height: 2.3rem !important;
            white-space: nowrap !important;
        }
        div[data-testid="stVerticalBlock"]:has(.mc-exam-card-anchor) div[data-testid="stMarkdownContainer"] p {
            line-height: 1.65 !important;
        }
        @media (max-width: 760px) {
            div[data-testid="stVerticalBlock"]:has(.mc-exam-card-anchor) .mc-exam-card-meta {
                gap: 0.35rem 0.8rem;
            }
        }
        </style>
        """, unsafe_allow_html=True)
    if is_delete_mode:
        st.markdown("""
        <style>
        div[data-testid="element-container"]:has(.red-btn-hook) + div[data-testid="stButton"] > button,
        div[data-testid="element-container"]:has(.red-btn-hook) + div[data-testid="element-container"] div[data-testid="stButton"] > button,
        div[class*="st-key-delete_mode_exit_btn_wrap"] button,
        div[class*="st-key-restore_deleted_close_wrap"] button,
        div[class*="st-key-backup_manager_close_wrap"] button,
        div[class*="st-key-backup_manager_clear_ok_wrap"] button,
        div[class*="st-key-backup_delete_wrap_"] button,
        div[class*="st-key-delete_mode_exit_btn"] button,
        div[class*="st-key-restore_deleted_close"] button,
        div[class*="st-key-backup_manager_close"] button,
        div[class*="st-key-backup_manager_clear_ok"] button,
        div[class*="st-key-backup_delete_"] button {
            background-color: #d73a49 !important;
            border-color: #d73a49 !important;
            color: #ffffff !important;
            font-weight: 700 !important;
        }
        div[data-testid="element-container"]:has(.red-btn-hook) + div[data-testid="stButton"] > button:hover,
        div[data-testid="element-container"]:has(.red-btn-hook) + div[data-testid="element-container"] div[data-testid="stButton"] > button:hover,
        div[class*="st-key-delete_mode_exit_btn_wrap"] button:hover,
        div[class*="st-key-restore_deleted_close_wrap"] button:hover,
        div[class*="st-key-backup_manager_close_wrap"] button:hover,
        div[class*="st-key-backup_manager_clear_ok_wrap"] button:hover,
        div[class*="st-key-backup_delete_wrap_"] button:hover,
        div[class*="st-key-delete_mode_exit_btn"] button:hover,
        div[class*="st-key-restore_deleted_close"] button:hover,
        div[class*="st-key-backup_manager_close"] button:hover,
        div[class*="st-key-backup_manager_clear_ok"] button:hover,
        div[class*="st-key-backup_delete_"] button:hover {
            background-color: #b92534 !important;
            border-color: #b92534 !important;
            color: #ffffff !important;
        }
        div[data-testid="column"]:has(.delete-exit-btn-hook) div[data-testid="stButton"] > button,
        div[data-testid="element-container"]:has(.delete-exit-btn-hook) + div[data-testid="stButton"] > button,
        div[data-testid="element-container"]:has(.delete-exit-btn-hook) + div[data-testid="element-container"] div[data-testid="stButton"] > button,
        div[class*="st-key-delete_mode_exit_btn_wrap"] button,
        div[class*="st-key-restore_deleted_close_wrap"] button,
        div[class*="st-key-backup_manager_close_wrap"] button {
            min-height: 58px !important;
            height: 58px !important;
            padding: 0.25rem 0.35rem !important;
            background-color: #d73a49 !important;
            border-color: #d73a49 !important;
            color: #ffffff !important;
            border-radius: 8px !important;
            font-weight: 750 !important;
            line-height: 1.15 !important;
            white-space: normal !important;
        }
        div[data-testid="column"]:has(.delete-exit-btn-hook) div[data-testid="stButton"] > button:hover,
        div[data-testid="element-container"]:has(.delete-exit-btn-hook) + div[data-testid="stButton"] > button:hover,
        div[data-testid="element-container"]:has(.delete-exit-btn-hook) + div[data-testid="element-container"] div[data-testid="stButton"] > button:hover,
        div[class*="st-key-delete_mode_exit_btn_wrap"] button:hover,
        div[class*="st-key-restore_deleted_close_wrap"] button:hover,
        div[class*="st-key-backup_manager_close_wrap"] button:hover {
            background-color: #b92534 !important;
            border-color: #b92534 !important;
            color: #ffffff !important;
        }
        div[data-testid="column"]:has(.delete-exit-btn-hook) div[data-testid="stButton"] > button p,
        div[data-testid="element-container"]:has(.delete-exit-btn-hook) + div[data-testid="stButton"] > button p,
        div[data-testid="element-container"]:has(.delete-exit-btn-hook) + div[data-testid="element-container"] div[data-testid="stButton"] > button p,
        div[class*="st-key-delete_mode_exit_btn_wrap"] button p,
        div[class*="st-key-restore_deleted_close_wrap"] button p,
        div[class*="st-key-backup_manager_close_wrap"] button p {
            white-space: pre-line !important;
            line-height: 1.15 !important;
        }
        div[data-testid="column"]:has(.delete-restore-btn-hook) div[data-testid="stButton"] > button,
        div[data-testid="element-container"]:has(.delete-restore-btn-hook) + div[data-testid="stButton"] > button,
        div[data-testid="element-container"]:has(.delete-restore-btn-hook) + div[data-testid="element-container"] div[data-testid="stButton"] > button,
        div[data-testid="element-container"]:has(.blue-restore-btn-hook) + div[data-testid="stButton"] > button,
        div[data-testid="element-container"]:has(.blue-restore-btn-hook) + div[data-testid="element-container"] div[data-testid="stButton"] > button,
        div[class*="st-key-delete_mode_restore_btn_wrap"] button,
        div[class*="st-key-restore_deleted_btn_wrap_"] button,
        div[class*="st-key-backup_restore_btn_wrap_"] button,
        div[class*="st-key-delete_mode_restore_btn"] button,
        div[class*="st-key-restore_deleted_"] button,
        div[class*="st-key-backup_restore_"] button {
            min-height: 58px !important;
            height: 58px !important;
            padding: 0.25rem 0.35rem !important;
            background-color: #0969da !important;
            border-color: #0969da !important;
            color: #ffffff !important;
            border-radius: 8px !important;
            font-weight: 750 !important;
            line-height: 1.15 !important;
            white-space: normal !important;
        }
        div[data-testid="column"]:has(.delete-restore-btn-hook) div[data-testid="stButton"] > button:hover,
        div[data-testid="element-container"]:has(.delete-restore-btn-hook) + div[data-testid="stButton"] > button:hover,
        div[data-testid="element-container"]:has(.delete-restore-btn-hook) + div[data-testid="element-container"] div[data-testid="stButton"] > button:hover,
        div[data-testid="element-container"]:has(.blue-restore-btn-hook) + div[data-testid="stButton"] > button:hover,
        div[data-testid="element-container"]:has(.blue-restore-btn-hook) + div[data-testid="element-container"] div[data-testid="stButton"] > button:hover,
        div[class*="st-key-delete_mode_restore_btn_wrap"] button:hover,
        div[class*="st-key-restore_deleted_btn_wrap_"] button:hover,
        div[class*="st-key-backup_restore_btn_wrap_"] button:hover,
        div[class*="st-key-delete_mode_restore_btn"] button:hover,
        div[class*="st-key-restore_deleted_"] button:hover,
        div[class*="st-key-backup_restore_"] button:hover {
            background-color: #0757b8 !important;
            border-color: #0757b8 !important;
            color: #ffffff !important;
        }
        div[data-testid="column"]:has(.delete-restore-btn-hook) div[data-testid="stButton"] > button p,
        div[data-testid="element-container"]:has(.delete-restore-btn-hook) + div[data-testid="stButton"] > button p,
        div[data-testid="element-container"]:has(.delete-restore-btn-hook) + div[data-testid="element-container"] div[data-testid="stButton"] > button p,
        div[class*="st-key-delete_mode_restore_btn_wrap"] button p,
        div[class*="st-key-restore_deleted_btn_wrap_"] button p,
        div[class*="st-key-backup_restore_btn_wrap_"] button p {
            white-space: pre-line !important;
            line-height: 1.15 !important;
        }
        div[data-testid="column"]:has(.backup-manage-btn-hook) div[data-testid="stButton"] > button,
        div[data-testid="element-container"]:has(.backup-manage-btn-hook) + div[data-testid="stButton"] > button,
        div[data-testid="element-container"]:has(.backup-manage-btn-hook) + div[data-testid="element-container"] div[data-testid="stButton"] > button,
        div[class*="st-key-delete_mode_backup_manager_btn_wrap"] button,
        div[class*="st-key-backup_manager_clear_all_wrap"] button,
        div[class*="st-key-delete_mode_backup_manager_btn"] button,
        div[class*="st-key-backup_manager_clear_all"] button {
            min-height: 58px !important;
            height: 58px !important;
            padding: 0.25rem 0.35rem !important;
            background-color: #f2cc60 !important;
            border-color: #d4a72c !important;
            color: #1f2328 !important;
            border-radius: 8px !important;
            font-weight: 800 !important;
            line-height: 1.15 !important;
            white-space: normal !important;
        }
        div[data-testid="column"]:has(.backup-manage-btn-hook) div[data-testid="stButton"] > button:hover,
        div[data-testid="element-container"]:has(.backup-manage-btn-hook) + div[data-testid="stButton"] > button:hover,
        div[data-testid="element-container"]:has(.backup-manage-btn-hook) + div[data-testid="element-container"] div[data-testid="stButton"] > button:hover,
        div[class*="st-key-delete_mode_backup_manager_btn_wrap"] button:hover,
        div[class*="st-key-backup_manager_clear_all_wrap"] button:hover,
        div[class*="st-key-delete_mode_backup_manager_btn"] button:hover,
        div[class*="st-key-backup_manager_clear_all"] button:hover {
            background-color: #e3b341 !important;
            border-color: #bf8700 !important;
            color: #1f2328 !important;
        }
        div[data-testid="column"]:has(.backup-manage-btn-hook) div[data-testid="stButton"] > button p,
        div[data-testid="element-container"]:has(.backup-manage-btn-hook) + div[data-testid="stButton"] > button p,
        div[data-testid="element-container"]:has(.backup-manage-btn-hook) + div[data-testid="element-container"] div[data-testid="stButton"] > button p,
        div[class*="st-key-delete_mode_backup_manager_btn_wrap"] button p,
        div[class*="st-key-backup_manager_clear_all_wrap"] button p {
            white-space: pre-line !important;
            line-height: 1.15 !important;
        }
        </style>
        """, unsafe_allow_html=True)
        c_header, c_actions = st.columns([1, 1.4])
        with c_header:
            st.header("🗑️ 删除题库问题")
            st.subheader("删除模式")
            if "browse_mode" not in st.session_state:
                st.session_state["browse_mode"] = "按知识板块浏览"
            browse_mode = st.radio("浏览模式", ["按知识板块浏览", "按试卷浏览", "按录入顺序浏览"], horizontal=True, label_visibility="collapsed", key="browse_mode")

        with c_actions:
            st.write("")
            st.write("")
            exit_btn_col, restore_btn_col, backup_btn_col = st.columns([1, 1, 1])
            with exit_btn_col:
                st.markdown('<span class="delete-exit-btn-hook"></span>', unsafe_allow_html=True)
                if st.button("退出\n删除模式", key="delete_mode_exit_btn", type="secondary", use_container_width=True):
                    st.session_state["tools_subpage"] = None
                    st.session_state["adv_search_active"] = False
                    _clear_advanced_search_result_cache()
                    st.rerun()
            with restore_btn_col:
                st.markdown('<span class="delete-restore-btn-hook"></span>', unsafe_allow_html=True)
                if st.button("恢复\n误删题目", key="delete_mode_restore_btn", type="primary", use_container_width=True):
                    restore_deleted_questions_dialog()
            with backup_btn_col:
                st.markdown('<span class="backup-manage-btn-hook"></span>', unsafe_allow_html=True)
                if st.button("管理\n备份问题", key="delete_mode_backup_manager_btn", type="secondary", use_container_width=True):
                    manage_backup_questions_dialog()

        search_workspace_active = st.session_state.get("adv_search_active") and _adv_search_has_query()
        if not search_workspace_active:
            render_advanced_search_inline()

    elif not is_exam_mode:
        st.header(page_title)
        st.subheader("浏览模式")
        if "browse_mode" not in st.session_state:
            st.session_state["browse_mode"] = "按知识板块浏览"
        browse_mode = st.radio("浏览模式", ["按知识板块浏览", "按试卷浏览", "按录入顺序浏览"], horizontal=True, label_visibility="collapsed", key="browse_mode")

        search_workspace_active = st.session_state.get("adv_search_active") and _adv_search_has_query()
        if not search_workspace_active:
            render_advanced_search_inline()
            
    else:
        if "browse_mode" not in st.session_state:
            st.session_state["browse_mode"] = "按知识板块浏览"
        browse_mode = st.radio("浏览模式", ["按知识板块浏览", "按试卷浏览", "按录入顺序浏览"], horizontal=True, label_visibility="collapsed", key="browse_mode")
    
    # 根据红线截图，我们在这里画一条醒目的红线
    st.markdown('<hr style="border-top: 1px solid #e1e4e8; margin-top: 10px; margin-bottom: 20px;">', unsafe_allow_html=True)
    if is_delete_mode:
        st.caption("删除会移除题目文件、CSV 索引记录和对应章节索引；原题目文件会自动备份到 .backups。若误删，可点右上角“恢复误删题目”恢复本次删除记录，或点“管理备份问题”查找历史备份；当前备份不会自动定期清理。")
    
    if not is_exam_mode and not is_delete_mode and st.session_state.get("recent_saved_active") and st.session_state.get("recent_saved_paths"):
        paths = [p for p in st.session_state.get("recent_saved_paths", []) if p and os.path.exists(p)]
        c1, c2 = st.columns([1, 1])
        with c1:
            st.subheader("🧾 本次录入的题目")
        with c2:
            def _clear_recent_saved():
                st.session_state["recent_saved_active"] = False
                st.session_state["recent_saved_paths"] = []
            st.button("返回正常浏览", type="secondary", use_container_width=True, on_click=_clear_recent_saved, key="recent_saved_back")
        
        if not paths:
            st.info("未找到可展示的文件（可能已移动/删除）。")
            return
        
        for fpath in paths:
            try:
                prepared_assets = load_question_editor_assets(fpath)
                content = prepared_assets["content"]
            except Exception as e:
                st.error(f"读取失败: {e}")
                continue
            
            fname = os.path.basename(fpath)
            q_label = format_question_title(fname)
            render_browse_question_editor_card(
                q_label,
                content,
                fpath,
                "recent_saved",
                paper_type_scope=paper_type_scope,
                rename_paths_key="recent_saved_paths",
                prepared_assets=prepared_assets,
            )
            st.divider()
        return
    
    # === 如果激活了搜索，优先显示搜索结果 ===
    if not is_exam_mode and st.session_state.get("adv_search_active"):
        if _adv_search_has_query():
            render_advanced_search_workspace(is_delete_mode=is_delete_mode, paper_type_scope=paper_type_scope)
            return  # 搜索状态下，不显示下方的常规浏览内容
        st.session_state["adv_search_active"] = False
    
    selected_file_path = None
    
    if browse_mode == "按知识板块浏览":
        # 左右布局：左侧导航，右侧文件列表与编辑
        col_nav, col_content = st.columns([1, 2.5])
        
        with col_nav:
            st.markdown('<div id="knowledge-subject-area"></div>', unsafe_allow_html=True)
            st.markdown('<div id="left-panel-anchor"></div>', unsafe_allow_html=True)
            st.markdown("### 📂 知识板块")
            
            # 使用自定义 CSS 优化按钮样式 (圆角、紧凑) 以及固定左栏
            st.markdown("""
                <style>
                /* 隐藏左侧栏的滚动条以便美观 */
                div[data-testid="column"]:has(#left-panel-anchor)::-webkit-scrollbar {
                    width: 4px;
                }
                div[data-testid="column"]:has(#left-panel-anchor)::-webkit-scrollbar-thumb {
                    background-color: rgba(0,0,0,0.1);
                    border-radius: 4px;
                }
                
                /* 精准定位知识板块区域的按钮 */
                div[data-testid="column"]:has(#knowledge-subject-area) div[data-testid="stButton"] {
                    display: flex !important;
                    justify-content: center !important;
                    width: 100% !important;
                }
                div[data-testid="column"]:has(#knowledge-subject-area) div[data-testid="stButton"] button {
                    width: 85% !important;  
                    min-width: 85% !important;
                    max-width: 85% !important;
                    border-radius: 6px !important;
                    padding: 0.1rem 0.15rem !important;
                    min-height: 32px !important;
                    height: 32px !important;
                    margin-bottom: 2px !important;
                }
                div[data-testid="column"]:has(#knowledge-subject-area) div[data-testid="stButton"] button p {
                    font-size: 13px !important;
                    line-height: 1.2 !important;
                }
                </style>
            """, unsafe_allow_html=True)
            
            # 使用 session_state 记录当前选中的板块
            if "browse_subject" not in st.session_state:
                st.session_state["browse_subject"] = SUBJECTS[0]

            # 三列排列，按钮宽度缩小
            # 通过 columns 来实现三列
            for i in range(0, len(SUBJECTS), 3):
                cols = st.columns(3)
                
                # 遍历当前行的三列
                for j in range(3):
                    idx = i + j
                    if idx < len(SUBJECTS):
                        subj = SUBJECTS[idx]
                        btn_type = "primary" if st.session_state["browse_subject"] == subj else "secondary"
                        with cols[j]:
                            if st.button(subj, key=f"nav_subj_{subj}", type=btn_type, use_container_width=True):
                                st.session_state["browse_subject"] = subj
                                for state_key in list(st.session_state.keys()):
                                    if isinstance(state_key, str) and state_key.startswith("browse_question_page_"):
                                        st.session_state[state_key] = 1
                                st.rerun()
            
            subject = st.session_state["browse_subject"]
            
            st.write("")
            st.write("")
            years = get_years(subject, paper_type=paper_type_scope)
            files = []
            year = None
            selected_option = None
            SHOW_ALL_OPT = None
            ALL_YEARS_OPT = "显示所有年份"
            if years:
                # 2. 选择年份 (横向排列)
                st.subheader("📅 选择年份")
                
                # 增加“显示所有年份”选项
                year_options = [ALL_YEARS_OPT] + years
                
                default_year_index = 0
                year = st.radio("📅 选择年份", options=year_options, index=default_year_index, key=f"browse_year_{subject}", horizontal=True, label_visibility="collapsed")
                
                st.divider()
                
                selected_option = None
                SHOW_ALL_OPT = None
                
                if year == ALL_YEARS_OPT:
                    # 获取该板块下所有年份的所有文件
                    files = []
                    for y in years:
                        y_files = get_files(subject, y, paper_type=paper_type_scope)
                        if y_files:
                            # 为了区分不同年份，我们在文件名列表中带上年份信息
                            files.extend([(y, f) for f in y_files])
                            
                    if files:
                        st.subheader(f"📄 文件列表 ({subject} - 所有年份)")
                        
                        # 增加“展示全部”选项
                        SHOW_ALL_OPT = "📂 展示该板块全部问题"
                        # 格式化选项供选择
                        display_options = [f"{y}年 - {f}" for y, f in files]
                        file_options = [SHOW_ALL_OPT] + display_options

                        selected_option = st.selectbox(
                            "3. 选择文件 (支持输入搜索)", 
                            options=file_options,
                            index=0,
                            key=f"browse_file_select_{subject}_all",
                            label_visibility="collapsed"
                        )
                else:
                    # 原来的单一年份逻辑
                    files = get_files(subject, year, paper_type=paper_type_scope)
                    if files:
                        st.subheader(f"📄 文件列表 ({subject} - {year})")
                        
                        SHOW_ALL_OPT = "📂 展示该年份全部问题"
                        file_options = [SHOW_ALL_OPT] + files

                        selected_option = st.selectbox(
                            "3. 选择文件 (支持输入搜索)", 
                            options=file_options,
                            index=0,
                            key=f"browse_file_select_{subject}_{year}",
                            label_visibility="collapsed"
                        )
            
            page_start = 0
            page_end = 0
            if files and selected_option == SHOW_ALL_OPT:
                page_size = 20
                page_scope = "all_years" if year == ALL_YEARS_OPT else year
                page_key = f"browse_question_page_{subject}_{page_scope}_{paper_type_scope or 'regular'}"
                total_pages = max(1, (len(files) + page_size - 1) // page_size)
                current_page = int(st.session_state.get(page_key, 1) or 1)
                current_page = max(1, min(total_pages, current_page))
                if st.session_state.get(page_key) != current_page:
                    st.session_state[page_key] = current_page
                current_page = st.number_input(
                    f"页码（共 {total_pages} 页）",
                    min_value=1,
                    max_value=total_pages,
                    step=1,
                    key=page_key,
                )
                page_start = (current_page - 1) * page_size
                page_end = min(len(files), page_start + page_size)
                st.caption(f"当前显示第 {page_start + 1}-{page_end} 题，每页最多 20 题")
        with col_content:
            st.markdown('<div id="right-panel-anchor"></div>', unsafe_allow_html=True)
            if years:
                if year == ALL_YEARS_OPT:
                    if files:
                        if selected_option == SHOW_ALL_OPT:
                            st.markdown(f"### {subject} - 所有年份所有题目")
                            
                            for i, (y, fname) in enumerate(files[page_start:page_end], start=page_start):
                                fpath = os.path.join(CHAPTERS_DIR, subject, y, fname)
                                if not os.path.exists(fpath):
                                    continue
                                prepared_assets = None
                                if not is_delete_mode and not is_exam_mode:
                                    prepared_assets = load_question_editor_assets(fpath)
                                    content = prepared_assets["content"]
                                else:
                                    content = read_question_text(fpath)
                                q_label = format_question_title(fname)
                                if is_delete_mode:
                                    render_delete_question_item(fpath, q_label, content, key_prefix="delete_subject_all_years")
                                    st.divider()
                                    continue
                                if is_exam_mode:
                                    render_exam_question_card(q_label, content, fpath, f"exam_action_subject_all_{fpath}")
                                    continue
                                render_browse_question_editor_card(
                                    q_label,
                                    content,
                                    fpath,
                                    "subj_all",
                                    paper_type_scope=paper_type_scope,
                                    prepared_assets=prepared_assets,
                                )
                                st.divider()
                        elif selected_option:
                            # 解析出真实的年份和文件名
                            sel_y = selected_option.split("年 - ")[0]
                            sel_f = selected_option.split("年 - ")[1]
                            selected_file_path = os.path.join(CHAPTERS_DIR, subject, sel_y, sel_f)
                    else:
                        st.info("该板块下暂无任何文件")
                else:
                    if files:
                        if selected_option == SHOW_ALL_OPT:
                            # 不显示底部的单文件编辑器
                            st.markdown(f"### {year}年 {subject} - 所有题目")
                            
                            for i, fname in enumerate(files[page_start:page_end], start=page_start):
                                fpath = os.path.join(CHAPTERS_DIR, subject, year, fname)
                                if not os.path.exists(fpath): continue
                                
                                # 读取内容
                                prepared_assets = None
                                if not is_delete_mode and not is_exam_mode:
                                    prepared_assets = load_question_editor_assets(fpath)
                                    content = prepared_assets["content"]
                                else:
                                    content = read_question_text(fpath)
                                
                                # 提取显示标签
                                q_label = format_question_title(fname)

                                if is_delete_mode:
                                    render_delete_question_item(fpath, q_label, content, key_prefix="delete_subject_year")
                                    st.divider()
                                    continue

                                if is_exam_mode:
                                    render_exam_question_card(q_label, content, fpath, f"exam_action_subject_year_{fpath}")
                                    continue

                                render_browse_question_editor_card(
                                    q_label,
                                    content,
                                    fpath,
                                    "subj_year",
                                    paper_type_scope=paper_type_scope,
                                    prepared_assets=prepared_assets,
                                )
                                st.divider()

                        elif selected_option and selected_option != SHOW_ALL_OPT:
                             selected_file_path = os.path.join(CHAPTERS_DIR, subject, year, selected_option)
                    else:
                        st.info("该目录下暂无文件")
            else:
                st.warning("该板块暂无年份数据")
                
    elif browse_mode == "按试卷浏览":
        # 采用一致的双栏独立滑动布局
        col_nav, col_content = st.columns([0.8, 3])
        
        with col_nav:
            st.markdown('<div id="paper-left-anchor"></div>', unsafe_allow_html=True)
            
            all_years = get_all_years_globally(paper_type=paper_type_scope)
            type_opts = ["WK"] if is_cloze_library else [key for key in PAPER_TYPES.keys() if key != "WK"]
            def _fmt_paper_type(x):
                if x == "全部类型":
                    return "全部类型"
                return PAPER_TYPES.get(x, x)
            def _on_paper_type_change():
                st.session_state.pop("paper_year", None)
                st.session_state.pop("paper_name", None)
            st.subheader("🗂️ 类型选择")
            paper_type = st.selectbox("题目类型", options=["全部类型"] + type_opts, format_func=_fmt_paper_type, key="paper_type", label_visibility="collapsed", on_change=_on_paper_type_change)
            
            if paper_type != "全部类型":
                years_for_type = get_all_years_by_paper_type(paper_type)
            else:
                years_for_type = all_years
            
            if not years_for_type:
                st.warning("题库中暂无任何年份数据")
            else:
                st.subheader("📅 选择年份")
                def _on_paper_year_change():
                    st.session_state.pop("paper_name", None)
                year = st.radio("📅 选择年份", options=years_for_type, key="paper_year", horizontal=True, label_visibility="collapsed", on_change=_on_paper_year_change)
                
                st.write("")
                st.subheader("📂 试卷选择")
                if paper_type != "全部类型":
                    papers = get_papers_by_year_and_type(year, paper_type)
                else:
                    papers = get_papers_by_year(year, paper_type=paper_type_scope)
                if papers:
                    paper_name = st.selectbox("选择试卷", options=papers, key="paper_name", label_visibility="collapsed")
                else:
                    paper_name = None
                    st.info("该年份下未找到试卷")
                    
                st.write("")
                st.subheader("👀 展示模式")
                view_mode = st.radio("展示模式", ["单题选择模式", "所有问题展示模式"], horizontal=False, label_visibility="collapsed")
                
                if all_years and year and paper_name:
                    if paper_type != "全部类型":
                        questions = get_questions_by_paper_and_type(year, paper_name, paper_type)
                    else:
                        questions = get_questions_by_paper(year, paper_name, paper_type=paper_type_scope)
                    if questions and view_mode == "单题选择模式":
                        st.write("")
                        st.subheader("选择题目进行删除" if is_delete_mode else "选择题目进行编辑")
                        
                        # 使用 session_state 记录当前选中的题目索引
                        select_key = f"selected_q_idx_{year}_{paper_name}"
                        if select_key not in st.session_state:
                            st.session_state[select_key] = 0
                        if st.session_state[select_key] >= len(questions):
                            st.session_state[select_key] = max(0, len(questions) - 1)
                        
                        # 按钮网格布局 (每行 3 个，适配左栏宽度)
                        num_cols = 3
                        rows = (len(questions) + num_cols - 1) // num_cols
                        
                        for r in range(rows):
                            cols = st.columns(num_cols)
                            for c in range(num_cols):
                                idx = r * num_cols + c
                                if idx < len(questions):
                                    q = questions[idx]
                                    q_num = q['file'].split('-')[3]
                                    btn_label = f"第{q_num}题"
                                    
                                    # 高亮当前选中的按钮
                                    is_selected = (idx == st.session_state[select_key])
                                    btn_type = "primary" if is_selected else "secondary"
                                    
                                    if cols[c].button(btn_label, key=f"q_btn_{year}_{paper_name}_{idx}", type=btn_type):
                                        st.session_state[select_key] = idx
                                        st.rerun()

                        selected_q_idx = st.session_state[select_key]
                        if selected_q_idx < len(questions):
                            selected_question = questions[selected_q_idx]
                            selected_file_path = selected_question["path"]
                        else:
                            selected_file_path = None
                    else:
                        selected_file_path = None
                        
        with col_content:
            st.markdown('<div id="paper-right-anchor"></div>', unsafe_allow_html=True)
            if all_years and year and paper_name:
                if not questions:
                     st.info("未找到该试卷的题目")
                else:
                    if view_mode == "单题选择模式":
                        # 单题模式下，右侧不展示列表，由外部逻辑(Split View)在最下方展示单题编辑
                        pass
                    else:
                        # 所有问题展示模式：逐题列出，左编辑右预览
                        for i, q in enumerate(questions):
                            q_path = q["path"]
                            if not os.path.exists(q_path): continue
                            
                            # 读取内容
                            prepared_assets = None
                            if not is_delete_mode and not is_exam_mode:
                                prepared_assets = load_question_editor_assets(q_path)
                                content = prepared_assets["content"]
                            else:
                                content = read_question_text(q_path)
                                
                            # 题目编号
                            q_label = format_question_title(q['file'])

                            if is_delete_mode:
                                render_delete_question_item(q_path, q_label, content, key_prefix="delete_paper_all")
                                st.divider()
                                continue

                            if is_exam_mode:
                                render_exam_question_card(q_label, content, q_path, f"exam_action_paper_{q_path}")
                                continue

                            render_browse_question_editor_card(
                                q_label,
                                content,
                                q_path,
                                "paper_all",
                                paper_type_scope=paper_type_scope,
                                prepared_assets=prepared_assets,
                            )
                            st.divider()
    
    elif browse_mode == "按录入顺序浏览":
        # 采用一致的双栏独立滑动布局
        col_nav, col_content = st.columns([1, 2.5])
        
        with col_nav:
            st.markdown('<div id="time-left-anchor"></div>', unsafe_allow_html=True)
            st.markdown("### 🕒 浏览设置")
            
            # 排序选项
            st.subheader("排序方式")
            sort_order = st.radio("排序方式", ["最新录入在最前", "最早录入在最前"], horizontal=False, label_visibility="collapsed")
            
            st.divider()
            
            try:
                from utils.csv_ops import read_csv_index
                csv_data = _filter_question_rows(read_csv_index(), paper_type_scope)
            except Exception as e:
                csv_data = []
                st.error(f"读取索引失败: {e}")
                
            if csv_data:
                st.subheader("显示数量限制")
                max_show = st.slider("最多展示题目数量", min_value=5, max_value=20, value=10, step=1, label_visibility="visible", key="time_max_show")
                if st.session_state.get("time_max_show_prev") != max_show:
                    st.session_state["time_browse_page"] = 1
                    st.session_state["time_max_show_prev"] = max_show
                
                sorted_data = sorted(
                    csv_data,
                    key=lambda r: r.get("初次录入的时间", "") or r.get("最后修改时间", ""),
                    reverse=(sort_order == "最新录入在最前"),
                )
                total_count = len(sorted_data)
                total_pages = max(1, (total_count + max_show - 1) // max_show)
                current_page = int(st.session_state.get("time_browse_page", 1) or 1)
                current_page = max(1, min(total_pages, current_page))
                st.session_state["time_browse_page"] = current_page
                
                st.divider()
                st.markdown(f"第 {current_page} 页")
                p1, p2 = st.columns(2)
                with p1:
                    if st.button("⬅️ 上一页", key="time_browse_prev", disabled=(current_page <= 1), use_container_width=True):
                        st.session_state["time_browse_page"] = current_page - 1
                        st.rerun()
                with p2:
                    if st.button("下一页 ➡️", key="time_browse_next", disabled=(current_page >= total_pages), use_container_width=True):
                        st.session_state["time_browse_page"] = current_page + 1
                        st.rerun()
                
        with col_content:
            st.markdown('<div id="time-right-anchor"></div>', unsafe_allow_html=True)
            if not csv_data:
                st.info("题库为空或索引未建立，请先一键重建题库索引。")
            else:
                total_count = len(sorted_data)
                start_idx = (current_page - 1) * max_show
                end_idx = min(start_idx + max_show, total_count)
                display_data = sorted_data[start_idx:end_idx]
                
                st.markdown(f"### 共找到 {total_count} 道题目，当前展示第 {current_page} 页。")
                
                for i, row in enumerate(display_data):
                    fpath = os.path.join(CHAPTERS_DIR, row["相对文件路径"])
                    if not os.path.exists(fpath):
                        continue

                    fname = row["文件名称"]
                    q_label = format_question_title(fname)

                    # 增加时间标识显示
                    time_str = row.get("初次录入的时间", "") or row.get("最后修改时间", "")
                    extra_label = ""
                    if time_str:
                        extra_label = f"<span style='font-size:0.5em; color:gray; font-weight:normal; margin-left: 10px;'>🕒 {time_str}</span>"
                        
                    lazy_key = hashlib.md5(f"time_browse:{fpath}".encode()).hexdigest()[:10]

                    if is_delete_mode:
                        content = read_question_text(fpath)
                        render_delete_question_item(fpath, q_label, content, key_prefix="delete_time", extra_html_label=extra_label)
                        st.divider()
                        continue

                    if is_exam_mode:
                        content = read_question_text(fpath)
                        render_exam_question_card(q_label, content, fpath, f"exam_action_time_{fpath}")
                        continue

                    prepared_assets = load_question_editor_assets(fpath)
                    content = prepared_assets["content"]
                    render_browse_question_editor_card(
                        q_label,
                        content,
                        fpath,
                        f"time_{lazy_key}",
                        paper_type_scope=paper_type_scope,
                        extra_html_label=extra_label,
                        prepared_assets=prepared_assets,
                    )
                    st.divider()

    # 编辑区域 (Split View) - 仅在选择了文件时显示，并严格限制在右栏内容区内
    if selected_file_path and os.path.exists(selected_file_path):
        
        # 为了让单题模式下也能正确渲染在右侧容器中，需要判断我们现在是否还有 col_content 的上下文。
        # 如果我们在主循环外，我们需要重新打开右侧的 column 容器。
        try:
            target_container = col_content
        except NameError:
            target_container = st.container()

        with target_container:
            prepared_assets = None
            if not is_exam_mode and not is_delete_mode:
                prepared_assets = load_question_editor_assets(selected_file_path)
                current_content = prepared_assets["content"]
            else:
                current_content = read_question_text(selected_file_path)
                
            # 组卷模式使用聚焦卡片，普通浏览继续使用完整编辑头部。
            if "browse_mode" in locals():
                q_fname = os.path.basename(selected_file_path)
                q_label = format_question_title(q_fname)
                
            if is_exam_mode:
                render_exam_question_card(q_label, current_content, selected_file_path, f"exam_action_selected_{selected_file_path}")
            elif is_delete_mode:
                render_static_question_header(q_label, current_content, selected_file_path)
                render_delete_question_item(selected_file_path, q_label, current_content, key_prefix="delete_selected", show_header=False)
            else:
                selected_key = _question_key("selected", selected_file_path)
                render_browse_question_editor_card(
                    q_label,
                    current_content,
                    selected_file_path,
                    f"selected_{selected_key}",
                    paper_type_scope=paper_type_scope,
                    prepared_assets=prepared_assets,
                )
                        
            if not is_exam_mode and not is_delete_mode:
                with st.expander("查看文件路径"):
                    st.code(selected_file_path)


def _render_sqlite_ai_exam_panel(theme: str, target_count: int):
    from services.database_service import DEFAULT_DATABASE_PATH
    from services.exam_selection_service import legacy_rows_to_existing_paths, select_exam_rows
    from services.question_db_service import QuestionListFilters
    from services.sqlite_legacy_adapter import list_sqlite_legacy_rows

    db_path = DEFAULT_DATABASE_PATH
    is_paper = "试卷" in str(theme or "")
    effective_target = 19 if is_paper else max(1, int(target_count or 10))
    st.markdown(
        """
        <style>
        div[data-testid="stVerticalBlock"]:has(.mc-sqlite-ai-exam-anchor) {
            gap: 0.56rem !important;
        }
        div[data-testid="stVerticalBlock"]:has(.mc-sqlite-ai-exam-anchor) div[data-testid="stButton"] > button {
            min-height: 2.45rem !important;
            white-space: normal !important;
        }
        .mc-sqlite-ai-exam-title {
            margin: 0;
            color: #4c1d95;
            font-size: 1.05rem;
            line-height: 1.35;
            font-weight: 820;
        }
        .mc-sqlite-ai-exam-caption {
            margin: -0.1rem 0 0.2rem;
            color: #5f6368;
            font-size: 0.84rem;
            line-height: 1.5;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.markdown('<span class="mc-sqlite-ai-exam-anchor"></span>', unsafe_allow_html=True)
        st.markdown('<div class="mc-sqlite-ai-exam-title">🤖 SQLite 智能预组卷</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="mc-sqlite-ai-exam-caption">只读取 SQLite 摘要字段生成候选池；抽中题目仍以旧 .tex 路径进入试题篮。本次目标 {effective_target} 题。</div>',
            unsafe_allow_html=True,
        )
        if not os.path.exists(db_path):
            st.warning(f"未找到正式数据库：{db_path}")
            return

        c_subject, c_diff, c_limit = st.columns([1.45, 0.9, 0.7], gap="small")
        with c_subject:
            extended_subjects = ["高考范围"] + SUBJECTS
            selected_subjects = st.multiselect(
                "知识板块",
                options=extended_subjects,
                default=["高考范围"],
                key="sqlite_ai_exam_subjects",
            )
        with c_diff:
            st.markdown("<div style='font-size: 14px; color: #31333F; margin-bottom: 5px;'><b>目标平均难度星级</b></div>", unsafe_allow_html=True)
            from utils.star_rating import st_star_rating

            ai_difficulty = st_star_rating(
                label="",
                value=st.session_state.get("sqlite_ai_exam_diff_val", 3.0),
                max_stars=6,
                key="star_sqlite_ai_exam_diff",
            )
            if ai_difficulty is not None and ai_difficulty != st.session_state.get("sqlite_ai_exam_diff_val", 3.0):
                st.session_state["sqlite_ai_exam_diff_val"] = ai_difficulty
        with c_limit:
            candidate_limit = st.selectbox(
                "候选上限",
                [500, 1000, "全部"],
                index=1,
                key="sqlite_ai_exam_candidate_limit",
            )

        c_intent, c_polish = st.columns([4, 1], gap="small", vertical_alignment="bottom")
        with c_intent:
            st.text_area(
                "组卷意图与附加要求",
                key="sqlite_ai_exam_intent",
                height=86,
                placeholder="例如：侧重函数与导数，最后一道导数压轴，不要太偏。",
            )
        with c_polish:
            if st.button("✨ AI 润色想法", key="sqlite_ai_exam_polish", use_container_width=True):
                txt = st.session_state.get("sqlite_ai_exam_intent", "").strip()
                if not txt:
                    st.toast("请先填写初步想法", icon="⚠️")
                else:
                    res = call_ai_for_polish(txt)
                    if res.startswith("❌"):
                        st.toast(res, icon="❌")
                    else:
                        st.session_state["sqlite_ai_exam_intent"] = res
                        st.toast("润色成功", icon="✨")
                        st.rerun()

        if is_paper:
            st.info("当前为试卷类模板，SQLite 智能抽题会按新高考结构尽量抽取 19 题。")
        else:
            st.caption(f"当前为非试卷类模板，将按上方组卷数量抽取 {effective_target} 题。")

        if st.button("🚀 开始 SQLite 智能抽题", key="sqlite_ai_exam_run", type="primary", use_container_width=True):
            if not selected_subjects:
                st.warning("请至少选择一个知识板块。")
                return
            max_rows = 0 if candidate_limit == "全部" else int(candidate_limit)
            with st.spinner("正在从 SQLite 摘要字段构建候选池..."):
                try:
                    rows = list_sqlite_legacy_rows(db_path, QuestionListFilters(limit=100, offset=0), max_rows=max_rows)
                    result = select_exam_rows(
                        rows,
                        selected_subjects,
                        all_subjects=SUBJECTS,
                        target_count=effective_target,
                        is_paper_template=is_paper,
                        target_difficulty=float(st.session_state.get("sqlite_ai_exam_diff_val", 3.0) or 3.0),
                        intent_text=st.session_state.get("sqlite_ai_exam_intent", ""),
                    )
                    final_paths = legacy_rows_to_existing_paths(
                        result["selected_rows"],
                        project_root=BASE_DIR,
                        chapters_dir=CHAPTERS_DIR,
                    )
                except Exception as exc:
                    st.error(f"SQLite 智能抽题失败：{exc}")
                    return

            if not final_paths:
                st.warning("当前条件下没有抽到可进入旧组卷流程的题目。")
                return

            st.session_state["exam_selected_qs"] = final_paths
            st.session_state["exam_q_count_input"] = len(final_paths)
            st.session_state["_count_widget"] = len(final_paths)
            st.session_state["exam_basket_open"] = True
            st.session_state["exam_expanded_q"] = final_paths[0]
            sync_exam_blocks_to_selected_order(final_paths)
            st.session_state["ai_exam_modified"] = False

            if len(final_paths) < effective_target:
                st.warning(f"候选池满足条件的题目不足，仅抽取到 {len(final_paths)} 题。")
            else:
                st.success(f"SQLite 智能抽题完成：已抽取 {len(final_paths)} 题。")
            intent_profile = result.get("intent_profile") or {}
            if intent_profile.get("active"):
                matched_subjects = "、".join(intent_profile.get("subjects") or []) or "无明确板块"
                st.caption(f"已使用意图参与筛选：匹配板块 {matched_subjects}，关键词 {len(intent_profile.get('tokens') or [])} 个。")
            st.rerun()


def page_exam_paper_generation():
    st.markdown('<span id="mc-exam-page-anchor"></span>', unsafe_allow_html=True)
    st.header("🖨️ 组卷服务")
    
    # 注入全局按钮样式 CSS Hook
    st.markdown("""
    <style>
    /* 让按钮靠得更近，高度一致 */
    .stButton > button {
        height: 100% !important;
        min-height: 40px !important;
    }
    
    /* 使用更兼容的选择器，确保选中按钮外层的 div */
    div:has(> div > .blue-btn-hook) + div button[kind="secondary"],
    div[data-testid="column"]:has(.blue-btn-hook) button[kind="secondary"] {
        background-color: #f0f2f6 !important; /* 淡灰色底 */
        border-color: #d0d7de !important;
        color: #24292f !important;
        font-weight: bold !important;
        box-shadow: inset 0 1px 2px rgba(0,0,0,0.05) !important;
    }
    
    div:has(> div > .white-btn-hook) + div button[kind="secondary"],
    div[data-testid="column"]:has(.white-btn-hook) button[kind="secondary"] {
        background-color: white !important;
        border-color: #e1e4e8 !important;
        color: black !important;
    }
    
    div[data-testid="element-container"]:has(.red-btn-hook) + div[data-testid="stButton"] > button {
        background-color: #d73a49 !important;
        border-color: #d73a49 !important;
        color: white !important;
    }
    
    /* 针对已选问题网格布局中的红色 X 按钮 */
    div[data-testid="element-container"]:has(.white-red-text-btn-hook) + div[data-testid="stButton"] > button {
        background-color: white !important;
        border-color: #e1e4e8 !important;
        color: #d73a49 !important;
        padding: 0 !important;
        font-weight: bold !important;
    }
    div[data-testid="element-container"]:has(.white-red-text-btn-hook) + div[data-testid="stButton"] > button:hover {
        background-color: #ffeef0 !important;
        border-color: #d73a49 !important;
    }
    
    /* 取消 Streamlit 按钮点击时的下沉动画效果 */
    .stButton > button:active {
        transform: none !important;
    }
    
    /* 调整“选择组卷服务模块”的单选按钮字号，使其与 h3 (###) 差不多大 */
    div.big-radio-container + div[data-testid="stRadio"] label[data-baseweb="radio"] div {
        font-size: 1.5rem !important;
        font-weight: 600 !important;
        line-height: 1.2 !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown('<div class="big-radio-container"></div>', unsafe_allow_html=True)
    exam_service_mode = st.radio("选择组卷服务模块", ["🖨️ 试卷排版工作台", "📂 历史组卷浏览"], horizontal=True, label_visibility="collapsed")

    if exam_service_mode == "📂 历史组卷浏览":
        # ================= 新增：历史组卷浏览 =================
        st.markdown("""
        <style>
        #mc-history-browser-anchor {
            display: none !important;
        }
        div[data-testid="stVerticalBlock"]:has(#mc-history-browser-anchor) {
            gap: 0.45rem !important;
        }
        div[data-testid="stVerticalBlock"]:has(#mc-history-browser-anchor) div[data-testid="stHorizontalBlock"] {
            gap: 0.65rem !important;
            margin: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(#mc-history-browser-anchor) h3,
        div[data-testid="stVerticalBlock"]:has(#mc-history-browser-anchor) h4,
        div[data-testid="stVerticalBlock"]:has(#mc-history-browser-anchor) h5 {
            margin-top: 0.28rem !important;
            margin-bottom: 0.18rem !important;
        }
        div[data-testid="stVerticalBlock"]:has(#mc-history-browser-anchor) hr {
            margin: 0.35rem 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(#mc-history-browser-anchor) div[data-testid="stRadio"] {
            margin-bottom: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(#mc-history-browser-anchor) div[data-testid="stRadio"] div[role="radiogroup"] {
            gap: 0.3rem !important;
        }
        div[data-testid="stVerticalBlock"]:has(#mc-history-browser-anchor) div[data-testid="stRadio"] label {
            padding-top: 0.18rem !important;
            padding-bottom: 0.18rem !important;
        }
        div[data-testid="stVerticalBlock"]:has(#mc-history-browser-anchor) div[data-testid="stSelectbox"] {
            margin-bottom: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(#mc-history-browser-anchor) .mc-history-divider {
            height: 1px;
            margin: 0.45rem 0;
            background: rgba(0, 0, 0, 0.08);
        }
        div[data-testid="stVerticalBlock"]:has(#mc-history-browser-anchor) .mc-history-question-number {
            color: #5b21b6;
            font-size: 0.86rem;
            font-weight: 700;
            line-height: 1.3;
            margin: 0.35rem 0 0.12rem;
        }
        div[data-testid="stVerticalBlock"]:has(#mc-history-browser-anchor) pre {
            margin-top: 0.2rem !important;
            margin-bottom: 0.2rem !important;
        }
        @media (prefers-reduced-motion: reduce) {
            div[data-testid="stVerticalBlock"]:has(#mc-history-browser-anchor) * {
                scroll-behavior: auto !important;
            }
        }
        </style>
        <span id="mc-history-browser-anchor"></span>
        """, unsafe_allow_html=True)
        export_base_dir = os.path.join(BASE_DIR, "Test Paper Group", "导出文件")
        if not os.path.exists(export_base_dir):
            st.info("暂无组卷记录")
        else:
            years = sorted([d for d in os.listdir(export_base_dir) if os.path.isdir(os.path.join(export_base_dir, d))], reverse=True)
            if not years:
                st.info("暂无组卷记录")
            else:
                c_y1, c_y2 = st.columns([1, 6], vertical_alignment="center")
                with c_y1:
                    st.markdown("##### 📅 选择年份")
                with c_y2:
                    selected_year = st.radio("选择年份", ["显示所有年份"] + years, horizontal=True, label_visibility="collapsed")
                
                months = []
                if selected_year != "显示所有年份":
                    year_dir = os.path.join(export_base_dir, selected_year)
                    if os.path.exists(year_dir):
                        months = sorted([d for d in os.listdir(year_dir) if os.path.isdir(os.path.join(year_dir, d))], reverse=True)
                else:
                    for y in years:
                        y_dir = os.path.join(export_base_dir, y)
                        months.extend([d for d in os.listdir(y_dir) if os.path.isdir(os.path.join(y_dir, d))])
                    months = sorted(list(set(months)), reverse=True)
                
                c_m1, c_m2 = st.columns([1, 6], vertical_alignment="center")
                with c_m1:
                    st.markdown("##### 📅 选择月份")
                with c_m2:
                    if months:
                        selected_month = st.radio("选择月份", ["显示所有月份"] + months, horizontal=True, label_visibility="collapsed")
                    else:
                        st.info("该年份下暂无记录")
                        selected_month = "显示所有月份"
                
                # 收集试卷列表
                papers = []
                years_to_search = years if selected_year == "显示所有年份" else [selected_year]
                for y in years_to_search:
                    y_dir = os.path.join(export_base_dir, y)
                    months_to_search = [m for m in os.listdir(y_dir) if os.path.isdir(os.path.join(y_dir, m))] if selected_month == "显示所有月份" else [selected_month]
                    for m in months_to_search:
                        m_dir = os.path.join(y_dir, m)
                        if os.path.exists(m_dir):
                            for p in os.listdir(m_dir):
                                p_dir = os.path.join(m_dir, p)
                                if os.path.isdir(p_dir):
                                    tex_file = os.path.join(p_dir, f"{p}.tex")
                                    if os.path.exists(tex_file):
                                        papers.append({"name": p, "path": tex_file, "dir": p_dir, "year": y, "month": m})
                
                if not papers:
                    st.info("未找到符合条件的试卷")
                else:
                    st.markdown('<div class="mc-history-divider"></div>', unsafe_allow_html=True)
                    paper_names = [p["name"] for p in papers]
                    st.markdown("##### 📄 选择试卷")
                    selected_paper_name = st.selectbox("选择试卷", paper_names, label_visibility="collapsed")
                    selected_paper = next(p for p in papers if p["name"] == selected_paper_name)
                    
                    st.markdown('<div class="mc-history-divider"></div>', unsafe_allow_html=True)
                    present_mode = st.radio("呈现形式", ["以题目组合形式呈现", "以整卷形式呈现"], horizontal=True, label_visibility="collapsed")
                    
                    if present_mode == "以整卷形式呈现":
                        c_src, c_pdf = st.columns(2)
                        with c_src:
                            st.markdown("##### 📜 LaTeX 源码")
                            with open(selected_paper["path"], "r", encoding="utf-8") as f:
                                tex_content = f.read()
                            st.code(tex_content, language="latex", line_numbers=True)
                        with c_pdf:
                            st.markdown("##### 📑 PDF 预览")
                            pdf_path = os.path.join(selected_paper["dir"], f"{selected_paper['name']}.pdf")
                            if os.path.exists(pdf_path):
                                import base64
                                with open(pdf_path, "rb") as f:
                                    base64_pdf = base64.b64encode(f.read()).decode('utf-8')
                                pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800px" type="application/pdf"></iframe>'
                                st.markdown(pdf_display, unsafe_allow_html=True)
                            else:
                                st.warning("未找到生成的 PDF 文件。请确认该试卷是否已成功编译。")
                    
                    elif present_mode == "以题目组合形式呈现":
                        st.markdown("##### 🧩 题目组合排列")
                        with open(selected_paper["path"], "r", encoding="utf-8") as f:
                            tex_content = f.read()
                        
                        # 简易解析：按 \section, \subsection, \chapter, \begin{problem}, \begin{question}, \begin{lanbox} 分块
                        import re
                        blocks = []
                        
                        # 使用正则提取所有的块
                        # 查找所有的开始标记位置
                        pattern = r'(\\chapter\{.*?\}|\\section\{.*?\}|\\subsection\{.*?\}|\\begin\{problem\}.*?\\end\{problem\}|\\begin\{question\}.*?\\end\{question\}|\\begin\{lanbox\}.*?\\end\{lanbox\})'
                        matches = re.finditer(pattern, tex_content, flags=re.DOTALL)
                        
                        for idx, match in enumerate(matches):
                            block_text = match.group(1)
                            if block_text.startswith(r'\chapter{'):
                                title = re.search(r'\\chapter\{(.*?)\}', block_text).group(1)
                                title = re.sub(r'\s+', ' ', title.replace('\n', ' ')).strip()
                                blocks.append({"type": "chapter", "content": title})
                            elif block_text.startswith(r'\section{'):
                                title = re.search(r'\\section\{(.*?)\}', block_text, re.DOTALL).group(1)
                                title = re.sub(r'\s+', ' ', title.replace('\n', ' ')).strip()
                                blocks.append({"type": "section", "content": title})
                            elif block_text.startswith(r'\subsection{'):
                                title = re.search(r'\\subsection\{(.*?)\}', block_text, re.DOTALL).group(1)
                                title = re.sub(r'\s+', ' ', title.replace('\n', ' ')).strip()
                                blocks.append({"type": "subsection", "content": title})
                            else:
                                # 清除可能会遗留的 \begin{lanbox} 和 \end{lanbox} 标记
                                clean_text = re.sub(r'\\begin\{lanbox\}', '', block_text)
                                clean_text = re.sub(r'\\end\{lanbox\}', '', clean_text)
                                blocks.append({"type": "question", "content": clean_text.strip()})
                                
                        if not blocks:
                            st.info("未能从源码中解析出具体的题目和章节，这可能是因为文件尚未插入任何题目，或者结构与预期不符。")
                        else:
                            q_count = 1
                            for b in blocks:
                                if b["type"] == "chapter":
                                    st.markdown(f"### 🗂️ {b['content']}")
                                elif b["type"] == "section":
                                    st.markdown(f"#### 🗂️ {b['content']}")
                                elif b["type"] == "subsection":
                                    st.markdown(f"##### 📝 {b['content']}")
                                elif b["type"] == "question":
                                    st.markdown(f'<div class="mc-history-question-number">第 {q_count} 题</div>', unsafe_allow_html=True)
                                    st.markdown(latex_to_markdown(b["content"]), unsafe_allow_html=True)
                                    q_count += 1
                                st.markdown('<div class="mc-history-divider"></div>', unsafe_allow_html=True)
        return

    # 1. 主题选择与组卷按钮
    template_dir = os.path.join(BASE_DIR, "Test Paper Group", "主题模板")
    theme_options = []
    if os.path.exists(template_dir):
        for d in os.listdir(template_dir):
            if os.path.isdir(os.path.join(template_dir, d)):
                theme_options.append(d)
    if not theme_options:
        theme_options = ["讲义类模板", "试卷类模板", "练习类模板"]
        
    if "exam_mode_stage" not in st.session_state:
        st.session_state["exam_mode_stage"] = "selection"
    if "exam_blocks" not in st.session_state:
        st.session_state["exam_blocks"] = []
        
    if "exam_theme_select" not in st.session_state:
        st.session_state["exam_theme_select"] = theme_options[0]
        
    if "exam_theme" not in st.session_state:
        st.session_state["exam_theme"] = st.session_state["exam_theme_select"]
        
    if "exam_q_count_input" not in st.session_state:
        st.session_state["exam_q_count_input"] = 19 if "试卷类" in st.session_state["exam_theme_select"] else 10
        
    if "exam_selected_qs" not in st.session_state:
        st.session_state["exam_selected_qs"] = []
        
    if "ai_exam_active" not in st.session_state:
        st.session_state["ai_exam_active"] = False
    if "ai_exam_modified" not in st.session_state:
        st.session_state["ai_exam_modified"] = False
        
    # 如果在排版阶段，跳过选题页面渲染
    if st.session_state["exam_mode_stage"] == "typesetting":
        render_typesetting_workspace()
        return

    # ================= 阶段一：选题购物车 =================
    # 提前处理状态同步，避免在 widget 渲染后修改其 session_state 导致 StreamlitAPIException
    # 这里非常关键，必须把用户选择的 theme 实时同步并保存到持久化变量中
    if "exam_theme_select" in st.session_state:
        if st.session_state.get("exam_theme_select") != st.session_state.get("exam_theme"):
            st.session_state["exam_theme"] = st.session_state["exam_theme_select"]
            # Only change the default value if the user hasn't actively modified the count
            if "试卷类" in st.session_state["exam_theme"]:
                st.session_state["exam_q_count_input"] = 19
            else:
                st.session_state["exam_q_count_input"] = 10
            st.session_state["_count_widget"] = st.session_state["exam_q_count_input"]

    selected_count = len(st.session_state.get("exam_selected_qs", []))
    if selected_count > st.session_state.get("exam_q_count_input", 10):
        st.session_state["exam_q_count_input"] = selected_count
        st.session_state["_count_widget"] = selected_count
        st.toast("当前新增问题数已超过预设定数，已为您新增题数上限", icon="⚠️")
    render_exam_floating_basket()
    from services.database_service import DEFAULT_DATABASE_PATH
    from services.local_preferences_service import QUESTION_SOURCE_LEGACY, QUESTION_SOURCE_SQLITE, get_exam_default_source, source_label
    from services.question_db_service import get_question_bank_availability

    exam_source_options = ["旧 TeX 题库", "SQLite 试用题库"]
    preferred_exam_source = get_exam_default_source()
    sqlite_availability = get_question_bank_availability(DEFAULT_DATABASE_PATH)
    if preferred_exam_source == QUESTION_SOURCE_SQLITE and not sqlite_availability.get("ready_for_browse"):
        preferred_exam_source = QUESTION_SOURCE_LEGACY
    default_exam_source_label = source_label(preferred_exam_source, surface="exam")
    if not st.session_state.get("exam_selection_source_bootstrapped_v3"):
        st.session_state.setdefault("exam_selection_source", default_exam_source_label)
        st.session_state["exam_selection_source_bootstrapped_v3"] = True
    if st.session_state.get("exam_selection_source") not in exam_source_options:
        st.session_state["exam_selection_source"] = default_exam_source_label

    source_label_col, source_control_col = st.columns([0.72, 3.4], gap="small", vertical_alignment="center")
    with source_label_col:
        st.markdown("##### 选题来源")
    with source_control_col:
        selection_source = st.radio(
            "选题来源",
            exam_source_options,
            key="exam_selection_source",
            horizontal=True,
            label_visibility="collapsed",
        )

    # Sync state before widget to preserve value
    current_count = st.session_state.get("exam_q_count_input", 10)
    if "_count_widget" not in st.session_state:
        st.session_state["_count_widget"] = current_count

    c_theme, c_num, c_ai = st.columns([3, 1, 3])
    with c_theme:
        theme = st.selectbox("选择组卷主题", options=theme_options, key="exam_theme_select", label_visibility="collapsed")
    with c_num:
        def _update_count():
            st.session_state["exam_q_count_input"] = st.session_state["_count_widget"]
        st.number_input("本次组卷数量", min_value=1, key="_count_widget", on_change=_update_count, label_visibility="collapsed")
    with c_ai:
        if selection_source == "旧 TeX 题库":
            # 按钮状态逻辑：白底(未激活) -> 绿底(激活且未被修改) -> 蓝底(激活且被修改)
            ai_btn_type = "primary" if st.session_state["ai_exam_active"] else "secondary"
            if st.button("🤖 启用AI辅助预组卷", use_container_width=True, type=ai_btn_type):
                st.session_state["ai_exam_active"] = True
                st.session_state["ai_exam_modified"] = False # 重置修改状态
                st.rerun()
        else:
            ai_btn_type = "primary" if st.session_state["ai_exam_active"] else "secondary"
            if st.button("🤖 启用SQLite智能预组卷", use_container_width=True, type=ai_btn_type):
                st.session_state["ai_exam_active"] = True
                st.session_state["ai_exam_modified"] = False
                st.rerun()

    if selection_source == "SQLite 试用题库":
        if not sqlite_availability.get("ready_for_browse"):
            st.warning("SQLite 正式库暂未包含题目；如需使用旧题库，请切回“旧 TeX 题库”。")
        if not sqlite_availability.get("has_schema"):
            st.error("SQLite 正式库不可读取或尚未初始化，请先到“工具箱 → 本地维护与升级”检查本地数据库。")
            return
        st.caption("SQLite 试用源会复用上方试题篮与后续排版工作台；SQLite 本身只读，最终生成沿用旧组卷引用次数逻辑。")
        if st.session_state.get("ai_exam_active", False):
            _render_sqlite_ai_exam_panel(theme, st.session_state.get("exam_q_count_input", 10))
        render_sqlite_readonly_browse_preview(
            allow_edit=False,
            allow_exam_basket=True,
            show_export_panel=False,
            right_heading="### SQLite 试用选题预览",
            right_caption="用左侧筛选定位题目，点击“加入试题篮”后可直接进入现有排版工作台。",
        )
        return
            
    # === 新增：AI 辅助预组卷面板 ===
    if st.session_state.get("ai_exam_active", False):
        st.markdown("---")
        st.markdown("### 🤖 智能组卷条件配置")
        with st.container(border=True):
            # 1. 知识板块约束
            st.markdown("##### 1. 考察知识板块")
            c_ai_subj, c_ai_diff = st.columns([1.5, 1])
            with c_ai_subj:
                extended_subjects = ["高考范围"] + SUBJECTS
                ai_subjects_raw = st.multiselect("选择本次组卷覆盖的知识板块", options=extended_subjects, default=["高考范围"], key="ai_exam_subjects")
            with c_ai_diff:
                # 2. 难度系数
                st.markdown("<div style='font-size: 14px; color: #31333F; margin-bottom: 5px;'><b>目标平均难度星级</b></div>", unsafe_allow_html=True)
                from utils.star_rating import st_star_rating
                ai_difficulty = st_star_rating(label="", value=st.session_state.get("ai_exam_diff_val", 3.0), max_stars=6, key="star_ai_exam_diff")
                if ai_difficulty is not None and ai_difficulty != st.session_state.get("ai_exam_diff_val", 3.0):
                    st.session_state["ai_exam_diff_val"] = ai_difficulty
            
            # 新增：组卷意图与要求
            st.markdown("##### 2. 组卷意图与附加要求")
            c_intent_lbl, c_intent_btn = st.columns([4, 1], vertical_alignment="bottom")
            with c_intent_lbl:
                intent_text = st.text_area("请填写您的组卷想法（例如：侧重考察导数的隐零点问题，解答题最后一道必须是解析几何，且不要太难）", key="ai_exam_intent", height=100)
            with c_intent_btn:
                def do_polish():
                    txt = st.session_state.get("ai_exam_intent", "").strip()
                    if not txt:
                        st.toast("请先填写初步想法", icon="⚠️")
                        return
                    res = call_ai_for_polish(txt)
                    if res.startswith("❌"):
                        st.toast(res, icon="❌")
                    else:
                        st.session_state["ai_exam_intent"] = res
                        st.toast("润色成功！", icon="✨")
                st.button("✨ AI 润色想法", on_click=do_polish, use_container_width=True)
            
            # 3. 题目数量与题型（根据主题推断，如果是试卷类则固定结构）
            st.markdown("##### 3. 试卷结构约束")
            is_paper = "试卷" in theme
            if is_paper:
                st.info("💡 当前为“试卷类模板”，系统将严格按照新高考结构（单选8+多选3+填空3+解答5=19题）抽取。")
                ai_q_count = 19
            else:
                ai_q_count = st.session_state.get("exam_q_count_input", 10)
                st.info(f"💡 当前为非试卷类模板，系统将按照您的预设，随机抽取 **{ai_q_count}** 道题目。")
            
            # 4. 执行生成按钮
            if st.button("🚀 开始智能抽题 (基于本地题库标签)", type="primary", use_container_width=True):
                if not ai_subjects_raw:
                    st.warning("请至少选择一个知识板块！")
                else:
                    with st.spinner("正在遍历题库并进行智能抽样..."):
                        # 执行基于规则的抽题算法
                        from utils.csv_ops import read_csv_index
                        csv_data = _filter_question_rows(read_csv_index())
                        
                        if not csv_data:
                            st.error("题库为空或索引未建立，请先在工具页一键重建题库索引。")
                        else:
                            from services.exam_selection_service import legacy_rows_to_existing_paths, select_exam_rows

                            current_diff = st.session_state.get("ai_exam_diff_val", 3.0)
                            result = select_exam_rows(
                                csv_data,
                                ai_subjects_raw,
                                all_subjects=SUBJECTS,
                                target_count=ai_q_count,
                                is_paper_template=is_paper,
                                target_difficulty=float(current_diff or 3.0),
                                intent_text=st.session_state.get("ai_exam_intent", ""),
                            )
                            final_paths = legacy_rows_to_existing_paths(
                                result["selected_rows"],
                                project_root=BASE_DIR,
                                chapters_dir=CHAPTERS_DIR,
                            )

                            if len(final_paths) < ai_q_count:
                                st.warning(f"题库中满足条件的题目不足，仅抽取到 {len(final_paths)} 题。")
                            else:
                                st.success(f"智能组卷完成！已成功抽取 {len(final_paths)} 道题目。")
                            intent_profile = result.get("intent_profile") or {}
                            if intent_profile.get("active"):
                                matched_subjects = "、".join(intent_profile.get("subjects") or []) or "无明确板块"
                                st.caption(f"已使用组卷意图参与筛选：匹配板块 {matched_subjects}，关键词 {len(intent_profile.get('tokens') or [])} 个。")

                            st.session_state["exam_selected_qs"] = final_paths
                            st.session_state["exam_q_count_input"] = len(final_paths)
                            st.session_state["ai_exam_modified"] = False
                            time.sleep(1)
                            st.rerun()
            
    # 注入 CSS：美化 number_input 的边框使其明显，并隐藏原生上下箭头，以及根据状态设置 primary 按钮颜色
    css_injection = """
    <style>
    """
    
    if st.session_state["ai_exam_active"]:
        if st.session_state["ai_exam_modified"]:
            btn_color = "#1f6feb" 
        else:
            btn_color = "#2ea043"
            
        css_injection += f"""
        div[data-testid="column"]:nth-child(3) button[kind="primary"] {{
            background-color: {btn_color} !important;
            border-color: {btn_color} !important;
            color: white !important;
        }}
        """
        
    css_injection += "</style>"
    st.markdown(css_injection, unsafe_allow_html=True)
        
    st.caption("已选题目会进入右侧悬浮试题篮，可在篮内预览、移除并拖拽排序。")
    st.divider()
    
    # 3. 复用浏览界面进行选题
    page_browse(is_exam_mode=True)

def _exam_output_tex_path(export_filename: str, export_dir: str) -> str:
    return os.path.join(export_dir, export_filename, f"{export_filename}.tex")

def _next_exam_export_filename(export_dir: str, theme_name: str, today=None) -> str:
    import datetime

    today = today or datetime.date.today()
    prefix = f"{today.strftime('%Y')}年{today.strftime('%m')}月{today.strftime('%d')}日 {theme_name}组卷"
    max_index = 0

    if os.path.exists(export_dir):
        for name in os.listdir(export_dir):
            stem = os.path.splitext(name)[0] if name.endswith(".tex") else name
            if not stem.startswith(prefix):
                continue
            suffix = stem[len(prefix):]
            if suffix.isdigit():
                max_index = max(max_index, int(suffix))

    return f"{prefix}{max_index + 1}"

def _compile_exam_pdf(tex_path: str) -> dict:
    if not tex_path or not os.path.exists(tex_path):
        return {"ok": False, "error": "找不到待编译的 tex 文件。"}

    xelatex = shutil.which("xelatex")
    if not xelatex:
        return {"ok": False, "error": "未检测到 xelatex，已生成 tex 文件但无法自动编译 PDF。"}

    work_dir = os.path.dirname(tex_path)
    tex_name = os.path.basename(tex_path)
    last_output = ""

    try:
        for _ in range(2):
            completed = subprocess.run(
                [
                    xelatex,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-file-line-error",
                    tex_name,
                ],
                cwd=work_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
            )
            last_output = completed.stdout or ""
            if completed.returncode != 0:
                return {
                    "ok": False,
                    "error": "PDF 编译失败，请检查 LaTeX 日志。",
                    "log": last_output[-4000:],
                }

        pdf_path = os.path.splitext(tex_path)[0] + ".pdf"
        if os.path.exists(pdf_path):
            return {"ok": True, "pdf_path": pdf_path, "log": last_output[-2000:]}
        return {"ok": False, "error": "xelatex 已运行，但未找到生成的 PDF 文件。", "log": last_output[-4000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "PDF 编译超时，tex 文件已保留，可稍后手动编译。", "log": last_output[-4000:]}
    except Exception as e:
        return {"ok": False, "error": f"PDF 编译异常：{e}", "log": last_output[-4000:]}

def _safe_int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default

def _question_paths_from_exam_blocks(blocks) -> list:
    paths = []
    seen = set()
    for blk in blocks or []:
        if blk.get("type") != "question":
            continue
        path = blk.get("path")
        if path and path not in seen and os.path.exists(path):
            paths.append(path)
            seen.add(path)
    return paths

def _increment_exam_usage_counts(question_paths) -> dict:
    updated = 0
    skipped = []
    chapters_root = os.path.abspath(CHAPTERS_DIR)

    for fpath in question_paths:
        try:
            abs_path = os.path.abspath(fpath)
            try:
                if os.path.commonpath([chapters_root, abs_path]) != chapters_root:
                    skipped.append(os.path.basename(fpath))
                    continue
            except ValueError:
                skipped.append(os.path.basename(fpath))
                continue
            content = read_question_text(fpath)
            meta, _ = parse_meta_data(content)
            if not meta or not str(meta.get("ID", "")).strip():
                skipped.append(os.path.basename(fpath))
                continue

            meta["组卷引用次数"] = str(_safe_int(meta.get("组卷引用次数", "0")) + 1)
            new_content = inject_meta_data(content, meta)
            if new_content != content:
                atomic_write_text(fpath, new_content, backup=True)
                _update_csv_index_for_content_change(fpath, new_content)
            updated += 1
        except Exception:
            skipped.append(os.path.basename(fpath))

    if updated:
        _clear_advanced_search_result_cache()
        clear_statistics_cache()
    return {"updated": updated, "skipped": skipped}

def _replace_choices_with_items(text: str) -> str:
    idx = 0
    while True:
        idx = text.find(r'\choice', idx)
        if idx == -1:
            break
        start_brace = text.find('{', idx)
        if start_brace == -1:
            idx += len(r'\choice')
            continue
        if text[idx + 7:start_brace].strip() != '':
            idx += len(r'\choice')
            continue
        next_char_idx = start_brace + 1
        while next_char_idx < len(text) and text[next_char_idx].isspace():
            next_char_idx += 1
        is_double = False
        if next_char_idx < len(text) and text[next_char_idx] == '{':
            is_double = True
            content_start = next_char_idx + 1
        else:
            content_start = start_brace + 1
        brace_count = 2 if is_double else 1
        match_end = -1
        content = ''
        for i in range(content_start, len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1
            if brace_count == 0:
                match_end = i + 1
                inner = text[content_start:i]
                if is_double:
                    last_brace_idx = inner.rfind('}')
                    content = inner[:last_brace_idx].strip() if last_brace_idx != -1 else inner.strip()
                else:
                    content = inner.strip()
                break
        if match_end != -1:
            prefix = text[:idx]
            suffix = text[match_end:]
            text = prefix + r'\item ' + content + suffix
            idx = len(prefix) + len(r'\item ') + len(content)
        else:
            idx += len(r'\choice')
    return text

def generate_exam_paper(export_filename, export_dir, blocks, theme_name):
    # 确保导出目录存在
    ensure_dir(export_dir)
    
    # 读取模板内容
    template_path = os.path.join(BASE_DIR, "Test Paper Group", "主题模板", theme_name, f"{theme_name}.tex")
    if not os.path.exists(template_path):
        return None
        
    with open(template_path, "r", encoding="utf-8") as f:
        template_content = f.read()
        
    # 生成要插入的 content
    body_lines = []
    for blk in blocks:
        if blk["type"] == "chapter":
            body_lines.append(f"\\chapter{{{blk['title']}}}")
            if blk.get("content"):
                body_lines.append(blk["content"])
        elif blk["type"] == "section":
            body_lines.append(f"\\section{{{blk['title']}}}")
            if blk.get("content"):
                body_lines.append(blk["content"])
        elif blk["type"] == "subsection":
            body_lines.append(f"\\subsection{{{blk['title']}}}")
            if blk.get("content"):
                body_lines.append(blk["content"])
        elif blk["type"] == "question":
            q_path = blk["path"]
            if os.path.exists(q_path):
                with open(q_path, "r", encoding="utf-8") as qf:
                    q_content = qf.read()
                    if theme_name == "讲义类模板":
                        body_lines.append("\\begin{lanbox}\n" + q_content + "\n\\end{lanbox}")
                    else:
                        body_lines.append(q_content)
                        
    # 如果是试卷类模板，需要对题目格式和分数进行二次加工
    if theme_name == "试卷类模板":
        import re
        q_index = 0
        current_section = 0
        new_body_lines = []
        for line in body_lines:
            if line.startswith(r"\section{"):
                current_section += 1
                new_body_lines.append(line)
            elif r"\begin{problem}" in line:
                q_index += 1
                
                # 第一步：增加题目序号注释 %*
                line = f"% {q_index}.\n" + line
                
                if current_section == 4:
                    # 对于第四个 section (解答题) 后的题目
                    # 1. 替换为 \begin{problem} 并带上对应分数
                    # 2. 删除后面紧跟的5个参数括号 {...}
                    if q_index == 15:
                        points = 13
                    elif q_index in (16, 17):
                        points = 15
                    elif q_index in (18, 19):
                        points = 17
                    else:
                        points = 12 # fallback
                        
                    # 替换 \begin{problem}{...}{...}{...}{...}{...} -> \begin{problem}[points = xx]
                    # 容错：有些参数可能换行了或者有空格，用 \s* 和 dotall 处理
                    line = re.sub(r'\\begin\{problem\}\s*\{.*?\}\s*\{.*?\}\s*\{.*?\}\s*\{.*?\}\s*\{.*?\}', f'\\\\begin{{problem}}[points = {points}]', line, flags=re.DOTALL)
                else:
                    # 对于前三个 section (选择填空) 的题目
                    # 1. 替换为 \begin{question}
                    # 2. 删除后面紧跟的5个参数括号 {...}
                    # 3. 将对应的 \end{problem} 替换为 \end{question}
                    line = re.sub(r'\\begin\{problem\}\s*\{.*?\}\s*\{.*?\}\s*\{.*?\}\s*\{.*?\}\s*\{.*?\}', r'\\begin{question}', line, flags=re.DOTALL)
                    line = line.replace(r'\end{problem}', r'\end{question}')
                    
                # 【新增修复】：将 \begin{choices} 替换为没有方括号的形式（比如去除 \begin{choices}[2] 等，恢复为 exam-zh 默认选项）
                # 题库里带参数的 \begin{choices}[2] 可能会在试卷模板里报错或者不兼容
                # 用户要求类似原来模板的纯净 \begin{choices}
                # 但是实际上用户刚才提到的是 choices，而模板里使用的是 \begin{choices} \item ...
                # 题库中用的是 \choice{{...}}，模板中似乎需要 \item
                # 我们在这里将 \choice{{...}} 转换为 \item ... 
                # 同时将带参数的 \begin{choices}[2] 去除参数
                line = re.sub(r'\\begin\{choices\}\[.*?\]', r'\\begin{choices}', line)
                
                line = _replace_choices_with_items(line)
                    
                new_body_lines.append(line)
            else:
                # 处理可能散落在别的行的 \end{problem} 和 \choice 等
                if current_section < 4 and r'\end{problem}' in line:
                    line = line.replace(r'\end{problem}', r'\end{question}')
                    
                line = re.sub(r'\\begin\{choices\}\[.*?\]', r'\\begin{choices}', line)
                line = _replace_choices_with_items(line)
                
                new_body_lines.append(line)
        body_lines = new_body_lines

    generated_body = "\n\n".join(body_lines)
    
    # 替换标题（如果有的话）
    import re
    if theme_name == "试卷类模板":
        # 试卷类模板使用的是 \title{...}
        template_content = re.sub(r'\\title\{.*?\}', f'\\\\title{{{export_filename}}}', template_content)
    elif r'\renewcommand{\mytitle}' in template_content:
        template_content = re.sub(r'\\renewcommand\{\\mytitle\}\{.*?\}', f'\\\\renewcommand{{\\\\mytitle}}{{{export_filename}}}', template_content)
    
    # 查找 \begin{document} 之后的内容
    doc_idx = template_content.find(r'\begin{document}')
    if doc_idx != -1:
        # 寻找正文里第一个 \chapter 或者 \section 或者 \begin{problem} 或者 \begin{question} 作为切割点
        chap_idx = template_content.find(r'\chapter{', doc_idx)
        sec_idx = template_content.find(r'\section{', doc_idx)
        prob_idx = template_content.find(r'\begin{problem}', doc_idx)
        ques_idx = template_content.find(r'\begin{question}', doc_idx)
        
        candidates = [idx for idx in (chap_idx, sec_idx, prob_idx, ques_idx) if idx != -1]
        if candidates:
            insert_idx = min(candidates)
            end_idx = template_content.rfind(r'\end{document}')
            
            if end_idx != -1:
                # 头部内容保留（包括 \renewcommand{\mytitle}{...} 和所有前置的格式设置）
                pre_content = template_content[:insert_idx]
                # 尾部内容保留（\end{document}及以后）
                post_content = template_content[end_idx:]
                
                final_content = pre_content + generated_body + "\n\n" + post_content
                
                # 修改点：在年月目录下，再创建一个与试卷名相同的独立文件夹
                final_export_dir = os.path.join(export_dir, export_filename)
                ensure_dir(final_export_dir)
                
                output_file = _exam_output_tex_path(export_filename, export_dir)
                atomic_write_text(output_file, final_content, backup=os.path.exists(output_file))
                return output_file
            
    return None

def render_typesetting_workspace():
    st.subheader("🖨️ 试卷排版工作台")
    
    # 动态生成默认的输出文件名
    import datetime
    today = datetime.date.today()
    y_str = today.strftime("%Y")
    m_str = today.strftime("%m")
    d_str = today.strftime("%d")
    
    theme_name = st.session_state.get("exam_theme", "练习类模板")
    export_dir = os.path.join(BASE_DIR, "Test Paper Group", "导出文件", y_str, m_str)
    
    default_filename = _next_exam_export_filename(export_dir, theme_name, today=today)
    
    # 返回按钮与生成按钮栏
    c_back, c_name, c_gen = st.columns([1, 1.5, 1])
    with c_back:
        def go_back_to_selection():
            st.session_state["exam_mode_stage"] = "selection"
        st.button("⬅️ 返回继续选题", on_click=go_back_to_selection, use_container_width=True)
    with c_name:
        export_filename = st.text_input("输出文件名", value=default_filename, label_visibility="collapsed")
    with c_gen:
        if st.button("🖨️ 确认生成试卷", type="primary", use_container_width=True):
            if theme_name in ("练习类模板", "讲义类模板", "试卷类模板"):
                expected_output_path = _exam_output_tex_path(export_filename, export_dir)
                is_overwrite = os.path.exists(expected_output_path)
                output_path = generate_exam_paper(export_filename, export_dir, st.session_state["exam_blocks"], theme_name)
                if output_path:
                    st.success(f"试卷已成功生成至：{output_path}")
                    compile_result = _compile_exam_pdf(output_path)
                    if compile_result.get("ok"):
                        st.success(f"PDF 已自动编译完成：{compile_result.get('pdf_path')}")
                    else:
                        st.warning(compile_result.get("error", "PDF 编译失败。"))
                        if compile_result.get("log"):
                            with st.expander("查看 xelatex 编译日志"):
                                st.code(compile_result["log"])

                    if is_overwrite:
                        st.info("检测到本次为覆盖同名试卷，未重复增加题目组卷引用次数。")
                    else:
                        usage_result = _increment_exam_usage_counts(_question_paths_from_exam_blocks(st.session_state["exam_blocks"]))
                        if usage_result.get("updated", 0):
                            st.success(f"已更新 {usage_result['updated']} 道题目的组卷引用次数。")
                        if usage_result.get("skipped"):
                            st.caption("部分题目缺少完整元数据，未更新引用次数：" + "、".join(usage_result["skipped"][:5]))
                else:
                    st.error("生成失败，请检查模板文件是否存在或格式是否正确！")
            else:
                st.warning("暂不支持其他模板的生成，敬请期待！")
    
    st.markdown("---")
    
    st.subheader("📑 试卷结构与排版")
    
    # 计算当前试卷中有多少道题目（用于下拉菜单选位置）
    blocks = st.session_state["exam_blocks"]
    q_count = sum(1 for b in blocks if b["type"] == "question")
    
    # 构建插入位置选项
    # 例如: "第1题前", "第2题前", ..., "最后一题后"
    insert_positions = [f"第{i}题前" for i in range(1, q_count + 1)]
    insert_positions.append("最后一题后" if q_count > 0 else "列表最末尾")
    
    # 插入新章节/小节
    st.markdown("""
    <style>
    /* 移除表单的外边框和背景色 */
    div[data-testid="stForm"] {
        border: none !important;
        padding: 0 !important;
        background-color: transparent !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # 构建表单处理逻辑的辅助函数
    def _insert_block(blk_type, title, pos_str):
        new_block = {"id": str(uuid.uuid4()), "type": blk_type, "title": title}
        if pos_str in ("最后一题后", "列表最末尾"):
            st.session_state["exam_blocks"].append(new_block)
        else:
            target_q_num = int(pos_str.replace("第", "").replace("题前", ""))
            current_q = 0
            insert_idx = len(blocks)
            for idx, b in enumerate(blocks):
                if b["type"] == "question":
                    current_q += 1
                    if current_q == target_q_num:
                        insert_idx = idx
                        break
            st.session_state["exam_blocks"].insert(insert_idx, new_block)
            
    # 动态渲染根据不同模板决定是 2 层还是 3 层结构
    if theme_name == "讲义类模板":
        # 讲义类有 章、节、小节 三层
        c_label_0, c_input_0, c_pos_0, c_submit_0 = st.columns([1.5, 3.5, 1.5, 1.5])
        with c_label_0:
            st.markdown("<div style='padding-top:8px;'><b>📚 插入章</b></div>", unsafe_allow_html=True)
        with c_input_0:
            chap_title = st.text_input("文本内容", placeholder="例如：第一章 集合", label_visibility="collapsed", key="chap_title_input")
        with c_pos_0:
            chap_pos = st.selectbox("插入位置", insert_positions, index=0, label_visibility="collapsed", key="chap_pos")
        with c_submit_0:
            def on_chap_submit():
                t = st.session_state.get("chap_title_input", "")
                p = st.session_state.get("chap_pos", insert_positions[0])
                if t:
                    _insert_block("chapter", t, p)
                    st.session_state["chap_title_input"] = ""
            st.button("确认插入", key="chap_submit", on_click=on_chap_submit, use_container_width=True)

        # 节
        c_label_1, c_input_1, c_pos_1, c_submit_1 = st.columns([1.5, 3.5, 1.5, 1.5])
        with c_label_1:
            st.markdown("<div style='padding-top:8px; color: #58a6ff;'><b>🗂️ 插入节</b></div>", unsafe_allow_html=True)
        with c_input_1:
            sec_title = st.text_input("文本内容", placeholder="例如：第一节 集合的概念", label_visibility="collapsed", key="sec_title_input")
        with c_pos_1:
            sec_pos = st.selectbox("插入位置", insert_positions, index=0, label_visibility="collapsed", key="sec_pos")
        with c_submit_1:
            def on_sec_submit():
                t = st.session_state.get("sec_title_input", "")
                p = st.session_state.get("sec_pos", insert_positions[0])
                if t:
                    _insert_block("section", t, p)
                    st.session_state["sec_title_input"] = ""
            st.button("确认插入", key="sec_submit", on_click=on_sec_submit, use_container_width=True)
                    
        # 小节
        c_label_2, c_input_2, c_pos_2, c_submit_2 = st.columns([1.5, 3.5, 1.5, 1.5])
        with c_label_2:
            st.markdown("<div style='padding-top:8px; color: #8b949e;'><b>📝 插入小节</b></div>", unsafe_allow_html=True)
        with c_input_2:
            subsec_title = st.text_input("文本内容", placeholder="例如：考点一", label_visibility="collapsed", key="subsec_title_input")
        with c_pos_2:
            subsec_pos = st.selectbox("插入位置", insert_positions, index=0, label_visibility="collapsed", key="subsec_pos")
        with c_submit_2:
            def on_subsec_submit():
                t = st.session_state.get("subsec_title_input", "")
                p = st.session_state.get("subsec_pos", insert_positions[0])
                if t:
                    _insert_block("subsection", t, p)
                    st.session_state["subsec_title_input"] = ""
            st.button("确认插入", key="subsec_submit", on_click=on_subsec_submit, use_container_width=True)
            
    elif theme_name == "试卷类模板":
        # 试卷类模板具有四个固定的 section，提供默认内容和位置，并且只允许修改这些节，不再随意新增
        st.markdown("<div style='color: #8b949e; font-size: 0.9em; margin-bottom: 10px;'>💡 提示：试卷类模板提供四个固定的试卷题型模块，您可以直接点击下方按钮快速插入到对应位置。</div>", unsafe_allow_html=True)
        
        # 预设的四个节信息
        exam_presets = [
            {
                "label": "插入单选题节",
                "default_title": "%\n  选择题：本题共 8 小题，每小题 5 分，共 40 分。\n  在每小题给出的四个选项中，只有一项是符合题目要求的。\n",
                "default_pos_index": 0 # 第1题前
            },
            {
                "label": "插入多选题节",
                "default_title": "%\n  选择题：本题共 3 小题，每小题 6 分，共 18 分。\n  在每小题给出的选项中，有多项符合题目要求的。\n  全部选对的得 6 分，部分选择的得部分分，有选错的得 0 分。\n",
                "default_pos_index": min(8, len(insert_positions)-1) # 第9题前
            },
            {
                "label": "插入填空题节",
                "default_title": "填空题：本题共 3 小题，每小题 5 分，共 15 分。",
                "default_pos_index": min(11, len(insert_positions)-1) # 第12题前
            },
            {
                "label": "插入解答题节",
                "default_title": "解答题：本题共 5 小题，共 77 分。解答应写出文字说明、证明过程或者演算步骤。",
                "default_pos_index": min(14, len(insert_positions)-1) # 第15题前
            }
        ]
        
        for i, preset in enumerate(exam_presets):
            c_label, c_input, c_pos, c_submit = st.columns([1.5, 3.5, 1.5, 1.5])
            with c_label:
                st.markdown(f"<div style='padding-top:8px;'><b>🗂️ {preset['label']}</b></div>", unsafe_allow_html=True)
            with c_input:
                # 试卷模板的标题通常比较长，直接放入 content 中，把真正的 title 留空，或者将这段话当作 title
                # 按照用户的代码，这些其实是放在 \section{...} 里面的，所以还是算作 title
                sec_title = st.text_area("文本内容", value=preset["default_title"], height=68, label_visibility="collapsed", key=f"exam_sec_title_{i}")
            with c_pos:
                sec_pos = st.selectbox("插入位置", insert_positions, index=preset["default_pos_index"], label_visibility="collapsed", key=f"exam_sec_pos_{i}")
            with c_submit:
                def make_submit_callback(i_val):
                    def callback():
                        t = st.session_state.get(f"exam_sec_title_{i_val}", "")
                        p = st.session_state.get(f"exam_sec_pos_{i_val}", insert_positions[0])
                        if t:
                            _insert_block("section", t, p)
                    return callback
                
                # 垂直居中对齐
                st.markdown("<div style='padding-top:12px;'></div>", unsafe_allow_html=True)
                st.button("确认插入", key=f"exam_sec_submit_{i}", on_click=make_submit_callback(i), use_container_width=True)

    else:
        # 练习类及其他模板，仅保留 章节 和 小节
        c_label_1, c_input_1, c_pos_1, c_submit_1 = st.columns([1.5, 3.5, 1.5, 1.5])
        with c_label_1:
            st.markdown("<div style='padding-top:8px;'><b>🗂️ 插入章节</b></div>", unsafe_allow_html=True)
        with c_input_1:
            sec_title = st.text_input("文本内容", placeholder="例如：一、选择题", label_visibility="collapsed", key="sec_title_input")
        with c_pos_1:
            sec_pos = st.selectbox("插入位置", insert_positions, index=0, label_visibility="collapsed", key="sec_pos")
        with c_submit_1:
            def on_sec_submit():
                t = st.session_state.get("sec_title_input", "")
                p = st.session_state.get("sec_pos", insert_positions[0])
                if t:
                    _insert_block("section", t, p)
                    st.session_state["sec_title_input"] = ""
            st.button("确认插入", key="sec_submit", on_click=on_sec_submit, use_container_width=True)
                    
        c_label_2, c_input_2, c_pos_2, c_submit_2 = st.columns([1.5, 3.5, 1.5, 1.5])
        with c_label_2:
            st.markdown("<div style='padding-top:8px; color: #8b949e;'><b>📝 插入小节</b></div>", unsafe_allow_html=True)
        with c_input_2:
            subsec_title = st.text_input("文本内容", placeholder="例如：(一) 单选题", label_visibility="collapsed", key="subsec_title_input")
        with c_pos_2:
            subsec_pos = st.selectbox("插入位置", insert_positions, index=0, label_visibility="collapsed", key="subsec_pos")
        with c_submit_2:
            def on_subsec_submit():
                t = st.session_state.get("subsec_title_input", "")
                p = st.session_state.get("subsec_pos", insert_positions[0])
                if t:
                    _insert_block("subsection", t, p)
                    st.session_state["subsec_title_input"] = ""
            st.button("确认插入", key="subsec_submit", on_click=on_subsec_submit, use_container_width=True)
                    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # 遍历显示 Blocks (单列流式布局，改为左右两栏)
    blocks = st.session_state["exam_blocks"]
    q_counter = 1
    chap_counter = 0
    sec_counter = 0
    subsec_counter = 0
    
    for i, blk in enumerate(blocks):
        # 每一行分为左右两列：左侧显示标题和控制按钮，右侧显示渲染结果
        c_left, c_right = st.columns([3, 7], gap="large")
        
        with c_left:
            if blk["type"] == "chapter":
                chap_counter += 1
                sec_counter = 0
                subsec_counter = 0
                # 允许动态修改章节标题
                col_l, col_r = st.columns([1.5, 3.5])
                with col_l:
                    st.markdown(f"<div style='padding-top:8px; white-space:nowrap;'><b>📚 第{chap_counter}章标题</b></div>", unsafe_allow_html=True)
                with col_r:
                    # 修复性能问题：不将 widget 的返回值直接硬塞回 blk 中，除非它发生了改变
                    # 使用 on_change 回调或直接依赖 session_state 来存储值
                    new_val = st.text_input("章标题", value=blk['title'], key=f"blk_title_{blk['id']}", label_visibility="collapsed")
                    if new_val != blk['title']: blk['title'] = new_val
                new_c = st.text_area("内容源码", value=blk.get("content", ""), key=f"blk_content_{blk['id']}", placeholder="在此输入章说明源码（可选）", label_visibility="collapsed")
                if new_c != blk.get("content", ""): blk["content"] = new_c
            elif blk["type"] == "section":
                sec_counter += 1
                subsec_counter = 0
                # 允许动态修改章节标题
                col_l, col_r = st.columns([1.5, 3.5])
                with col_l:
                    if theme_name == "讲义类模板":
                        st.markdown(f"<div style='padding-top:8px; color: #58a6ff; white-space:nowrap;'><b>🗂️ 第{chap_counter}.{sec_counter}节标题</b></div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div style='padding-top:8px; white-space:nowrap;'><b>🗂️ 第{sec_counter}章标题</b></div>", unsafe_allow_html=True)
                with col_r:
                    new_val = st.text_input("节/章标题", value=blk['title'], key=f"blk_title_{blk['id']}", label_visibility="collapsed")
                    if new_val != blk['title']: blk['title'] = new_val
                new_c = st.text_area("内容源码", value=blk.get("content", ""), key=f"blk_content_{blk['id']}", placeholder="在此输入节/章说明源码（可选）", label_visibility="collapsed")
                if new_c != blk.get("content", ""): blk["content"] = new_c
            elif blk["type"] == "subsection":
                subsec_counter += 1
                # 允许动态修改小节标题
                col_l, col_r = st.columns([1.5, 3.5])
                with col_l:
                    if theme_name == "讲义类模板":
                        st.markdown(f"<div style='padding-top:8px; color: #8b949e; white-space:nowrap;'><b>📝 第{chap_counter}.{sec_counter}.{subsec_counter}小节标题</b></div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div style='padding-top:8px; color: #8b949e; white-space:nowrap;'><b>📝 第{sec_counter}.{subsec_counter}小节标题</b></div>", unsafe_allow_html=True)
                with col_r:
                    new_val = st.text_input("小节标题", value=blk['title'], key=f"blk_title_{blk['id']}", label_visibility="collapsed")
                    if new_val != blk['title']: blk['title'] = new_val
                new_c = st.text_area("内容源码", value=blk.get("content", ""), key=f"blk_content_{blk['id']}", placeholder="在此输入小节说明源码（可选）", label_visibility="collapsed")
                if new_c != blk.get("content", ""): blk["content"] = new_c
            else:
                name = os.path.basename(blk['path']).replace('.tex', '')
                st.markdown(f"<h5 style='color: #c9d1d9; margin-top: 0;'>📄 {name}</h5>", unsafe_allow_html=True)
                
            # 按钮栏放在标题下方
            c_up, c_down, c_del = st.columns(3)
            with c_up:
                if st.button("⬆️", key=f"blk_up_{blk['id']}", disabled=(i==0), help="上移", use_container_width=True):
                    blocks[i], blocks[i-1] = blocks[i-1], blocks[i]
                    st.rerun()
            with c_down:
                if st.button("⬇️", key=f"blk_down_{blk['id']}", disabled=(i==len(blocks)-1), help="下移", use_container_width=True):
                    blocks[i], blocks[i+1] = blocks[i+1], blocks[i]
                    st.rerun()
            with c_del:
                if st.button("❌", key=f"blk_del_{blk['id']}", help="移除", use_container_width=True):
                    removed = blocks.pop(i)
                    if removed["type"] == "question" and removed["path"] in st.session_state["exam_selected_qs"]:
                        st.session_state["exam_selected_qs"].remove(removed["path"])
                    st.rerun()
                    
        with c_right:
            # 右侧渲染内容区
            if blk["type"] == "chapter":
                st.markdown(f"<h2 style='color: #d2a8ff; margin: 0;'>{blk['title']}</h2>", unsafe_allow_html=True)
                if blk.get("content"):
                    st.markdown(f"<div style='margin-top: 10px;'>{blk['content']}</div>", unsafe_allow_html=True)
            elif blk["type"] == "section":
                st.markdown(f"<h3 style='color: #58a6ff; margin: 0;'>{blk['title']}</h3>", unsafe_allow_html=True)
                if blk.get("content"):
                    st.markdown(f"<div style='margin-top: 10px;'>{blk['content']}</div>", unsafe_allow_html=True)
            elif blk["type"] == "subsection":
                st.markdown(f"<h4 style='color: #8b949e; border-left: 4px solid #8b949e; padding-left: 10px; margin: 0;'>{blk['title']}</h4>", unsafe_allow_html=True)
                if blk.get("content"):
                    st.markdown(f"<div style='margin-top: 10px;'>{blk['content']}</div>", unsafe_allow_html=True)
            else:
                if os.path.exists(blk["path"]):
                    with open(blk["path"], "r", encoding="utf-8") as f:
                        content = f.read()
                    try:
                        header_fields = extract_problem_header_fields(content) or {}
                        header_year = header_fields.get("year", "")
                        header_paper = header_fields.get("paper", "")
                        header_number = header_fields.get("number", "")
                        if header_year and header_paper and header_number:
                            workbench_title = f"\u3010{header_year} {header_paper}\uff0c{header_number}\u3011"
                        else:
                            workbench_title = format_question_title(os.path.basename(blk["path"]))
                        st.markdown(
                            f'<div style="font-weight:700; margin-bottom:0.45rem;">{q_counter}. {html.escape(workbench_title)}</div>',
                            unsafe_allow_html=True,
                        )
                        md_content = latex_to_markdown(content, show_title=False)
                        st.markdown(md_content, unsafe_allow_html=True)
                        q_counter += 1
                    except Exception as e:
                        st.error(f"渲染出错: {e}")
                else:
                    st.error(f"文件不存在: {blk['path']}")
                    
        st.divider()

# ================= 题目查重与操作日志 =================
def render_duplicate_check_page():
    st.header("题目查重")
    st.caption("按题干内容检查完全重复和高度相似题目。查重只提供核对建议，不会自动删除任何题目。")

    c_threshold, c_limit = st.columns([1, 1], gap="small")
    with c_threshold:
        threshold = st.slider("相似度阈值", min_value=0.80, max_value=0.99, value=0.88, step=0.01)
    with c_limit:
        max_pairs = st.number_input("最多显示组合数", min_value=20, max_value=500, value=200, step=20)

    if st.button("开始扫描题库", key="duplicate_scan_start", type="primary", use_container_width=True):
        with st.spinner("正在扫描题目内容，请稍候..."):
            results = scan_duplicate_pairs(
                rows=_csv_index_cached(_csv_index_cache_token()),
                similarity_threshold=threshold,
                max_pairs=int(max_pairs),
            )
        st.session_state["duplicate_scan_results"] = results
        st.session_state["duplicate_scan_threshold"] = threshold
        record_operation(
            "scan_duplicates",
            details=f"threshold={threshold:.2f}, pairs={len(results)}",
        )

    results = st.session_state.get("duplicate_scan_results") or []
    if not results:
        st.info("暂未发现重复组合，或尚未开始扫描。")
        return

    exact_count = sum(1 for item in results if item.get("kind") == "exact")
    similar_count = len(results) - exact_count
    st.success(f"共发现 {len(results)} 组候选：完全重复 {exact_count} 组，高度相似 {similar_count} 组。")

    for index, pair in enumerate(results, start=1):
        left = pair.get("left") or {}
        right = pair.get("right") or {}
        kind_label = "完全重复" if pair.get("kind") == "exact" else "高度相似"
        score_text = f"{float(pair.get('score', 0)) * 100:.1f}%"
        title = f"{index}. {kind_label} · {score_text}"
        with st.expander(title, expanded=index == 1):
            c_left, c_right = st.columns(2, gap="large")
            for container, item in ((c_left, left), (c_right, right)):
                with container:
                    st.markdown(f"**{html.escape(item.get('name') or '未命名题目')}**", unsafe_allow_html=True)
                    st.caption(
                        f"ID：{item.get('question_id') or '无'} · "
                        f"板块：{item.get('subject') or '未分类'}"
                    )
                    st.code(item.get("relative_path") or item.get("path") or "路径不可用", language="text")
                    path = item.get("path") or ""
                    if path and os.path.isfile(path):
                        try:
                            with open(path, "r", encoding="utf-8") as question_file:
                                render_question_preview(question_file.read())
                        except Exception as exc:
                            st.warning(f"题目预览失败：{exc}")
                    else:
                        st.warning("题目文件不存在，建议先重建题库索引。")

    st.caption("处理建议：保留信息更完整、来源更可靠的题目；确认后再通过现有删除/编辑功能处理另一份。")


def render_operation_log_panel():
    with st.expander("最近操作日志", expanded=False):
        operations = read_recent_operations(limit=100)
        if not operations:
            st.info("暂时没有题目操作日志。")
            return

        action_labels = {
            "create_question": "创建题目",
            "update_question_content": "修改题目内容",
            "update_question_meta": "修改题目属性",
            "rename_question": "重命名题目",
            "delete_question": "删除题目",
            "restore_question": "恢复题目",
            "permanently_delete_backup": "永久删除备份",
            "scan_duplicates": "题目查重",
            "rebuild_csv_index": "重建题库索引",
            "update_chapter_index": "更新章节索引",
            "legacy_tex_migration_dry_run": "旧 TeX 迁移预览",
            "legacy_tex_migration_promote_check": "SQLite 提升检查",
            "legacy_tex_migration_promote_apply": "SQLite 正式提升",
            "schema_migration_check": "数据库升级检查",
            "schema_migration_apply": "应用数据库升级",
            "local_update_plan": "本地更新预览",
            "local_update_apply": "执行本地更新",
            "local_data_bundle_export": "导出本地数据包",
            "local_data_bundle_restore_check": "检查数据包恢复",
            "local_data_bundle_restore_apply": "恢复本地数据包",
        }
        display_rows = []
        for operation in operations:
            display_rows.append({
                "时间": operation.get("created_at", ""),
                "操作": action_labels.get(operation.get("action"), operation.get("action", "")),
                "状态": operation.get("status", ""),
                "题目 ID": operation.get("question_id", ""),
                "路径": operation.get("path", ""),
                "说明": operation.get("details", ""),
            })
        st.dataframe(display_rows, use_container_width=True, hide_index=True)


def _legacy_migration_parse_stdout(output: str) -> dict:
    parsed = {}
    for line in (output or "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def _legacy_migration_abs_path(path: str) -> str:
    cleaned = str(path or "").strip()
    if not cleaned:
        return ""
    if os.path.isabs(cleaned):
        return os.path.abspath(cleaned)
    return os.path.abspath(os.path.join(BASE_DIR, cleaned))


def _legacy_migration_existing_preview_dbs() -> list:
    data_dir = os.path.join(BASE_DIR, "data")
    if not os.path.isdir(data_dir):
        return []

    previews = []
    for name in os.listdir(data_dir):
        if not (name.startswith("mathcyclus_preview") and name.endswith(".sqlite3")):
            continue
        full_path = os.path.join(data_dir, name)
        if os.path.isfile(full_path):
            previews.append(full_path)
    previews.sort(key=lambda item: os.path.getmtime(item), reverse=True)
    return previews


def _legacy_migration_read_report(path: str, limit: int = 12000) -> str:
    abs_path = _legacy_migration_abs_path(path)
    if not abs_path or not os.path.exists(abs_path):
        return ""
    with open(abs_path, "r", encoding="utf-8", errors="replace") as report_file:
        content = report_file.read(limit + 1)
    if len(content) > limit:
        return content[:limit] + "\n\n……报告较长，已截断预览。请打开完整报告查看。"
    return content


def _legacy_migration_run_command(command: list, timeout: int = 600) -> dict:
    try:
        completed = subprocess.run(
            command,
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
            "command": subprocess.list2cmdline(command),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": exc.stdout or "",
            "stderr": "执行超时：旧 TeX 题库较大时请先设置 limit 小样本检查。",
            "command": subprocess.list2cmdline(command),
        }
    except Exception as exc:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
            "command": subprocess.list2cmdline(command),
        }


def _maintenance_script_path(script_name: str) -> str:
    return os.path.join(BASE_DIR, "scripts", script_name)


def _maintenance_run_json_command(command: list, timeout: int = 900) -> dict:
    result = _legacy_migration_run_command(command, timeout=timeout)
    parsed_json = None
    stdout = result.get("stdout") or ""
    if stdout.strip():
        try:
            parsed_json = json.loads(stdout)
        except json.JSONDecodeError:
            parsed_json = None
    result["json"] = parsed_json
    result["parsed"] = _legacy_migration_parse_stdout(stdout)
    return result


def _maintenance_git_snapshot() -> dict:
    def _git(args: list, timeout: int = 20) -> str:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=BASE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            return (completed.stdout or "").strip()
        except Exception:
            return ""

    status_lines = [line for line in _git(["status", "--short"]).splitlines() if line.strip()]
    return {
        "branch": _git(["branch", "--show-current"]) or "未检测到",
        "head": _git(["rev-parse", "--short", "HEAD"]) or "未检测到",
        "upstream": _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]) or "未设置",
        "dirty_count": len(status_lines),
        "dirty_preview": status_lines[:8],
    }


def _maintenance_status_text(status: str) -> str:
    status = str(status or "").lower()
    if status in {"ok", "pass"}:
        return "正常"
    if status in {"warning", "pending"}:
        return "需确认"
    if status in {"blocked", "missing_database", "failed", "fail"}:
        return "阻塞"
    return status or "未知"


def _maintenance_render_summary_panel(title: str, items: list[tuple[str, str]], tone: str = "neutral"):
    tone_class = {
        "ok": "mc-maintenance-panel-ok",
        "warning": "mc-maintenance-panel-warning",
        "blocked": "mc-maintenance-panel-blocked",
    }.get(tone, "mc-maintenance-panel-neutral")
    rows = "".join(
        f"""
        <div class="mc-maintenance-kv">
            <span>{html.escape(str(label))}</span>
            <strong>{html.escape(str(value))}</strong>
        </div>
        """
        for label, value in items
    )
    st.markdown(
        f"""
        <div class="mc-maintenance-panel {tone_class}">
            <div class="mc-maintenance-panel-title">{html.escape(title)}</div>
            <div class="mc-maintenance-kv-grid">{rows}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _maintenance_render_command_result(result: dict, *, title: str, expanded: bool = False):
    status = "ok" if result.get("ok") else "blocked"
    parsed_json = result.get("json") or {}
    parsed = result.get("parsed") or {}
    result_status = parsed_json.get("status") or parsed.get("status") or status
    if result.get("ok") and str(result_status).lower() not in {"blocked", "failed", "fail", "missing_database"}:
        st.success(f"{title}完成：{_maintenance_status_text(result_status)}")
    else:
        st.error(f"{title}失败或被阻断：{_maintenance_status_text(result_status)}")

    report_path = parsed_json.get("report") or parsed.get("report") or ""
    json_path = parsed_json.get("json") or parsed.get("json") or ""
    if report_path or json_path:
        st.caption(
            "报告："
            + (f"`{report_path}`" if report_path else "无")
            + (" · JSON：" + f"`{json_path}`" if json_path else "")
        )

    with st.expander("查看命令输出", expanded=expanded or not result.get("ok")):
        st.code(result.get("command") or "", language="powershell")
        if result.get("stdout"):
            st.code(result["stdout"], language="text")
        if result.get("stderr"):
            st.code(result["stderr"], language="text")


def _maintenance_schema_status(force: bool = False) -> dict:
    if force or "local_maintenance_schema_status" not in st.session_state:
        script = _maintenance_script_path("migrate_schema.py")
        st.session_state["local_maintenance_schema_status"] = _maintenance_run_json_command(
            [sys.executable, script, "--status-only", "--json"],
            timeout=120,
        )
    return st.session_state.get("local_maintenance_schema_status") or {}


def render_local_maintenance_tool():
    st.markdown("### 🧰 本地维护、升级与迁移")
    st.caption("给 GitHub 源码版和后续打包版使用：检查更新、升级 SQLite schema、备份/恢复本地数据。默认不删除数据。")

    st.markdown(
        """
        <style>
        .mc-maintenance-note {
            border: 1px solid rgba(109, 40, 217, 0.12);
            border-radius: 14px;
            padding: 14px 16px;
            background: rgba(255, 255, 255, 0.76);
            color: #383445;
            line-height: 1.7;
            margin: 4px 0 16px;
        }
        .mc-maintenance-panel {
            border-radius: 16px;
            padding: 14px 16px;
            margin: 8px 0 14px;
            border: 1px solid rgba(62, 53, 97, 0.12);
            background: rgba(255, 255, 255, 0.82);
        }
        .mc-maintenance-panel-ok {
            background: rgba(240, 253, 244, 0.82);
            border-color: rgba(34, 197, 94, 0.18);
        }
        .mc-maintenance-panel-warning {
            background: rgba(255, 251, 235, 0.84);
            border-color: rgba(245, 158, 11, 0.2);
        }
        .mc-maintenance-panel-blocked {
            background: rgba(254, 242, 242, 0.84);
            border-color: rgba(239, 68, 68, 0.2);
        }
        .mc-maintenance-panel-title {
            font-weight: 800;
            color: #2f2552;
            margin-bottom: 10px;
            letter-spacing: -0.01em;
        }
        .mc-maintenance-kv-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 8px 14px;
        }
        .mc-maintenance-kv {
            min-width: 0;
            display: flex;
            justify-content: space-between;
            gap: 12px;
            color: #6b6680;
            font-size: 13px;
        }
        .mc-maintenance-kv strong {
            color: #27213f;
            font-size: 13px;
            text-align: right;
            overflow-wrap: anywhere;
        }
        @media (max-width: 900px) {
            .mc-maintenance-kv-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        <div class="mc-maintenance-note">
            <strong>安全边界：</strong>本页的检查按钮默认只读或 dry-run；真正更新代码、应用数据库迁移、恢复数据包，都需要输入确认文本。
            本地 <code>data/</code>、<code>assets/questions/</code>、<code>reports/</code>、<code>exports/</code> 仍不上传 GitHub。
        </div>
        """,
        unsafe_allow_html=True,
    )

    from services.local_preferences_service import (
        BROWSE_SOURCE_LABELS,
        EXAM_SOURCE_LABELS,
        QUESTION_SOURCE_LEGACY,
        QUESTION_SOURCE_SQLITE,
        load_local_preferences,
        save_local_preferences,
        source_from_label,
        source_label,
    )

    preferences = load_local_preferences()
    with st.expander("本地使用偏好", expanded=False):
        st.caption("只写入本机 `data/local_preferences.json`，不提交 GitHub；用于控制打开页面时默认使用 SQLite 还是旧 TeX。")
        browse_labels = [
            BROWSE_SOURCE_LABELS[QUESTION_SOURCE_SQLITE],
            BROWSE_SOURCE_LABELS[QUESTION_SOURCE_LEGACY],
        ]
        exam_labels = [
            EXAM_SOURCE_LABELS[QUESTION_SOURCE_SQLITE],
            EXAM_SOURCE_LABELS[QUESTION_SOURCE_LEGACY],
        ]
        pref_col1, pref_col2, pref_col3 = st.columns([1.25, 1.25, 0.75], gap="small", vertical_alignment="bottom")
        with pref_col1:
            browse_label = source_label(preferences.get("browse_default_source"), surface="browse")
            browse_default_label = st.selectbox(
                "全局浏览默认来源",
                browse_labels,
                index=browse_labels.index(browse_label) if browse_label in browse_labels else 0,
                key="local_pref_browse_default_source",
            )
        with pref_col2:
            exam_label = source_label(preferences.get("exam_default_source"), surface="exam")
            exam_default_label = st.selectbox(
                "组卷选题默认来源",
                exam_labels,
                index=exam_labels.index(exam_label) if exam_label in exam_labels else 0,
                key="local_pref_exam_default_source",
            )
        with pref_col3:
            if st.button("保存偏好", key="local_pref_save", type="primary", use_container_width=True):
                saved_preferences = save_local_preferences(
                    {
                        "browse_default_source": source_from_label(browse_default_label),
                        "exam_default_source": source_from_label(exam_default_label),
                    }
                )
                st.session_state["exam_selection_source"] = source_label(
                    saved_preferences.get("exam_default_source"),
                    surface="exam",
                )
                st.session_state["exam_selection_source_bootstrapped_v3"] = True
                st.success("本地使用偏好已保存。")

    git_info = _maintenance_git_snapshot()
    schema_result = _maintenance_schema_status()
    schema_report = schema_result.get("json") or {}
    schema_tone = "ok"
    if schema_report.get("pending_count"):
        schema_tone = "warning"
    if not schema_result.get("ok") or str(schema_report.get("status", "")).lower() in {"blocked", "missing_database"}:
        schema_tone = "blocked"
    git_tone = "warning" if git_info["dirty_count"] else "ok"

    overview_left, overview_right = st.columns([1, 1], gap="medium")
    with overview_left:
        _maintenance_render_summary_panel(
            "Git 状态",
            [
                ("当前分支", git_info["branch"]),
                ("提交", git_info["head"]),
                ("上游", git_info["upstream"]),
                ("未提交项", str(git_info["dirty_count"])),
            ],
            tone=git_tone,
        )
        if git_info["dirty_preview"]:
            with st.expander("查看未提交项样例", expanded=False):
                st.code("\n".join(git_info["dirty_preview"]), language="text")
    with overview_right:
        _maintenance_render_summary_panel(
            "SQLite Schema",
            [
                ("状态", _maintenance_status_text(schema_report.get("status") or "")),
                ("当前版本", str(schema_report.get("current_version", "未知"))),
                ("目标版本", str(schema_report.get("target_version", "未知"))),
                ("待执行迁移", str(schema_report.get("pending_count", "未知"))),
            ],
            tone=schema_tone,
        )

    st.markdown("#### 数据库升级")
    c_schema_1, c_schema_2, c_schema_3 = st.columns([1, 1, 1], gap="small")
    migrate_script = _maintenance_script_path("migrate_schema.py")
    with c_schema_1:
        if st.button("检查数据库版本", key="btn_maintenance_schema_status", use_container_width=True):
            result = _maintenance_schema_status(force=True)
            record_operation("schema_migration_check", details="migrate_schema --status-only")
            _maintenance_render_command_result(result, title="数据库版本检查")
    with c_schema_2:
        if st.button("预览待执行迁移", key="btn_maintenance_schema_dry_run", use_container_width=True):
            result = _maintenance_run_json_command([sys.executable, migrate_script, "--json"], timeout=180)
            st.session_state["local_maintenance_schema_preview"] = result
            record_operation("schema_migration_check", details="migrate_schema dry-run")
    with c_schema_3:
        confirm_schema = st.text_input(
            "输入 APPLY_SCHEMA_MIGRATION 后应用",
            key="local_maintenance_confirm_schema",
            placeholder="APPLY_SCHEMA_MIGRATION",
        )
        if st.button(
            "应用数据库升级",
            key="btn_maintenance_schema_apply",
            type="primary",
            disabled=confirm_schema.strip() != "APPLY_SCHEMA_MIGRATION",
            use_container_width=True,
        ):
            result = _maintenance_run_json_command(
                [sys.executable, migrate_script, "--apply", "--json"],
                timeout=300,
            )
            st.session_state["local_maintenance_schema_apply"] = result
            st.session_state.pop("local_maintenance_schema_status", None)
            record_operation("schema_migration_apply", details="migrate_schema --apply")

    for key, title in (
        ("local_maintenance_schema_preview", "最近一次迁移预览"),
        ("local_maintenance_schema_apply", "最近一次数据库升级"),
    ):
        if st.session_state.get(key):
            _maintenance_render_command_result(st.session_state[key], title=title, expanded=False)

    st.divider()
    st.markdown("#### 程序更新")
    st.caption("适合未来 GitHub 源码版用户：先 dry-run 看计划，再决定是否执行。执行 `git pull` 时会拒绝脏工作区，避免覆盖本地改动。")
    update_script = _maintenance_script_path("update_local_installation.py")
    update_options = st.columns([1, 1, 1, 1], gap="small")
    with update_options[0]:
        update_pull = st.checkbox("从 GitHub 拉取", value=True, key="local_maintenance_update_pull")
    with update_options[1]:
        update_deps = st.checkbox("更新依赖", value=True, key="local_maintenance_update_deps")
    with update_options[2]:
        update_checks = st.checkbox("运行快速检查", value=True, key="local_maintenance_update_checks")
    with update_options[3]:
        update_allow_dirty = st.checkbox("允许脏工作区 pull", value=False, key="local_maintenance_update_allow_dirty")

    update_command_base = [sys.executable, update_script]
    if update_pull:
        update_command_base.append("--pull")
    if update_deps:
        update_command_base.append("--install-deps")
    if update_checks:
        update_command_base.append("--run-checks")
    if update_allow_dirty:
        update_command_base.append("--allow-dirty")

    c_update_1, c_update_2 = st.columns([1, 1], gap="small")
    with c_update_1:
        if st.button("生成更新计划（dry-run）", key="btn_maintenance_update_plan", use_container_width=True):
            result = _maintenance_run_json_command(
                [*update_command_base, "--write-report", "--json"],
                timeout=600,
            )
            st.session_state["local_maintenance_update_plan"] = result
            record_operation("local_update_plan", details=result.get("command", ""))
    with c_update_2:
        confirm_update = st.text_input(
            "输入 APPLY_LOCAL_UPDATE 后执行",
            key="local_maintenance_confirm_update",
            placeholder="APPLY_LOCAL_UPDATE",
        )
        if st.button(
            "执行本地升级",
            key="btn_maintenance_update_apply",
            type="primary",
            disabled=confirm_update.strip() != "APPLY_LOCAL_UPDATE",
            use_container_width=True,
        ):
            result = _maintenance_run_json_command(
                [*update_command_base, "--apply", "--json"],
                timeout=1800,
            )
            st.session_state["local_maintenance_update_apply"] = result
            record_operation("local_update_apply", details=result.get("command", ""))

    for key, title in (
        ("local_maintenance_update_plan", "最近一次更新计划"),
        ("local_maintenance_update_apply", "最近一次本地升级"),
    ):
        if st.session_state.get(key):
            _maintenance_render_command_result(st.session_state[key], title=title, expanded=False)

    st.divider()
    st.markdown("#### 本地数据迁移包")
    st.caption("用于换电脑或备份个人数据。默认包含 SQLite 和题目图片；旧 TeX、reports、exports 需要手动勾选。")
    bundle_script = _maintenance_script_path("local_data_bundle.py")
    bundle_options = st.columns([1, 1, 1], gap="small")
    with bundle_options[0]:
        include_legacy_tex = st.checkbox("包含旧 TeX 题源", value=False, key="local_maintenance_bundle_legacy")
    with bundle_options[1]:
        include_reports = st.checkbox("包含 reports", value=False, key="local_maintenance_bundle_reports")
    with bundle_options[2]:
        include_exports = st.checkbox("包含 exports", value=False, key="local_maintenance_bundle_exports")

    bundle_command_base = [sys.executable, bundle_script, "export"]
    if include_legacy_tex:
        bundle_command_base.append("--include-legacy-tex")
    if include_reports:
        bundle_command_base.append("--include-reports")
    if include_exports:
        bundle_command_base.append("--include-exports")

    c_bundle_1, c_bundle_2 = st.columns([1, 1], gap="small")
    with c_bundle_1:
        if st.button("预览备份范围", key="btn_maintenance_bundle_preview", use_container_width=True):
            result = _maintenance_run_json_command([*bundle_command_base, "--dry-run", "--json"], timeout=600)
            st.session_state["local_maintenance_bundle_preview"] = result
    with c_bundle_2:
        if st.button("导出本地数据包", key="btn_maintenance_bundle_export", type="primary", use_container_width=True):
            result = _maintenance_run_json_command([*bundle_command_base, "--json"], timeout=1800)
            st.session_state["local_maintenance_bundle_export"] = result
            record_operation("local_data_bundle_export", details=result.get("command", ""))

    for key, title in (
        ("local_maintenance_bundle_preview", "最近一次备份范围预览"),
        ("local_maintenance_bundle_export", "最近一次数据包导出"),
    ):
        if st.session_state.get(key):
            _maintenance_render_command_result(st.session_state[key], title=title, expanded=False)

    with st.expander("检查或恢复已有迁移包", expanded=False):
        bundle_path = st.text_input("迁移包 zip 路径", key="local_maintenance_bundle_path")
        restore_overwrite = st.checkbox("恢复时允许覆盖已有文件", value=False, key="local_maintenance_restore_overwrite")
        restore_cols = st.columns([1, 1, 1], gap="small")
        with restore_cols[0]:
            if st.button("检查迁移包", key="btn_maintenance_bundle_inspect", disabled=not bundle_path.strip(), use_container_width=True):
                result = _maintenance_run_json_command(
                    [sys.executable, bundle_script, "inspect", bundle_path.strip(), "--json"],
                    timeout=300,
                )
                st.session_state["local_maintenance_bundle_inspect"] = result
        with restore_cols[1]:
            if st.button("恢复预览（dry-run）", key="btn_maintenance_bundle_restore_preview", disabled=not bundle_path.strip(), use_container_width=True):
                command = [sys.executable, bundle_script, "restore", bundle_path.strip(), "--json"]
                if restore_overwrite:
                    command.append("--overwrite")
                result = _maintenance_run_json_command(command, timeout=600)
                st.session_state["local_maintenance_bundle_restore_preview"] = result
                record_operation("local_data_bundle_restore_check", details=result.get("command", ""))
        with restore_cols[2]:
            confirm_restore = st.text_input(
                "输入 RESTORE_LOCAL_BUNDLE 后恢复",
                key="local_maintenance_confirm_restore",
                placeholder="RESTORE_LOCAL_BUNDLE",
            )
            if st.button(
                "执行恢复",
                key="btn_maintenance_bundle_restore_apply",
                type="primary",
                disabled=not bundle_path.strip() or confirm_restore.strip() != "RESTORE_LOCAL_BUNDLE",
                use_container_width=True,
            ):
                command = [sys.executable, bundle_script, "restore", bundle_path.strip(), "--apply", "--json"]
                if restore_overwrite:
                    command.append("--overwrite")
                result = _maintenance_run_json_command(command, timeout=1800)
                st.session_state["local_maintenance_bundle_restore_apply"] = result
                record_operation("local_data_bundle_restore_apply", details=result.get("command", ""))

        for key, title in (
            ("local_maintenance_bundle_inspect", "最近一次迁移包检查"),
            ("local_maintenance_bundle_restore_preview", "最近一次恢复预览"),
            ("local_maintenance_bundle_restore_apply", "最近一次恢复执行"),
        ):
            if st.session_state.get(key):
                _maintenance_render_command_result(st.session_state[key], title=title, expanded=False)


def render_legacy_tex_migration_tool():
    st.markdown("### 🧱 旧 TeX 题库迁移到 SQLite")
    st.caption("用于早期本地 TeX 题库存储方案升级。当前页面只做预览迁移和提升检查，不直接覆盖正式数据库。")

    st.markdown(
        """
        <style>
        .legacy-migration-note {
            border: 1px solid rgba(109, 40, 217, 0.14);
            border-radius: 14px;
            padding: 14px 16px;
            background: rgba(255, 255, 255, 0.78);
            color: #3f4150;
            line-height: 1.65;
            margin: 4px 0 14px 0;
        }
        .legacy-migration-note strong {
            color: #342255;
        }
        .legacy-migration-result {
            border: 1px solid rgba(0, 122, 255, 0.16);
            border-radius: 12px;
            padding: 12px 14px;
            background: rgba(237, 246, 255, 0.78);
            margin: 10px 0;
        }
        .legacy-migration-result code {
            color: #2f2360;
            word-break: break-all;
        }
        </style>
        <div class="legacy-migration-note">
            <strong>安全边界：</strong>第一步只生成 <code>data/mathcyclus_preview_*.sqlite3</code> 和
            <code>reports/tex_to_db_dry_run_*.md</code>，不会修改旧 <code>.tex</code>，也不会写入正式
            <code>data/mathcyclus.sqlite3</code>。
        </div>
        """,
        unsafe_allow_html=True,
    )

    migrate_script = os.path.join(BASE_DIR, "scripts", "migrate_tex_to_db_dry_run.py")
    promote_script = os.path.join(BASE_DIR, "scripts", "promote_preview_to_database.py")

    st.session_state.setdefault("legacy_migration_root", "chapters")
    st.session_state.setdefault("legacy_migration_stamp", datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    st.session_state.setdefault("legacy_migration_limit", 0)
    st.session_state.setdefault("legacy_migration_promote_stamp", datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))

    root_col, limit_col, stamp_col = st.columns([2.2, 0.8, 1.2])
    with root_col:
        source_root = st.text_input(
            "旧 TeX 题库目录",
            key="legacy_migration_root",
            help="默认读取当前项目的 chapters。也可以填写另一个旧版本题库的 chapters 目录。",
        )
    with limit_col:
        limit = st.number_input(
            "最多迁移",
            min_value=0,
            max_value=20000,
            step=20,
            key="legacy_migration_limit",
            help="0 表示全量；排查格式问题时建议先填 20 或 100。",
        )
    with stamp_col:
        stamp = st.text_input("输出标记", key="legacy_migration_stamp")

    source_abs = _legacy_migration_abs_path(source_root)
    if not os.path.exists(migrate_script):
        st.error("找不到迁移脚本：scripts/migrate_tex_to_db_dry_run.py")
    elif not source_abs or not os.path.isdir(source_abs):
        st.warning("请填写有效的旧 TeX 题库目录。")
    else:
        st.caption(f"将读取：{_db_preview_relative_path(source_abs)}")

    dry_run_disabled = not os.path.exists(migrate_script) or not source_abs or not os.path.isdir(source_abs)
    if st.button("生成 SQLite 预览库（安全 dry-run）", type="primary", disabled=dry_run_disabled, use_container_width=True):
        command = [sys.executable, migrate_script, "--root", source_root, "--stamp", stamp.strip() or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")]
        if int(limit or 0) > 0:
            command.extend(["--limit", str(int(limit))])
        with st.spinner("正在扫描旧 TeX 题库并生成 SQLite 预览库..."):
            result = _legacy_migration_run_command(command)
        st.session_state["legacy_migration_last_run"] = result
        if result["ok"]:
            record_operation("legacy_tex_migration_dry_run", details=result["command"])
            st.success("预览迁移完成。请先检查报告，再决定是否进入正式库提升流程。")
        else:
            st.error("预览迁移失败。请根据 stderr 修复旧 TeX 格式或路径问题。")

    last_run = st.session_state.get("legacy_migration_last_run")
    if last_run:
        parsed = _legacy_migration_parse_stdout(last_run.get("stdout", ""))
        if parsed:
            q_col, eq_col, db_col = st.columns([0.8, 0.8, 2.4])
            q_col.metric("预览题目", parsed.get("questions", "0"))
            eq_col.metric("疑似同题", parsed.get("equivalence_candidates", "0"))
            db_col.markdown(
                f"""
                <div class="legacy-migration-result">
                    预览库：<code>{html.escape(parsed.get("database", ""))}</code><br>
                    报告：<code>{html.escape(parsed.get("report", ""))}</code>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with st.expander("查看脚本输出", expanded=not last_run.get("ok")):
            st.code(last_run.get("command", ""), language="powershell")
            if last_run.get("stdout"):
                st.code(last_run["stdout"], language="text")
            if last_run.get("stderr"):
                st.code(last_run["stderr"], language="text")
        report_preview = _legacy_migration_read_report(parsed.get("report", "") if parsed else "")
        if report_preview:
            with st.expander("预览迁移报告", expanded=False):
                st.code(report_preview, language="markdown")

    st.divider()
    st.markdown("#### 提升检查（仍然不写正式库）")
    st.caption("这一步检查某个预览库如果提升为正式库，会产生哪些表级差异、阻塞项和 warning。")

    preview_dbs = _legacy_migration_existing_preview_dbs()
    preview_options = preview_dbs or [""]
    selected_preview = st.selectbox(
        "选择预览库",
        options=preview_options,
        format_func=lambda value: _db_preview_relative_path(value) if value else "暂无预览库，请先生成 dry-run",
        key="legacy_migration_preview_db_select",
    )
    manual_preview = st.text_input("手动预览库路径（可选）", key="legacy_migration_manual_preview_db")
    preview_source = manual_preview.strip() or selected_preview

    promote_col_1, promote_col_2 = st.columns([1, 1])
    with promote_col_1:
        promote_stamp = st.text_input("提升检查标记", key="legacy_migration_promote_stamp")
    with promote_col_2:
        sample_limit = st.number_input("差异样例上限", min_value=10, max_value=500, value=50, step=10, key="legacy_migration_sample_limit")

    preview_abs = _legacy_migration_abs_path(preview_source)
    promote_disabled = (
        not os.path.exists(promote_script)
        or not preview_source
        or not os.path.isfile(preview_abs)
    )
    if st.button("生成提升检查报告（dry-run）", disabled=promote_disabled, use_container_width=True):
        command = [
            sys.executable,
            promote_script,
            "--source-db",
            preview_source,
            "--stamp",
            promote_stamp.strip() or datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
            "--sample-limit",
            str(int(sample_limit)),
        ]
        with st.spinner("正在检查预览库提升为正式库的差异..."):
            result = _legacy_migration_run_command(command)
        st.session_state["legacy_migration_last_promote_check"] = result
        if result["ok"]:
            record_operation("legacy_tex_migration_promote_check", details=result["command"])
            st.success("提升检查报告已生成；当前仍未写入正式数据库。")
        else:
            st.error("提升检查失败。请确认预览库存在且结构完整。")

    last_promote_check = st.session_state.get("legacy_migration_last_promote_check")
    if last_promote_check:
        parsed = _legacy_migration_parse_stdout(last_promote_check.get("stdout", ""))
        with st.expander("查看提升检查输出", expanded=not last_promote_check.get("ok")):
            st.code(last_promote_check.get("command", ""), language="powershell")
            if last_promote_check.get("stdout"):
                st.code(last_promote_check["stdout"], language="text")
            if last_promote_check.get("stderr"):
                st.code(last_promote_check["stderr"], language="text")
        report_preview = _legacy_migration_read_report(parsed.get("report", "") if parsed else "")
        if report_preview:
            with st.expander("预览提升检查报告", expanded=False):
                st.code(report_preview, language="markdown")

    st.divider()
    st.markdown("#### 正式提升到 SQLite（强确认）")
    st.caption(
        "确认预览库和提升检查报告无问题后，可以在这里把预览库提升为正式库。"
        "执行前会自动备份现有 data/mathcyclus.sqlite3；不会删除旧 .tex 题源。"
    )
    apply_confirm = st.text_input(
        "写入确认文本",
        key="legacy_migration_apply_confirm",
        placeholder="PROMOTE_SQLITE_PREVIEW",
        help="必须完整输入 PROMOTE_SQLITE_PREVIEW 才会真正写入正式 SQLite。",
    )
    allow_promote_warnings = st.checkbox(
        "允许带 warning 提升",
        value=False,
        key="legacy_migration_allow_warnings",
        help="只允许非阻断 warning；如果审计存在 blocker，仍会拒绝写入。",
    )
    apply_disabled = promote_disabled or apply_confirm.strip() != "PROMOTE_SQLITE_PREVIEW"
    if st.button("正式提升为 data/mathcyclus.sqlite3", disabled=apply_disabled, type="primary", use_container_width=True):
        command = [
            sys.executable,
            promote_script,
            "--source-db",
            preview_source,
            "--stamp",
            promote_stamp.strip() or datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
            "--sample-limit",
            str(int(sample_limit)),
            "--apply",
            "--confirm",
            "PROMOTE_SQLITE_PREVIEW",
        ]
        if allow_promote_warnings:
            command.append("--allow-warnings")
        with st.spinner("正在备份并提升正式 SQLite 数据库..."):
            result = _legacy_migration_run_command(command)
        st.session_state["legacy_migration_last_apply"] = result
        if result["ok"]:
            record_operation("legacy_tex_migration_promote_apply", details=result["command"])
            clear_statistics_cache()
            st.success("正式 SQLite 已更新；旧 .tex 文件未被修改。")
        else:
            st.error("正式提升失败。请查看 stderr 和提升报告后再处理。")

    last_apply = st.session_state.get("legacy_migration_last_apply")
    if last_apply:
        with st.expander("查看正式提升输出", expanded=not last_apply.get("ok")):
            st.code(last_apply.get("command", ""), language="powershell")
            if last_apply.get("stdout"):
                st.code(last_apply["stdout"], language="text")
            if last_apply.get("stderr"):
                st.code(last_apply["stderr"], language="text")

    st.caption("数据统计页已改为 SQLite 优先读取；API 设置仍然只负责模型和提示词配置，不需要跟随数据库迁移。")


# ================= 页面：工具箱 =================
def page_tools():
    st.header("🛠️ 工具箱")

    if st.session_state.get("tools_subpage") == "tag_edit":
        if st.button("⬅️ 返回工具箱", type="secondary"):
            st.session_state["tools_subpage"] = None
            st.rerun()
        page_tag_edit()
        return
    if st.session_state.get("tools_subpage") == "delete_questions":
        page_browse(is_delete_mode=True)
        return
    if st.session_state.get("tools_subpage") == "cloze_generator":
        if st.button("⬅️ 返回工具箱", type="secondary"):
            st.session_state["tools_subpage"] = None
            st.rerun()
        page_entry(force_single_mode=True, cloze_mode=True)
        return
    if st.session_state.get("tools_subpage") == "cloze_library":
        if st.button("⬅️ 返回工具箱", type="secondary"):
            st.session_state["tools_subpage"] = "cloze_generator"
            st.session_state["adv_search_active"] = False
            _clear_advanced_search_result_cache()
            st.rerun()
        page_browse(paper_type_scope="WK", page_title="🧩 挖空题库")
        return
    if st.session_state.get("tools_subpage") == "duplicate_check":
        if st.button("返回工具箱", type="secondary"):
            st.session_state["tools_subpage"] = None
            st.rerun()
        render_duplicate_check_page()
        return
    if st.session_state.get("tools_subpage") == "legacy_tex_migration":
        if st.button("⬅️ 返回工具箱", type="secondary"):
            st.session_state["tools_subpage"] = None
            st.rerun()
        render_legacy_tex_migration_tool()
        return
    if st.session_state.get("tools_subpage") == "local_maintenance":
        if st.button("⬅️ 返回工具箱", type="secondary"):
            st.session_state["tools_subpage"] = None
            st.rerun()
        render_local_maintenance_tool()
        return
    
    st.markdown("""
    <style>
    /* 工具卡片网格布局：一行三个 */
    .tool-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 20px;
        margin-top: 15px;
    }
    
    /* 单个工具卡片样式 */
    .tool-card {
        background-color: var(--mc-surface);
        border: 1px solid var(--mc-border);
        border-radius: 10px;
        padding: 20px;
        box-shadow: var(--mc-shadow);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        min-height: 240px; /* 确保同一行的卡片高度一致 */
    }
    .tool-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 8px 15px rgba(0,0,0,0.08);
        border-color: var(--mc-accent); /* 悬浮时边框变紫 */
    }
    
    /* 工具卡片标题 */
    .tool-title {
        font-size: 18px;
        font-weight: 700;
        color: var(--mc-text);
        margin-bottom: 10px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    
    /* 工具卡片描述文本 */
    .tool-desc {
        font-size: 14px;
        color: var(--mc-muted);
        line-height: 1.5;
        margin-bottom: 20px;
        flex-grow: 1; /* 让描述部分占据剩余空间，把按钮推到最底 */
    }
    
    /* 强力覆盖 Streamlit 按钮在工具卡片内的样式 */
    .tool-card div[data-testid="stButton"] > button {
        width: 100% !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
    }
    
    /* 如果描述带有高亮底色 (例如第一个工具) */
    .tool-desc-highlight {
        background-color: var(--mc-surface-soft);
        border: 1px solid var(--mc-border);
        padding: 10px;
        border-radius: 4px;
        margin-bottom: 20px;
        font-size: 13px;
        color: var(--mc-text);
        flex-grow: 1;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # 开启网格布局容器
    st.markdown('<div class="tool-grid">', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True) 
    
    # 第一行 3 个工具
    r1_c1, r1_c2, r1_c3 = st.columns([1, 1, 1])
    
    with r1_c1:
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">🗄️ 1. 数据库维护</div>
            <div class="tool-desc-highlight">
                如果您手动删除、外部复制等变动，导致与 CSV 索引不一致，或者统计数据异常，可以点击下方按钮进行一键重建。该操作会保留现有题目的 ID，并自动追加新题或删除不存在的死链接。
            </div>
        </div>
        """, unsafe_allow_html=True)
        # 负 margin 把按钮拉进卡片里
        st.markdown("<style>div:has(> button[key='btn_rebuild_db']) { margin-top: -65px; padding: 0 20px; position: relative; z-index: 10; }</style>", unsafe_allow_html=True)
        if st.button("🔄 一键重建/同步题库索引", key="btn_rebuild_db", use_container_width=True):
            with st.spinner("正在扫描所有目录并重建 CSV 索引..."):
                try:
                    init_script = os.path.join(BASE_DIR, "utils", "init_csv_index.py")
                    subprocess.run(
                        [sys.executable, init_script],
                        cwd=BASE_DIR,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    clear_statistics_cache()
                    st.success("题库索引重建成功！")
                    record_operation("rebuild_csv_index", details="manual rebuild from chapters")
                    st.toast("题库索引同步完成！", icon="✅")
                    time.sleep(1)
                    st.rerun()
                except subprocess.CalledProcessError as e:
                    st.error(f"同步失败：\n{e.stderr}")
                except Exception as e:
                    st.error(f"发生错误：{str(e)}")
            
    with r1_c2:
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">📑 2. 更新板块题目索引</div>
            <div class="tool-desc">
                调用本地的脚本，自动扫描 chapters 目录下的所有题目，并为每个板块重新生成最新的 <code>content_*.tex</code> 索引文件。供主文件 <code>main.tex</code> 调用编译。
                <br><br><i>(当您新增、删除或重命名了题目文件后，请执行此操作以确保主文件目录同步)</i>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<style>div:has(> button[key='btn_update_idx']) { margin-top: -65px; padding: 0 20px; position: relative; z-index: 10; }</style>", unsafe_allow_html=True)
        if st.button("⚡ 执行更新章节索引", key="btn_update_idx", use_container_width=True):
            with st.spinner("正在运行更新脚本..."):
                try:
                    if BASE_DIR not in sys.path:
                        sys.path.append(BASE_DIR)
                    import utils.batch_gen as batch_gen
                    batch_gen.update_chapter_contents()
                    st.success("章节索引更新完成！")
                    record_operation("update_chapter_index", details="manual chapter index update")
                except Exception as e:
                    st.error(f"执行失败: {e}")

    with r1_c3:
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">🎨 3. 提取并分离 TikZ 绘图</div>
            <div class="tool-desc">
                扫描题库中所有现存的 <code>.tex</code> 文件。如果发现未被分离的 <code>\\begin{tikzpicture} ... \\end{tikzpicture}</code> 代码，将会自动将其剥离到同级目录下的 <code>相关图</code> 文件夹中生成副本，同时在主文件中保留内联 TikZ 源码。
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<style>div:has(> button[key='btn_extract_tikz']) { margin-top: -65px; padding: 0 20px; position: relative; z-index: 10; }</style>", unsafe_allow_html=True)
        if st.button("✂️ 执行全库 TikZ 剥离", key="btn_extract_tikz", use_container_width=True):
            updated_files = batch_extract_tikz_all()
            if updated_files:
                st.success(f"操作完成，共处理了 {len(updated_files)} 个文件。")
                with st.expander("查看更新的文件名单", expanded=True):
                    for f in updated_files: st.write(f"- {f}")
            else:
                st.info("未发现需要处理的文件。")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # 第二行 3 个工具
    r2_c1, r2_c2, r2_c3 = st.columns([1, 1, 1])
    
    with r2_c1:
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">✅ 4. 纠正选择题选项格式</div>
            <div class="tool-desc">
                扫描题库中所有现存的 <code>.tex</code> 文件。如果发现形如 <code>A. xxx B. xxx C. xxx D. xxx</code> 的非标准选择题格式，将自动尝试提取选项内容，并用规范的 <code>\\begin{choices} ... \\end{choices}</code> 指令进行替换。
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<style>div:has(> button[key='btn_fix_choices']) { margin-top: -65px; padding: 0 20px; position: relative; z-index: 10; }</style>", unsafe_allow_html=True)
        if st.button("🔧 执行全库选择题格式纠正", key="btn_fix_choices", use_container_width=True):
            updated_files = batch_fix_choice_formats()
            if updated_files:
                st.success(f"操作完成，共修复了 {len(updated_files)} 个文件。")
                with st.expander("查看已修复的文件名单", expanded=True):
                    for f in updated_files: st.write(f"- {f}")
            else:
                st.info("未发现需要修复的选择题格式文件。")

    with r2_c2:
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">🏷️ 5. 标签与属性修改</div>
            <div class="tool-desc">
                查找并修改某一道题或某一整套试卷的元数据：年份、试卷类别、试卷名称、题号、知识板块，并同步更新文件名与 CSV 索引。
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<style>div:has(> button[key='btn_tools_tag_edit']) { margin-top: -65px; padding: 0 20px; position: relative; z-index: 10; }</style>", unsafe_allow_html=True)
        if st.button("进入标签与属性修改", key="btn_tools_tag_edit", use_container_width=True):
            st.session_state["tools_subpage"] = "tag_edit"
            st.rerun()

    with r2_c3:
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">🗑️ 6. 删除题库问题</div>
            <div class="tool-desc">
                进入专用删除模式，沿用全局浏览和三级查找定位题目。删除时会先把题目文件及同名相关图备份到 <code>.backups</code>，再从题库目录移除，并同步 CSV 索引和章节索引；误删可在删除模式右上角“恢复误删题目”恢复本次删除记录，也可点“管理备份问题”查找历史备份。当前备份不会自动定期清理。
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<style>div:has(> button[key='btn_tools_delete_questions']) { margin-top: -65px; padding: 0 20px; position: relative; z-index: 10; }</style>", unsafe_allow_html=True)
        if st.button("开始删除选定问题", key="btn_tools_delete_questions", use_container_width=True):
            st.session_state["tools_subpage"] = "delete_questions"
            st.session_state["adv_search_active"] = False
            _clear_advanced_search_result_cache()
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # 第三行工具
    r3_c1, r3_c2, r3_c3 = st.columns([1, 1, 1])

    with r3_c1:
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">🧩 7. 挖空题生成</div>
            <div class="tool-desc">
                上传或粘贴题目与解答，按预设要求生成挖空题。当前先沿用单题录入界面，支持实时预览、保存题目，并可导出当前挖空题图片；具体 AI 提示词与挖空生成策略后续补充。
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<style>div:has(> button[key='btn_tools_cloze_generator']) { margin-top: -65px; padding: 0 20px; position: relative; z-index: 10; }</style>", unsafe_allow_html=True)
        if st.button("进入挖空题生成界面", key="btn_tools_cloze_generator", use_container_width=True):
            st.session_state["tools_subpage"] = "cloze_generator"
            st.session_state["cloze_image_result"] = None
            st.session_state.setdefault("cloze_auto_solve", True)
            st.rerun()

    with r3_c2:
        try:
            semantic_status = semantic_index_status()
            semantic_status_error = ""
        except SemanticSearchError as exc:
            semantic_status = {"count": 0, "model_name": ""}
            semantic_status_error = str(exc)
        status_text = "未建立"
        if semantic_status.get("count"):
            status_text = f"{semantic_status['count']} 道题"
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">🧠 8. 语义搜索索引</div>
            <div class="tool-desc">
                使用可配置的 embedding 模型建立题干语义索引，供高级搜索中的“混合搜索”和“语义搜索”使用。索引是可重建的派生数据，不会修改题目文件或 CSV。
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.caption(f"当前状态：{status_text} · 模型：{semantic_status.get('model_name') or '未配置'}")
        if semantic_status_error:
            st.warning(f"索引状态读取失败：{semantic_status_error}")
        force_rebuild = st.checkbox("强制重新生成已有向量", key="semantic_force_rebuild")
        st.markdown("<style>div:has(> button[key='btn_rebuild_semantic']) { margin-top: -24px; padding: 0 20px; position: relative; z-index: 10; }</style>", unsafe_allow_html=True)
        if st.button("🔄 更新语义索引", key="btn_rebuild_semantic", use_container_width=True):
            config = _semantic_api_config()
            progress_bar = st.progress(0)

            def _semantic_progress(done, total):
                progress_bar.progress(1.0 if total <= 0 else min(1.0, done / total))

            try:
                rows = _csv_index_cached(_csv_index_cache_token())
                with st.spinner("正在生成题目 embedding，请稍候..."):
                    result = build_semantic_index(
                        rows,
                        config["base_url"],
                        config["api_key"],
                        config["model_name"],
                        force=force_rebuild,
                        progress=_semantic_progress,
                    )
                progress_bar.empty()
                _clear_advanced_search_result_cache()
                st.success(f"语义索引已更新：处理 {result['updated']} 道，当前共 {result['total']} 道。")
            except SemanticSearchError as exc:
                progress_bar.empty()
                st.error(str(exc))
            except Exception as exc:
                progress_bar.empty()
                st.error(f"语义索引更新失败：{exc}")

    with r3_c3:
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">🔎 9. 搜索模式说明</div>
            <div class="tool-desc">
                精确筛选适合题号、年份、题型等明确条件；混合搜索在语义相关度基础上优先展示关键词命中的题目；语义搜索适合用自然语言描述考点。
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    r4_c1, r4_c2, r4_c3 = st.columns([1, 1, 1])
    with r4_c1:
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">🔎 10. 题目查重</div>
            <div class="tool-desc">
                按题干内容扫描题库，识别完全重复和高度相似的题目，提供题目 ID、来源路径和并排预览，方便人工确认后处理。
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<style>div:has(> button[key='btn_tools_duplicate_check']) { margin-top: -65px; padding: 0 20px; position: relative; z-index: 10; }</style>", unsafe_allow_html=True)
        if st.button("进入题目查重", key="btn_tools_duplicate_check", use_container_width=True):
            st.session_state["tools_subpage"] = "duplicate_check"
            st.session_state.pop("duplicate_scan_results", None)
            st.rerun()

    with r4_c2:
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">🧾 11. 操作记录</div>
            <div class="tool-desc">
                查看题目创建、编辑、重命名、删除、恢复和查重记录，便于追踪最近的数据变更。
            </div>
        </div>
        """, unsafe_allow_html=True)

    with r4_c3:
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">🧱 12. 旧 TeX 迁移到 SQLite</div>
            <div class="tool-desc">
                为早期本地 TeX 题库用户提供升级入口：先从旧 <code>chapters</code> 生成 SQLite 预览库和迁移报告，再做提升检查；确认无阻塞后可强确认提升为正式库。全程不删除旧题源。
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<style>div:has(> button[key='btn_tools_legacy_tex_migration']) { margin-top: -65px; padding: 0 20px; position: relative; z-index: 10; }</style>", unsafe_allow_html=True)
        if st.button("进入旧库迁移工具", key="btn_tools_legacy_tex_migration", use_container_width=True):
            st.session_state["tools_subpage"] = "legacy_tex_migration"
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    r5_c1, r5_c2, r5_c3 = st.columns([1, 1, 1])
    with r5_c1:
        st.markdown("""
        <div class="tool-card">
            <div class="tool-title">🧰 13. 本地维护与升级</div>
            <div class="tool-desc">
                面向源码版和未来打包版用户：检查 GitHub 更新计划、应用 SQLite schema 迁移、导出/检查/恢复本地数据迁移包。默认 dry-run，真正写入需要手动确认。
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<style>div:has(> button[key='btn_tools_local_maintenance']) { margin-top: -65px; padding: 0 20px; position: relative; z-index: 10; }</style>", unsafe_allow_html=True)
        if st.button("进入本地维护与升级", key="btn_tools_local_maintenance", use_container_width=True):
            st.session_state["tools_subpage"] = "local_maintenance"
            st.rerun()
    with r5_c2:
        st.empty()
    with r5_c3:
        st.empty()

    render_operation_log_panel()


def batch_fix_choice_formats():
    import re
    updated_files = []
    
    for root, dirs, files in os.walk(CHAPTERS_DIR):
        for file in files:
            if not file.endswith(".tex"): continue
            if file.startswith("content_"): continue
            if " 相关图" in root or " 图" in file: continue
            
            file_path = os.path.join(root, file)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 寻找 A. B. C. D. 模式 (支持全半角和换行)
                pattern = r'(?:A|Ａ)[\.．]\s*(.*?)\s*(?:B|Ｂ)[\.．]\s*(.*?)\s*(?:C|Ｃ)[\.．]\s*(.*?)\s*(?:D|Ｄ)[\.．]\s*(.*?)(?=\\end\{problem\}|\\begin\{solutions?\}|$)'
                
                def replace_choices(match):
                    opt_a = match.group(1).strip()
                    opt_b = match.group(2).strip()
                    opt_c = match.group(3).strip()
                    opt_d = match.group(4).strip()
                    
                    # 移除选项末尾可能多余的 \quad, \qquad 和 \\ 等
                    def clean_opt(opt):
                        opt = re.sub(r'\\quad\s*$', '', opt).strip()
                        opt = re.sub(r'\\qquad\s*$', '', opt).strip()
                        opt = re.sub(r'\\\\$', '', opt).strip() # 去除换行符 \\
                        return opt
                        
                    opt_a = clean_opt(opt_a)
                    opt_b = clean_opt(opt_b)
                    opt_c = clean_opt(opt_c)
                    opt_d = clean_opt(opt_d)
                    
                    return f"\n\\begin{{choices}}\n\\choice{{{{{opt_a}}}}}\n\\choice{{{{{opt_b}}}}}\n\\choice{{{{{opt_c}}}}}\n\\choice{{{{{opt_d}}}}}\n\\end{{choices}}\n"
                
                new_content, count = re.subn(pattern, replace_choices, content, flags=re.DOTALL)
                
                # 检查 \begin{choices} 前面是否有 (\hspace{1cm})
                if r'\begin{choices}' in new_content:
                    parts = new_content.split(r'\begin{choices}')
                    for i in range(len(parts) - 1):
                        prefix = parts[i]
                        stripped_prefix = prefix.rstrip()
                        
                        # 检查是否已经有 (\hspace{1cm}) 或者类似的占位符 (支持全角半角括号和空格)
                        has_hspace = re.search(r'[\(（]\s*\\hspace\{1cm\}\s*[\)）]$', stripped_prefix)
                        
                        if not has_hspace:
                            # 检查是否有空的括号 () 或 （），有的话直接替换掉
                            if stripped_prefix.endswith('()') or stripped_prefix.endswith('（）'):
                                stripped_prefix = stripped_prefix[:-2] + r'(\hspace{1cm})'
                            else:
                                stripped_prefix += r' (\hspace{1cm})'
                                
                        parts[i] = stripped_prefix + '\n'
                        
                    new_content = r'\begin{choices}'.join(parts)
                
                if new_content != content:
                    atomic_write_text(file_path, new_content, backup=True)
                    updated_files.append(file)
            except Exception as e:
                print(f"Error processing {file_path}: {e}")
                
    return updated_files

def batch_extract_tikz_all():
    updated_files = []
    for root, dirs, files in os.walk(CHAPTERS_DIR):
        for file in files:
            if not file.endswith(".tex"): continue
            # 跳过已经被提取出来的图文件
            if " 图" in file and " 相关图" in root: continue
            
            file_path = os.path.join(root, file)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 如果包含原生的 tikzpicture 才需要处理
                if r'\begin{tikzpicture}' in content:
                    save_dir = root
                    filename = file
                    # 复用核心抽取函数
                    new_content = extract_and_replace_tikz(content, filename, save_dir)
                    if new_content != content:
                        atomic_write_text(file_path, new_content, backup=True)
                        # 触发一次预渲染生成PNG
                        latex_to_markdown(new_content)
                        updated_files.append(file_path)
            except Exception as e:
                print(f"Error processing {file_path}: {e}")
                
    return updated_files

def add_blank_lines_to_all():
    count = 0
    for root, dirs, files in os.walk(CHAPTERS_DIR):
        for file in files:
            if not file.endswith(".tex"): continue
            
            file_path = os.path.join(root, file)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 使用简单的正则或字符串处理
                # 这里复用之前的逻辑：查找 \begin{problem}... 到 \end{problem}
                # 简单起见，我们假设文件就是标准的 problem 结构
                
                lines = content.split('\n')
                new_lines = []
                in_problem = False
                modified = False
                
                for i, line in enumerate(lines):
                    if "\\begin{problem}" in line:
                        in_problem = True
                        new_lines.append(line)
                        continue
                    if "\\end{problem}" in line:
                        in_problem = False
                        new_lines.append(line)
                        continue
                        
                    if in_problem:
                        # 如果当前行不空，且上一行不空，且不是环境开始，则加空行
                        # 但要小心不要破坏数学公式块 $ ... $
                        # 这是一个简化的处理，主要针对文本段落
                        
                        # 简单策略：如果当前行是非空文本，且上一行也是非空文本，插入空行
                        # 但为了安全，我们只处理显式的中文段落结尾？
                        # 或者复用之前的逻辑：每行后面加一个空行，如果已经有空行则不加
                        
                        # 更稳健的策略：读取内容，如果发现没有空行分隔的段落，则插入
                        # 这里我们采用保守策略：如果当前行有内容，且下一行也有内容，中间插入空行
                        # 并不容易完美自动化。
                        # 让我们回退到最安全的方式：不做复杂语法分析，仅提示用户
                        # 或者，只处理显式的文字段落。
                        
                        # 实际上，之前的 update_doc.py 逻辑比较复杂。
                        # 在这里，我们实现一个简化版本：确保 \end{problem} 前有一行空行，
                        # 以及 \begin{problem} 后有一行空行（如果不为空的话）。
                        # 真正的段落间空行最好人工确认。
                        
                        # 重新考虑：用户之前的需求是“分行加空行”。
                        # 我们可以简单地将非空行之间插入空行。
                        
                        stripped = line.strip()
                        if stripped:
                            new_lines.append(line)
                            # 如果下一行不是空行，也不是 end problem，则添加空行
                            if i + 1 < len(lines):
                                next_line = lines[i+1].strip()
                                if next_line and "\\end{problem}" not in next_line:
                                    new_lines.append("") # 插入空行
                                    modified = True
                        else:
                            new_lines.append(line)
                    else:
                        new_lines.append(line)
                
                if modified:
                    new_content = "\n".join(new_lines)
                    if new_content != content:
                        atomic_write_text(file_path, new_content, backup=True)
                        count += 1
            except Exception as e:
                print(f"Error processing {file}: {e}")
                
    return count


def standardize_national_papers():
    # 这里集成之前的重命名逻辑
    count = 0
    local_keywords = [
        "北京", "上海", "天津", "重庆", "浙江", "江苏", "江西", "山东", 
        "湖北", "湖南", "广东", "福建", "辽宁", "吉林", "黑龙江", 
        "河北", "河南", "山西", "陕西", "四川", "云南", "贵州", 
        "安徽", "广西", "海南", "内蒙古", "西藏", "青海", "宁夏", 
        "新疆", "甘肃", "港", "澳", "台"
    ]
    
    for root, dirs, files in os.walk(CHAPTERS_DIR):
        for file in files:
            if not file.endswith(".tex"): continue
            
            parts = file[:-4].split('-')
            if len(parts) != 5: continue
            
            year_str, type_str, paper_name, number, subject = parts
            try:
                year = int(year_str)
            except:
                continue
                
            # 过滤地方卷和甲乙卷
            is_local = any(kw in paper_name for kw in local_keywords)
            if is_local or "甲卷" in paper_name or "乙卷" in paper_name:
                continue
                
            new_paper_name = paper_name
            # 规则匹配
            if 2020 <= year <= 2022:
                if "新课标" in new_paper_name: new_paper_name = new_paper_name.replace("新课标", "新高考")
                if "新高考全国" in new_paper_name: new_paper_name = new_paper_name.replace("新高考全国", "新高考")
            elif 2023 <= year <= 2025:
                if "新高考" in new_paper_name: new_paper_name = new_paper_name.replace("新高考", "新课标")
                if "新课标全国" in new_paper_name: new_paper_name = new_paper_name.replace("新课标全国", "新课标")
            
            if new_paper_name != paper_name:
                # 重命名文件
                new_filename = f"{year_str}-{type_str}-{new_paper_name}-{number}-{subject}.tex"
                old_path = os.path.join(root, file)
                new_path = os.path.join(root, new_filename)
                
                # 更新内容中的标签
                try:
                    with open(old_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    # 替换 {paper_name} 为 {new_paper_name}
                    # 简单的字符串替换可能误伤，使用比较精确的替换
                    old_tag = f"{{{paper_name}}}"
                    new_tag = f"{{{new_paper_name}}}"
                    content = content.replace(old_tag, new_tag, 1) # 只替换第一个匹配（通常是标签）
                    
                    atomic_write_text(old_path, content, backup=True)
                        
                    os.rename(old_path, new_path)
                    st.write(f"已重命名: {file} -> {new_filename}")
                    count += 1
                except Exception as e:
                    st.error(f"处理 {file} 时出错: {e}")
    return count

# ================= 页面：标签与属性修改 (含搜索) =================
def page_tag_edit():
    st.header("🏷️ 标签与属性修改")
    st.info("在此模式下，您可以修改题目的元数据（年份、试卷名、题号、板块）以及文件名。")
    
    # Session state for selected file in this tab
    if "tag_edit_file" not in st.session_state:
        st.session_state["tag_edit_file"] = None

    # 定义匹配函数 (局部使用)
    # def is_match(path, s_type, s_query): ... (Use global check_search_match instead)
        
    c_left, c_right = st.columns([1, 1.5])  # 调整比例，使右侧搜索栏宽度缩小
    
    with c_left:
        st.markdown("""
        <style>
        #tag-edit-dir-label {
            font-size: 16px;
            font-weight: 700;
            margin: 0.35rem 0 0.15rem 0;
        }
        #tag-edit-dir-box div[data-testid="stSelectbox"] div[data-baseweb="select"] * {
            font-size: 16px !important;
            font-weight: 700 !important;
        }
        </style>
        """, unsafe_allow_html=True)
        st.markdown('<div id="tag-edit-dir-box"></div>', unsafe_allow_html=True)
        st.subheader("📂 目录选择")
        csv_rows = []
        all_years = get_all_years_globally()
        st.markdown('<div id="tag-edit-dir-label">年份</div>', unsafe_allow_html=True)
        year = st.selectbox("年份", options=all_years, key="te_year", label_visibility="collapsed")

        type_opts = ["全部试卷类别"] + _editable_paper_type_options()
        st.markdown('<div id="tag-edit-dir-label">试卷类别筛选</div>', unsafe_allow_html=True)
        ptype_filter = st.selectbox("试卷类别筛选", options=type_opts, key="te_ptype_filter", label_visibility="collapsed", format_func=lambda x: x if x == "全部试卷类别" else f"{x} ({PAPER_TYPES.get(x, '')})")

        paper_name = None
        if year:
            csv_token = _csv_index_cache_token()
            try:
                csv_rows = _csv_index_cached(csv_token)
            except Exception:
                from utils.csv_ops import read_csv_index
                csv_rows = _filter_question_rows(read_csv_index())

            papers_set = set()
            for row in csv_rows:
                if (row.get("年份", "") or "").strip() != str(year):
                    continue
                if ptype_filter != "全部试卷类别" and (row.get("试卷类型", "") or "").strip() != ptype_filter:
                    continue
                pname = (row.get("试卷名称", "") or "").strip()
                if pname:
                    papers_set.add(pname)
            papers = sorted(papers_set) if papers_set else get_papers_by_year(year)
            if papers:
                st.markdown('<div id="tag-edit-dir-label">试卷</div>', unsafe_allow_html=True)
                paper_name = st.selectbox("试卷", options=papers, key="te_paper", label_visibility="collapsed")
        
        if year and paper_name:
            questions = get_questions_by_paper(year, paper_name)
            if questions:
                by_path = {}
                for row in csv_rows if year else []:
                    relp = (row.get("相对文件路径", "") or "").strip()
                    if not relp:
                        continue
                    by_path[os.path.join(CHAPTERS_DIR, relp)] = row

                filtered_questions = []
                for q in questions:
                    qpath = q.get("path")
                    r = by_path.get(qpath)
                    if ptype_filter != "全部试卷类别":
                        if not r or (r.get("试卷类型", "") or "").strip() != ptype_filter:
                            continue
                    filtered_questions.append(q)

                questions = filtered_questions
                q_options = ["（所有题目：本试卷）"] + [f"第{q['file'].split('-')[3]}题 ({q['subject']})" for q in questions]
                st.markdown('<div id="tag-edit-dir-label">题目</div>', unsafe_allow_html=True)
                sel_idx = st.selectbox("题目", range(len(q_options)), format_func=lambda i: q_options[i], key="te_q_select", label_visibility="collapsed")
                
                if st.button("⬇️ 加载选中题目", key="btn_load_hierarchy", use_container_width=True):
                    if sel_idx == 0:
                        st.session_state["tag_edit_file"] = None
                        st.session_state["tag_edit_bulk_paths"] = [q.get("path") for q in questions if q.get("path")]
                        st.session_state["tag_edit_bulk_meta"] = {"year": str(year), "paper": str(paper_name)}
                    else:
                        st.session_state["tag_edit_bulk_paths"] = []
                        st.session_state["tag_edit_bulk_meta"] = None
                        st.session_state["tag_edit_file"] = questions[sel_idx - 1]["path"]
                    st.rerun()

    with c_right:
        st.subheader("🔍 搜索选择")
        search_opts = ["全文内容", "题目类型", "题目内容", "解答内容", "难度星级", "标签", "备注"]
        # 因为需要级联更新 UI（selectbox -> text_input/selectbox），不能将包含动态类型的输入框直接放进 form
        # 我们改用普通的容器，最后加一个搜索按钮
        c1a, c1b = st.columns([1, 2])
        with c1a: 
            t1 = st.selectbox("一级类型", search_opts, index=0, key="te_s_t1", label_visibility="collapsed")
        with c1b: 
            if t1 == "题目类型":
                q1 = st.selectbox("一级检索", ["选择题", "填空题", "解答题"], key="te_s_q1_sel", label_visibility="collapsed")
            else:
                q1 = st.text_input("一级检索", placeholder="一级关键词", key="te_s_q1", label_visibility="collapsed")
        
        # Level 2
        c2a, c2b = st.columns([1, 2])
        with c2a: 
            t2 = st.selectbox("二级类型", search_opts, index=0, key="te_s_t2", label_visibility="collapsed")
        with c2b: 
            if t2 == "题目类型":
                q2 = st.selectbox("二级检索", ["选择题", "填空题", "解答题"], key="te_s_q2_sel", label_visibility="collapsed")
            else:
                q2 = st.text_input("二级检索", placeholder="筛选词", key="te_s_q2", label_visibility="collapsed")
        
        # Level 3
        c3a, c3b = st.columns([1, 2])
        with c3a: 
            t3 = st.selectbox("三级类型", search_opts, index=0, key="te_s_t3", label_visibility="collapsed")
        with c3b: 
            if t3 == "题目类型":
                q3 = st.selectbox("三级检索", ["选择题", "填空题", "解答题"], key="te_s_q3_sel", label_visibility="collapsed")
            else:
                q3 = st.text_input("三级检索", placeholder="筛选词", key="te_s_q3", label_visibility="collapsed")
        
        submitted = st.button("🔍 搜索", type="primary", use_container_width=True)
             
        if submitted:
            st.session_state["te_search_active"] = True
            
        if st.session_state.get("te_search_active"):
            def _row_match(row, s_type, s_query):
                s_query = (s_query or "").strip()
                if not s_query:
                    return True
                if s_type == "题目类型":
                    return s_query == (row.get("题型", "") or "").strip()
                if s_type == "题目内容":
                    return s_query in (row.get("题干", "") or "")
                if s_type == "解答内容":
                    return s_query in (row.get("解析", "") or "")
                if s_type == "难度星级":
                    return s_query in (row.get("难度星级", "") or "")
                if s_type == "标签":
                    return s_query in (row.get("标签", "") or "")
                if s_type == "备注":
                    return s_query in (row.get("备注", "") or "")
                if s_type == "全文内容":
                    hay = (row.get("题干", "") or "") + "\n" + (row.get("答案", "") or "") + "\n" + (row.get("解析", "") or "") + "\n" + (row.get("标签", "") or "") + "\n" + (row.get("备注", "") or "")
                    return s_query in hay
                return False

            csv_token = _csv_index_cache_token()
            try:
                csv_rows = _csv_index_cached(csv_token)
            except Exception:
                from utils.csv_ops import read_csv_index
                csv_rows = _filter_question_rows(read_csv_index())

            results = []
            for row in csv_rows:
                if q1 and not _row_match(row, t1, q1):
                    continue
                if q2 and not _row_match(row, t2, q2):
                    continue
                if q3 and not _row_match(row, t3, q3):
                    continue
                relp = (row.get("相对文件路径", "") or "").strip()
                if not relp:
                    continue
                absp = os.path.join(CHAPTERS_DIR, relp)
                if not os.path.exists(absp):
                    continue
                fname = (row.get("文件名称", "") or "").strip()
                if fname and not fname.lower().endswith(".tex"):
                    fname = fname + ".tex"
                results.append({"file": fname or os.path.basename(absp), "path": absp})
            
            if results:
                st.success(f"找到 {len(results)} 个结果")
                res_options = [r["file"] for r in results]
                sel_res_idx = st.selectbox("选择搜索结果", range(len(results)), format_func=lambda i: res_options[i], key="te_res_select")
                
                if st.button("⬇️ 加载搜索结果", key="btn_load_search", use_container_width=True):
                    st.session_state["tag_edit_file"] = results[sel_res_idx]["path"]
                    st.rerun()
            else:
                st.warning("未找到匹配项")

    st.divider()
    
    # 编辑区域
    bulk_paths = st.session_state.get("tag_edit_bulk_paths") or []
    bulk_meta = st.session_state.get("tag_edit_bulk_meta") or {}
    if bulk_paths:
        st.subheader("🧩 批量修改（本试卷所有题目）")
        st.caption("仅修改：年份、试卷类别、试卷名称；题号与知识板块保持不变。")

        cur_year = (bulk_meta.get("year") or "").strip()
        cur_paper = (bulk_meta.get("paper") or "").strip()
        st.info(f"当前试卷：{cur_year} 年｜{cur_paper}｜共 {len(bulk_paths)} 题")

        type_opts = _editable_paper_type_options()
        with st.form("te_bulk_update_form"):
            new_year = st.text_input("统一年份", value=cur_year)
            new_type = st.selectbox("统一试卷类别", options=type_opts, format_func=lambda x: f"{x} ({PAPER_TYPES[x]})")
            new_name = st.text_input("统一试卷名称", value=cur_paper)
            submitted = st.form_submit_button("执行批量更新", type="primary")

        if submitted:
            ok, fail = 0, 0
            log_lines = []
            for old_path in bulk_paths:
                try:
                    if not old_path or not os.path.exists(old_path):
                        fail += 1
                        continue
                    base = os.path.basename(old_path).replace(".tex", "")
                    parts = base.split("-")
                    if len(parts) < 5:
                        fail += 1
                        continue
                    old_year, old_ptype, old_pname, old_pnum, old_subj = parts[0], parts[1], parts[2], parts[3], parts[4]
                    new_filename = generate_filename(new_year, new_type, new_name, old_pnum, old_subj)
                    primary_subj = old_subj.split("，")[0] if old_subj else ""
                    target_dir = os.path.join(CHAPTERS_DIR, primary_subj, str(new_year))
                    ensure_dir(target_dir)
                    new_path = os.path.join(target_dir, new_filename)
                    with open(old_path, "r", encoding="utf-8") as f:
                        old_content = f.read()
                    new_header = f"\\begin{{problem}}{{{new_year}}}{{{new_type}}}{{{new_name}}}{{{old_pnum}}}{{{old_subj}}}"
                    new_content = re.sub(r"\\begin\{problem\}\{.*?\}\{.*?\}\{.*?\}\{.*?\}\{.*?\}", lambda _m: new_header, old_content, count=1)
                    if new_content == old_content and "\\begin{problem}" in old_content:
                        new_content = re.sub(r"\\begin\{problem\}", lambda _m: new_header, old_content, count=1)
                    atomic_write_text(new_path, new_content, backup=os.path.exists(new_path))
                    if os.path.abspath(new_path) != os.path.abspath(old_path):
                        os.remove(old_path)
                    update_csv_index_for_edit(old_path, new_path, new_content, str(new_year), new_type, new_name, old_pnum, old_subj)
                    ok += 1
                    log_lines.append(f"✅ {os.path.basename(old_path)} -> {os.path.basename(new_path)}")
                except Exception as e:
                    fail += 1
                    log_lines.append(f"❌ {os.path.basename(old_path) if old_path else ''}: {e}")

            clear_statistics_cache()
            st.success(f"批量更新完成：成功 {ok}，失败 {fail}")
            with st.expander("查看日志", expanded=(fail > 0)):
                for line in log_lines:
                    st.write(line)
            st.session_state["tag_edit_bulk_paths"] = []
            st.session_state["tag_edit_bulk_meta"] = None
            time.sleep(0.5)
            st.rerun()

    file_path = st.session_state.get("tag_edit_file")
    if file_path and os.path.exists(file_path):
        # 读取文件内容
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 解析当前元数据
        current_meta = {}
        parts = os.path.basename(file_path)[:-4].split('-')
        if len(parts) >= 5:
            current_meta = {
                "year": parts[0],
                "type": parts[1],
                "name": parts[2],
                "num": parts[3],
                "subject": parts[4]
            }
        
        c_edit_left, c_edit_right = st.columns([1, 1])
        
        with c_edit_left:
            st.subheader("LaTeX 源码预览")
            est_height = get_editor_height(content)
            mtime_token = int(os.path.getmtime(file_path)) if os.path.exists(file_path) else 0
            st.text_area("源码", value=content, height=est_height, disabled=True, key=f"te_preview_left_{file_path}_{mtime_token}")
            st.caption(f"文件路径: {file_path}")
            
        with c_edit_right:
            st.subheader("修改元数据")
            with st.form("te_meta_update_form"):
                new_year = st.text_input("年份", value=current_meta.get("year", ""))
                
                type_opts = _editable_paper_type_options()
                default_type_idx = 0
                if current_meta.get("type") in type_opts:
                    default_type_idx = type_opts.index(current_meta.get("type"))
                new_type = st.selectbox("试卷类型", options=type_opts, index=default_type_idx, format_func=lambda x: f"{x} ({PAPER_TYPES[x]})")
                
                new_name = st.text_input("试卷名称", value=current_meta.get("name", ""))
                new_num = st.text_input("题号", value=current_meta.get("num", ""))
                
                # 多板块处理
                current_subjects = current_meta.get("subject", "").split("，")
                valid_current_subjects = [s for s in current_subjects if s in SUBJECTS]
                if not valid_current_subjects:
                    valid_current_subjects = [SUBJECTS[0]] if SUBJECTS else []
                
                new_subjects = st.multiselect("知识板块 (首个为主)", options=SUBJECTS, default=valid_current_subjects)
                new_subject_str = "，".join(new_subjects) if new_subjects else (SUBJECTS[0] if SUBJECTS else "")
                
                st.caption("注意：修改元数据将重命名文件并更新文件内容的 problem 头部信息。主板块(第一个)决定文件存储位置。")
                
                if st.form_submit_button("执行重命名与标签更新", type="primary"):
                    new_filename = generate_filename(new_year, new_type, new_name, new_num, new_subject_str)
                    
                    primary_subj = new_subject_str.split("，")[0] if new_subject_str else ""
                    current_primary = current_meta.get("subject", "").split("，")[0]
                    
                    target_dir = os.path.join(CHAPTERS_DIR, primary_subj, new_year)
                    if primary_subj != current_primary or new_year != current_meta.get("year"):
                        ensure_dir(target_dir)
                    new_path = os.path.join(target_dir, new_filename)

                    try:
                        new_header = f"\\begin{{problem}}{{{new_year}}}{{{new_type}}}{{{new_name}}}{{{new_num}}}{{{new_subject_str}}}"
                        new_full_text = re.sub(r"\\begin\{problem\}\{.*?\}\{.*?\}\{.*?\}\{.*?\}\{.*?\}", lambda _m: new_header, content, count=1)
                        if new_full_text == content and "\\begin{problem}" in content:
                            new_full_text = re.sub(r"\\begin\{problem\}", lambda _m: new_header, content, count=1)
                        with open(new_path, "w", encoding="utf-8") as f:
                            f.write(new_full_text)
                        
                        if new_path != file_path:
                            os.remove(file_path)
                            
                        # 同步更新到 CSV 索引
                        update_csv_index_for_edit(file_path, new_path, new_full_text, new_year, new_type, new_name, new_num, new_subject_str)
                        _invalidate_semantic_for_file(file_path)
                        _invalidate_semantic_for_file(new_path)
                            
                        st.success(f"更新成功！\n旧: {os.path.basename(file_path)}\n新: {new_filename}")
                        clear_statistics_cache()
                        st.session_state["tag_edit_file"] = new_path
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"更新失败: {e}")

def update_question_meta(fpath, key, value):
    from utils.latex_ops import parse_meta_data, inject_meta_data
    with open(fpath, "r", encoding="utf-8") as f:
        fc = f.read()
    fm, _ = parse_meta_data(fc)
    fm[key] = value
    new_fc = inject_meta_data(fc, fm)
    atomic_write_text(fpath, new_fc, backup=True)
    record_operation(
        "update_question_meta",
        path=os.path.abspath(fpath),
        details=f"field={key}",
    )
    _invalidate_semantic_for_file(fpath)
    try:
        from utils.csv_ops import update_csv_index_for_edit
        # 从文件名解析基础信息
        basename = os.path.basename(fpath).replace(".tex", "")
        parts = basename.split("-")
        if len(parts) >= 5:
            new_year = parts[0]
            new_ptype = parts[1]
            new_pname = parts[2]
            new_pnum = parts[3]
            new_subj = parts[4]
            update_csv_index_for_edit(fpath, fpath, new_fc, new_year, new_ptype, new_pname, new_pnum, new_subj)
            _clear_advanced_search_result_cache()
        else:
            print("Update CSV failed: Invalid filename format.")
    except Exception as e:
        print("Update CSV failed:", e)

def _split_tag_values(tag_text: str) -> list[str]:
    tags = []
    seen = set()
    for raw in re.split(r"[，,]", tag_text or ""):
        tag = raw.strip()
        if tag and tag not in seen:
            tags.append(tag)
            seen.add(tag)
    return tags

def _parse_tag_history_time(value: str) -> float:
    text = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt).timestamp()
        except ValueError:
            pass
    return 0.0

@st.cache_data(show_spinner=False)
def _tag_history_suggestions_cached(csv_token, limit=5):
    from utils.csv_ops import read_csv_index

    stats = {}
    for row in _filter_question_rows(read_csv_index()):
        row_time = max(
            _parse_tag_history_time(row.get("最后修改时间", "")),
            _parse_tag_history_time(row.get("初次录入的时间", "")),
        )
        for tag in _split_tag_values(row.get("标签", "")):
            item = stats.setdefault(tag, {"tag": tag, "count": 0, "last_seen": 0.0})
            item["count"] += 1
            item["last_seen"] = max(item["last_seen"], row_time)

    ranked = sorted(
        stats.values(),
        key=lambda item: (-item["count"], -item["last_seen"], item["tag"]),
    )
    return ranked[:limit]

def get_tag_history_suggestions(limit=5):
    return _tag_history_suggestions_cached(file_change_token(CSV_INDEX_PATH), limit)

def _append_tag_text(current_tags: str, tag: str) -> str:
    tags = _split_tag_values(current_tags)
    if tag not in tags:
        tags.append(tag)
    return "，".join(tags)

def _apply_tag_suggestion(input_key: str, tag: str):
    st.session_state[input_key] = _append_tag_text(st.session_state.get(input_key, ""), tag)


@st.cache_data(show_spinner=False)
def _cloze_source_lookup_cached(source_question_id: str, csv_token: str) -> dict:
    """Resolve a WK source ID through the existing CSV index without exposing WK as a source."""
    from utils.csv_ops import read_csv_index

    source_question_id = str(source_question_id or "").strip()
    if not source_question_id:
        return {}

    for row in read_csv_index():
        if (row.get("试卷类型", "") or "").strip() == "WK":
            continue
        if str(row.get("题目ID", "") or "").strip() != source_question_id:
            continue
        rel_path = (row.get("相对文件路径", "") or "").strip()
        source_path = os.path.join(CHAPTERS_DIR, rel_path) if rel_path else ""
        return {
            "path": source_path,
            "label": _cloze_source_label(row),
            "exists": bool(source_path and os.path.exists(source_path)),
        }
    return {}


def render_cloze_source_trace(content: str, fpath: str, meta: dict):
    """Show an on-demand source preview only for generated WK questions."""
    fields = extract_problem_header_fields(content) or {}
    if fields.get("p_type") != "WK":
        return

    source_question_id = str(meta.get("来源题目ID", "") or "").strip()
    if not source_question_id:
        st.caption("来源原题：未关联")
        return

    trace_key = f"cloze_source_trace_open_{hashlib.md5(fpath.encode()).hexdigest()[:12]}"
    lookup = _cloze_source_lookup_cached(source_question_id, file_change_token(CSV_INDEX_PATH))
    trace_label, trace_action = st.columns([4, 1])
    with trace_label:
        source_label = lookup.get("label") or f"题目 ID：{source_question_id}"
        st.caption(f"来源原题：{source_label}")
    with trace_action:
        action_label = "收起原题" if st.session_state.get(trace_key) else "查看原题"
        if st.button(action_label, key=f"btn_{trace_key}", use_container_width=True):
            st.session_state[trace_key] = not st.session_state.get(trace_key, False)

    if not st.session_state.get(trace_key):
        return
    if not lookup:
        st.warning(f"未在题库索引中找到来源题目 ID：{source_question_id}")
        return
    if not lookup.get("exists"):
        st.warning(f"来源题目文件已不存在：{lookup.get('label') or source_question_id}")
        return

    try:
        with open(lookup["path"], "r", encoding="utf-8") as f:
            source_content = f.read()
        with st.expander(f"原题预览：{lookup['label']}", expanded=True):
            st.markdown(latex_to_markdown(source_content, show_title=False), unsafe_allow_html=True)
    except Exception as e:
        st.warning(f"打开来源原题失败：{e}")


def _static_difficulty_stars_html(diff_val, max_stars=6):
    rounded_value = max(0, min(max_stars, int(round(float(diff_val or 0)))))
    stars = "".join(
        f"<span class='{'is-filled' if star_index <= rounded_value else 'is-empty'}'>★</span>"
        for star_index in range(1, max_stars + 1)
    )
    return f"{stars}<span class='mc-static-diff-value'>{float(diff_val or 0):g}</span>"


def render_question_header(q_label, content, fpath, extra_html_label="", compact=False, prepared_meta=None, interactive_difficulty=True):
    st.markdown(f"### {q_label} {extra_html_label}", unsafe_allow_html=True)
    
    meta = prepared_meta if prepared_meta is not None else _cached_question_meta(content)
    diff = meta.get("难度星级", "").strip()
    tags = meta.get("标签", "").strip()
    remark = meta.get("备注", "").strip()
    render_cloze_source_trace(content, fpath, meta)

    try:
        diff_val = float(diff)
    except:
        diff_val = 0.0

    from utils.star_rating import st_star_rating
    
    pending_key = f"pending_diff_{fpath}"
    version_key = f"star_key_version_{fpath}"
    if compact:
        from utils.star_rating import st_star_rating
        compact_hash = hashlib.md5(f"compact:{fpath}:{q_label}".encode()).hexdigest()[:8]
        st.markdown("""
        <style>
        .mc-compact-meta-anchor {
            display: none !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.mc-compact-meta-anchor) {
            display: grid !important;
            grid-template-columns: minmax(218px, 230px) max-content max-content minmax(0, 1fr) !important;
            align-items: center !important;
            column-gap: 1rem !important;
            row-gap: 0.35rem !important;
            margin: 0.1rem 0 0.45rem !important;
            width: 100% !important;
            min-width: 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.mc-compact-meta-anchor) > div[data-testid="column"] {
            width: auto !important;
            min-width: 0 !important;
            max-width: none !important;
            flex: initial !important;
            padding: 0 !important;
        }
        div[data-testid="stMarkdownContainer"]:has(.mc-compact-meta-anchor) {
            display: none !important;
        }
        div[data-testid="column"]:has(.mc-compact-meta-anchor) iframe {
            width: 218px !important;
            min-width: 218px !important;
            max-width: 218px !important;
            height: 35px !important;
            display: block !important;
        }
        .mc-compact-meta-row {
            display: flex;
            align-items: center;
            gap: 0.45rem 0.65rem;
            flex-wrap: nowrap;
            margin: 0;
            white-space: nowrap;
            min-width: 0;
        }
        .mc-compact-meta-row .meta-title {
            color: #1f2328;
            font-size: 14px;
            font-weight: 700;
            line-height: 1.2;
        }
        .mc-compact-meta-row .badge-tag,
        .mc-compact-meta-row .badge-rem {
            display: inline-flex;
            align-items: center;
            padding: 2px 8px;
            font-size: 14px;
            font-weight: 700;
            line-height: 1.45;
            border-radius: 999px;
        }
        .mc-compact-meta-row .badge-tag {
            color: #0366d6;
            background-color: #f1f8ff;
            border: 1px solid #c8e1ff;
        }
        .mc-compact-meta-row .badge-rem {
            color: #7a5a00;
            background-color: #fff8dd;
            border: 1px solid #ead999;
        }
        .mc-static-diff-row {
            display: flex;
            align-items: center;
            gap: 0.3rem;
            min-height: 35px;
            white-space: nowrap;
        }
        .mc-static-diff-stars {
            display: inline-flex;
            align-items: center;
            gap: 1px;
            color: #d8dee9;
            font-size: 1.15rem;
            line-height: 1;
            letter-spacing: -0.02em;
        }
        .mc-static-diff-stars .is-filled {
            color: #f2b94b;
        }
        .mc-static-diff-stars .is-empty {
            color: #e5e7eb;
        }
        .mc-static-diff-value {
            margin-left: 0.25rem;
            color: #6e6e73;
            font-size: 0.82rem;
            font-weight: 700;
        }
        </style>
        """, unsafe_allow_html=True)
        compact_diff, compact_tag, compact_remark, compact_spacer = st.columns([1.15, 0.5, 0.5, 4], gap="small", vertical_alignment="center")
        with compact_diff:
            st.markdown(f'<span class="mc-compact-meta-anchor" data-key="{compact_hash}"></span>', unsafe_allow_html=True)
            if interactive_difficulty:
                new_diff = st_star_rating(label="难度星级：", value=diff_val, max_stars=6, key=f"compact_star_{compact_hash}_{st.session_state.get(version_key, 0)}")
                if new_diff is not None and new_diff != diff_val:
                    update_question_meta(fpath, "难度星级", str(new_diff))
                    st.session_state[version_key] = st.session_state.get(version_key, 0) + 1
                    st.rerun()
            else:
                st.markdown(
                    f"<div class='mc-static-diff-row'><span class='meta-title'>难度星级：</span>"
                    f"<span class='mc-static-diff-stars'>{_static_difficulty_stars_html(diff_val)}</span></div>",
                    unsafe_allow_html=True,
                )
        with compact_tag:
            tag_text = tags or "无标签"
            st.markdown(f"<div class='mc-compact-meta-row'><span class='meta-title'>标签：</span><span class='badge-tag'>{html.escape(tag_text)}</span></div>", unsafe_allow_html=True)
        with compact_remark:
            remark_text = remark or "无备注"
            st.markdown(f"<div class='mc-compact-meta-row'><span class='meta-title'>备注：</span><span class='badge-rem'>{html.escape(remark_text)}</span></div>", unsafe_allow_html=True)
        with compact_spacer:
            st.empty()
        return
    # --- 注入 CSS 实现紧凑同行布局与徽章样式 ---
    st.markdown("""
    <style>
    .meta-cell {
        display: flex;
        align-items: center;
        min-height: 40px;
        gap: 5px;
        white-space: nowrap;
    }
    .meta-cell .meta-title {
        color: #1f2328;
        font-size: 14px;
        font-weight: 700;
        line-height: 1;
        flex: 0 0 auto;
    }
    .meta-cell .meta-empty {
        color: #3f3a46;
        font-size: 14px;
        font-weight: 600;
        line-height: 1;
    }
    div[data-testid="stHorizontalBlock"]:has(.meta-row-marker) {
        display: grid !important;
        grid-template-columns: 190px minmax(72px, max-content) 36px minmax(72px, max-content) 36px minmax(0, 1fr) !important;
        gap: 4px !important;
        align-items: center !important;
        width: 100% !important;
        min-width: 0 !important;
        flex-wrap: nowrap !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.meta-row-marker) > div[data-testid="column"] {
        width: auto !important;
        min-width: 0 !important;
        max-width: none !important;
        flex: initial !important;
        padding: 0 !important;
    }
    div[data-testid="column"]:has(.meta-star-cell) {
        width: 190px !important;
        min-width: 190px !important;
        max-width: 190px !important;
        margin-right: 0 !important;
    }
    div[data-testid="column"]:has(.meta-tag-cell),
    div[data-testid="column"]:has(.meta-remark-cell) {
        flex: 0 1 auto !important;
        width: fit-content !important;
        min-width: 72px !important;
        max-width: 180px !important;
    }
    div[data-testid="column"]:has(.meta-action-cell),
    .mc-meta-action-column {
        flex: 0 0 36px !important;
        width: 36px !important;
        min-width: 36px !important;
        max-width: 36px !important;
        justify-content: flex-start !important;
    }
    div[data-testid="column"]:has(.meta-tag-action-cell) {
        margin-right: 0 !important;
    }
    div[data-testid="column"]:has(.meta-filler-cell) {
        flex: 1 1 auto !important;
        min-width: 0 !important;
    }
    div[data-testid="column"]:has(.meta-star-cell),
    div[data-testid="column"]:has(.meta-tag-cell),
    div[data-testid="column"]:has(.meta-remark-cell),
    div[data-testid="column"]:has(.meta-action-cell) {
        display: flex !important;
        align-items: center !important;
        min-height: 44px !important;
    }
    div[data-testid="column"]:has(.meta-star-cell) iframe {
        display: block !important;
        width: 190px !important;
        min-width: 190px !important;
        max-width: 190px !important;
        height: 35px !important;
        margin: 0 !important;
        padding: 0 !important;
        transform: translateY(1px);
    }
    div[data-testid="column"]:has(.meta-text-cell) p {
        margin: 0 !important;
        padding: 0 !important;
        line-height: 1 !important;
    }
    /* 淡灰色 + 按钮 */
    div[data-testid="column"]:has(.meta-action-cell) div[data-testid="stPopover"] > button,
    .mc-meta-action-popover button,
    .mc-meta-action-button {
        color: var(--mc-action-text) !important;
        background: var(--mc-action-bg) !important;
        border: 1px solid var(--mc-action-border) !important;
        padding: 0 !important;
        min-height: 36px !important;
        height: 36px !important;
        width: 36px !important;
        min-width: 36px !important;
        max-width: 36px !important;
        border-radius: 10px !important;
        font-size: 22px !important;
        font-weight: 800 !important;
        margin: 0 !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        position: relative !important;
        overflow: hidden !important;
        gap: 0 !important;
        text-shadow: none !important;
        box-shadow: var(--mc-action-shadow) !important;
        transform: translateY(0);
        transition: transform 0.14s ease, box-shadow 0.14s ease, background 0.14s ease !important;
    }
    div[data-testid="column"]:has(.meta-action-cell) div[data-testid="stPopover"] > button::after,
    .mc-meta-action-button::after {
        content: "";
        position: absolute;
        top: 1px;
        left: 2px;
        right: 2px;
        height: 45%;
        border-radius: 8px 8px 6px 6px;
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.36), rgba(255, 255, 255, 0));
        pointer-events: none;
    }
    div[data-testid="column"]:has(.meta-action-cell) div[data-testid="stPopover"],
    .mc-meta-action-popover {
        width: 36px !important;
        min-width: 36px !important;
        max-width: 36px !important;
    }
    div[data-testid="column"]:has(.meta-action-cell) div[data-testid="stPopover"] > button svg,
    .mc-meta-action-popover button svg,
    .mc-meta-action-popover button [data-testid="stIconMaterial"],
    .mc-meta-action-button svg,
    .mc-meta-action-button [data-testid="stIconMaterial"] {
        display: none !important;
    }
    div[data-testid="column"]:has(.meta-action-cell) div[data-testid="stPopover"] > button p,
    .mc-meta-action-popover button p,
    .mc-meta-action-button p {
        margin: 0 !important;
        line-height: 1 !important;
        font-size: 22px !important;
        color: var(--mc-action-text) !important;
    }
    div[data-testid="column"]:has(.meta-action-cell) div[data-testid="stPopover"] > button:hover,
    .mc-meta-action-popover button:hover,
    .mc-meta-action-button:hover {
        background: var(--mc-action-bg-hover) !important;
        border-color: var(--mc-action-border) !important;
        box-shadow: 0 8px 18px rgba(91, 33, 182, 0.16) !important;
        transform: translateY(-1px);
    }
    .mc-meta-action-button[aria-expanded="true"],
    .mc-meta-action-button:active {
        background: #b99ddd !important;
        border-color: #a789cc !important;
        box-shadow: 0 4px 10px rgba(91, 33, 182, 0.14) !important;
        transform: translateY(0);
    }
    .mc-meta-plus {
        display: block;
        position: relative;
        z-index: 1;
        color: var(--mc-action-text);
        font-size: 22px;
        font-weight: 800;
        line-height: 1;
        transform: translateY(-1px);
    }
    .tag-suggestion-title {
        color: #6b7280;
        font-size: 13px;
        font-weight: 700;
        margin: 8px 0 6px 0;
    }

    /* 现代徽章样式 (Badge) */
    .badge-tag {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        font-size: 14px; /* 调整为与难度标签一致的字号 */
        font-weight: 700;
        line-height: 1.5;
        color: #0366d6;
        background-color: #f1f8ff;
        border: 1px solid #c8e1ff;
        border-radius: 2em;
        margin-right: 4px;
    }
    .badge-rem {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        font-size: 14px; /* 调整为与难度标签一致的字号 */
        font-weight: 700;
        line-height: 1.5;
        color: #b08800;
        background-color: #fffdef;
        border: 1px solid #dfd8c2;
        border-radius: 4px;
        margin-right: 4px;
    }
    </style>
    """, unsafe_allow_html=True)

    components.html(
        """
        <script>
        (() => {
            const w = window.parent;
            const d = w.document;

            function closestColumn(node) {
                return node ? node.closest('div[data-testid="column"]') : null;
            }

            function paintActionButton(button) {
                if (!button) {
                    return;
                }
                const text = (button.textContent || "").trim();
                if (!text.includes("+") && !text.includes("＋")) {
                    return;
                }
                button.classList.add("mc-meta-action-button");
                if (!button.querySelector(".mc-meta-plus")) {
                    button.innerHTML = '<span class="mc-meta-plus">＋</span>';
                }
                Object.assign(button.style, {
                    color: "#332442",
                    background: "#d6c4ee",
                    border: "1px solid #b49ad2",
                    width: "36px",
                    minWidth: "36px",
                    maxWidth: "36px",
                    height: "36px",
                    minHeight: "36px",
                    padding: "0",
                    borderRadius: "10px",
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    position: "relative",
                    overflow: "hidden",
                    gap: "0",
                    textShadow: "none",
                    boxShadow: "0 5px 14px rgba(91, 33, 182, 0.12)",
                    transition: "transform 0.14s ease, box-shadow 0.14s ease, background 0.14s ease"
                });
                button.querySelectorAll('svg, [data-testid="stIconMaterial"]').forEach((icon) => {
                    icon.style.setProperty("display", "none", "important");
                });
                button.querySelectorAll("p, span").forEach((textNode) => {
                    if ((textNode.textContent || "").includes("+") || (textNode.textContent || "").includes("＋")) {
                        textNode.style.setProperty("color", "#332442", "important");
                        textNode.style.setProperty("font-size", "22px", "important");
                        textNode.style.setProperty("font-weight", "800", "important");
                        textNode.style.setProperty("line-height", "1", "important");
                        textNode.style.setProperty("margin", "0", "important");
                    }
                });
            }

            function applyMetaActionClasses() {
                d.querySelectorAll(".meta-action-cell").forEach((marker) => {
                    const column = closestColumn(marker);
                    if (!column) {
                        return;
                    }
                    column.classList.add("mc-meta-action-column");
                    column.querySelectorAll("button").forEach(paintActionButton);
                    column.querySelectorAll('div[data-testid="stPopover"]').forEach((popover) => {
                        popover.classList.add("mc-meta-action-popover");
                        popover.querySelectorAll("button").forEach((button) => {
                            button.classList.add("mc-meta-action-button");
                            paintActionButton(button);
                        });
                    });
                });
            }

            applyMetaActionClasses();
            w.setTimeout(applyMetaActionClasses, 50);
            w.setTimeout(applyMetaActionClasses, 200);
            w.setTimeout(applyMetaActionClasses, 600);

            if (w.__mcMetaActionObserver) {
                w.__mcMetaActionObserver.disconnect();
            }
            w.__mcMetaActionObserver = new w.MutationObserver(applyMetaActionClasses);
            w.__mcMetaActionObserver.observe(d.body, {
                childList: true,
                subtree: true
            });
        })();
        </script>
        """,
        height=0,
    )

    with st.container(border=True):
        # === 统一放在同一行：星级 | 标签 + 按钮 | 备注 + 按钮 ===
        c_star, c_tag_lbl, c_tag_btn, c_rem_lbl, c_rem_btn, c_filler = st.columns([1.65, 1.05, 0.5, 1.05, 0.5, 7.25], vertical_alignment="center", gap="small")

        with c_star:
            st.markdown("<span class='meta-row-marker meta-star-cell'></span>", unsafe_allow_html=True)
            # 使用更全局唯一的 key，防止在不同页面（全局浏览 vs 搜索结果）复用同一个文件时产生冲突
            unique_hash = hashlib.md5(f"{fpath}_{q_label}_{extra_html_label}".encode()).hexdigest()[:8]
            comp_key = f"star_rating_{unique_hash}_{st.session_state.get(version_key, 0)}"
            new_diff = st_star_rating(label="难度星级：", value=diff_val, max_stars=6, key=comp_key)

            if new_diff is not None and new_diff != diff_val:
                if diff_val == 0.0:
                    update_question_meta(fpath, "难度星级", str(new_diff))
                    st.session_state[version_key] = st.session_state.get(version_key, 0) + 1
                    st.rerun()
                else:
                    st.session_state[pending_key] = new_diff

        with c_tag_lbl:
            if tags:
                # 把逗号分隔的标签拆分成多个小徽章
                tag_html = "".join([f"<span class='badge-tag'>🏷️ {t.strip()}</span>" for t in tags.split("，") if t.strip()])
                st.markdown(f"<div class='meta-cell meta-text-cell meta-tag-cell'><span class='meta-title'>标签：</span>{tag_html}</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div class='meta-cell meta-text-cell meta-tag-cell'><span class='meta-title'>标签：</span><span class='meta-empty'>无标签</span></div>", unsafe_allow_html=True)

        with c_tag_btn:
            st.markdown("<span class='meta-action-cell meta-tag-action-cell'></span>", unsafe_allow_html=True)
            tag_popover_key = f"tag_popover_{fpath}_{st.session_state.get(f'tag_version_{fpath}', 0)}"
            with st.popover("＋", help="修改标签"):
                tag_input_key = f"tag_input_{tag_popover_key}"
                new_tags_str = st.text_input("编辑标签（逗号“，”分隔）", value=tags, key=tag_input_key)
                tag_suggestions = get_tag_history_suggestions(limit=5)
                if tag_suggestions:
                    st.markdown("<div class='tag-suggestion-title'>历史热门标签</div>", unsafe_allow_html=True)
                    for idx, item in enumerate(tag_suggestions):
                        tag = item["tag"]
                        count = item["count"]
                        st.button(
                            f"🏷️ {tag}  ×{count}",
                            key=f"tag_suggest_{idx}_{tag_popover_key}",
                            help="点击添加到标签输入框",
                            use_container_width=True,
                            on_click=_apply_tag_suggestion,
                            args=(tag_input_key, tag),
                        )
                if not tags:
                    if st.button("直接保存", key=f"tag_save_{tag_popover_key}", type="primary"):
                        update_question_meta(fpath, "标签", new_tags_str)
                        st.session_state[f'tag_version_{fpath}'] = st.session_state.get(f'tag_version_{fpath}', 0) + 1
                        st.rerun()
                else:
                    tc1, tc2 = st.columns(2)
                    with tc1:
                        if st.button("确认", key=f"tag_ok_{tag_popover_key}", type="primary"):
                            update_question_meta(fpath, "标签", new_tags_str)
                            st.session_state[f'tag_version_{fpath}'] = st.session_state.get(f'tag_version_{fpath}', 0) + 1
                            st.rerun()
                    with tc2:
                        if st.button("取消", key=f"tag_cancel_{tag_popover_key}", type="secondary"):
                            st.session_state[f'tag_version_{fpath}'] = st.session_state.get(f'tag_version_{fpath}', 0) + 1
                            st.rerun()

        with c_rem_lbl:
            if remark:
                st.markdown(f"<div class='meta-cell meta-text-cell meta-remark-cell'><span class='meta-title'>备注：</span><span class='badge-rem'>📝 {remark}</span></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div class='meta-cell meta-text-cell meta-remark-cell'><span class='meta-title'>备注：</span><span class='meta-empty'>无备注</span></div>", unsafe_allow_html=True)

        with c_rem_btn:
            st.markdown("<span class='meta-action-cell meta-rem-action-cell'></span>", unsafe_allow_html=True)
            rem_popover_key = f"rem_popover_{fpath}_{st.session_state.get(f'rem_version_{fpath}', 0)}"
            with st.popover("＋", help="修改备注"):
                new_rem_str = st.text_input("编辑备注", value=remark, key=f"rem_input_{rem_popover_key}")
                if not remark:
                    if st.button("直接保存", key=f"rem_save_{rem_popover_key}", type="primary"):
                        update_question_meta(fpath, "备注", new_rem_str)
                        st.session_state[f'rem_version_{fpath}'] = st.session_state.get(f'rem_version_{fpath}', 0) + 1
                        st.rerun()
                else:
                    rc1, rc2 = st.columns(2)
                    with rc1:
                        if st.button("确认", key=f"rem_ok_{rem_popover_key}", type="primary"):
                            update_question_meta(fpath, "备注", new_rem_str)
                            st.session_state[f'rem_version_{fpath}'] = st.session_state.get(f'rem_version_{fpath}', 0) + 1
                            st.rerun()
                    with rc2:
                        if st.button("取消", key=f"rem_cancel_{rem_popover_key}", type="secondary"):
                            st.session_state[f'rem_version_{fpath}'] = st.session_state.get(f'rem_version_{fpath}', 0) + 1
                            st.rerun()

        with c_filler:
            st.markdown("<span class='meta-filler-cell'></span>", unsafe_allow_html=True)

        # 处理未保存的星级变更弹窗（放到最后，避免打乱单行布局）
        if pending_key in st.session_state:
            st.warning(f"确认修改为 {st.session_state[pending_key]} 星吗？")
            bc1, bc2 = st.columns(2)
            with bc1:
                if st.button("✅ 确认", key=f"diff_ok_{fpath}", type="primary"):
                    final_diff = st.session_state[pending_key]
                    update_question_meta(fpath, "难度星级", str(final_diff))
                    del st.session_state[pending_key]
                    st.session_state[version_key] = st.session_state.get(version_key, 0) + 1
                    st.rerun()
            with bc2:
                if st.button("❌ 取消", key=f"diff_cancel_{fpath}", type="secondary"):
                    del st.session_state[pending_key]
                    st.session_state[version_key] = st.session_state.get(version_key, 0) + 1
                    st.rerun()

# ================= 辅助函数：搜索匹配 =================
import datetime

def clear_statistics_cache():
    get_statistics.clear()


def _filter_question_rows(rows, paper_type_scope=None):
    """Keep WK indexed, but isolate it from ordinary question-bank workflows."""
    filtered_rows = []
    for row in rows or []:
        paper_type = (row.get("试卷类型", "") or "").strip()
        if paper_type_scope:
            if paper_type != paper_type_scope:
                continue
        elif paper_type == "WK":
            continue
        filtered_rows.append(row)
    return filtered_rows

def _csv_index_cache_token():
    from utils.core_config import CSV_INDEX_PATH
    return file_change_token(CSV_INDEX_PATH)

@st.cache_data(show_spinner=False)
def _csv_index_cached(csv_token):
    from utils.csv_ops import read_csv_index
    return _filter_question_rows(read_csv_index())

@st.cache_data(show_spinner=False)
def _advanced_search_index_cached(csv_token, paper_type_scope=None):
    from utils.csv_ops import read_csv_index

    index_rows = []
    for row in _filter_question_rows(read_csv_index(), paper_type_scope):
        rel_path = (row.get("相对文件路径", "") or "").strip()
        abs_path = os.path.join(CHAPTERS_DIR, rel_path) if rel_path else ""
        filename = (row.get("文件名称", "") or "").strip()
        if filename and not filename.lower().endswith(".tex"):
            filename = filename + ".tex"

        stem = row.get("题干", "") or ""
        answer = row.get("答案", "") or ""
        solution = row.get("解析", "") or ""
        tags = row.get("标签", "") or ""
        remark = row.get("备注", "") or ""

        index_rows.append({
            "row": row,
            "file": filename,
            "path": abs_path,
            "type": (row.get("题型", "") or "").strip(),
            "stem": stem,
            "answer": answer,
            "solution": solution,
            "difficulty": row.get("难度星级", "") or "",
            "tags": tags,
            "remark": remark,
            "full_text": "\n".join([stem, answer, solution, tags, remark]),
        })
    return index_rows

@st.cache_data(ttl=10)
def get_statistics():
    from services.statistics_service import get_statistics_sqlite_first

    return get_statistics_sqlite_first()

def render_statistics_dashboard():
    from utils.charts import generate_heatmap_html, generate_activity_curve_html, generate_echarts_bar_html, generate_echarts_pie_html
    stats = get_statistics()

    st.markdown("### 📊 数据统计")

    # 统计页视觉层：只调整展示质感，不改统计数据。
    st.markdown("""
    <style>
    @keyframes statsFadeUp {
        from {
            opacity: 0;
            transform: translateY(8px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    div[data-testid="stMetric"],
    .stats-chart-title {
        animation: statsFadeUp 0.38s ease both;
    }
    div[data-testid="stMetric"] {
        position: relative;
        min-height: 112px;
        background:
            linear-gradient(180deg, rgba(255,255,255,0.86), rgba(255,255,255,0.68)),
            rgba(255,255,255,0.72);
        border: 1px solid rgba(109, 40, 217, 0.10);
        padding: 14px 18px 14px 20px;
        border-radius: 10px;
        box-shadow: 0 8px 24px rgba(31, 35, 48, 0.055);
        display: flex;
        flex-direction: column;
        justify-content: center;
        overflow: hidden;
        transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease, background 0.16s ease;
    }
    div[data-testid="stMetric"]::before {
        content: "";
        position: absolute;
        left: 0;
        top: 14px;
        bottom: 14px;
        width: 3px;
        border-radius: 0 999px 999px 0;
        background: linear-gradient(180deg, #a78bfa, #007aff);
        opacity: 0.82;
    }
    div[data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        border-color: rgba(109, 40, 217, 0.18);
        box-shadow: 0 14px 34px rgba(31, 35, 48, 0.09);
        background: rgba(255,255,255,0.9);
    }
    div[data-testid="stMetric"] label,
    div[data-testid="stMetric"] [data-testid="stMetricLabel"] {
        color: #5f6472 !important;
        font-size: 0.9rem !important;
        font-weight: 650 !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: #242733 !important;
        font-weight: 680 !important;
        letter-spacing: 0 !important;
    }
    .stats-chart-title {
        margin: 20px 0 10px 4px;
        color: #20232d;
        font-size: 1.05rem;
        font-weight: 720;
        letter-spacing: 0;
    }
    .stats-source-row {
        display: flex;
        align-items: center;
        gap: 8px;
        margin: 2px 0 14px 2px;
        color: #5f6472;
        font-size: 0.88rem;
        line-height: 1.35;
    }
    .stats-source-badge {
        display: inline-flex;
        align-items: center;
        min-height: 1.45rem;
        padding: 0.1rem 0.58rem;
        border-radius: 999px;
        background: #f5f3ff;
        color: #5b21b6;
        border: 1px solid rgba(109, 40, 217, 0.14);
        font-size: 0.78rem;
        font-weight: 720;
        white-space: nowrap;
    }
    .stats-source-detail {
        color: #7b8190;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    div[data-testid="stVerticalBlock"]:has(.stats-chart-title) iframe {
        border-radius: 12px !important;
        box-shadow: 0 10px 30px rgba(31, 35, 48, 0.065) !important;
        transition: transform 0.16s ease, box-shadow 0.16s ease, filter 0.16s ease;
    }
    div[data-testid="stVerticalBlock"]:has(.stats-chart-title) iframe:hover {
        transform: translateY(-2px);
        box-shadow: 0 16px 40px rgba(31, 35, 48, 0.10) !important;
        filter: saturate(1.03);
    }
    </style>
    """, unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="stats-source-row">
            <span>数据来源</span>
            <span class="stats-source-badge">{html.escape(stats.get("source_label", "未知"))}</span>
            <span class="stats-source-detail">{html.escape(stats.get("source_detail", ""))}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if stats.get("fallback_error"):
        st.caption(stats["fallback_error"])
    elif stats.get("sqlite_primary"):
        st.caption("当前统计已直接读取 SQLite 正式库；CSV 和旧 TeX 只作为旧安装环境的兼容兜底。")

    # 计算平均难度
    avg_diff = 0.0
    if stats.get("difficulty_count", 0) > 0:
        avg_diff = stats["total_difficulty"] / stats["difficulty_count"]

    # 指标数据 - 恢复8个卡片两行排列
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("题库总题目数", stats["total_questions"])
    c2.metric("题库Tikz总数", stats["total_tikz"])
    c3.metric("今日新增题目", stats["today_new_questions"])
    c4.metric("今日改动题目", stats["today_mod_questions"])

    st.write("")
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("今日新增Tikz", stats["today_new_tikz"])
    c6.metric("今日改动Tikz", stats["today_mod_tikz"])
    c7.metric("平均难度星级", f"{avg_diff:.1f} ★" if avg_diff > 0 else "N/A")

    # 获取最高频的三个标签
    top_tags = sorted(stats.get("tag_counts", {}).items(), key=lambda x: x[1], reverse=True)[:3]
    top_tags_str = "、".join([t[0] for t in top_tags]) if top_tags else "暂无"
    c8.metric("热门标签", top_tags_str)

    st.write("")

    # 热力图与代码活跃时段曲线
    r2_c1, r2_c2 = st.columns([1, 1])
    with r2_c1:
        heatmap_html = generate_heatmap_html(stats["daily_activity"])
        st.markdown(heatmap_html, unsafe_allow_html=True)

    with r2_c2:
        import streamlit.components.v1 as components
        hourly_activity_by_day = stats.get("hourly_activity_by_day", {})
        components.html(generate_activity_curve_html(hourly_activity_by_day), height=300)

    st.write("")

    # 更多有趣的数据统计：图表区
    r3_c1, r3_c2 = st.columns([1, 1])
    with r3_c1:
        st.markdown('<div class="stats-chart-title">📈 各知识板块题目分布</div>', unsafe_allow_html=True)
        subj_counts = stats.get("subject_counts", {})
        components.html(generate_echarts_bar_html(subj_counts, "各知识板块题目分布"), height=370)

    with r3_c2:
        st.markdown('<div class="stats-chart-title">🍰 题型占比分布 & 难度分布</div>', unsafe_allow_html=True)
        type_counts = stats.get("type_counts", {})
        diff_counts = stats.get("difficulty_dist", {})
        components.html(generate_echarts_pie_html(type_counts, diff_counts, "题型与难度分布"), height=370)

    if stats.get("sqlite_primary"):
        st.write("")
        st.markdown('<div class="stats-chart-title">🗃️ SQLite 结构化维度</div>', unsafe_allow_html=True)
        rel_c1, rel_c2, rel_c3, rel_c4 = st.columns(4)
        rel_c1.metric("试卷来源关联", stats.get("paper_relation_count", 0))
        rel_c2.metric("专题收录题目", stats.get("topic_linked_questions", 0))
        rel_c3.metric("教材关联题目", stats.get("book_linked_questions", 0))
        rel_c4.metric("图片资源", stats.get("asset_count", 0))

        def _stats_table(title, values, value_label="题目数", limit=12):
            st.markdown(f"**{title}**")
            items = sorted((values or {}).items(), key=lambda item: item[1], reverse=True)[:limit]
            if not items:
                st.caption("暂无数据")
                return
            st.dataframe(
                [{"名称": key, value_label: value} for key, value in items],
                use_container_width=True,
                hide_index=True,
                height=min(420, 38 * len(items) + 38),
            )

        s1, s2, s3 = st.columns([1, 1, 1])
        with s1:
            _stats_table("按年份覆盖", stats.get("year_counts", {}))
            _stats_table("按卷别覆盖", stats.get("source_series_counts", {}))
        with s2:
            _stats_table("按文理/新高考覆盖", stats.get("track_counts", {}))
            _stats_table("按修订来源统计", stats.get("revision_source_counts", {}), value_label="修订次数")
        with s3:
            _stats_table("专题收录分布", stats.get("topic_counts", {}))
            _stats_table("教材来源分布", stats.get("book_counts", {}))


# ================= 页面：规范说明 =================
def page_manual():
    st.header("📖 题库规范说明")
    st.markdown("""
    **📂 一、 文件命名规范**

    所有题目的 `.tex` 文件必须严格按照以下 **“五段式”** 结构命名，各部分之间使用英文连字符 `-` 连接，格式为：
    `<font color="red">**年份-试卷类别-试卷名称-题号-知识板块.tex**</font>`
    *示例：`2024-G-新高考I卷-12-数列，集合.tex`*
    - **年份**：四位纯数字（如 `2024`）；
    - **试卷类别**：必须是系统预设的缩写代码，仅限 `G`(高考题)、`M`(模拟题)、`W`(外国题)、`XK`(学考题)、`XS`(线上联考)；
    - **试卷名称**：明确试卷全称，如 `新课标I卷`、`浙江学考` 等，尽量避免包含特殊符号；
    - **题号**：纯数字（如 `12`）；
    - **知识板块**：如涉及多个板块，必须用**中文全角逗号 `，`** 分隔，且将**最核心的主板块放在最前**（如 `函数，导数`）。

    **📝 二、 LaTeX 源码书写格式**

    每个题目文件内部必须且仅包含一个完整的 `problem` 环境：
    ```latex
    \\begin{problem}{年份}{试卷类别}{试卷名称}{题号}{知识板块}
    这里是具体的题目题干内容...
    \\end{problem}
    ```
    如果题目附带详细解析，请使用 `\\begin{answer}` 和 `\\begin{solutions}` 环境：
    ```latex
    \\begin{answer}
    这里是答案...
    \\end{answer}

    \\begin{solutions}
    这里是解析...
    \\end{solutions}
    ```

    **💡 三、 附加规范**
    - **选择题**：请使用 `\\begin{choices}` 与 `\\choice{{选项内容}}` 宏包结构，务必确保选项内容被**两层大括号**包裹。
    - **TikZ 绘图**：直接在题干中插入 `\\begin{tikzpicture}...\\end{tikzpicture}` 代码，系统会自动提取。
    - **非 TikZ 图片**：在 SQLite 预览编辑里用“添加/管理图片”登记，TeX 中用 `\\questionasset{引用名}` 引用。

    **🖼️ 四、 非 TikZ 图片规范**
    - **登记入口**：在 SQLite 预览编辑中点击“添加/管理图片”，默认不展开，只有需要插入图片或附件时再打开。
    - **引用名**：每张图单独填写引用名，建议只使用英文、数字、下划线或短横线，例如 `problem_01`、`solution_graph`。
    - **源码占位**：题干、答案或解析中需要显示图片的位置写 `\\questionasset{引用名}`。
    - **仅登记，不改 TeX**：只复制文件并登记到 SQLite，不自动改源码，适合先整理资源再手动排版。
    - **多图顺序**：最终显示顺序以 TeX 源码中多个 `\\questionasset{...}` 的先后位置为准。
    - **后续扩展**：数据库大修后，图片尺寸、裁剪信息、来源页码、资源用途等字段也应同步写入这里作为规范说明。

    **✍️ 五、 SQLite 录入问题规范**
    - **入口定位**：左侧栏的“录入问题”面向新版 SQLite 草稿库；旧“录入新题”继续服务 `.tex` 文件、OCR、批量文件写入和挖空题生成。
    - **写入原则**：录入问题只写入 `question_import_draft`，不会直接写正式题库，也不会修改旧 `.tex` 源文件。
    - **单题录入**：用于人工精修一题，字段包括来源、题型、难度、官方标记、题干、选项、答案、解析、标签、备注和图片草稿路径。
    - **批量试题录入**：用于粘贴多题 TeX；系统优先识别 `---xxx.tex---` 分隔符，其次按多个 `problem` 环境拆分。
    - **同卷试题录入**：多题共享年份、卷别、文理/新高考和试卷名称；题号优先从 `problem` 头读取，读不到时按顺序编号。
    - **同书试题录入**：多题共享教材名称、册次/年级、页码和栏目；后续审核时可进一步维护教材来源关系。
    - **选项填写**：单题模式只填写选项内部 TeX；系统保存和导出时统一生成 `\\choice{{...}}`。

    **🧰 六、 本地维护与升级规范**
    - **入口**：工具箱 → 本地维护与升级。
    - **数据库升级**：先检查或预览 schema 迁移；真正应用迁移必须输入 `APPLY_SCHEMA_MIGRATION`。
    - **程序更新**：先生成 dry-run 更新计划；真正执行 GitHub 拉取、依赖安装和快速检查必须输入 `APPLY_LOCAL_UPDATE`。
    - **数据迁移包**：用于备份或换电脑，默认包含 SQLite 与题目图片；旧 TeX、reports、exports 需要手动勾选。
    - **恢复数据包**：默认只 dry-run；真正恢复必须输入 `RESTORE_LOCAL_BUNDLE`，避免误覆盖本地题库。
    - **GitHub 边界**：`data/`、`assets/questions/`、`reports/`、`exports/` 和 `.env` 属于本地私有数据，不上传。

    **📚 七、专题收录规范**
    - **入口定位**：左侧栏“专题收录”用于维护 SQLite 中的大专题、小专题与专题题目关系，不替代原有组卷服务。
    - **专题层级**：`大专题` 负责目录归类，`专题名称` 负责具体专题，`文件名称` 是导出专题 TeX 时的默认文件名。
    - **收录方式**：支持按题目编号/qid、整张试卷、整本教材或教材栏目收录题目；同一题可出现在多个专题中。
    - **分组与排序**：`group_name` 与 `sort_order` 只影响该专题内的展示和导出顺序，不修改题目本体。
    - **专题引言**：`试题引言` 会插入专题题目部分前，`答案引言` 会插入答案部分前，适合写专题导语、方法说明或分层训练提示。
    - **导出边界**：专题导出写入 `exports/topic_collection_exports/`，属于本地生成文件，不提交到 GitHub。
    """, unsafe_allow_html=True)

def page_system_intro():
    st.header("📘 项目体系介绍（录入 · 浏览 · 标签 · 组卷）")
    st.markdown("""
### 🎯 这套系统解决什么问题？

这是一套面向高中数学的题库项目管理系统：以 `.tex` 为数据单元，把“题目内容、标签元数据、索引检索、批量维护、组卷导出”统一在一个可视化工作流里，做到：

- 🧱 题目文件结构规范、可长期维护
- 🔎 检索与定位迅速（多维筛选/全文查找/三级查找）
- 🏷️ 标签与元数据可视化修改（并自动同步文件名/索引）
- 🖨️ 支持按模板组卷导出
- 🧠 可选的 AI 辅助：图片转写、标签提取、解答生成

---

### 📚 0) 关于本项目

**GitHub 项目链接：** [MathCyclus - Lingxi Question Bank Assistant](https://github.com/JinLingxi/MathCyclus---Lingxi-Question-Bank-Assistant)

**知乎 AI Works 页面：** [AI Works - MathCyclus高中数学题库 - 知乎](https://www.zhihu.com/project/detail/180133)

**创作感想文章：** [关于本项目的一些创作感想](https://www.zhihu.com/question/2052717294719956381/answer/2053305696041677288)

欢迎加入用户群沟通交流。
    """, unsafe_allow_html=True)

    user_group_img_path = os.path.join(BASE_DIR, "fig", "用户群.png")
    if os.path.exists(user_group_img_path):
        st.image(user_group_img_path, caption="用户群", width=260)

    st.markdown("""
### 🗂️ 1) 数据与目录结构（“文件即数据库”）

**核心原则：`.tex` 文件是单一事实来源（Source of Truth）。**

- 每道题对应一个 `.tex` 文件
- 物理归档采用 “知识板块/年份/文件.tex” 的层级组织
- 题内的标签与元数据会被写入专用的 Label Data 注释块，确保题目“自描述”

---

### 🧾 2) 文件命名规则（五段式，强约束）

文件名必须严格使用：

`年份-试卷类别-试卷名称-题号-知识板块.tex`

示例：`2024-G-上海卷-12-数列，集合.tex`

- 📅 年份：四位数字（如 `2024`）
- 🧩 试卷类别：系统预设代码（如 `G/M/W/XK/XS`）
- 🧾 试卷名称：建议使用普通文字，避免特殊符号
- 🔢 题号：纯数字（如 `12`）
- 🧠 知识板块：多标签用中文全角逗号 `，` 分隔；**首个为主板块**（决定题目归档目录）

---

### ✍️ 3) LaTeX 内容结构（题干、答案、解析）

每个文件内部必须且仅包含一个 `problem` 环境，且 5 个参数与文件名五段信息一致：

```latex
\\begin{problem}{年份}{试卷类别}{试卷名称}{题号}{知识板块}
题干内容...
\\end{problem}
```

如果有答案与解析（推荐），放在 `\\end{problem}` 之后：

```latex
\\begin{answer}
最终答案
\\end{answer}

\\begin{solutions}
解析步骤...
\\end{solutions}
```

补充约定：

- 🧩 选择题：用 `choices/choice` 结构（选项内容必须双层大括号）
- 🧑‍🎨 TikZ：可直接写在题干内；系统会在保存/维护过程中自动处理相关图资源
- 🖼️ 非 TikZ 图片：通过 SQLite 预览编辑里的“添加/管理图片”登记，题干、答案或解析中用 `\\questionasset{引用名}` 占位

---

### 🖼️ 4) 非 TikZ 图片与附件引用

非 TikZ 图片暂时采用“附件登记 + TeX 占位符”的方式，不直接把图片二进制塞进题目源码：

- `引用名`：每张上传图片都需要一个引用名，建议只使用英文、数字、下划线或短横线，例如 `problem_01`、`solution_graph`。
- `存储位置`：登记后文件会复制到 `assets/questions/<question_id>/`，当前实现会用引用名作为保存文件名的主体。
- `TeX 写法`：需要显示图片的位置写 `\\questionasset{引用名}`，系统预览时会把它解析成对应图片。
- `仅登记，不改 TeX`：只把图片记录到 SQLite，不自动插入占位符；适合先整理图片，再手动决定插入位置。
- `多图顺序`：数据库资源列表按资源类型、排序号、资源 ID 排列；题目正文实际显示顺序以 TeX 中多个 `\\questionasset{...}` 的出现位置为准。
- `未来扩展`：后续如果数据库 schema 大修，可把引用名、图片用途、版面尺寸、来源页码、裁剪信息作为独立字段，而不是只依赖文件名。

### 🏷️ 5) ID / 难度 / 标签：Label Data 元数据机制

为了让题目文件可长期维护与可追溯，系统把元数据写在题目文件内部的注释块中：

- 🆔 ID：每题唯一标识（用于跨文件移动/重命名时保持引用稳定）
- ⭐ 难度星级：0–6（支持 0.5 步长）
- 🏷️ 标签：自定义标签（与知识板块不同，偏“属性标签”）
- 📝 备注：人工补充说明
- 📌 组卷引用次数：用于统计与推荐

这些字段存储在题目文件里的 `% === Begin Label Data === ... % === End Label Data ===` 区块中。

---

### ⚡ 6) CSV 索引：加速检索的缓存层

系统会维护一个 `utils/题库索引表.csv` 作为“高速缓存索引”来提升检索速度：

- 🔁 索引可通过扫描全库重新生成（以 `.tex` 为准）
- ✅ 即便 CSV 丢失，也能依靠 `.tex` 里的 Label Data 重新构建
    - 🚀 数据统计优先读取 SQLite 正式库；CSV 只作为旧安装环境下的兼容缓存
- 🧯 CSV 写入前会做基础校验，降低重复 ID、关键字段缺失导致索引损坏的风险

（对应脚本：`utils/init_csv_index.py`）

---

### 🧱 7) 工程模块分工（给开源读者的快速地图）

如果你是第一次阅读这个项目，可以按下面的层次理解代码：

- `question_bank_app.py`：主应用入口，负责 Streamlit 页面、交互状态、业务流程串联
- `utils/core_config.py`：全局路径、试卷类型、知识板块等基础配置
- `utils/csv_ops.py`：题库索引的读取、写入、增量更新与字段解析
- `utils/latex_ops.py`：LaTeX 题目结构处理、TikZ 提取、题目重命名与保存辅助
- `utils/tikz_ops.py`：TikZ 编译、缓存与预览渲染
- `utils/charts.py`：数据统计页面的图表渲染
- `services/file_service.py`：原子写入、覆盖备份等文件安全能力
- `services/ai_service.py`：AI 接口地址规范化、请求封装与 JSON 提取
- `services/question_service.py`：题目创建、查重指纹和重复题扫描
- `services/operation_log.py`：批量操作记录与维护审计
- `Test Paper Group/主题模板/`：组卷导出的 LaTeX 模板来源

整体设计思路是：主应用负责“把流程跑通”，服务层负责“把单个动作做稳”。新版结构以 SQLite 作为主存储，旧 `.tex` 文件保留为迁移来源、人工备份和 TeX 兼容导出目标。

---

### 🛡️ 8) 稳定性与数据安全设计

题库项目的核心风险不是页面显示，而是“误覆盖、索引错乱、题目 ID 重复、批量操作难回退”。因此系统内部做了几层保护：

- SQLite 正式库是新版结构化题库的主数据源；旧 `.tex` 与 CSV 保留为兼容层和迁移来源
- 覆盖保存时使用原子写入，避免写到一半导致文件损坏
- 修改既有题目或批量处理时，会尽量在 `.backups/` 中保留覆盖前副本
- CSV 写入前会检查关键字段与重复 ID，发现异常时阻止写入
- 搜索缓存会跟随 CSV 文件变化自动失效，减少“刚保存但搜索不到”的情况

如果出现搜索结果异常、统计不准确、题目移动后找不到，优先执行“工具箱”中的一键重建/同步题库索引。

---

### 🧭 9) 日常使用工作流（给协作者的最短路径）

**📝 录入新题**

- 支持单题/批量/同卷录入
- 单题录入支持实时预览、查找替换、AI 自动打标签
- 可选 “本次录入同时生成解答”，并可选 “快速模式”

**🔍 全局浏览与编辑**

- 面向“找题 + 改题”的主工作台
- 支持预览、源码编辑保存、AI 生成解答、加入/移除组卷
- 在标签修改面板中可改年份/试卷类别/试卷名/题号/知识板块，并自动同步文件名与索引

**🔎 三级查找**

- 面向“多条件精确过滤”的检索入口
- 适合做专题筛选、交叉检索与快速定位

**🛠️ 工具箱**

- 面向“全库/批量维护”的工具集合
- 适合做批量规范化、批量修复、批量结构调整、题目查重和操作记录查看

**🖨️ 组卷服务**

- 以模板为核心的排版与导出流程
- 读取 `Test Paper Group/主题模板/` 下的主题模板，并在导出目录生成成品

---

### 🧩 10) 推荐的维护习惯

为了让题库长期可维护，建议按下面的方式协作：

- 新题录入后先检查预览，再补充难度、标签、备注
- 不手动复制已有题目的 ID；ID 应保持唯一
- 不直接把 CSV 当主数据库编辑；需要修复时优先重建索引
- 批量改名、批量修复前，先确认目标范围
- 导出文件、LaTeX 编译产物、临时缓存不应作为题库核心数据维护
- 修改规则类代码后，至少检查一次录入、搜索、标签修改和组卷导出主流程

---

### 🔭 11) 适合二次开发的方向

这个项目的后续扩展可以围绕“题库质量”和“教研效率”展开：

- 更细的标签体系：考点、方法、易错点、能力层级
- 更稳定的批量导入校验：录入前预检文件名、题号、ID、题型
- 更智能的组卷策略：按难度、知识点覆盖率、近年频次进行约束
- 更清晰的题目版本记录：记录每道题的修改历史与来源变化
- 更完整的本地部署方案：后续可再考虑封装为桌面应用或 exe

""", unsafe_allow_html=False)


# ================= 页面：三级查找 =================
# ================= 页面：三级查找嵌入组件 =================
def render_advanced_search_inline(compact=False, search_result_count=None):
    results_page_size_options = [5, 10, 15, 20]
    default_results_page_size = 10
    if st.session_state.get("adv_results_page_size") not in (None, *results_page_size_options):
        del st.session_state["adv_results_page_size"]
    st.markdown("""
    <style>
    div[data-testid="stMarkdownContainer"]:has(#adv-search-inputs-anchor),
    div[data-testid="stMarkdownContainer"]:has(#adv-search-compact-inputs-anchor),
    div[data-testid="stMarkdownContainer"]:has(#adv-search-btn-anchor),
    div[data-testid="stMarkdownContainer"]:has(#adv-search-info-anchor),
    div[data-testid="stMarkdownContainer"]:has(#adv-search-compact-btn-anchor),
    div[data-testid="stMarkdownContainer"]:has(#adv-search-compact-info-anchor),
    div[data-testid="stMarkdownContainer"]:has(#adv-search-pager-anchor) {
        display: none !important;
        margin: 0 !important;
        padding: 0 !important;
        height: 0 !important;
    }
    div[data-testid="stHorizontalBlock"]:has(#adv-search-inputs-anchor) {
        display: grid !important;
        grid-template-columns: minmax(0, 2fr) minmax(96px, 112px) minmax(320px, 1fr) !important;
        width: 100% !important;
        min-width: 0 !important;
        align-items: stretch !important;
        gap: 1rem !important;
    }
    div[data-testid="stHorizontalBlock"]:has(#adv-search-inputs-anchor) > div[data-testid="column"] {
        min-width: 0 !important;
        width: auto !important;
        max-width: none !important;
        flex: initial !important;
    }
    div[data-testid="column"]:has(#adv-search-inputs-anchor) {
        overflow: hidden !important;
        margin-top: 0 !important;
        padding-top: 0 !important;
    }
    div[data-testid="column"]:has(#adv-search-inputs-anchor) div[data-testid="stHorizontalBlock"] {
        display: grid !important;
        grid-template-columns: minmax(0, 1fr) minmax(0, 2fr) !important;
        width: 100% !important;
        min-width: 0 !important;
        align-items: center !important;
        gap: 0.75rem !important;
        margin: 0 0 0.75rem !important;
    }
    div[data-testid="column"]:has(#adv-search-inputs-anchor) div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
    div[data-testid="column"]:has(#adv-search-inputs-anchor) div[data-testid="stElementContainer"] {
        min-width: 0 !important;
        width: auto !important;
        max-width: none !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    div[data-testid="column"]:has(#adv-search-inputs-anchor) div[data-testid="stSelectbox"],
    div[data-testid="column"]:has(#adv-search-inputs-anchor) div[data-testid="stTextInput"],
    div[data-testid="column"]:has(#adv-search-inputs-anchor) div[data-baseweb="select"] {
        width: 100% !important;
        max-width: none !important;
    }
    div[data-testid="column"]:has(#adv-search-inputs-anchor) div[data-baseweb="select"] > div,
    div[data-testid="column"]:has(#adv-search-inputs-anchor) div[data-testid="stTextInput"] input {
        min-height: 42px !important;
        height: 42px !important;
    }
    div[data-testid="column"]:has(#adv-search-btn-anchor) {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        height: 196px !important;
        min-height: 196px !important;
        max-height: 196px !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    div[data-testid="column"]:has(#adv-search-btn-anchor) > div[data-testid="stVerticalBlock"] {
        width: 100% !important;
        height: 100% !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 0 !important;
    }
    div[data-testid="column"]:has(#adv-search-btn-anchor) button {
        width: 96px !important;
        min-width: 96px !important;
        max-width: 96px !important;
        height: 176px !important;
        min-height: 176px !important;
        max-height: 176px !important;
        padding: 0.75rem !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: center !important;
        justify-content: center !important;
        border-radius: 10px !important;
        white-space: normal !important;
    }
    div[data-testid="column"]:has(#adv-search-btn-anchor) button p {
        white-space: pre-wrap !important;
        word-break: keep-all !important;
        text-align: center !important;
        line-height: 1.35 !important;
        margin: 0 !important;
    }
    div[data-testid="column"]:has(#adv-search-info-anchor) {
        display: flex !important;
        align-items: flex-start !important;
        height: 196px !important;
        min-height: 196px !important;
        max-height: 196px !important;
        padding: 0 !important;
    }
    div[data-testid="column"]:has(#adv-search-info-anchor) div[data-testid="stAlert"] {
        width: 100% !important;
        min-height: 64px !important;
        height: 64px !important;
        max-height: 64px !important;
        box-sizing: border-box !important;
        margin: 0 !important;
        box-shadow: none !important;
        filter: none !important;
        overflow: hidden !important;
    }
    div[data-testid="column"]:has(#adv-search-info-anchor) div[data-testid="stAlert"] > div {
        box-shadow: none !important;
        filter: none !important;
    }
    div[data-testid="column"]:has(#adv-search-left-anchor) div[data-testid="column"]:has(#adv-search-btn-anchor),
    div[data-testid="column"]:has(#adv-search-left-anchor) div[data-testid="column"]:has(#adv-search-info-anchor) {
        height: auto !important;
        min-height: 0 !important;
        max-height: none !important;
    }
    div[data-testid="column"]:has(#adv-search-left-anchor) div[data-testid="column"]:has(#adv-search-btn-anchor) button {
        width: 100% !important;
        min-width: 0 !important;
        max-width: none !important;
        height: 48px !important;
        min-height: 48px !important;
        max-height: 48px !important;
    }
    div[data-testid="column"]:has(#adv-search-left-anchor) div[data-testid="column"]:has(#adv-search-info-anchor) div[data-testid="stAlert"] {
        height: auto !important;
        min-height: 64px !important;
        max-height: none !important;
    }
    div[data-testid="column"]:has(#adv-search-left-anchor) div[data-testid="stButton"] > button {
        width: 100% !important;
        min-width: 0 !important;
        max-width: none !important;
        min-height: 44px !important;
        height: 44px !important;
        max-height: 44px !important;
        padding: 0 1rem !important;
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        justify-content: center !important;
        border-radius: 10px !important;
        white-space: nowrap !important;
    }
    div[data-testid="column"]:has(#adv-search-left-anchor) div[data-testid="stButton"] > button p {
        white-space: nowrap !important;
        word-break: keep-all !important;
        line-height: 1.2 !important;
        margin: 0 !important;
    }
    div[data-testid="column"]:has(#adv-search-left-anchor) div[data-testid="stRadio"] div[role="radiogroup"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: center !important;
        gap: 0.35rem !important;
    }
    div[data-testid="column"]:has(#adv-search-left-anchor) div[data-testid="stRadio"] label {
        width: auto !important;
        min-width: 0 !important;
        margin: 0 !important;
        padding-right: 0.2rem !important;
        white-space: nowrap !important;
    }
    div[data-testid="column"]:has(#adv-search-left-anchor) div[data-testid="stRadio"] label p {
        white-space: nowrap !important;
        font-size: 0.92rem !important;
        line-height: 1.15 !important;
    }
    .mc-adv-result-summary {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.75rem;
        margin: 1rem 0 0.75rem;
    }
    .mc-adv-result-summary h3 {
        margin: 0;
        font-size: 1.16rem;
        line-height: 1.25;
    }
    .mc-adv-result-summary span {
        color: #4c1d95;
        font-weight: 750;
        font-size: 0.98rem;
        white-space: nowrap;
    }
    div[data-testid="stHorizontalBlock"]:has(#adv-search-pager-anchor) {
        display: grid !important;
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) !important;
        gap: 0.75rem !important;
        align-items: end !important;
    }
    div[data-testid="stHorizontalBlock"]:has(#adv-search-pager-anchor) > div[data-testid="column"] {
        width: auto !important;
        min-width: 0 !important;
        max-width: none !important;
        flex: initial !important;
    }
    div[data-testid="stHorizontalBlock"]:has(#adv-search-pager-anchor) div[data-testid="stSelectbox"],
    div[data-testid="stHorizontalBlock"]:has(#adv-search-pager-anchor) div[data-testid="stNumberInput"],
    div[data-testid="stHorizontalBlock"]:has(#adv-search-pager-anchor) div[data-baseweb="select"] {
        width: 100% !important;
        min-width: 0 !important;
    }
    @media (max-width: 900px) {
        div[data-testid="stHorizontalBlock"]:has(#adv-search-inputs-anchor) {
            grid-template-columns: minmax(0, 1fr) !important;
            gap: 0.75rem !important;
        }
        div[data-testid="column"]:has(#adv-search-btn-anchor),
        div[data-testid="column"]:has(#adv-search-info-anchor) {
            height: auto !important;
            min-height: 0 !important;
            max-height: none !important;
        }
        div[data-testid="column"]:has(#adv-search-btn-anchor) button {
            width: 100% !important;
            min-width: 0 !important;
            max-width: none !important;
            height: 48px !important;
            min-height: 48px !important;
            max-height: 48px !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)

    def on_adv_search():
        if not _adv_search_has_query():
            st.session_state["adv_search_active"] = False
            st.toast("请输入至少一个关键词后再开始查找。", icon="⚠️")
            return
        st.session_state["adv_search_active"] = True
        st.session_state["adv_results_page"] = 1
        st.session_state["adv_results_page_size"] = 10

    if compact:
        if st.button("❌ 退出检索", use_container_width=True):
            st.session_state["adv_search_active"] = False
            st.rerun()

    search_mode = st.radio(
        "检索模式",
        ["精确筛选", "混合搜索", "语义搜索"],
        horizontal=True,
        key="adv_search_mode",
        help="精确筛选使用字段匹配；混合搜索和语义搜索需要配置 embedding 模型。",
    )
    if search_mode != "精确筛选":
        st.text_input(
            "语义描述",
            placeholder="例如：含参数的函数单调性与最值问题",
            key="adv_semantic_query",
            on_change=on_adv_search,
        )

    search_opts = ["全文内容", "题目类型", "题目内容", "解答内容", "难度星级", "标签"]

    if compact:
        st.markdown('<div id="adv-search-compact-inputs-anchor"></div>', unsafe_allow_html=True)
        t1 = st.selectbox("一级类型", search_opts, index=0, key="adv_t1")
        if t1 == "题目类型":
            q1 = st.selectbox("一级关键词", ["选择题", "填空题", "解答题"], key="adv_q1_sel", on_change=on_adv_search)
        else:
            q1 = st.text_input("一级关键词", placeholder="输入一级关键词...", key="adv_q1", on_change=on_adv_search)

        t2 = st.selectbox("二级类型", search_opts, index=0, key="adv_t2")
        if t2 == "题目类型":
            q2 = st.selectbox("二级关键词", ["选择题", "填空题", "解答题"], key="adv_q2_sel", on_change=on_adv_search)
        else:
            q2 = st.text_input("二级关键词", placeholder="输入二级关键词...", key="adv_q2", on_change=on_adv_search)

        t3 = st.selectbox("三级类型", search_opts, index=0, key="adv_t3")
        if t3 == "题目类型":
            q3 = st.selectbox("三级关键词", ["选择题", "填空题", "解答题"], key="adv_q3_sel", on_change=on_adv_search)
        else:
            q3 = st.text_input("三级关键词", placeholder="输入三级关键词...", key="adv_q3", on_change=on_adv_search)

        st.markdown('<div id="adv-search-compact-btn-anchor"></div>', unsafe_allow_html=True)
        st.button("🔎 再次搜索", use_container_width=True, type="primary", on_click=on_adv_search)

        st.markdown('<span id="adv-search-compact-info-anchor"></span>', unsafe_allow_html=True)
        semantic_query = st.session_state.get("adv_semantic_query", "") if search_mode != "精确筛选" else ""
        if not (st.session_state.get("adv_search_active") and (q1 or q2 or q3 or semantic_query)):
            st.info("输入查找条件后开始查找。")
            return

        search_info = []
        if q1: search_info.append(f"{t1}: `{q1}`")
        if q2: search_info.append(f"{t2}: `{q2}`")
        if q3: search_info.append(f"{t3}: `{q3}`")
        if semantic_query: search_info.append(f"语义: `{semantic_query}`")
        search_info.append(f"模式: `{search_mode}`")
        st.markdown(f"**检索条件**: {' | '.join(search_info)}")

        if search_result_count is not None:
            st.markdown(
                f"""
                <div class="mc-adv-result-summary">
                    <h3>🎯 查找结果</h3>
                    <span>找到 {search_result_count} 个匹配题目</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if search_result_count:
                pager_size_col, pager_page_col = st.columns([1, 1], gap="small")
                with pager_size_col:
                    st.markdown('<span id="adv-search-pager-anchor"></span>', unsafe_allow_html=True)
                    page_size = st.selectbox("每页显示", options=results_page_size_options, index=1, key="adv_results_page_size")
                total_pages = max(1, (search_result_count + page_size - 1) // page_size)
                current_results_page = int(st.session_state.get("adv_results_page", 1) or 1)
                current_results_page = max(1, min(total_pages, current_results_page))
                st.session_state["adv_results_page"] = current_results_page
                with pager_page_col:
                    page = st.number_input("页码", min_value=1, max_value=total_pages, value=current_results_page, step=1, key="adv_results_page")
                start = (page - 1) * page_size
                end = min(search_result_count, start + page_size)
                st.caption(f"当前显示：第 {start + 1}–{end} 条 / 共 {search_result_count} 条")
            else:
                st.warning("未找到匹配的题目。")
        return

    col_inputs, col_btn, col_info = st.columns([2.5, 0.44, 2.18])

    with col_inputs:
        st.markdown('<div id="adv-search-inputs-anchor"></div>', unsafe_allow_html=True)
        c1a, c1b = st.columns([1, 2])
        with c1a:
            t1 = st.selectbox("一级类型", search_opts, index=0, key="adv_t1", label_visibility="collapsed")
        with c1b:
            if t1 == "题目类型":
                q1 = st.selectbox("一级关键词", ["选择题", "填空题", "解答题"], key="adv_q1_sel", label_visibility="collapsed", on_change=on_adv_search)
            else:
                q1 = st.text_input("一级关键词", placeholder="输入一级关键词...", key="adv_q1", label_visibility="collapsed", on_change=on_adv_search)

        c2a, c2b = st.columns([1, 2])
        with c2a:
            t2 = st.selectbox("二级类型", search_opts, index=0, key="adv_t2", label_visibility="collapsed")
        with c2b:
            if t2 == "题目类型":
                q2 = st.selectbox("二级关键词", ["选择题", "填空题", "解答题"], key="adv_q2_sel", label_visibility="collapsed", on_change=on_adv_search)
            else:
                q2 = st.text_input("二级关键词", placeholder="输入二级关键词...", key="adv_q2", label_visibility="collapsed", on_change=on_adv_search)

        c3a, c3b = st.columns([1, 2])
        with c3a:
            t3 = st.selectbox("三级类型", search_opts, index=0, key="adv_t3", label_visibility="collapsed")
        with c3b:
            if t3 == "题目类型":
                q3 = st.selectbox("三级关键词", ["选择题", "填空题", "解答题"], key="adv_q3_sel", label_visibility="collapsed", on_change=on_adv_search)
            else:
                q3 = st.text_input("三级关键词", placeholder="输入三级关键词...", key="adv_q3", label_visibility="collapsed", on_change=on_adv_search)

    with col_btn:
        st.markdown('<div id="adv-search-btn-anchor"></div>', unsafe_allow_html=True)
        st.button("🔎\n开始查找", use_container_width=False, type="primary", on_click=on_adv_search)

    with col_info:
        st.markdown('<span id="adv-search-info-anchor"></span>', unsafe_allow_html=True)
        q1 = st.session_state.get("adv_q1_sel" if t1 == "题目类型" else "adv_q1", "")
        q2 = st.session_state.get("adv_q2_sel" if t2 == "题目类型" else "adv_q2", "")
        q3 = st.session_state.get("adv_q3_sel" if t3 == "题目类型" else "adv_q3", "")
        semantic_query = st.session_state.get("adv_semantic_query", "") if search_mode != "精确筛选" else ""

        if not (st.session_state.get("adv_search_active") and (q1 or q2 or q3 or semantic_query)):
            st.info("👈 请在左侧输入查找条件，点击“开始查找”或回车即可在下方显示结果。")
            return

        # 动态生成搜索信息提示
        search_info = []
        if q1: search_info.append(f"{t1}: `{q1}`")
        if q2: search_info.append(f"{t2}: `{q2}`")
        if q3: search_info.append(f"{t3}: `{q3}`")
        if semantic_query: search_info.append(f"语义: `{semantic_query}`")
        search_info.append(f"模式: `{search_mode}`")
        search_str = " | ".join(search_info)
        st.markdown(f"**检索条件**: {search_str}")
        if st.button("❌ 退出搜索状态"):
            st.session_state["adv_search_active"] = False
            st.rerun()

def render_advanced_search_workspace(is_delete_mode=False, paper_type_scope=None):
    results = _get_advanced_search_results(is_delete_mode=is_delete_mode, paper_type_scope=paper_type_scope)
    c_search, c_results = st.columns([0.55, 2.75], gap="large")
    with c_search:
        st.markdown('<div id="adv-search-left-anchor"></div>', unsafe_allow_html=True)
        render_advanced_search_inline(compact=True, search_result_count=len(results))
    with c_results:
        st.markdown('<div id="adv-search-right-anchor"></div>', unsafe_allow_html=True)
        render_advanced_search_results(is_delete_mode=is_delete_mode, paper_type_scope=paper_type_scope, results=results, controls_in_sidebar=True)

def _get_advanced_search_results(is_delete_mode=False, paper_type_scope=None):
    search_mode = st.session_state.get("adv_search_mode", "精确筛选")
    semantic_query = (st.session_state.get("adv_semantic_query", "") or "").strip() if search_mode != "精确筛选" else ""

    t1 = st.session_state.get("adv_t1", "全文内容")
    t2 = st.session_state.get("adv_t2", "全文内容")
    t3 = st.session_state.get("adv_t3", "全文内容")

    q1 = st.session_state.get("adv_q1_sel" if t1 == "题目类型" else "adv_q1", "")
    q2 = st.session_state.get("adv_q2_sel" if t2 == "题目类型" else "adv_q2", "")
    q3 = st.session_state.get("adv_q3_sel" if t3 == "题目类型" else "adv_q3", "")

    def _row_match(item, s_type, s_query):
        s_query = (s_query or "").strip()
        if not s_query:
            return True
        if s_type == "题目类型":
            return s_query == item["type"]
        if s_type == "题目内容":
            return s_query in item["stem"]
        if s_type == "解答内容":
            return s_query in item["solution"]
        if s_type == "难度星级":
            return s_query in item["difficulty"]
        if s_type == "标签":
            return s_query in item["tags"]
        if s_type == "备注":
            return s_query in item["remark"]
        if s_type == "全文内容":
            return s_query in item["full_text"]
        return False

    query_key = (
        search_mode,
        semantic_query,
        t1,
        q1,
        t2,
        q2,
        t3,
        q3,
        paper_type_scope or "regular",
        "delete" if is_delete_mode else "edit",
    )
    if st.session_state.get("adv_last_query") == query_key and st.session_state.get("adv_last_results") is not None:
        results = st.session_state.get("adv_last_results") or []
    else:
        search_rows = _advanced_search_index_cached(_csv_index_cache_token(), paper_type_scope)

        results = []
        with st.spinner("正在全库检索中..."):
            filtered_items = []
            for item in search_rows:
                if q1 and not _row_match(item, t1, q1):
                    continue
                if q2 and not _row_match(item, t2, q2):
                    continue
                if q3 and not _row_match(item, t3, q3):
                    continue
                fpath = item["path"]
                if not fpath or not os.path.exists(fpath):
                    continue
                filtered_items.append(item)

            if search_mode == "精确筛选" or not semantic_query:
                results = [
                    {
                        "file": item["file"] or os.path.basename(item["path"]),
                        "path": item["path"],
                        "reason": "字段匹配",
                    }
                    for item in filtered_items
                ]
            elif filtered_items:
                config = _semantic_api_config()
                row_map = {
                    (item["row"].get("相对文件路径", "") or "").replace("/", "\\"): item
                    for item in filtered_items
                }
                try:
                    semantic_matches = semantic_search(
                        semantic_query,
                        [item["row"] for item in filtered_items],
                        config["base_url"],
                        config["api_key"],
                        config["model_name"],
                        top_k=max(1, len(filtered_items)),
                    )
                    for match in semantic_matches:
                        relative_path = (match.get("path") or "").replace("/", "\\")
                        item = row_map.get(relative_path)
                        if not item:
                            continue
                        boost = _semantic_lexical_boost(_semantic_item_text(item), semantic_query) if search_mode == "混合搜索" else 0.0
                        results.append({
                            "file": item["file"] or os.path.basename(item["path"]),
                            "path": item["path"],
                            "score": match["score"] + boost,
                            "semantic_score": match["score"],
                            "reason": "语义 + 关键词" if boost else "语义相似",
                        })
                    results.sort(key=lambda result: result.get("score", 0.0), reverse=True)
                except SemanticSearchError as exc:
                    if search_mode == "混合搜索":
                        st.warning(f"语义检索暂不可用，已退回关键词匹配：{exc}")
                        for item in filtered_items:
                            fallback_score = _semantic_lexical_boost(_semantic_item_text(item), semantic_query)
                            if fallback_score <= 0:
                                continue
                            results.append({
                                "file": item["file"] or os.path.basename(item["path"]),
                                "path": item["path"],
                                "score": fallback_score,
                                "reason": "关键词回退",
                            })
                        results.sort(key=lambda result: result.get("score", 0.0), reverse=True)
                    else:
                        st.error(f"语义检索不可用：{exc}")

        st.session_state["adv_last_query"] = query_key
        st.session_state["adv_last_results"] = results

    return results


def render_advanced_search_results(is_delete_mode=False, paper_type_scope=None, results=None, controls_in_sidebar=False):
    results_page_size_options = [5, 10, 15, 20]
    default_results_page_size = 10
    if not controls_in_sidebar and st.session_state.get("adv_results_page_size") not in (None, *results_page_size_options):
        del st.session_state["adv_results_page_size"]
    results = _get_advanced_search_results(is_delete_mode=is_delete_mode, paper_type_scope=paper_type_scope) if results is None else results
    if not controls_in_sidebar:
        st.markdown(
            f"""
            <div style="display:flex;align-items:center;justify-content:space-between;gap:1rem;margin:0 0 0.75rem;">
                <h3 style="margin:0;">🎯 查找结果</h3>
                <span style="font-weight:700;color:#4c1d95;">找到 {len(results)} 个匹配题目</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if results:
        if controls_in_sidebar:
            page_size = int(st.session_state.get("adv_results_page_size", default_results_page_size) or default_results_page_size)
            if page_size not in results_page_size_options:
                page_size = default_results_page_size
        else:
            page_size = st.selectbox("每页显示", options=results_page_size_options, index=1, key="adv_results_page_size")
        total_pages = (len(results) + page_size - 1) // page_size
        current_results_page = int(st.session_state.get("adv_results_page", 1) or 1)
        current_results_page = max(1, min(max(1, total_pages), current_results_page))
        if controls_in_sidebar:
            page = current_results_page
        else:
            st.session_state["adv_results_page"] = current_results_page
            page = st.number_input("页码", min_value=1, max_value=max(1, total_pages), value=current_results_page, step=1, key="adv_results_page")

        start = (page - 1) * page_size
        end = min(len(results), start + page_size)
        if not controls_in_sidebar:
            st.caption(f"每页 {page_size} 题 · 当前第 {page} 页 · 显示第 {start + 1}–{end} 条 / 共 {len(results)} 条")

        for i, res in enumerate(results[start:end], start=start):
            fpath = res["path"]
            fname = res["file"]

            prepared_assets = None
            if is_delete_mode:
                content = read_question_text(fpath)
            else:
                prepared_assets = load_question_editor_assets(fpath)
                content = prepared_assets["content"]

            q_label = format_question_title(fname)
            if res.get("semantic_score") is not None:
                st.caption(f"{res.get('reason', '语义相似')} · 相关度 {max(-1.0, min(1.0, res['semantic_score'])):.0%}")
            elif res.get("reason") == "关键词回退":
                st.caption("关键词回退匹配")

            if is_delete_mode:
                render_delete_question_item(fpath, q_label, content, key_prefix="delete_search")
                st.divider()
                continue

            render_browse_question_editor_card(
                q_label,
                content,
                fpath,
                "adv_search",
                paper_type_scope=paper_type_scope,
                prepared_assets=prepared_assets,
                interactive_difficulty=True,
            )
            st.divider()
    else:
        st.warning("未找到匹配的题目。")

def page_advanced_search():
    st.header("🔎 三级查找")
    t1, t2, t3 = st.columns(3)
    with t1:
        st.markdown("**一级提示**\n\n先选检索字段，再填关键词")
    with t2:
        st.markdown("**二级提示**\n\n可留空，也可继续细化")
    with t3:
        st.markdown("**三级提示**\n\n可留空，也可进一步过滤")

    if st.session_state.get("adv_search_active") and _adv_search_has_query():
        render_advanced_search_workspace()
        return

    render_advanced_search_inline()
    st.markdown('<hr style="border-top: 1px solid #e1e4e8; margin-top: 10px; margin-bottom: 20px;">', unsafe_allow_html=True)
    if st.session_state.get("adv_search_active") and _adv_search_has_query():
        render_advanced_search_results()

# ================= 主程序 =================
def main():
    st.set_page_config(page_title="高中数学题库管理系统", layout="wide", initial_sidebar_state="expanded")

    inject_custom_css()

    api_nav_option = "🔑\nAPI设置"
    stats_nav_option = "📊\n数据统计"
    entry_nav_option = "📝\n录入新题"
    sqlite_entry_nav_option = "✍️\n录入问题"
    browse_nav_option = "🔍\n全局浏览\n与编辑"
    sqlite_nav_option = "🗃️\nSQLite预览"
    exam_nav_option = "🖨️\n组卷服务"
    topic_nav_option = "📚\n专题收录"
    tools_nav_option = "🛠️\n工具箱"
    advanced_nav_option = "🔎\n三级查找"
    intro_nav_option = "📘\n项目介绍"
    manual_nav_option = "📖\n规范说明"
    legacy_browse_nav_option = "🔍\n全局浏览与编辑"
    nav_options = [
        api_nav_option,
        stats_nav_option,
        entry_nav_option,
        sqlite_entry_nav_option,
        browse_nav_option,
        sqlite_nav_option,
        exam_nav_option,
        topic_nav_option,
        tools_nav_option,
        advanced_nav_option,
        intro_nav_option,
        manual_nav_option,
    ]
    default_nav_option = stats_nav_option

    legacy_nav_aliases = {
        "API设置": api_nav_option,
        "数据统计": stats_nav_option,
        "录入新题": entry_nav_option,
        "录入问题": sqlite_entry_nav_option,
        "全局浏览\n与编辑": browse_nav_option,
        "SQLite预览": sqlite_nav_option,
        "组卷服务": exam_nav_option,
        "专题收录": topic_nav_option,
        "工具箱": tools_nav_option,
        "三级查找": advanced_nav_option,
        "项目介绍": intro_nav_option,
        "规范说明": manual_nav_option,
        "🔑\nAPI设置": api_nav_option,
        "📊\n数据统计": stats_nav_option,
        "📝\n录入新题": entry_nav_option,
        "✍️\n录入问题": sqlite_entry_nav_option,
        "🔍\n全局浏览\n与编辑": browse_nav_option,
        "🗃️\nSQLite预览": sqlite_nav_option,
        "🖨️\n组卷服务\n(完善中)": exam_nav_option,
        "🖨️\n组卷服务": exam_nav_option,
        "📚\n专题收录": topic_nav_option,
        "🛠️\n工具箱": tools_nav_option,
        "🔎\n三级查找": advanced_nav_option,
        "📘\n项目介绍": intro_nav_option,
        "📖\n规范说明": manual_nav_option,
        legacy_browse_nav_option: browse_nav_option,
    }

    for state_key in ("main_nav_selection", "main_sidebar_radio"):
        saved_value = st.session_state.get(state_key)
        if saved_value in legacy_nav_aliases:
            st.session_state[state_key] = legacy_nav_aliases[saved_value]
    if "main_nav_selection" not in st.session_state:
        st.session_state["main_nav_selection"] = default_nav_option
    if "main_sidebar_radio" not in st.session_state:
        st.session_state["main_sidebar_radio"] = st.session_state["main_nav_selection"]
    if "navigation_layout" not in st.session_state:
        st.session_state["navigation_layout"] = "sidebar"

    def _select_main_navigation(selection):
        if selection == api_nav_option:
            st.session_state["api_settings_dialog_requested"] = True
            previous_nav = st.session_state.get("main_nav_selection", default_nav_option)
            if previous_nav not in nav_options or previous_nav == api_nav_option:
                previous_nav = default_nav_option
            st.session_state["main_nav_selection"] = previous_nav
            st.session_state["main_sidebar_radio"] = previous_nav
            return

        if selection not in nav_options:
            return

        st.session_state["main_nav_selection"] = selection
        st.session_state["main_sidebar_radio"] = selection
        if selection == browse_nav_option:
            st.session_state["adv_search_active"] = False
            st.session_state["browse_mode"] = "按知识板块浏览"
        elif selection != advanced_nav_option:
            st.session_state["adv_search_active"] = False
        if selection != tools_nav_option:
            st.session_state["tools_subpage"] = None

    # Existing workflows can set the sidebar widget key directly before rerun.
    # Keep those jumps working when the top navigation is active.
    pending_nav = st.session_state.get("main_sidebar_radio")
    if (
        pending_nav in nav_options
        and pending_nav != api_nav_option
        and pending_nav != st.session_state.get("main_nav_selection")
    ):
        _select_main_navigation(pending_nav)

    def _on_main_sidebar_nav_change():
        _select_main_navigation(st.session_state.get("main_sidebar_radio"))

    top_nav_items = [
        (stats_nav_option, stats_nav_option),
        (entry_nav_option, entry_nav_option),
        (sqlite_entry_nav_option, sqlite_entry_nav_option),
        (browse_nav_option, browse_nav_option),
        (sqlite_nav_option, sqlite_nav_option),
        (exam_nav_option, exam_nav_option),
        (topic_nav_option, topic_nav_option),
        (tools_nav_option, tools_nav_option),
        (advanced_nav_option, advanced_nav_option),
        (intro_nav_option, intro_nav_option),
        (manual_nav_option, manual_nav_option),
    ]
    top_nav_value_by_label = dict(top_nav_items)
    top_nav_label_by_value = {value: label for label, value in top_nav_items}

    def _on_top_nav_change():
        _select_main_navigation(top_nav_value_by_label.get(st.session_state.get("top_nav_radio"), default_nav_option))

    navigation_layout = st.session_state["navigation_layout"]
    if navigation_layout == "sidebar":
        if st.button("切换为顶部导航", key="sidebar_layout_toggle"):
            st.session_state["navigation_layout"] = "top"
            st.rerun()
    if _query_param_enabled("mathcyclus_intro"):
        st.session_state["mathcyclus_intro_requested"] = True
        _remove_query_param("mathcyclus_intro")
    if st.session_state.pop("mathcyclus_intro_requested", False):
        show_mathcyclus_intro()

    # 注入侧边栏的自定义 CSS (SolEdu 深色极简风格)
    st.markdown("""
        <style>
        /* 隐藏默认顶部的 padding */
        .block-container {
            padding-top: 0.5rem !important;
        }

        /* ================= 侧边栏重构 (SolEdu / 暗紫色居中极简风格) ================= */
        /* 侧边栏整体背景 - 暗紫色主题 */
        [data-testid="stSidebar"] {
            background-color: #ede9fe !important;
            min-width: 110px !important;
            max-width: 110px !important;
        }

        /* 调整内部边距，让内容完全居中 */
        [data-testid="stSidebarUserContent"] {
            padding: 0.3rem 0rem 1rem 0rem !important;
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: flex-start !important;
        }

        /* 原生切换由持久代理触发，避免 Streamlit 重建控件时产生闪烁。 */
        [data-testid="stSidebarResizer"] {
            display: none !important;
        }
        /* Keep the persistent proxy in control while Streamlit rebuilds its native toggle. */
        body:has(#mc-sidebar-collapse-switch) [data-testid="stSidebarCollapseButton"],
        body:has(#mc-sidebar-collapse-switch) [data-testid="collapsedControl"],
        body:has(#mc-sidebar-collapse-switch) [data-testid="stSidebarCollapsedControl"] {
            display: none !important;
        }
        #mc-sidebar-layout-switch[data-sidebar-collapsed="true"] {
            opacity: 0 !important;
            pointer-events: none !important;
            transform: translateX(-8px) !important;
        }
        #mc-sidebar-layout-switch[data-switching="true"] {
            opacity: 0 !important;
            pointer-events: none !important;
        }
        @media (prefers-reduced-motion: reduce) {
            #mc-sidebar-layout-switch,
            #mc-sidebar-collapse-switch {
                transition: none !important;
            }
        }
        [data-testid="stSidebarCollapseButton"],
        [data-testid="collapsedControl"],
        [data-testid="stSidebarCollapsedControl"] {
            position: fixed !important;
            top: 2px !important;
            left: 70px !important;
            z-index: 2147483647 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            width: 31px !important;
            height: 30px !important;
            visibility: visible !important;
            opacity: 1 !important;
            pointer-events: auto !important;
            transform: none !important;
        }
        [data-testid="stSidebarCollapseButton"] button,
        [data-testid="collapsedControl"] button,
        [data-testid="stSidebarCollapsedControl"] button {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            width: 31px !important;
            height: 30px !important;
            min-height: 30px !important;
            margin: 0 !important;
            padding: 0 !important;
            visibility: visible !important;
            opacity: 1 !important;
            pointer-events: auto !important;
            border: 1px solid rgba(109, 40, 217, 0.14) !important;
            border-left: 0 !important;
            border-radius: 0 5px 5px 0 !important;
            background: transparent !important;
            box-shadow: none !important;
            color: #5b21b6 !important;
        }
        [data-testid="stSidebarCollapseButton"] button:hover,
        [data-testid="collapsedControl"] button:hover,
        [data-testid="stSidebarCollapsedControl"] button:hover {
            background: rgba(109, 40, 217, 0.10) !important;
        }
        [data-testid="stSidebarCollapseButton"] button svg,
        [data-testid="collapsedControl"] button svg,
        [data-testid="stSidebarCollapsedControl"] button svg {
            display: none !important;
        }
        [data-testid="stSidebarCollapseButton"] button::before {
            content: "<<";
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
            font-size: 16px;
            font-weight: 700;
            line-height: 1;
        }
        [data-testid="collapsedControl"] button svg,
        [data-testid="stSidebarCollapsedControl"] button svg {
            display: none !important;
        }
        [data-testid="collapsedControl"] button::before,
        [data-testid="stSidebarCollapsedControl"] button::before {
            content: ">>";
            color: #5b21b6;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
            font-size: 16px;
            font-weight: 700;
            line-height: 1;
        }
        [data-testid="stSidebar"] {
            position: relative !important;
        }
        /* Logo 样式：白色居中 */
        .sol-logo {
            color: #5b21b6;
            font-size: 18px;
            font-weight: 800;
            text-align: center;
            margin-top: 0px;
            margin-bottom: 35px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
            letter-spacing: -0.5px;
            line-height: 1.2;
            word-wrap: break-word;
            width: 100%;
        }
        .sol-logo span {
            color: #c084fc;
        }

        /* 隐藏 Radio 默认的圆形按钮 */
        [data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-child {
            display: none !important;
        }

        /* 强力清除所有隐藏边距，解决文字整体偏右问题 */
        [data-testid="stSidebar"] div[role="radiogroup"] > label {
            margin-left: 0 !important;
            margin-right: 0 !important;
            padding-left: 0 !important;
            padding-right: 0 !important;
            box-sizing: border-box !important;
        }

        /* 强制覆盖文本容器的默认边距，实现完美居中 */
        [data-testid="stSidebar"] div[role="radiogroup"] > label > div:nth-child(2) {
            display: flex !important;
            flex-direction: column !important;
            justify-content: center !important;
            align-items: center !important;
        }

        /* Radio 容器间距 - 确保内容居中 */
        [data-testid="stSidebar"] div[role="radiogroup"] {
            width: 100% !important;
            gap: 8px !important;
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: flex-start !important;
        }
        /* 强制把 stRadio 组件本体也居中，避免整体看起来偏移 */
        [data-testid="stSidebar"] div[data-testid="stRadio"] > div {
            display: flex !important;
            justify-content: center !important;
            padding: 0 !important;
        }

        /* Radio 项 (上下结构，图标居上文字居下) */
        [data-testid="stSidebar"] div[role="radiogroup"] > label {
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: center !important;
            width: calc(100% - 12px) !important;
            min-height: 58px !important;
            padding: 8px 6px !important;
            margin: 0 auto !important;
            max-width: 90px !important; /* 固定宽度，居中 */
            border-radius: 8px !important;
            background-color: transparent !important;
            color: #5b21b6 !important;
            transition: all 0.2s ease !important;
            cursor: pointer !important;
        }

        /* 悬停状态：亮紫色 */
        [data-testid="stSidebar"] div[role="radiogroup"] > label:hover {
            background-color: rgba(109, 40, 217, 0.16) !important;
            color: #4c1d95 !important;
        }

        [data-testid="stSidebar"] div[role="radiogroup"] > label:hover p,
        [data-testid="stSidebar"] div[role="radiogroup"] > label:hover span {
            color: #4c1d95 !important;
        }

        [data-testid="stSidebar"] div[role="radiogroup"] > label:hover svg,
        [data-testid="stSidebar"] div[role="radiogroup"] > label:hover svg path {
            fill: #4c1d95 !important;
            color: #4c1d95 !important;
            stroke: #4c1d95 !important;
        }

        /* 选中状态：深紫色高亮 */
        [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {
            background-color: #6d28d9 !important;
            color: #ffffff !important;
            border-radius: 8px !important;
            box-shadow: 0 10px 22px rgba(109, 40, 217, 0.22) !important;
        }

        [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) p,
        [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) span {
            color: #ffffff !important;
        }

        [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) svg,
        [data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) svg path {
            fill: #ffffff !important;
            color: #ffffff !important;
            stroke: #ffffff !important;
        }

        /* 图标与文字的排版 */
        [data-testid="stSidebar"] div[role="radiogroup"] p {
            font-size: 14px !important;
            font-weight: 800 !important;
            text-align: center !important;
            margin: 0 !important;
            padding: 0 !important;
            line-height: 1.6 !important;
            /* Keep each navigation label together; only the explicit \n in an
               option may create a new line. */
            white-space: pre !important;
            word-break: keep-all !important;
            overflow-wrap: normal !important;
            width: 100% !important;
            color: #5b21b6 !important;
        }

        /* 针对 Streamlit 在亮色模式下覆盖 label 颜色的特殊处理 */
        [data-testid="stSidebar"] div[role="radiogroup"] p,
        [data-testid="stSidebar"] div[role="radiogroup"] span {
            color: #5b21b6 !important;
        }
        [data-testid="stSidebar"] div[role="radiogroup"] > label {
            max-width: 96px !important;
        }
        [data-testid="stSidebar"] div[role="radiogroup"] p {
            width: auto !important;
            max-width: 100% !important;
            font-size: 13px !important;
            font-weight: 700 !important;
            line-height: 1.35 !important;
        }
        .sol-logo,
        .sol-logo span {
            white-space: nowrap !important;
        }
        </style>
    """, unsafe_allow_html=True)

    if navigation_layout == "top":
        inject_sidebar_layout_switch(navigation_layout)
        st.markdown("""
        <style>
        [data-testid="stSidebar"],
        [data-testid="collapsedControl"],
        [data-testid="stSidebarCollapsedControl"] {
            display: none !important;
        }
        .block-container {
            max-width: none !important;
            padding: 0 1.5rem 2rem !important;
        }
        div[data-testid="stHorizontalBlock"]:has(#mc-top-nav-anchor) {
            position: sticky !important;
            top: 0 !important;
            z-index: 100 !important;
            margin: -2.875rem -1.5rem 0.9rem !important;
            padding: 0.42rem 1.5rem !important;
            background: #ffffff !important;
            display: flex;
            align-items: center;
            gap: 0.2rem !important;
            min-width: 0 !important;
            overflow: visible !important;
            border: 0 !important;
            border-bottom: 1px solid rgba(109, 40, 217, 0.16) !important;
            border-radius: 0 !important;
            box-shadow: none !important;
        }
        div[data-testid="stHorizontalBlock"]:has(#mc-top-nav-anchor) div[data-testid="column"] {
            min-width: 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(#mc-top-nav-anchor) div[data-testid="stRadio"] > div,
        div[data-testid="stHorizontalBlock"]:has(#mc-top-nav-anchor) div[role="radiogroup"] {
            display: flex;
            align-items: center;
            flex-wrap: nowrap !important;
            min-width: 0 !important;
            gap: 0.18rem !important;
        }
        div[data-testid="stHorizontalBlock"]:has(#mc-top-nav-anchor) div[role="radiogroup"] {
            width: 100% !important;
            overflow-x: auto !important;
            scrollbar-width: none;
        }
        div[data-testid="stHorizontalBlock"]:has(#mc-top-nav-anchor) div[role="radiogroup"]::-webkit-scrollbar {
            display: none;
        }
        div[data-testid="stHorizontalBlock"]:has(#mc-top-nav-anchor) div[role="radiogroup"] > label {
            flex: 0 0 auto !important;
            display: inline-flex !important;
            align-items: center;
            justify-content: center;
            min-height: 3.2rem;
            margin: 0 !important;
            padding: 0 0.78rem !important;
            border: 0;
            border-bottom: 2px solid transparent;
            border-radius: 0;
            color: #5b21b6 !important;
            cursor: pointer;
            transition: background 0.14s ease, color 0.14s ease;
        }
        div[data-testid="stHorizontalBlock"]:has(#mc-top-nav-anchor) div[role="radiogroup"] > label > div:first-child {
            display: none !important;
        }
        div[data-testid="stHorizontalBlock"]:has(#mc-top-nav-anchor) div[role="radiogroup"] > label p {
            margin: 0 !important;
            color: inherit !important;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif !important;
            font-size: 0.98rem !important;
            font-weight: 720 !important;
            line-height: 1.22 !important;
            text-align: center !important;
            white-space: pre-line !important;
            word-break: keep-all !important;
            overflow-wrap: normal !important;
        }
        div[data-testid="stHorizontalBlock"]:has(#mc-top-nav-anchor) div[role="radiogroup"] > label:hover {
            background: rgba(109, 40, 217, 0.06) !important;
            color: #4c1d95 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(#mc-top-nav-anchor) div[role="radiogroup"] > label:has(input:checked) {
            background: transparent !important;
            color: #4c1d95 !important;
            border-bottom-color: #6d28d9 !important;
            box-shadow: none !important;
        }
        div[data-testid="stHorizontalBlock"]:has(#mc-top-nav-anchor) div[role="radiogroup"] > label:has(input:checked):hover {
            background: rgba(109, 40, 217, 0.06) !important;
        }
        div[class*="st-key-top-nav-layout-toggle"] button,
        div[class*="st-key-top-nav-api-settings"] button {
            min-height: 3.2rem !important;
            padding: 0 0.76rem !important;
            border: 0 !important;
            border-radius: 4px !important;
            background: transparent !important;
            color: #5b21b6 !important;
            box-shadow: none !important;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif !important;
            font-size: 0.98rem !important;
            font-weight: 720 !important;
            white-space: nowrap !important;
        }
        div[class*="st-key-top-nav-layout-toggle"] button {
            width: 2.65rem !important;
            padding: 0 !important;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif !important;
            font-size: 1.03rem !important;
        }
        div[class*="st-key-top-nav-layout-toggle"] button:hover,
        div[class*="st-key-top-nav-api-settings"] button:hover {
            background: rgba(109, 40, 217, 0.09) !important;
            color: #4c1d95 !important;
            transform: none !important;
        }
        div[class*="st-key-top-nav-api-settings"] button {
            justify-content: center !important;
        }
        @media (max-width: 760px) {
            .block-container {
                padding-left: 0.7rem !important;
                padding-right: 0.7rem !important;
            }
            div[data-testid="stHorizontalBlock"]:has(#mc-top-nav-anchor) {
                margin-left: -0.7rem !important;
                margin-right: -0.7rem !important;
                padding: 0.42rem 0.7rem !important;
            }
            div[class*="st-key-top-nav-api-settings"] button {
                width: 2.65rem !important;
                padding: 0 !important;
                font-size: 0 !important;
            }
            div[class*="st-key-top-nav-api-settings"] button::before {
                content: "⚙";
                font-size: 1rem;
            }
        }
        </style>
        """, unsafe_allow_html=True)

        selected_top_label = top_nav_label_by_value.get(st.session_state["main_nav_selection"], top_nav_items[0][0])
        if st.session_state.get("top_nav_radio") != selected_top_label:
            st.session_state["top_nav_radio"] = selected_top_label

        top_nav_column, top_layout_column, top_api_column = st.columns([12, 0.62, 1.25], gap="small")
        with top_nav_column:
            st.markdown('<span id="mc-top-nav-anchor"></span>', unsafe_allow_html=True)
            st.radio(
                "主导航",
                [label for label, _ in top_nav_items],
                horizontal=True,
                label_visibility="collapsed",
                key="top_nav_radio",
                on_change=_on_top_nav_change,
            )
        with top_layout_column:
            if st.button("侧栏", key="top_nav_layout_toggle", help="切换为左侧导航", use_container_width=True):
                st.session_state["navigation_layout"] = "sidebar"
                st.rerun()
        with top_api_column:
            if st.button("API设置", key="top_nav_api_settings", use_container_width=True):
                _select_main_navigation(api_nav_option)
    else:
        # --- 左侧：全局导航 ---
        with st.sidebar:
            logo_img_path = os.path.join(BASE_DIR, "fig", "MathCyclus_logo.png")
            if os.path.exists(logo_img_path):
                st.image(logo_img_path, width=72)
            st.markdown(
                '<a class="sol-logo sol-logo-link" href="?mathcyclus_intro=1" target="_self" '
                'title="打开 MathCyclus 题库介绍" style="margin-bottom:0; padding-bottom:0;">'
                'Math<br><span>Cyclus</span></a>',
                unsafe_allow_html=True,
            )

            st.markdown("""
            <style>
            [data-testid="stSidebar"] div[data-testid="stImage"] {
                display: flex !important;
                justify-content: center !important;
                margin: 0 auto 4px auto !important;
            }
            [data-testid="stSidebar"] div[data-testid="stImage"] img {
                width: 72px !important;
                max-width: 72px !important;
                height: auto !important;
            }
            .sol-logo-link,
            .sol-logo-link:visited,
            .sol-logo-link:hover,
            .sol-logo-link:active {
                display: block !important;
                text-decoration: none !important;
                color: #5b21b6 !important;
                cursor: pointer !important;
            }
            .sol-logo-link span,
            .sol-logo-link:visited span,
            .sol-logo-link:hover span,
            .sol-logo-link:active span {
                color: #c084fc !important;
            }
            </style>
            """, unsafe_allow_html=True)

            st.radio(
                "工作流导航",
                nav_options,
                label_visibility="collapsed",
                key="main_sidebar_radio",
                on_change=_on_main_sidebar_nav_change,
            )
            inject_sidebar_layout_switch(navigation_layout)

    if st.session_state.get("api_settings_dialog_requested"):
        api_settings_dialog()
        st.session_state["api_settings_dialog_requested"] = False
    selected_nav = st.session_state.get("main_nav_selection", default_nav_option)

    # Inject the shared visual system before route content to avoid first-painting legacy styles.
    # Keep the final injection below as a cascade safeguard for page-local styles.
    inject_unified_visual_system_css()

    # --- 主内容区路由 ---
    if selected_nav == stats_nav_option:
        render_statistics_dashboard()
    elif selected_nav == entry_nav_option:
        page_entry()
    elif selected_nav == sqlite_entry_nav_option:
        render_sqlite_manual_draft_entry()
    elif selected_nav == browse_nav_option:
        page_browse()
    elif selected_nav == sqlite_nav_option:
        from services.database_service import DEFAULT_DATABASE_PATH
        from services.question_db_service import get_question_bank_availability

        st.header("🗃️ SQLite 数据库预览")
        sqlite_availability = get_question_bank_availability(DEFAULT_DATABASE_PATH)
        if not sqlite_availability.get("has_schema"):
            st.error("SQLite 正式库不可读取或尚未初始化，请先到“工具箱 → 本地维护与升级”检查本地数据库。")
        else:
            if not sqlite_availability.get("ready_for_browse"):
                st.info("SQLite 正式库当前暂无题目。")
            render_sqlite_readonly_browse_preview(allow_exam_basket=False)
    elif selected_nav == exam_nav_option:
        page_exam_paper_generation()
    elif selected_nav == topic_nav_option:
        page_topic_collection()
    elif selected_nav == tools_nav_option:
        page_tools()
    elif selected_nav == advanced_nav_option:
        page_advanced_search()
    elif selected_nav == intro_nav_option:
        page_system_intro()
    elif selected_nav == manual_nav_option:
        page_manual()


if __name__ == "__main__":
    main()
