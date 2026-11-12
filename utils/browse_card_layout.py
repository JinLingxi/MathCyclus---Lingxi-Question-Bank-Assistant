"""Compact native metadata controls and top-right source drawer."""

BROWSE_CARD_HEADER_CSS = r'''<style>
/* A content-sized native row keeps the action immediately after the tags. */
div[data-testid="stVerticalBlock"]:has(> :is(div[data-testid="element-container"],div[data-testid="stElementContainer"]) .mc-db-inline-meta-anchor) {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: wrap !important;
    align-items: center !important;
    gap: .4rem .6rem !important;
}
div[data-testid="stVerticalBlock"]:has(> :is(div[data-testid="element-container"],div[data-testid="stElementContainer"]) .mc-db-inline-meta-anchor) > :is(div[data-testid="element-container"],div[data-testid="stElementContainer"]) {
    width: auto !important;
    max-width: 100% !important;
    min-width: 0 !important;
    flex: 0 1 auto !important;
}
div[data-testid="stVerticalBlock"]:has(> :is(div[data-testid="element-container"],div[data-testid="stElementContainer"]) .mc-db-inline-meta-anchor) > :is(div[data-testid="element-container"],div[data-testid="stElementContainer"]) > div {
    width: auto !important;
    max-width: 100% !important;
}
.mc-db-browse-meta.mc-db-inline-meta-anchor {margin: 0 !important;}
/* Streamlit's Markdown renderer compensates paragraph spacing with a -1rem
   margin. These custom HTML blocks have no paragraph margin to compensate. */
div[data-testid="stMarkdownContainer"]:has(> :is(.mc-db-browse-meta,.mc-db-browse-note,.mc-db-browse-source,.mc-db-browse-title,.mc-db-browse-kicker,.mc-db-material-drawer-shell)) {
    margin: 0 !important;
}
.mc-db-browse-source {margin-top: 0 !important;}
.mc-db-browse-note {font-size: .86rem;line-height: 1.5;color: #4b5563;overflow-wrap: anywhere;}
div[data-testid="stVerticalBlock"]:has(> :is(div[data-testid="element-container"],div[data-testid="stElementContainer"]) .mc-db-browse-card-anchor) {gap: .55rem !important;}

/* Only full source/preview cards float the drawer. Two-column exam cards
   retain their compact in-flow drawer and do not lose reading space. */
div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-db-full-preview-anchor):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-db-full-preview-anchor)) {
    position: relative !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-db-full-preview-anchor):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-db-full-preview-anchor)) :is(div[data-testid="element-container"],div[data-testid="stElementContainer"]):has(.mc-db-material-drawer-shell) {
    position: absolute !important;
    top: 1rem;
    right: 1rem;
    width: min(31rem, 42%) !important;
    margin: 0 !important;
    z-index: 28;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-db-full-preview-anchor):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-db-full-preview-anchor)) :is(div[data-testid="element-container"],div[data-testid="stElementContainer"]):has(.mc-db-material-drawer-shell) > div {width: 100% !important;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-db-full-preview-anchor):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-db-full-preview-anchor)) .mc-db-material-drawer-shell {
    min-height: 0;
    margin: 0;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-db-full-preview-anchor):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-db-full-preview-anchor)) .mc-db-material-drawer {width: 100%;}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-db-full-preview-anchor):has(.mc-db-material-drawer-shell):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-db-full-preview-anchor)) .mc-db-browse-title {
    max-width: calc(58% - 1rem);
}
@media (max-width: 1100px) {
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-db-full-preview-anchor):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-db-full-preview-anchor)) :is(div[data-testid="element-container"],div[data-testid="stElementContainer"]):has(.mc-db-material-drawer-shell) {
        position: static !important;
        width: 100% !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-db-full-preview-anchor):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-db-full-preview-anchor)) .mc-db-material-drawer-shell {min-height: 2.25rem;}
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.mc-db-full-preview-anchor):not(:has(div[data-testid="stVerticalBlockBorderWrapper"] .mc-db-full-preview-anchor)) .mc-db-browse-title {max-width: 100%;}
}
</style>'''
