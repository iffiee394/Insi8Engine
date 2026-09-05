# InsightEngine — Developer Handoff & Implementation Guide

Use this guide to implement the high-fidelity UI for the Streamlit `app.py`.

## 1. Theme Configuration (`.streamlit/config.toml`)
```toml
[theme]
primaryColor = "#6C5CE7"
backgroundColor = "#0F0F1A"
secondaryBackgroundColor = "#1A1A2E"
textColor = "#E8E8F0"
font = "sans serif"
```

## 2. Core Layout CSS (Inject via `st.markdown`)
```css
/* Custom App Shell */
.main {
    background-color: #0F0F1A;
}

/* Icon Rail (Column A) */
[data-testid="stSidebar"] {
    min-width: 64px !important;
    max-width: 64px !important;
    background-color: #0c0d1c !important;
}

/* Card Styling */
.insight-card {
    background: #1A1A2E;
    border: 1px solid #2A2A42;
    border-radius: 12px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    transition: background 0.2s;
}
.insight-card:hover {
    background: #22223A;
}

/* Monospace Timestamps */
.timestamp {
    font-family: 'JetBrains Mono', 'Source Code Pro', monospace;
    color: #6C5CE7;
    font-size: 0.85rem;
    font-weight: 600;
}

/* Progress Bar (Violet) */
.stProgress > div > div > div > div {
    background-color: #6C5CE7;
}
```

## 3. Component Snippets

### 3.1 Insight Card (Tag-less)
```html
<div class="insight-card">
  <div style="display: flex; justify-content: space-between; align-items: flex-start;">
    <span style="color: #94A3B8; font-size: 0.8rem; font-weight: bold;">01</span>
    <a href="#" class="timestamp">12:34</a>
  </div>
  <h3 style="margin: 0.5rem 0; font-size: 1.1rem;">The "Zero to One" Recruitment Strategy</h3>
  <p style="color: #E8E8F0; font-size: 0.95rem; line-height: 1.6;">
    The founder emphasizes hiring individuals who are 'product-obsessed' rather than career-driven...
  </p>
</div>
```

### 3.2 Timeline Density Map
```html
<div style="width: 100%; height: 8px; background: #2A2A42; border-radius: 4px; overflow: hidden; display: flex; margin: 1rem 0;">
  <div style="width: 15%; background: #6C5CE7; height: 100%; opacity: 0.4;"></div>
  <div style="width: 5%; height: 100%;"></div>
  <div style="width: 20%; background: #6C5CE7; height: 100%;"></div>
  <!-- ... more segments ... -->
</div>
```

## 4. Cursor Prompt Strategy
Copy and paste this into Cursor:
> "I need you to rebuild the Streamlit UI for InsightEngine. Use the CSS provided in `DEVELOPER_HANDOFF.md` for the theme. Implement a three-column layout: 
> 1. A 64px fixed left rail for icons.
> 2. A context column for lists (Queue/Library).
> 3. A main detail panel with tabs.
> Use `st.markdown` with `unsafe_allow_html=True` for the Insight Cards and Timeline Map to ensure they match the exact visual style. Follow the UI-1 through UI-9 tasks in `UI_BUILD_SPEC.md` strictly."
