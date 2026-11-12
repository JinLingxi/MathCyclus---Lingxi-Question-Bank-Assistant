"""Shared window chrome for empty and populated exam baskets."""

BASKET_LAUNCHER_CSS = r'''<style>
/* Streamlit 1.37 does not emit st-key-* classes. Locate the native widget
   through its preceding marker so it is fixed before any iframe script runs. */
:is(div[data-testid="element-container"], div[data-testid="stElementContainer"]):has(.mc-exam-basket-collapsed-anchor) {
    display: none !important;
}
:is(div[data-testid="element-container"], div[data-testid="stElementContainer"]):has(.mc-exam-basket-collapsed-anchor) + :is(div[data-testid="element-container"], div[data-testid="stElementContainer"]) {
    position: fixed !important;
    right: 1rem !important;
    top: calc(50% - 8.1rem) !important;
    width: 5.4rem !important;
    margin: 0 !important;
    z-index: 2147483000 !important;
}
:is(div[data-testid="element-container"], div[data-testid="stElementContainer"]):has(.mc-exam-basket-collapsed-anchor) + :is(div[data-testid="element-container"], div[data-testid="stElementContainer"]) button {
    width: 5.4rem !important;
    min-height: 2.55rem !important;
    border-radius: .55rem !important;
    border: 1px solid rgba(109,40,217,.28) !important;
    background: rgba(255,255,255,.97) !important;
    color: #312e81 !important;
    box-shadow: 0 6px 18px rgba(36,28,52,.14) !important;
    font-weight: 700 !important;
}
/* The closed fragment has no in-flow content. Remove its structural boxes
   as well, otherwise the page flex gap still reserves an empty row. */
div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-exam-basket-collapsed-anchor):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-exam-basket-collapsed-anchor)),
div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-exam-basket-collapsed-anchor):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-exam-basket-collapsed-anchor)) > div,
div[data-testid="stVerticalBlock"]:has(> :is(div[data-testid="element-container"], div[data-testid="stElementContainer"]) .mc-exam-basket-collapsed-anchor) {
    display: contents !important;
}
/* CSS, zero-height utility frames and empty anchors are layout plumbing,
   not rows of visible exam content. Hide their wrappers, not just children. */
body:has(#mc-exam-page-anchor) :is(div[data-testid="element-container"], div[data-testid="stElementContainer"]):has(> div[data-testid="stMarkdown"] > div[data-testid="stMarkdownContainer"] > style:only-child),
body:has(#mc-exam-page-anchor) :is(div[data-testid="element-container"], div[data-testid="stElementContainer"]):has(iframe[height="0"]),
body:has(#mc-exam-page-anchor) :is(div[data-testid="element-container"], div[data-testid="stElementContainer"]):has(iframe[height="1"]),
body:has(#mc-exam-page-anchor) :is(div[data-testid="element-container"], div[data-testid="stElementContainer"]):has(> div[data-testid="stMarkdown"] > div[data-testid="stMarkdownContainer"] > span:empty[class*="anchor"]:only-child),
body:has(#mc-exam-page-anchor) :is(div[data-testid="element-container"], div[data-testid="stElementContainer"]):has(> div[data-testid="stMarkdown"] > div[data-testid="stMarkdownContainer"] > span:empty[id$="anchor"]:only-child) {
    display: none !important;
}
</style>'''

BASKET_WINDOW_CSS = r'''<style>
body div#mc-exam-basket-panel[data-testid],
#mc-exam-basket-panel,
body:has(.mc-exam-basket-open-state) div[data-testid="stElementContainer"]:has(.mc-exam-basket-open-state) + div[data-testid="stVerticalBlockBorderWrapper"],
body:has(.mc-exam-basket-anchor) div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-exam-basket-anchor):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-exam-basket-anchor)) {
    position: fixed !important;
    left: var(--mc-basket-left, auto) !important;
    right: var(--mc-basket-right, 6.5rem) !important;
    top: var(--mc-basket-top, 14vh) !important;
    bottom: auto !important;
    width: var(--mc-basket-width, min(760px, calc(100vw - 24px))) !important;
    height: var(--mc-basket-height, min(620px, 72vh)) !important;
    min-width: min(480px, calc(100vw - 24px)) !important;
    min-height: min(280px, calc(100vh - 24px)) !important;
    max-width: calc(100vw - 24px) !important;
    max-height: calc(100vh - 24px) !important;
    margin: 0 !important;
    padding: 0 !important;
    box-sizing: border-box !important;
    overflow: hidden !important;
    resize: none !important;
    z-index: 1100 !important;
    border: 1px solid var(--mc-border, #d9d1e6) !important;
    border-radius: 14px !important;
    background: var(--mc-surface, #fffdfd) !important;
    box-shadow: 0 18px 48px rgba(36,28,52,.16) !important;
}
#mc-exam-basket-panel > div:not(.mc-basket-resize-handle) {
    height: 100% !important;
    min-height: 0 !important;
}
#mc-exam-basket-panel > div > div[data-testid="stVerticalBlock"] {
    height: 100% !important;
    min-height: 0 !important;
    overflow-y: auto !important;
    overflow-x: hidden !important;
    padding: 1.1rem 1.1rem 1.8rem !important;
    box-sizing: border-box !important;
    scrollbar-width: thin;
    scrollbar-gutter: stable;
}
#mc-exam-basket-panel :is([data-testid="element-container"], [data-testid="stElementContainer"], [data-testid="stMarkdown"], [data-testid="stHorizontalBlock"], [data-testid="stButton"], [data-testid="stDownloadButton"]),
#mc-exam-basket-panel [data-testid="stButton"] button {
    max-width: 100% !important;
    min-width: 0 !important;
    box-sizing: border-box !important;
}
#mc-exam-basket-panel :is([data-testid="element-container"], [data-testid="stElementContainer"]):has(.mc-exam-basket-close-anchor),
#mc-exam-basket-panel :is([data-testid="element-container"], [data-testid="stElementContainer"]):has(.mc-exam-basket-anchor) {display: none !important;}
#mc-exam-basket-panel [data-testid="stHorizontalBlock"]:has(.mc-exam-basket-close-anchor) {position: relative !important;}
#mc-exam-basket-panel :is([data-testid="column"], [data-testid="stColumn"]):has(.mc-exam-basket-close-anchor),
#mc-exam-basket-panel :is([data-testid="column"], [data-testid="stColumn"]):has(.mc-exam-basket-close-anchor) div {position: static !important;}
#mc-exam-basket-panel :is([data-testid="column"], [data-testid="stColumn"]):has(.mc-exam-basket-close-anchor) div[data-testid="stButton"] {
    position: absolute !important;
    right: 0;
    top: 0;
    width: 36px !important;
    z-index: 6;
}
#mc-exam-basket-panel :is(.mc-exam-basket-close, #mc-exam-basket-panel :is([data-testid="column"], [data-testid="stColumn"]):has(.mc-exam-basket-close-anchor) [data-testid="stButton"] button) {
    position: relative;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    flex: 0 0 36px;
    width: 36px !important;
    min-width: 36px !important;
    max-width: 36px !important;
    height: 36px !important;
    min-height: 36px !important;
    max-height: 36px !important;
    padding: 0 !important;
    border: 1px solid transparent !important;
    border-radius: 10px !important;
    background: transparent !important;
    color: #71687d !important;
    box-shadow: none !important;
    transition: background-color 140ms ease, color 140ms ease, border-color 140ms ease;
}
:is(.mc-exam-basket-close, #mc-exam-basket-panel :is([data-testid="column"], [data-testid="stColumn"]):has(.mc-exam-basket-close-anchor) [data-testid="stButton"] button) > div {
    position: absolute !important;
    width: 1px !important;
    height: 1px !important;
    overflow: hidden !important;
    clip-path: inset(50%);
}
:is(.mc-exam-basket-close, #mc-exam-basket-panel :is([data-testid="column"], [data-testid="stColumn"]):has(.mc-exam-basket-close-anchor) [data-testid="stButton"] button)::before {
    content: "";
    width: 18px;
    height: 18px;
    background: currentColor;
    mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='m6 6 12 12M18 6 6 18' fill='none' stroke='black' stroke-width='1.8' stroke-linecap='round'/%3E%3C/svg%3E") center / contain no-repeat;
}
#mc-exam-basket-panel :is(.mc-exam-basket-close, #mc-exam-basket-panel :is([data-testid="column"], [data-testid="stColumn"]):has(.mc-exam-basket-close-anchor) [data-testid="stButton"] button):hover {
    background: #f3edf9 !important;
    color: #5b21b6 !important;
    border-color: #e4d9ef !important;
}
#mc-exam-basket-panel :is(.mc-exam-basket-close, #mc-exam-basket-panel :is([data-testid="column"], [data-testid="stColumn"]):has(.mc-exam-basket-close-anchor) [data-testid="stButton"] button):focus-visible {
    outline: 2px solid #6d28d9 !important;
    outline-offset: 3px;
}
.mc-basket-resize-handle {
    position: absolute;
    bottom: 0;
    width: 30px;
    height: 30px;
    z-index: 5;
    display: grid;
    place-items: center;
    touch-action: none;
    user-select: none;
    color: #a998bd;
    border-radius: 8px;
}
.mc-basket-resize-handle svg {width: 16px; height: 16px; pointer-events: none;}
.mc-basket-resize-left {left: 0; cursor: nesw-resize;}
.mc-basket-resize-left svg {transform: scaleX(-1);}
.mc-basket-resize-right {right: 0; cursor: nwse-resize;}
.mc-basket-resize-handle:hover, .mc-basket-resize-handle:focus-visible {
    color: #6d28d9;
    background: #f3edf9;
}
.mc-basket-resize-handle:focus-visible {outline: 2px solid #6d28d9; outline-offset: -3px;}
@media (prefers-reduced-motion: reduce) {
    #mc-exam-basket-panel :is(.mc-exam-basket-close, #mc-exam-basket-panel :is([data-testid="column"], [data-testid="stColumn"]):has(.mc-exam-basket-close-anchor) [data-testid="stButton"] button) {transition: none;}
}
</style>'''

BASKET_WINDOW_SCRIPT = r'''<script>
(() => {
    const win = window.parent, doc = win.document;
    const frame = window.frameElement;
    if (frame) frame.style.display = 'none';
    const marker = doc.querySelector('.mc-exam-basket-anchor');
    const panel = marker?.closest('[data-testid="stVerticalBlockBorderWrapper"]');
    if (!panel) return;
    panel.classList.add('mc-exam-basket-fixed-target');
    panel.id = 'mc-exam-basket-panel';
    const clamp = (value, min, max) => Math.min(Math.max(value, min), Math.max(min, max));
    const read = () => {
        const r = panel.getBoundingClientRect();
        return {left:r.left, top:r.top, width:r.width, height:r.height};
    };
    const handles = [];
    const apply = geometry => {
        const vw = win.innerWidth, vh = win.innerHeight;
        const minWidth = Math.min(480, vw - 24), minHeight = Math.min(280, vh - 24);
        const width = clamp(geometry.width, minWidth, vw - 24);
        const height = clamp(geometry.height, minHeight, vh - 24);
        const left = clamp(geometry.left, 12, vw - width - 12);
        const top = clamp(geometry.top, 12, vh - height - 12);
        for (const [name,value] of Object.entries({left,top,width,height})) {
            panel.style.setProperty('--mc-basket-' + name, value + 'px');
        }
        panel.style.setProperty('--mc-basket-right','auto');
        win.__mcExamBasketGeometry = {left,top,width,height};
        handles.forEach(handle => {
            handle.setAttribute('aria-valuenow', String(Math.round(width)));
            handle.setAttribute('aria-valuetext', Math.round(width) + ' × ' + Math.round(height));
        });
    };
    const resize = (side, start, dx, dy) => {
        const minWidth = Math.min(480, win.innerWidth - 24);
        const right = start.left + start.width;
        const left = side === 'left' ? clamp(start.left + dx, 12, right - minWidth) : start.left;
        const width = side === 'left' ? right - left : clamp(start.width + dx, minWidth, win.innerWidth - start.left - 12);
        const height = clamp(start.height + dy, Math.min(280, win.innerHeight - 24), win.innerHeight - start.top - 12);
        apply({left, top:start.top, width, height});
    };
    const close = [...panel.querySelectorAll('button')].find(button => button.textContent.trim() === '关闭试题篮');
    if (close) {
        close.classList.add('mc-exam-basket-close');
        close.setAttribute('aria-label','关闭试题篮');
        close.title = '关闭试题篮';
        const host = close.closest('[data-testid="stButton"]');
        if (host) {host.style.display = 'flex'; host.style.justifyContent = 'flex-end';}
    }
    panel.querySelectorAll('.mc-basket-resize-handle').forEach(node => node.remove());
    for (const side of ['left','right']) {
        const handle = doc.createElement('div');
        handle.className = 'mc-basket-resize-handle mc-basket-resize-' + side;
        handle.tabIndex = 0;
        handle.setAttribute('role','separator');
        handle.setAttribute('aria-controls',panel.id);
        handle.setAttribute('aria-label', side === 'left' ? '从左下角调整试题篮大小' : '从右下角调整试题篮大小');
        handle.title = '拖动调整大小；方向键微调';
        handle.innerHTML = '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M6 16 16 6M11 16 16 11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>';
        let drag = null;
        handle.onpointerdown = event => {
            if (event.button !== 0) return;
            event.preventDefault(); event.stopPropagation();
            drag = {...read(), x:event.clientX, y:event.clientY};
            handle.setPointerCapture(event.pointerId);
        };
        handle.onpointermove = event => {
            if (!drag) return;
            resize(side, drag, event.clientX - drag.x, event.clientY - drag.y);
        };
        handle.onpointerup = handle.onpointercancel = () => {drag=null;};
        handle.onkeydown = event => {
            const delta = {ArrowLeft:[-16,0],ArrowRight:[16,0],ArrowUp:[0,-16],ArrowDown:[0,16]}[event.key];
            if (!delta) return;
            event.preventDefault(); resize(side, read(), ...delta);
        };
        handles.push(handle); panel.appendChild(handle);
    }
    apply(win.__mcExamBasketGeometry || read());
    const header = panel.querySelector('h4');
    if (header) {
        header.style.cursor = 'move'; header.style.touchAction = 'none';
        let drag = null;
        header.onpointerdown = event => {
            if (event.button !== 0) return;
            drag={...read(), x:event.clientX, y:event.clientY};
            header.setPointerCapture(event.pointerId);event.preventDefault();
        };
        header.onpointermove = event => {
            if (drag) apply({...drag,left:drag.left+event.clientX-drag.x,top:drag.top+event.clientY-drag.y});
        };
        header.onpointerup = header.onpointercancel = () => {drag=null;};
    }
    if (win.__mcExamBasketViewportResize) win.removeEventListener('resize',win.__mcExamBasketViewportResize);
    win.__mcExamBasketViewportResize = () => {if (panel.isConnected) apply(win.__mcExamBasketGeometry || read());};
    win.addEventListener('resize',win.__mcExamBasketViewportResize);
})();
</script>'''
