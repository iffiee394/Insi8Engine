"""Global CSS aligned with Stitch code.html exports."""

from __future__ import annotations


def baseline_css() -> str:
    """Only style the active native UI; avoid legacy iframe layout overrides."""
    return """<style>
    .stApp { background:#111221; color:#E8E8F0; }
    header[data-testid="stHeader"], footer, #MainMenu { display:none; }
    [data-testid="stMainBlockContainer"] { padding-top:0; }
    [data-baseweb="select"] div[value] {
        line-height:1.5 !important; font-size:14px !important; max-height:none !important;
    }
    </style>"""


def global_css() -> str:
    return """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
    @import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0&display=swap');

    :root {
        --bg: #111221;
        --bg-app: #0F0F1A;
        --surface: #1A1A2E;
        --surface-low: #191a2a;
        --surface-hover: #22223A;
        --rail: #111221;
        --border: #2A2A42;
        --accent: #6C5CE7;
        --secondary: #c6bfff;
        --secondary-dark: #4029ba;
        --text: #E8E8F0;
        --muted: #94A3B8;
        --muted-dim: #5C5C70;
        --lib-width: 360px;
    }

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background: #111221 !important; color: #E8E8F0; }

    /* ── Hide ALL Streamlit chrome ── */
    #MainMenu, footer, header[data-testid="stHeader"],
    [data-testid="stToolbar"], [data-testid="stDecoration"],
    [data-testid="stStatusWidget"], [data-testid="stSidebarCollapsedControl"],
    .stDeployButton { display: none !important; }
    .stApp > header { display: none !important; }

    /* Remove all padding from the main content area */
    [data-testid="stAppViewContainer"] > section.main { padding-top: 0 !important; }
    .main .block-container,
    [data-testid="stMainBlockContainer"],
    .block-container {
        padding: 0 !important;
        max-width: 100% !important;
        margin: 0 !important;
    }

    /* Zero gap so the hidden queue-tick fragment doesn't push the iframe down */
    [data-testid="stVerticalBlock"] {
        gap: 0 !important;
        row-gap: 0 !important;
    }

    /* Make the iframe component fill the viewport */
    [data-testid="stCustomComponentV1"],
    iframe[title="st.iframe"] {
        width: 100% !important;
        border: none !important;
        display: block !important;
    }
    /* Remove gaps around the component element */
    [data-testid="stVerticalBlock"] > div:has(iframe) {
        padding: 0 !important;
        margin: 0 !important;
    }

    .material-symbols-outlined {
        font-family: 'Material Symbols Outlined';
        font-weight: normal; font-style: normal; font-size: 20px;
        line-height: 1; letter-spacing: normal; text-transform: none;
        display: inline-block; white-space: nowrap; word-wrap: normal;
        direction: ltr; font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
        vertical-align: middle;
    }

    @keyframes spin { to { transform: rotate(360deg); } }

    /* ── Hide Streamlit sidebar — nav rail lives inside the iframe now ── */
    section[data-testid="stSidebar"],
    [data-testid="stSidebar"],
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarContent"],
    [data-testid="stSidebarUserContent"],
    button[kind="header"],
    .css-1cypcdb, .css-18e3th9 {
        display: none !important;
        width: 0 !important;
        min-width: 0 !important;
        max-width: 0 !important;
        overflow: hidden !important;
    }

    /* Force main content to fill full width with no gaps */
    section.main, [data-testid="stAppViewContainer"] > .main,
    [data-testid="stAppViewContainer"] {
        margin-left: 0 !important;
        padding-left: 0 !important;
        width: 100% !important;
    }

    /* Iframe fills parent fully */
    [data-testid="stCustomComponentV1"] iframe,
    [data-testid="stMainBlockContainer"] iframe {
        width: 100% !important;
    }

    /* ── Main layout ── */
    /* No trailing padding: the iframe sizes itself to the remaining viewport
       height (see _FIT in stitch_pages.py), so any extra here would show up as
       a second, outer scrollbar. */
    .main .block-container {
        padding: 0 !important; max-width: 100% !important;
    }
    html, body, [data-testid="stAppViewContainer"],
    [data-testid="stMain"], section.stMain,
    [data-testid="stMainBlockContainer"] { overflow: hidden !important; }

    /* Two-pane split */
    .ie-split-row [data-testid="column"]:first-child {
        max-width: var(--lib-width) !important;
        min-width: 280px !important;
        flex: 0 0 var(--lib-width) !important;
        border-right: 1px solid var(--border);
        background: var(--bg);
        padding-right: 0 !important;
    }
    .ie-split-row [data-testid="column"]:last-child {
        flex: 1 1 auto !important;
        min-width: 0 !important;
        padding-left: 1.25rem !important;
    }

    /* Top app bar */
    .stitch-topbar-wrap {
        border-bottom: 1px solid var(--border);
        background: var(--bg);
        margin: 0 0 1.5rem;
        padding: 1.25rem 1.5rem;
    }
    .stitch-topbar-title {
        font-size: 28px; font-weight: 700; letter-spacing: -0.02em;
        color: var(--text); margin: 0; line-height: 1.1;
    }

    /* Nav tabs (radio styled as underline tabs) */
    .stitch-nav-row {
        padding: 0 1.5rem 0.75rem;
    }
    .stitch-nav-row [data-testid="stRadio"] > div {
        flex-direction: row !important; gap: 0 !important;
        background: transparent !important;
    }
    .stitch-nav-row [data-testid="stRadio"] label {
        background: transparent !important;
        border: none !important;
        padding: 0.75rem 0 !important;
        margin-right: 2rem !important;
        color: var(--muted-dim) !important;
        font-size: 14px !important; font-weight: 500 !important;
        border-bottom: 3px solid transparent !important;
        border-radius: 0 !important;
    }
    .stitch-nav-row [data-testid="stRadio"] label:hover { color: var(--text) !important; }
    .stitch-nav-row [data-testid="stRadio"] label[data-checked="true"],
    .stitch-nav-row [data-testid="stRadio"] label:has(input:checked) {
        color: var(--text) !important;
        border-bottom-color: var(--secondary-dark) !important;
    }
    .stitch-nav-row [data-testid="stRadio"] div[role="radiogroup"] > label > div:first-child {
        display: none !important;
    }

    .stitch-search-row {
        padding: 0 1.5rem;
    }
    .stitch-search-row input {
        font-size: 14px !important; padding: 0.6rem 1rem !important;
        background: var(--surface) !important; border: 1px solid var(--border) !important;
        border-radius: 8px !important; color: var(--text) !important;
    }
    .stitch-poll-btn button {
        font-size: 13px !important; padding: 0.45rem 1rem !important;
        min-height: 36px !important;
    }

    .stitch-label-caps {
        font-size: 12px; font-weight: 700; letter-spacing: 0.08em;
        text-transform: uppercase; color: var(--muted-dim);
    }
    .stitch-mono { font-family: 'JetBrains Mono', monospace; font-size: 12px; }
    .stitch-accent { color: var(--secondary); }

    /* Library pane */
    .ie-library-pane {
        max-height: calc(100vh - 120px);
        overflow-y: auto;
        padding: 0 0.5rem 1rem 0;
    }
    .ie-library-pane::-webkit-scrollbar { width: 6px; }
    .ie-library-pane::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

    .stitch-lib-header {
        display: flex; justify-content: space-between; align-items: center;
        padding: 12px 14px; border-bottom: 1px solid var(--border);
        background: var(--surface-low); margin: 0 -0.5rem 12px;
    }
    .stitch-lib-filters {
        display: flex; gap: 8px; padding: 0 4px 8px;
    }
    .stitch-lib-filters [data-testid="stSelectbox"] {
        margin-bottom: 0 !important;
    }
    .stitch-lib-filters [data-testid="stSelectbox"] > div > div {
        min-height: 32px !important; font-size: 12px !important;
    }

    .stitch-lib-row {
        display: flex; gap: 12px; padding: 10px 12px; margin: 2px 0;
        border-radius: 6px; cursor: pointer; transition: background 0.15s;
        min-height: 72px; box-sizing: border-box;
    }
    .stitch-lib-row:hover { background: var(--surface-hover); }
    .stitch-lib-row-selected {
        background: rgba(108,92,231,0.1) !important;
        border-left: 2px solid var(--accent); padding-left: 10px;
    }
    .stitch-lib-thumb {
        width: 64px; height: 64px; border-radius: 8px; overflow: hidden;
        flex-shrink: 0; background: #323344; position: relative;
    }
    .stitch-lib-thumb img { width: 100%; height: 100%; object-fit: cover; }
    .stitch-lib-progress {
        position: absolute; bottom: 0; left: 0; right: 0; height: 2px;
        background: #F5A623;
    }
    .stitch-lib-body { min-width: 0; flex: 1; display: flex; flex-direction: column; justify-content: center; }
    .stitch-lib-title {
        font-size: 14px; font-weight: 600; color: var(--text);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .stitch-lib-meta {
        font-size: 12px; color: var(--muted); margin: 2px 0 6px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .stitch-status-badge {
        display: inline-flex; align-items: center; gap: 4px;
        font-size: 10px; font-weight: 600; text-transform: uppercase;
        padding: 2px 8px; border-radius: 4px;
    }
    .stitch-status-badge .material-symbols-outlined { font-size: 12px; }

    /* Invisible click target over each library row */
    .ie-library-pane [data-testid="stMarkdown"]:has(.stitch-lib-wrap) {
        margin-bottom: 0 !important;
    }
    .ie-library-pane [data-testid="stMarkdown"]:has(.stitch-lib-wrap) + [data-testid="stButton"] {
        margin-top: -76px !important;
        margin-bottom: 2px !important;
        height: 76px !important;
        position: relative !important;
        z-index: 5 !important;
    }
    .ie-library-pane [data-testid="stMarkdown"]:has(.stitch-lib-wrap) + [data-testid="stButton"] button {
        opacity: 0 !important;
        height: 76px !important;
        min-height: 76px !important;
        width: 100% !important;
        padding: 0 !important;
        margin: 0 !important;
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
        cursor: pointer !important;
    }

    /* Detail pane */
    .ie-detail-pane {
        max-height: calc(100vh - 120px);
        overflow-y: auto;
        padding-right: 0.5rem;
    }
    .stitch-detail-header {
        padding: 0 0 1.25rem; margin-bottom: 1rem;
        border-bottom: 1px solid var(--border);
    }
    .stitch-detail-eyebrow {
        font-size: 12px; color: var(--muted); margin-bottom: 8px;
        text-transform: uppercase; letter-spacing: 0.05em;
        white-space: normal; word-wrap: break-word;
    }
    .stitch-detail-title {
        font-size: 26px; font-weight: 700; line-height: 1.4;
        color: var(--text); margin: 0;
        white-space: normal; word-wrap: break-word;
    }

    /* Token panel */
    .stitch-token-details {
        background: var(--surface-low); border: 1px solid var(--border);
        border-radius: 8px; margin: 0 0 1rem; overflow: hidden;
    }
    .stitch-token-summary {
        display: flex; align-items: center; justify-content: space-between;
        padding: 12px 16px; cursor: pointer; list-style: none;
    }
    .stitch-token-summary::-webkit-details-marker { display: none; }
    .stitch-token-summary:hover { background: var(--surface-hover); }
    .stitch-token-summary-left, .stitch-token-summary-right {
        display: flex; align-items: center; gap: 8px;
    }
    .stitch-token-details[open] .stitch-chevron { transform: rotate(180deg); }
    .stitch-chevron { transition: transform 0.15s; font-size: 18px !important; color: var(--muted-dim); }
    .stitch-token-body { padding: 12px 16px; border-top: 1px solid rgba(42,42,66,0.5); }
    .stitch-token-row {
        display: flex; justify-content: space-between; padding: 6px 0;
        font-size: 12px; color: var(--muted);
    }
    .stitch-token-row .stitch-mono { color: var(--text); }
    .stitch-token-total {
        display: flex; justify-content: space-between; margin-top: 8px;
        padding-top: 8px; border-top: 1px solid var(--border);
        font-size: 11px; font-weight: 700; color: var(--text);
    }

    /* Insight cards */
    .stitch-insight-card {
        background: var(--surface); border: 1px solid var(--border);
        border-radius: 10px; padding: 1.5rem; margin-bottom: 1.25rem;
        transition: border-color 0.15s;
    }
    .stitch-insight-card:hover { border-color: #3A3A5C; }
    .stitch-insight-top {
        display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px;
    }
    .stitch-insight-idx {
        font-family: 'JetBrains Mono', monospace; font-size: 18px;
        font-weight: 700; color: var(--secondary-dark); opacity: 0.6;
    }
    .stitch-ts-btn {
        font-family: 'JetBrains Mono', monospace; font-size: 12px;
        color: var(--secondary-dark); background: rgba(108,92,231,0.12);
        padding: 5px 10px; border-radius: 5px; text-decoration: none;
    }
    .stitch-insight-title { font-size: 18px; font-weight: 700; color: var(--text); margin: 0 0 10px; }
    .stitch-insight-body { color: var(--muted); line-height: 1.7; margin: 0 0 14px; font-size: 15px; }
    .stitch-insight-tags { display: flex; flex-wrap: wrap; gap: 8px; }
    .stitch-insight-tag {
        font-size: 11px; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.05em; color: var(--secondary);
        background: rgba(64,41,186,0.2); padding: 5px 10px; border-radius: 5px;
    }

    /* Settings */
    .stitch-section-title {
        font-size: 20px; font-weight: 600; color: var(--text);
        border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 16px;
    }
    .stitch-profile-card {
        display: flex; gap: 24px; padding: 24px; background: var(--surface);
        border: 1px solid var(--border); border-radius: 12px; margin-bottom: 24px;
    }
    .stitch-avatar {
        width: 96px; height: 96px; border-radius: 12px; background: #323344;
        border: 1px solid var(--border); flex-shrink: 0;
        display: flex; align-items: center; justify-content: center;
        font-size: 36px; color: var(--secondary);
    }
    .stitch-glass-panel {
        background: var(--surface); border: 1px solid var(--border);
        border-radius: 12px; padding: 28px;
    }
    .stitch-usage-big { font-size: 42px; font-weight: 700; color: var(--text); margin: 12px 0 20px; }
    .stitch-usage-of { font-size: 18px; color: var(--muted); font-weight: 400; }
    .stitch-meter { height: 10px; background: #0f0f1a; border-radius: 999px; overflow: hidden; }
    .stitch-meter-fill { height: 100%; background: var(--secondary-dark); border-radius: 999px; }
    .stitch-meter-meta {
        display: flex; justify-content: space-between; font-size: 12px;
        font-family: 'JetBrains Mono', monospace; color: var(--muted-dim); margin-top: 12px;
    }
    .stitch-stat-box {
        padding: 20px; background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    }
    .stitch-stat-val { font-family: 'JetBrains Mono', monospace; font-size: 28px; font-weight: 700; color: var(--text); }
    .stitch-log-table {
        border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
        background: #0f0f1a; font-size: 12px;
    }
    .stitch-log-head {
        display: grid; grid-template-columns: 2fr 2fr 1fr 1fr; gap: 12px;
        padding: 14px 16px; background: var(--surface); border-bottom: 1px solid var(--border);
        text-transform: uppercase; font-size: 11px; font-weight: 700; color: var(--muted-dim);
        letter-spacing: 0.03em;
    }
    .stitch-log-row {
        display: grid; grid-template-columns: 2fr 2fr 1fr 1fr; gap: 12px;
        padding: 14px 16px; border-bottom: 1px solid rgba(42,42,66,0.5);
        align-items: center;
    }

    /* Playlists */
    .stitch-pl-card {
        background: var(--surface); border-radius: 14px; overflow: hidden;
        display: flex; flex-direction: column; border: 1px solid var(--border);
    }
    .stitch-pl-hero { height: 180px; position: relative; }
    .stitch-pl-hero-badges {
        position: absolute; bottom: 14px; left: 14px; display: flex; gap: 10px;
    }
    .stitch-pl-badge-active {
        background: rgba(198,191,255,0.2); color: var(--secondary);
        font-size: 10px; font-weight: 700; padding: 4px 10px; border-radius: 5px;
        text-transform: uppercase;
    }
    .stitch-pl-count {
        background: rgba(0,0,0,0.4); color: rgba(255,255,255,0.9);
        font-family: 'JetBrains Mono', monospace; font-size: 11px; padding: 4px 10px; border-radius: 5px;
        font-weight: 600;
    }
    .stitch-pl-body { padding: 24px; flex: 1; }
    .stitch-pl-name { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 14px; }
    .stitch-pl-focus-label {
        font-size: 11px; font-weight: 700; letter-spacing: 0.1em;
        text-transform: uppercase; color: var(--muted-dim); margin-bottom: 10px;
    }
    .stitch-pl-focus-active, .stitch-pl-focus-idle {
        background: var(--bg-app); border: 1px solid var(--border);
        border-radius: 10px; padding: 16px; min-height: 90px;
    }
    .stitch-pl-focus-active { border-color: var(--accent); }
    .stitch-pl-add {
        border: 2px dashed var(--border); border-radius: 14px;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        padding: 36px; text-align: center; min-height: 220px;
    }

    /* Widget polish */
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px; background: transparent; border-bottom: 1px solid var(--border);
    }
    .stTabs [data-baseweb="tab"] {
        background: transparent !important; border: none !important;
        color: var(--muted-dim) !important; font-size: 13px !important; font-weight: 500 !important;
        padding: 10px 4px !important; border-bottom: 2px solid transparent !important;
        border-radius: 0 !important;
    }
    .stTabs [aria-selected="true"] {
        color: var(--text) !important; border-bottom-color: var(--secondary-dark) !important;
    }
    div[data-testid="stButton"] button[kind="primary"] {
        background: var(--secondary-dark) !important; border-color: var(--secondary-dark) !important;
        color: #fff !important; border-radius: 10px !important;
        font-weight: 600 !important; padding: 10px 24px !important;
    }
    div[data-testid="stButton"] button[kind="secondary"] {
        background: var(--surface) !important; border: 1px solid var(--border) !important;
        color: var(--text) !important; border-radius: 10px !important;
        font-weight: 600 !important; padding: 10px 24px !important;
    }
    .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div {
        background: var(--surface) !important; border-color: var(--border) !important;
        color: var(--text) !important; border-radius: 8px !important;
        font-size: 14px !important; padding: 10px 12px !important;
    }
    .empty-state {
        padding: 3rem 2rem; text-align: center; color: var(--muted);
        border: 1px dashed var(--border); border-radius: 12px; margin-top: 2rem;
    }
    .empty-state h3 { color: var(--text); margin-bottom: 0.5rem; }

    /* Detail action buttons — keep labels on one line */
    .ie-detail-pane [data-testid="stLinkButton"] a,
    .ie-detail-pane [data-testid="stDownloadButton"] button,
    .ie-detail-pane [data-testid="stButton"] button {
        white-space: nowrap !important;
        font-size: 13px !important;
        min-height: 36px !important;
    }

    /* ── Top bar right icons ── */
    .stitch-topbar-right {
        display: flex; align-items: center; gap: 12px; justify-content: flex-end;
    }
    .stitch-topbar-icon-btn {
        width: 40px; height: 40px; display: flex; align-items: center; justify-content: center;
        border-radius: 50%; border: 1px solid var(--border); color: var(--muted);
        cursor: pointer; font-size: 20px; background: transparent; transition: all 0.15s;
    }
    .stitch-topbar-icon-btn:hover { background: var(--surface-hover); color: var(--text); }
    .stitch-topbar-avatar {
        width: 40px; height: 40px; border-radius: 50%;
        background: linear-gradient(135deg, var(--accent), var(--secondary-dark));
        border: 2px solid var(--border); flex-shrink: 0;
        display: flex; align-items: center; justify-content: center;
        overflow: hidden; font-weight: 700;
    }
    .stitch-topbar-avatar img {
        width: 100%; height: 100%; object-fit: cover; border-radius: 50%;
    }

    /* ── Settings: field labels ── */
    .stitch-field-label {
        font-size: 11px; font-weight: 700; letter-spacing: 0.1em;
        text-transform: uppercase; color: var(--muted-dim);
        margin-bottom: 8px; margin-top: 20px;
    }

    /* ── Settings: personalize toggle card ── */
    .stitch-personalize-card {
        padding: 20px 24px; background: var(--surface);
        border: 1px solid var(--border); border-left: 4px solid var(--accent);
        border-radius: 10px; margin: 20px 0;
    }
    .stitch-personalize-card .title {
        font-weight: 700; font-size: 15px; color: var(--text); margin-bottom: 6px;
    }
    .stitch-personalize-card .desc {
        font-size: 13px; color: var(--muted); line-height: 1.6;
    }

    /* ── Settings: API provider rows ── */
    .stitch-api-row {
        display: flex; align-items: center; padding: 16px 18px;
        background: var(--surface); border: 1px solid var(--border);
        border-radius: 10px; margin-bottom: 12px; gap: 14px;
    }
    .stitch-api-icon {
        width: 40px; height: 40px; display: flex; align-items: center; justify-content: center;
        border-radius: 8px; background: rgba(108,92,231,0.15);
        color: var(--secondary); flex-shrink: 0; font-size: 20px;
    }
    .stitch-api-name {
        flex: 1; font-weight: 700; font-size: 15px; color: var(--text);
    }
    .stitch-api-badge-ok {
        font-size: 10px; font-weight: 700; text-transform: uppercase;
        padding: 5px 12px; border-radius: 5px;
        background: rgba(46,204,113,0.15); color: #2ECC71;
        letter-spacing: 0.02em;
    }
    .stitch-api-badge-missing {
        font-size: 10px; font-weight: 700; text-transform: uppercase;
        padding: 5px 12px; border-radius: 5px;
        background: rgba(92,92,112,0.2); color: var(--muted-dim);
        letter-spacing: 0.02em;
    }
    .stitch-api-key-mask {
        margin-top: 12px; padding: 12px 16px; background: var(--bg-app);
        border: 1px solid var(--border); border-radius: 8px;
        font-family: 'JetBrains Mono', monospace; font-size: 13px; color: var(--muted);
        display: flex; justify-content: space-between; align-items: center;
    }
    .stitch-api-key-mask .eye-icon {
        color: var(--muted-dim); cursor: pointer; font-size: 18px;
    }

    /* ── Settings: cost badge ── */
    .stitch-cost-row {
        display: flex; justify-content: space-between; align-items: center;
        padding: 16px 0; margin-top: 16px;
    }
    .stitch-cost-row .label {
        display: flex; align-items: center; gap: 10px;
        font-size: 15px; color: var(--muted);
    }
    .stitch-cost-badge {
        font-family: 'JetBrains Mono', monospace; font-size: 18px; font-weight: 700;
        color: var(--text); padding: 8px 18px; border: 1px solid var(--border);
        border-radius: 10px; background: var(--surface);
    }

    /* ── Settings: stat change indicators ── */
    .stitch-stat-change { font-size: 11px; font-family: 'JetBrains Mono', monospace; float: right; margin-top: 8px; }
    .stitch-stat-change.up { color: #2ECC71; }
    .stitch-stat-change.down { color: var(--muted-dim); }

    /* ── Settings: log status icons ── */
    .stitch-log-row .status-icon { font-size: 14px; margin-right: 4px; vertical-align: middle; }
    .stitch-log-row .status-icon.ok { color: #2ECC71; }
    .stitch-log-row .status-icon.fail { color: #EF4444; }
    .stitch-log-export-link {
        font-size: 12px; color: var(--muted); cursor: pointer;
        display: inline-flex; align-items: center; gap: 4px; text-decoration: none;
    }
    .stitch-log-export-link:hover { color: var(--text); }

    /* ── Playlists: Grid/List toggle ── */
    .stitch-view-toggle {
        display: inline-flex; border: 1px solid var(--border); border-radius: 8px;
        overflow: hidden; background: var(--surface);
    }
    .stitch-view-btn {
        padding: 6px 16px; font-size: 12px; font-weight: 500;
        color: var(--muted); background: transparent; border: none; cursor: pointer;
    }
    .stitch-view-btn.active {
        background: var(--surface-hover); color: var(--text);
    }

    /* ── Playlists: updated timestamp ── */
    .stitch-pl-updated {
        font-size: 12px; color: var(--muted-dim); margin-top: 8px;
        display: flex; align-items: center; gap: 4px;
    }

    /* ── Playlists: pagination dots ── */
    .stitch-pl-dots {
        display: flex; gap: 6px; justify-content: center; padding: 12px 0 0;
    }
    .stitch-pl-dot {
        width: 6px; height: 6px; border-radius: 50%; background: var(--muted-dim);
    }
    .stitch-pl-dot.active { background: var(--secondary); }

    /* ── Detail: Watch / Export action buttons ── */
    .stitch-action-row {
        display: flex; gap: 14px; margin: 16px 0 20px;
    }
    .stitch-action-watch {
        display: inline-flex; align-items: center; gap: 10px;
        padding: 11px 22px; border: 1px solid var(--border);
        border-radius: 10px; background: var(--surface); color: var(--text);
        font-size: 14px; font-weight: 600; text-decoration: none; cursor: pointer;
        transition: all 0.15s;
    }
    .stitch-action-watch:hover { background: var(--surface-hover); border-color: #3A3A5C; }
    .stitch-action-watch .play-icon { color: #EF4444; font-size: 20px; }
    .stitch-action-export {
        display: inline-flex; align-items: center; gap: 10px;
        padding: 11px 22px; border: none; border-radius: 10px;
        background: var(--accent); color: #fff;
        font-size: 14px; font-weight: 600; cursor: pointer;
        text-decoration: none; transition: background 0.15s;
    }
    .stitch-action-export:hover { background: #5A4BD6; }

    /* ── Chat footer pinned ── */
    .stitch-chat-footer {
        border-top: 1px solid var(--border); padding-top: 12px; margin-top: 16px;
    }
    .stitch-chat-input-row {
        display: flex; gap: 8px; align-items: center;
    }
    .stitch-chat-send {
        width: 40px; height: 40px; border-radius: 8px;
        background: var(--accent); border: none; color: #fff;
        display: flex; align-items: center; justify-content: center;
        cursor: pointer; flex-shrink: 0;
    }
    </style>
    """
