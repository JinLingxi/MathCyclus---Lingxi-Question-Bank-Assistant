"""Presentation only: compact smart-exam controls using native widgets."""

SMART_EXAM_CSS = r'''<style>
body:has(#mc-exam-page-anchor) div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-smart-exam-root):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-smart-exam-root)) {
    background: #fffdfd !important;
    border: 1px solid #ded5e9 !important;
    border-radius: 14px !important;
    box-shadow: none !important;
    padding: 1.35rem 1.5rem !important;
    margin: .7rem 0 1.2rem !important;
}
:is(div[data-testid="element-container"],div[data-testid="stElementContainer"]):has(.mc-smart-exam-root) {display:none !important;}
div[data-testid="stMarkdownContainer"]:has(> :is(.mc-smart-exam-header,.mc-smart-exam-summary,.mc-smart-exam-result)) {margin:0 !important;}
.mc-smart-exam-header {display:flex;align-items:flex-start;justify-content:space-between;gap:24px;margin:0 0 10px;}
.mc-smart-exam-header h3 {margin:0 !important;padding:0 !important;font-size:1.22rem !important;line-height:1.4 !important;font-weight:700 !important;color:#30273c !important;}
.mc-smart-exam-progress {display:flex;align-items:center;gap:10px;margin-top:10px;color:#877b93;font-size:.78rem;line-height:1.5;}
.mc-smart-exam-progress .current {color:#6d28d9;font-weight:700;}
.mc-smart-exam-progress .complete {color:#5c4b70;}
.mc-smart-exam-target {text-align:right;color:#746780;white-space:nowrap;font-size:.8rem;line-height:1.6;}
.mc-smart-exam-target strong {font-size:1.6rem;font-weight:650;color:#4f337b;margin-right:4px;font-variant-numeric:tabular-nums;}
.mc-smart-exam-target small {display:block;font-size:.76rem;color:#746780;}
.mc-smart-exam-summary {font-size:.82rem;line-height:1.7;color:#71647e;padding:5px 0;}
.mc-smart-exam-result {border-top:1px solid #ece5f2;padding-top:24px;margin-top:12px;}
.mc-smart-exam-result h3 {margin:0 0 8px !important;padding:0 !important;font-size:1.1rem !important;}
.mc-smart-exam-result p {margin:0 !important;color:#71647e;font-size:.84rem;line-height:1.7;}
body:has(#mc-exam-page-anchor) div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-smart-exam-root):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-smart-exam-root)) label[data-baseweb="checkbox"]:has(input:checked) > span {
    background-color:#6d28d9 !important;
    border-color:#6d28d9 !important;
}
body:has(#mc-exam-page-anchor) div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-smart-exam-root):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-smart-exam-root)) label[data-baseweb="checkbox"] > span {border-radius:4px !important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-smart-exam-root):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-smart-exam-root)) [data-testid="stExpander"] {
    border:1px solid #e9e2ef !important;border-radius:9px !important;box-shadow:none !important;background:transparent !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-smart-exam-root):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-smart-exam-root)) [data-testid="stExpander"] summary {
    font-size:.86rem !important;color:#685776 !important;min-height:42px !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-smart-exam-root):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-smart-exam-root)) [data-testid="stRadio"] [role="radiogroup"] {
    gap:8px !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-smart-exam-root):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-smart-exam-root)) [data-testid="stRadio"] [role="radiogroup"] > label {
    padding:6px 10px !important;margin:0 !important;border:1px solid #e4dcec;border-radius:8px;background:#fffdfd;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-smart-exam-root):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-smart-exam-root)) [data-testid="stRadio"] label:has(input:checked) {
    background:#f2ebfa !important;border-color:#cdb8e4 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-smart-exam-root):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-smart-exam-root)) :is([data-testid="stCheckbox"],[data-testid="stRadio"]) p {
    font-size:.85rem !important;
}
@media(max-width:700px) {
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-smart-exam-root):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-smart-exam-root)) {padding:1rem !important;}
    .mc-smart-exam-header {gap:12px;}
    .mc-smart-exam-progress {gap:6px;font-size:.72rem;}
    .mc-smart-exam-target strong {font-size:1.3rem;}
}
</style>'''
