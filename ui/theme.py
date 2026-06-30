"""StatArb UI theme — night blue background, gold typography."""

from __future__ import annotations

NIGHT_BLUE = "#0a1628"
NIGHT_PANEL = "#12233d"
NIGHT_PANEL_ALT = "#1a2f4d"
GOLD = "#d4af37"
GOLD_BRIGHT = "#ffd700"
GOLD_SOFT = "#f0d878"
GOLD_DIM = "#9a7b2f"


def theme_css() -> str:
    return f"""
<style>
    .stApp {{
        background: linear-gradient(165deg, {NIGHT_BLUE} 0%, #0d2137 45%, {NIGHT_PANEL} 100%);
        color: {GOLD_SOFT};
    }}
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {NIGHT_PANEL} 0%, {NIGHT_BLUE} 100%);
        border-right: 1px solid {GOLD_DIM};
    }}
    [data-testid="stSidebar"] * {{
        color: {GOLD_SOFT} !important;
    }}
    h1, h2, h3, h4, h5, h6,
    [data-testid="stMarkdownContainer"] h1,
    [data-testid="stMarkdownContainer"] h2,
    [data-testid="stMarkdownContainer"] h3 {{
        color: {GOLD_BRIGHT} !important;
        font-weight: 600;
    }}
    p, label, span, .stMarkdown, .stCaption {{
        color: {GOLD_SOFT};
    }}
    [data-testid="stMetricValue"] {{
        color: {GOLD_BRIGHT} !important;
    }}
    [data-testid="stMetricLabel"] {{
        color: {GOLD} !important;
    }}
    .gold-title {{
        color: {GOLD_BRIGHT};
        font-size: 2rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        margin-bottom: 0.25rem;
    }}
    .gold-subtitle {{
        color: {GOLD};
        font-size: 0.95rem;
        margin-bottom: 1rem;
    }}
    .panel-gold {{
        background: {NIGHT_PANEL_ALT};
        border: 1px solid {GOLD_DIM};
        border-radius: 10px;
        padding: 1rem 1.25rem;
        margin-bottom: 1rem;
    }}
    .warn-gold {{
        color: {GOLD_BRIGHT};
        background: rgba(212, 175, 55, 0.12);
        border: 1px solid {GOLD_DIM};
        border-radius: 8px;
        padding: 0.75rem 1rem;
    }}
    div[data-testid="stDataFrame"] {{
        border: 1px solid {GOLD_DIM};
        border-radius: 8px;
    }}
    .stButton > button {{
        background: linear-gradient(90deg, {GOLD_DIM}, {GOLD});
        color: {NIGHT_BLUE};
        border: none;
        font-weight: 600;
    }}
    .stButton > button:hover {{
        color: {NIGHT_BLUE};
        border: 1px solid {GOLD_BRIGHT};
    }}
    @media (max-width: 768px) {{
        .gold-title {{
            font-size: 1.45rem;
        }}
        .gold-subtitle {{
            font-size: 0.85rem;
        }}
        [data-testid="stSidebar"] {{
            min-width: 14rem;
        }}
        div[data-testid="column"] {{
            min-width: 0 !important;
        }}
        div[data-testid="stDataFrame"] {{
            font-size: 0.8rem;
        }}
    }}
    .mobile-url {{
        color: {GOLD_BRIGHT};
        font-size: 0.9rem;
        font-weight: 600;
        word-break: break-all;
    }}
</style>
"""
