"""Identidade visual compartilhada pelos componentes do painel."""

COLORS = {'ink': '#173c35', 'green': '#157a5b', 'mint': '#91d8b9', 'pale': '#e8f4ee', 'text': '#1d2d2a', 'muted': '#6f7f7b', 'grid': '#e8eeeb', 'background': '#f5f7f6'}

CHART_CONFIG = {"displayModeBar": False, "responsive": True}

GLOBAL_CSS = """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');

    :root {
        --ink: #173c35;
        --green: #157a5b;
        --mint: #91d8b9;
        --muted: #6f7f7b;
        --line: #e2e9e5;
        --surface: #ffffff;
        --background: #f5f7f6;
    }
    html, body, [class*="css"], .stApp { font-family: 'DM Sans', 'Segoe UI', sans-serif; }
    .stApp { background: var(--background); color: var(--text); }
    #MainMenu, footer { visibility: hidden; }
    [data-testid="stHeader"] { background: rgba(245,247,246,.88); }
    [data-testid="stMainBlockContainer"] { max-width: 1440px; padding-top: 2rem; padding-bottom: 3rem; }
    [data-testid="stSidebar"] { background: #153b34; border-right: 0; }
    [data-testid="stSidebar"] > div:first-child { padding: 1.8rem 1.15rem 1rem; }
    [data-testid="stSidebar"] * { color: #e7f1ed; }
    [data-testid="stSidebar"] .brand { display:flex; align-items:center; gap:.75rem; padding: 0 .45rem 1.6rem; }
    [data-testid="stSidebar"] .brand-mark {
        width: 40px; height: 40px; border-radius: 12px; background:#9be1bf; color:#153b34;
        display:flex; align-items:center; justify-content:center; font-size:24px; font-weight:700;
    }
    [data-testid="stSidebar"] .brand-name { font-size:22px; line-height:1.1; font-weight:700; letter-spacing:-.5px; }
    [data-testid="stSidebar"] .brand-sub { font-size:11px; color:#a9c4ba; letter-spacing:1.7px; text-transform:uppercase; margin-top:4px; }
    [data-testid="stSidebar"] .nav-caption { color:#8fb2a5; font-size:10px; letter-spacing:1.5px; font-weight:700; padding:0 .65rem .5rem; }
    [data-testid="stSidebar"] [role="radiogroup"] { gap: .3rem; }
    [data-testid="stSidebar"] [role="radiogroup"] label {
        width:100%; padding:.72rem .8rem; border-radius:9px; transition:all .15s; cursor:pointer;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:hover { background:rgba(255,255,255,.07); }
    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) { background:#2b564b; }
    [data-testid="stSidebar"] [role="radiogroup"] label > div:first-child { display:none; }
    [data-testid="stSidebar"] [role="radiogroup"] label p { font-size:14px; font-weight:500; }
    [data-testid="stSidebar"] hr { border-color:rgba(255,255,255,.12); margin:1.2rem .4rem; }
    [data-testid="stSidebar"] .sidebar-foot { color:#94b3a8; font-size:12px; line-height:1.55; padding:0 .45rem; }
    [data-testid="stSidebar"] .sidebar-foot strong { color:#d8e9e2; font-weight:600; }

    h1, h2, h3 { color:#18342f; letter-spacing:-.035em; }
    h1 { font-size:2rem !important; font-weight:700 !important; margin-bottom:.1rem !important; }
    h2 { font-size:1.15rem !important; font-weight:650 !important; }
    h3 { font-size:1rem !important; font-weight:650 !important; }
    p { color:var(--muted); }
    .page-subtitle { color:var(--muted); font-size:14px; margin-top:.15rem; }
    .header-meta { text-align:right; color:var(--muted); font-size:12px; padding-top:12px; line-height:1.55; }
    .header-meta strong { color:#36514b; font-weight:600; }
    .demo-banner {
        background:#edf6f1; border:1px solid #d2e9dd; color:#315d4f; padding:.78rem 1rem;
        border-radius:10px; font-size:13px; margin:1.1rem 0 1rem;
    }
    .demo-banner strong { color:#194b3c; }
    .filter-label { color:#4f6560; font-size:12px; font-weight:600; margin-bottom:-5px; }
    .kpi-card { background:#fff; border:1px solid var(--line); border-radius:13px; padding:1.15rem 1.25rem 1rem; min-height:134px; }
    .kpi-top { display:flex; align-items:center; justify-content:space-between; gap:.5rem; }
    .kpi-label { font-size:12px; font-weight:600; color:#667b75; }
    .kpi-dot { width:28px; height:28px; border-radius:8px; background:#edf5f1; display:flex; align-items:center; justify-content:center; font-size:13px; color:var(--green); font-weight:700; }
    .kpi-value { font-size:28px; line-height:1.15; letter-spacing:-1px; font-weight:700; color:#173c35; margin:.7rem 0 .25rem; }
    .kpi-note { font-size:11px; color:#81918c; }
    .kpi-note.positive { color:#218361; }
    .kpi-note.negative { color:#bc5d58; }
    .section-heading { margin:1.45rem 0 .75rem; display:flex; justify-content:space-between; align-items:end; }
    .section-heading h2 { margin:0 !important; }
    .section-heading p { margin:.15rem 0 0; font-size:12px; }
    [data-testid="stVerticalBlockBorderWrapper"] { background:#fff; border-color:var(--line) !important; border-radius:13px !important; }
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] { gap:.8rem; }
    [data-testid="stPlotlyChart"] { border-radius:8px; }
    .stButton > button, .stDownloadButton > button { border-radius:8px; font-weight:600; min-height:2.55rem; }
    .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] { background:var(--green); border-color:var(--green); }
    .stButton > button[kind="primary"]:hover { background:#106349; border-color:#106349; }
    .stTextInput input, .stSelectbox > div > div, .stMultiSelect > div > div, .stDateInput > div > div { border-radius:8px; }
    [data-testid="stFileUploader"] { background:#f9fbfa; border:1px dashed #b8ccc3; border-radius:12px; padding:.4rem; }
    [data-testid="stDataFrame"] { border:1px solid #e8eeeb; border-radius:9px; overflow:hidden; }
    .small-muted { color:var(--muted); font-size:12px; line-height:1.5; }
    .formula { background:#f2f7f4; border-radius:9px; padding:.8rem 1rem; color:#365e50; font-size:13px; border:1px solid #e0ece5; }
    .technician-hero { display:flex; align-items:center; gap:1rem; padding:.25rem 0 .8rem; }
    .avatar { width:50px; height:50px; border-radius:50%; background:#dff0e7; color:#23654e; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:17px; }
    .tech-name { color:#173c35; font-size:20px; font-weight:700; line-height:1.2; }
    .rank-pill { display:inline-block; background:#edf5f1; color:#36705a; padding:4px 9px; border-radius:20px; font-size:11px; font-weight:600; margin-top:5px; }
    .empty-state { text-align:center; background:white; border:1px solid var(--line); border-radius:14px; padding:3rem 1.5rem; margin-top:1.2rem; }
    .empty-icon { width:54px; height:54px; margin:0 auto 1rem; border-radius:15px; background:#e9f4ee; color:#237455; display:flex; align-items:center; justify-content:center; font-size:25px; }
    .empty-state h2 { margin-bottom:.4rem !important; }
    .empty-state p { max-width:540px; margin:0 auto 1.2rem; font-size:14px; }
    .footer { text-align:center; color:#8a9995; font-size:11px; margin-top:2rem; padding-top:1rem; border-top:1px solid #e2e9e5; }
    .stTabs [data-baseweb="tab-list"] { gap:1.5rem; }
    .stTabs [data-baseweb="tab"] { font-weight:600; }
    @media (max-width: 700px) {
        [data-testid="stMainBlockContainer"] { padding:1rem; }
        .header-meta { display:none; }
        .kpi-card { padding:1rem; min-height:120px; }
        .kpi-value { font-size:23px; }
    }
    </style>
    """
