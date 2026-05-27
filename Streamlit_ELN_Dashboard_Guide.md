# Building a Streamlit ELN Dashboard for AWS AppStream

**A step-by-step guide for tracking, trending, and visualizing ELN data from Benchling and/or TetraScience using Python + Streamlit, bundled as a single Windows executable that drops onto an AppStream Image Builder.**

> **Scope note.** This guide assumes the target AWS AppStream environment is already established — VPC, subnets, fleet/stack provisioning, SAML/AD authentication, Secrets Manager, and network egress to Benchling/TetraScience are owned by your platform team. The dashboard is delivered as a self-contained `.exe` that the AppStream admin installs onto the Image Builder like any other application; no AppStream hosting configuration is covered here.

---

## Table of Contents

1. [Overview & Architecture](#1-overview--architecture)
2. [Prerequisites](#2-prerequisites)
3. [Local Development Environment Setup](#3-local-development-environment-setup)
4. [Connecting to the Benchling ELN Data Source](#4-connecting-to-the-benchling-eln-data-source)
5. [Connecting to the TetraScience Data Lake](#5-connecting-to-the-tetrascience-data-lake)
6. [Designing the Data Model](#6-designing-the-data-model)
7. [Building the Streamlit Dashboard](#7-building-the-streamlit-dashboard)
8. [Visualizations: Tracking, Trending, KPIs](#8-visualizations-tracking-trending-kpis)
9. [Bundling Python + Streamlit + Benchling Connector into a Single Executable](#9-bundling-python--streamlit--benchling-connector-into-a-single-executable)
10. [Installing the Executable onto the AppStream Image Builder](#10-installing-the-executable-onto-the-appstream-image-builder)
11. [Testing & Iteration](#11-testing--iteration)
12. [Validation Considerations (GxP / 21 CFR Part 11)](#12-validation-considerations-gxp--21-cfr-part-11)
13. [Appendix A — Full Example App](#appendix-a--full-example-app)
14. [Appendix B — Troubleshooting](#appendix-b--troubleshooting)

---

## 1. Overview & Architecture

The goal is a self-service analytics dashboard for laboratory leadership and scientists that surfaces ELN activity in near-real-time:

- **Compound coverage** — which compound IDs (registry entries) appear across notebooks, and at what cadence.
- **Analysis distribution** — count and type of analyses (e.g., HPLC, LC-MS, NMR, bioassay) per compound, per program, per site.
- **User activity** — who is running which experiments, throughput per scientist, idle vs. active accounts.
- **Experiment timing** — start/finish timestamps, time-to-review, cycle time per workflow step.

### Delivery model

```
┌──────────────────────────────────────────────────┐
│   Developer workstation                          │
│   ├─ Python 3.11 + Streamlit + connectors        │
│   ├─ PyInstaller --onefile                       │
│   └─ Produces: ELN_Dashboard.exe                 │
└────────────────────┬─────────────────────────────┘
                     │  hand off to AppStream admin
                     ▼
┌──────────────────────────────────────────────────┐
│   AWS AppStream 2.0 Image Builder (managed)      │
│   └─ Install ELN_Dashboard.exe via Image         │
│      Assistant → published as an Application     │
└──────────────────────────────────────────────────┘
                     │  (fleet/stack/auth handled
                     │   by the platform team —
                     │   out of scope)
                     ▼
        ┌────────────────────────────────┐
        │ Benchling tenant (REST + WH)   │
        │ TetraScience TDP (Data Lake)   │
        └────────────────────────────────┘
```

The deliverable from the dashboard team is one artifact: **`ELN_Dashboard.exe`** (plus an optional sidecar config file for endpoint URLs). Everything else — credentials retrieval, network egress, user federation, fleet sizing — is already wired in the AppStream environment.

---

## 2. Prerequisites

| Item | Notes |
|---|---|
| Benchling tenant URL + API key (or Warehouse Postgres creds) | Read-only service account preferred |
| TetraScience TDP account + API token | Optional if only Benchling |
| Python 3.11 (64-bit) on Windows dev box | Same arch as the AppStream Image Builder |
| Git client + code editor (VS Code recommended) | |
| A test compound/experiment in Benchling | To validate end-to-end |
| Permission to hand a `.exe` to your AppStream admin | The admin installs it on the Image Builder |

> **Build host = target host.** Build the executable on Windows 64-bit so it runs on the Windows-based AppStream Image Builder. PyInstaller is not a cross-compiler.

---

## 3. Local Development Environment Setup

### 3.1 Create a project workspace

```bash
mkdir eln-dashboard && cd eln-dashboard
python -m venv .venv
.\.venv\Scripts\activate              # Windows
```

### 3.2 Install dependencies

`requirements.txt`:

```
streamlit==1.36.0
pandas==2.2.2
plotly==5.22.0
altair==5.3.0
requests==2.32.3
sqlalchemy==2.0.30
psycopg2-binary==2.9.9
python-dotenv==1.0.1
benchling-sdk==1.16.0
pyarrow==16.1.0
pyinstaller==6.8.0
```

Install:

```bash
pip install -r requirements.txt
```

### 3.3 Project layout

```
eln-dashboard/
├── app/
│   ├── eln_dashboard.py          # Streamlit entrypoint
│   ├── launcher.py               # bootstraps streamlit + opens browser
│   ├── config.py                 # loads endpoint URLs / creds at runtime
│   ├── connectors/
│   │   ├── __init__.py
│   │   ├── benchling_api.py
│   │   ├── benchling_warehouse.py
│   │   └── tetra_client.py
│   ├── transforms/
│   │   ├── compounds.py
│   │   ├── analyses.py
│   │   └── timing.py
│   └── components/
│       ├── filters.py
│       └── charts.py
├── .streamlit/
│   └── config.toml
├── build/
│   └── eln_dashboard.spec        # PyInstaller spec
├── requirements.txt
└── README.md
```

---

## 4. Connecting to the Benchling ELN Data Source

Benchling exposes data in three useful ways. Pick what fits your access tier.

### 4.1 Option A — Benchling REST / SDK (best for live UI queries)

`app/connectors/benchling_api.py`:

```python
from benchling_sdk.benchling import Benchling
from benchling_sdk.auth.api_key_auth import ApiKeyAuth
import streamlit as st
from app.config import get_config

@st.cache_resource
def get_client() -> Benchling:
    cfg = get_config()["benchling"]
    return Benchling(url=cfg["tenant_url"], auth_method=ApiKeyAuth(cfg["api_key"]))

@st.cache_data(ttl=300)
def list_entries(project_id: str | None = None, page_size: int = 100):
    client = get_client()
    pages = client.entries.list_entries(project_id=project_id, page_size=page_size)
    return [e for page in pages for e in page]

@st.cache_data(ttl=600)
def list_registered_entities(schema_id: str, page_size: int = 100):
    client = get_client()
    pages = client.custom_entities.list(schema_id=schema_id, page_size=page_size)
    return [e for page in pages for e in page]
```

**Rate limits.** Benchling enforces per-tenant API limits. Use `@st.cache_data(ttl=...)` aggressively and chunk pulls by date window.

### 4.2 Option B — Benchling Warehouse (best for trending across millions of rows)

The Warehouse is a read-replica Postgres view of your tenant. Connect with SQLAlchemy:

`app/connectors/benchling_warehouse.py`:

```python
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from app.config import get_config

@st.cache_resource
def get_engine():
    c = get_config()["benchling_warehouse"]
    url = f"postgresql+psycopg2://{c['user']}:{c['password']}@{c['host']}:{c['port']}/{c['dbname']}"
    return create_engine(url, pool_pre_ping=True, connect_args={"sslmode": "require"})

@st.cache_data(ttl=900, show_spinner="Querying Benchling Warehouse…")
def query(sql: str, params: dict | None = None) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})
```

Example query — compound IDs appearing in entries with associated assays:

```sql
SELECT  e.id                AS entry_id,
        e.name              AS entry_name,
        e.created_at        AS entry_created_at,
        u.name              AS author,
        comp.file_registry_id$ AS compound_id,
        assay.schema_name   AS analysis_type,
        assay.id            AS analysis_id,
        assay.created_at    AS analysis_created_at
FROM    entry           e
JOIN    user_           u    ON u.id = e.creator_id
JOIN    entry_link      el   ON el.entry_id = e.id
JOIN    custom_entity$raw comp ON comp.id = el.entity_id
LEFT JOIN assay_result$raw assay ON assay.entry_id$ = e.id
WHERE   e.created_at >= :start_date
  AND   e.created_at <  :end_date
  AND   e.archived = false
```

> **Schema naming.** Warehouse columns ending in `$` are Benchling system columns; tables ending in `$raw` are unflattened. Use the Benchling schema browser for your tenant — names vary by tenant configuration.

### 4.3 Option C — Events / Webhook firehose

For real-time activity feeds, subscribe to Benchling Events (entry created, entry reviewed, result uploaded). The dashboard then reads recent events for a "live activity" panel.

---

## 5. Connecting to the TetraScience Data Lake

If your instruments stream into the Tetra Data Platform (TDP), use it to join instrument metadata (sample IDs, run timing, instrument ID, user) with Benchling compound IDs.

`app/connectors/tetra_client.py`:

```python
import requests, streamlit as st, pandas as pd
from app.config import get_config

class TetraClient:
    def __init__(self):
        c = get_config()["tetra"]
        self.base = c["base_url"].rstrip("/")
        self.org  = c["org_slug"]
        self.hdrs = {
            "ts-auth-token": c["auth_token"],
            "x-org-slug": self.org,
            "Content-Type": "application/json",
        }

    @st.cache_data(ttl=300)
    def sql_search(_self, sql: str) -> pd.DataFrame:
        r = requests.post(f"{_self.base}/v1/datalake/search-eql",
                          json={"sql": sql}, headers=_self.hdrs, timeout=60)
        r.raise_for_status()
        return pd.DataFrame(r.json().get("hits", []))

    @st.cache_data(ttl=300)
    def list_files(_self, category: str, limit: int = 1000):
        r = requests.get(f"{_self.base}/v1/datalake/files",
                         params={"category": category, "limit": limit},
                         headers=_self.hdrs, timeout=60)
        r.raise_for_status()
        return r.json()
```

Example Tetra SQL — analyses by instrument type for the last 30 days:

```sql
SELECT  file.id,
        file.category,
        ids.sample.id              AS sample_id,
        ids.instrument.model       AS instrument_model,
        ids.user.username          AS scientist,
        ids.acquisition.start_time AS run_started_at,
        ids.acquisition.duration_s AS duration_s
FROM    "ts-ids"
WHERE   ids.acquisition.start_time >= now() - interval '30' day
```

Join Tetra `sample_id` to Benchling `compound_id` via your registration convention (often Tetra `sample_id` == Benchling `file_registry_id`).

---

## 6. Designing the Data Model

Define a small set of canonical DataFrames every page of the dashboard will use:

| DataFrame | Grain | Required columns |
|---|---|---|
| `entries_df` | one row per ELN entry | `entry_id, entry_name, project, author_id, author_name, created_at, reviewed_at, status` |
| `compound_links_df` | one row per (entry, compound) | `entry_id, compound_id, compound_name, schema, registered_at` |
| `analyses_df` | one row per analysis result | `analysis_id, entry_id, compound_id, analysis_type, instrument, run_started_at, run_duration_s, scientist` |
| `users_df` | one row per user | `user_id, name, email, department, last_active_at` |

Put the joins in `app/transforms/*.py` so the UI layer only consumes already-joined frames. This separation also makes unit testing the data layer painless.

---

## 7. Building the Streamlit Dashboard

### 7.1 Bootstrapping `eln_dashboard.py`

```python
import streamlit as st
import pandas as pd
from datetime import date, timedelta
from app.connectors import benchling_warehouse as bw, tetra_client as tc
from app.components import filters, charts
from app.transforms import compounds, analyses, timing

st.set_page_config(
    page_title="ELN Activity Dashboard",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("ELN Activity Dashboard")
st.caption("Benchling + TetraScience • refreshed every 15 min")

# --- Sidebar filters ----------------------------------------------------------
with st.sidebar:
    st.header("Filters")
    end   = st.date_input("End date",   value=date.today())
    start = st.date_input("Start date", value=end - timedelta(days=90))
    projects   = filters.multiselect_projects()
    scientists = filters.multiselect_users()
    analysis_types = filters.multiselect_analysis_types()

# --- Data load ----------------------------------------------------------------
with st.spinner("Loading ELN activity…"):
    entries_df  = compounds.load_entries(start, end, projects, scientists)
    analyses_df = analyses.load_analyses(start, end, analysis_types, scientists)
    timing_df   = timing.load_timing(entries_df)

# --- KPI strip ----------------------------------------------------------------
k1, k2, k3, k4 = st.columns(4)
k1.metric("Entries",         len(entries_df))
k2.metric("Unique compounds", entries_df["compound_id"].nunique())
k3.metric("Analyses",        len(analyses_df))
k4.metric("Active scientists", entries_df["author_id"].nunique())

# --- Tabs ---------------------------------------------------------------------
tab_overview, tab_compounds, tab_analyses, tab_users, tab_timing = st.tabs(
    ["Overview", "Compounds", "Analyses", "Users", "Timing"]
)

with tab_overview:
    charts.weekly_activity(entries_df)
    charts.heatmap_compound_x_assay(analyses_df)

with tab_compounds:
    charts.top_compounds(analyses_df, top_n=25)
    st.dataframe(compounds.compound_summary(analyses_df), use_container_width=True)

with tab_analyses:
    charts.analyses_by_type(analyses_df)
    charts.analyses_trend(analyses_df)

with tab_users:
    charts.scientist_throughput(entries_df, analyses_df)
    st.dataframe(analyses_df.groupby("scientist").agg(
        analyses=("analysis_id", "count"),
        compounds=("compound_id", "nunique"),
        last_active=("run_started_at", "max"),
    ).reset_index(), use_container_width=True)

with tab_timing:
    charts.cycle_time(timing_df)
    charts.experiment_calendar(entries_df)
```

### 7.2 `.streamlit/config.toml`

```toml
[server]
port = 8501
headless = true
enableCORS = false
enableXsrfProtection = true

[browser]
gatherUsageStats = false

[theme]
base = "light"
primaryColor = "#0B6FA4"
```

### 7.3 Configuration loader

`app/config.py` — reads endpoint URLs/creds from a sidecar TOML next to the exe, or from environment variables. This keeps the secret material out of the bundled binary.

```python
import os, sys, tomllib
from pathlib import Path
from functools import lru_cache

@lru_cache(maxsize=1)
def get_config() -> dict:
    # When frozen by PyInstaller, sys.executable points at the .exe location
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    cfg_path = Path(os.environ.get("ELN_DASHBOARD_CONFIG", base / "eln_dashboard.toml"))
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config not found: {cfg_path}")
    with cfg_path.open("rb") as f:
        return tomllib.load(f)
```

Sample sidecar `eln_dashboard.toml` (the AppStream admin drops this next to the exe; secrets come from the established environment's secret store):

```toml
[benchling]
tenant_url = "https://yourcompany.benchling.com"
api_key    = "${BENCHLING_API_KEY}"

[benchling_warehouse]
host = "postgres-warehouse.benchling.com"
port = 5432
dbname = "warehouse"
user = "ro_dashboard"
password = "${BENCHLING_WAREHOUSE_PW}"

[tetra]
base_url   = "https://api.tetrascience.com"
auth_token = "${TETRA_TOKEN}"
org_slug   = "yourcompany"
```

### 7.4 Run locally during development

```bash
streamlit run app/eln_dashboard.py
```

Open `http://localhost:8501` and confirm the KPI strip and tabs render with cached test data.

---

## 8. Visualizations: Tracking, Trending, KPIs

These belong in `app/components/charts.py`. Each function takes a DataFrame and renders directly via `st.plotly_chart` / `st.altair_chart`.

### 8.1 Weekly activity trend

```python
import plotly.express as px
import streamlit as st

def weekly_activity(entries_df):
    df = (entries_df
          .assign(week=lambda d: d["created_at"].dt.to_period("W").dt.start_time)
          .groupby("week").size().reset_index(name="entries"))
    fig = px.line(df, x="week", y="entries", markers=True,
                  title="ELN entries per week")
    st.plotly_chart(fig, use_container_width=True)
```

### 8.2 Top compounds by analysis count

```python
def top_compounds(analyses_df, top_n=25):
    df = (analyses_df.groupby("compound_id").size()
          .reset_index(name="analyses").nlargest(top_n, "analyses"))
    fig = px.bar(df, x="compound_id", y="analyses",
                 title=f"Top {top_n} compounds by # analyses")
    fig.update_layout(xaxis_tickangle=-45)
    st.plotly_chart(fig, use_container_width=True)
```

### 8.3 Compound × assay heatmap

```python
def heatmap_compound_x_assay(analyses_df, top_compounds=30):
    keep = analyses_df["compound_id"].value_counts().head(top_compounds).index
    pivot = (analyses_df[analyses_df["compound_id"].isin(keep)]
             .pivot_table(index="compound_id", columns="analysis_type",
                          values="analysis_id", aggfunc="count", fill_value=0))
    fig = px.imshow(pivot, aspect="auto", title="Analyses by compound × type")
    st.plotly_chart(fig, use_container_width=True)
```

### 8.4 Scientist throughput

```python
def scientist_throughput(entries_df, analyses_df):
    a = analyses_df.groupby("scientist").size().rename("analyses")
    e = entries_df.groupby("author_name").size().rename("entries")
    df = a.to_frame().join(e, how="outer").fillna(0).reset_index(names="scientist")
    fig = px.scatter(df, x="entries", y="analyses", text="scientist",
                     title="Scientist throughput: entries vs analyses")
    fig.update_traces(textposition="top center")
    st.plotly_chart(fig, use_container_width=True)
```

### 8.5 Cycle time (created → reviewed)

```python
def cycle_time(timing_df):
    df = timing_df.dropna(subset=["reviewed_at"]).copy()
    df["cycle_days"] = (df["reviewed_at"] - df["created_at"]).dt.total_seconds() / 86400
    fig = px.box(df, x="project", y="cycle_days", points="suspectedoutliers",
                 title="Entry cycle time by project (days)")
    st.plotly_chart(fig, use_container_width=True)
```

### 8.6 Experiment calendar heatmap

```python
import altair as alt

def experiment_calendar(entries_df):
    df = entries_df.assign(
        day=entries_df["created_at"].dt.date,
        weekday=entries_df["created_at"].dt.day_name(),
        week=entries_df["created_at"].dt.isocalendar().week,
    )
    daily = df.groupby(["week", "weekday"]).size().reset_index(name="entries")
    chart = (alt.Chart(daily)
             .mark_rect()
             .encode(x="week:O", y="weekday:N",
                     color=alt.Color("entries:Q", scale=alt.Scale(scheme="blues")),
                     tooltip=["week", "weekday", "entries"])
             .properties(title="Experiment activity by day of week"))
    st.altair_chart(chart, use_container_width=True)
```

---

## 9. Bundling Python + Streamlit + Benchling Connector into a Single Executable

The deliverable to the AppStream admin is **`ELN_Dashboard.exe`** — a single Windows binary that, when launched, starts Streamlit on `localhost:8501` and opens the default browser to it.

This section is the heart of the new packaging model.

### 9.1 Launcher entry point

PyInstaller can't run `streamlit run` directly because Streamlit's CLI re-execs itself. Instead, invoke Streamlit's bootstrap API from a small launcher and point it at the bundled script.

`app/launcher.py`:

```python
"""
Entry point for the bundled ELN Dashboard executable.

Launches Streamlit in-process against the bundled eln_dashboard.py,
then opens the default browser to the local server.
"""
import os
import sys
import socket
import threading
import time
import webbrowser
from pathlib import Path

from streamlit.web import bootstrap
from streamlit import config as st_config


def _resource_path(relative: str) -> str:
    """Resolve a path that works both in dev and inside a PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        # PyInstaller unpacks data files into sys._MEIPASS at runtime
        return str(Path(sys._MEIPASS) / relative)
    return str(Path(__file__).resolve().parent.parent / relative)


def _wait_then_open(url: str, port: int) -> None:
    deadline = time.time() + 30
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                webbrowser.open(url)
                return
        time.sleep(0.25)


def main() -> None:
    port = int(os.environ.get("ELN_DASHBOARD_PORT", "8501"))
    script = _resource_path("app/eln_dashboard.py")

    st_config.set_option("server.port", port)
    st_config.set_option("server.headless", True)
    st_config.set_option("server.enableCORS", False)
    st_config.set_option("browser.gatherUsageStats", False)

    threading.Thread(
        target=_wait_then_open,
        args=(f"http://localhost:{port}", port),
        daemon=True,
    ).start()

    # Blocks until the server stops
    bootstrap.run(script, is_hello=False, args=[], flag_options={})


if __name__ == "__main__":
    main()
```

### 9.2 PyInstaller spec file

Streamlit has a quirky import graph and ships data files (static assets, themes, the metadata `.dist-info`). The spec file pulls them in explicitly.

`build/eln_dashboard.spec`:

```python
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import (
    collect_submodules, collect_data_files, copy_metadata,
)

block_cipher = None

hidden = (
    collect_submodules("streamlit")
    + collect_submodules("altair")
    + collect_submodules("plotly")
    + collect_submodules("pyarrow")
    + collect_submodules("benchling_sdk")
    + collect_submodules("benchling_api_client")
)

datas = (
    collect_data_files("streamlit")
    + collect_data_files("altair")
    + collect_data_files("plotly")
    + copy_metadata("streamlit")
    + copy_metadata("altair")
    + copy_metadata("plotly")
    + copy_metadata("pyarrow")
    + copy_metadata("pandas")
    + copy_metadata("benchling-sdk")
    + [("../app", "app"), ("../.streamlit", ".streamlit")]
)

a = Analysis(
    ["../app/launcher.py"],
    pathex=["../"],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib.tests", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas,
    name="ELN_Dashboard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,             # leave UPX off; antivirus on managed images often flags it
    console=False,         # set True while you debug; False for production
    icon="eln_icon.ico",   # optional
    onefile=True,
)
```

### 9.3 The Streamlit `--onefile` gotcha

Streamlit's runtime walks `sys.argv[0]` to determine the script path and watches it for hot-reload. Inside a PyInstaller `--onefile` bundle, `sys.argv[0]` is the exe, not the `.py`. The launcher above sidesteps this by calling `bootstrap.run()` with an explicit script path resolved via `sys._MEIPASS`, instead of re-execing the Streamlit CLI.

If you still see `FileNotFoundError: eln_dashboard.py` at runtime, double-check the `datas` tuple in the spec: the `("../app", "app")` entry copies the whole `app/` folder into the bundle so `_resource_path("app/eln_dashboard.py")` resolves.

### 9.4 Build the executable

From the project root, on a 64-bit Windows machine:

```powershell
.\.venv\Scripts\activate
pyinstaller build\eln_dashboard.spec --clean --noconfirm
```

Output:

```
dist\ELN_Dashboard.exe              ← ship this
```

Typical size: 150–250 MB (Streamlit + Plotly + pandas + pyarrow are heavy). That is normal and acceptable for a managed image.

### 9.5 Smoke-test the binary on a clean Windows VM

Before handing off, copy `dist\ELN_Dashboard.exe` plus a populated `eln_dashboard.toml` onto a Windows VM that does **not** have Python installed and double-click it. Confirm:

1. A console window or system tray indication appears (depending on `console=True/False`).
2. The default browser opens to `http://localhost:8501` within ~30 seconds.
3. Sidebar filters populate (proves Benchling auth works).
4. KPI strip shows non-zero numbers (proves Warehouse query path works).
5. Closing the browser tab and re-running the exe works repeatedly.

Only after this clean-room test should you hand the exe to the AppStream admin.

### 9.6 Versioning the deliverable

Tag each released build:

```bash
git tag -a v1.0.0 -m "Initial release"
git push origin v1.0.0
```

Rename the artifact `ELN_Dashboard_v1.0.0.exe` so the AppStream admin can track which build is on which image.

---

## 10. Installing the Executable onto the AppStream Image Builder

> Reminder: the AppStream environment — VPC, fleet/stack, auth, secret retrieval, networking — is already in place. This section covers only the act of registering the exe as an Application on the existing Image Builder.

Hand off to the AppStream admin a folder containing:

```
ELN_Dashboard_v1.0.0.exe
eln_dashboard.toml              # endpoint URLs only; secrets pulled from your env
eln_icon.ico                    # optional
README_install.txt              # the 4 steps below
```

`README_install.txt`:

```
1. Copy ELN_Dashboard_v1.0.0.exe and eln_dashboard.toml into
   C:\Apps\ELN_Dashboard\ on the AppStream Image Builder.

2. Open Image Assistant → Add App →
      Path:           C:\Apps\ELN_Dashboard\ELN_Dashboard_v1.0.0.exe
      Display name:   ELN Dashboard
      Launch params:  (none)
      Working dir:    C:\Apps\ELN_Dashboard\
      Icon:           C:\Apps\ELN_Dashboard\eln_icon.ico

3. Switch to the Test User profile, launch ELN Dashboard from the
   AppStream catalog, verify the browser opens to localhost:8501 and
   the KPI strip populates within 30 seconds.

4. Return to the admin profile and create a new image
   (suggested name: eln-dash-v1.0.0). Promote according to your
   established image-promotion process.
```

That is the entire AppStream-side touch. No fleet edits, no IAM changes, no networking work — the binary is just one more application icon in the existing catalog.

---

## 11. Testing & Iteration

### 11.1 Unit tests

```bash
pytest app/tests/ -v
```

Mock connectors in tests; never hit live Benchling from CI.

### 11.2 Pre-bundle smoke checklist

Run before every `pyinstaller` build:

- `streamlit run app/eln_dashboard.py` starts cleanly with a test config.
- All five tabs render at least one chart.
- `python -m app.launcher` (the unbundled launcher) opens the browser correctly.

### 11.3 Post-bundle smoke checklist

Run the dist exe on a clean Windows VM:

- Launches without a Python interpreter installed.
- Browser opens within 30 seconds.
- All tabs render.
- Closing the browser releases port 8501; re-running works.

### 11.4 Release tagging

Every exe handed to AppStream is tied to a Git tag and a Changelog entry. The image name on AppStream should match the exe version exactly.

---

## 12. Validation Considerations (GxP / 21 CFR Part 11)

If this dashboard informs regulated decisions, treat it as **Category 5 custom software** under GAMP 5:

- **URS / FRS / DS** — document user requirements, functional spec, design spec.
- **IQ/OQ/PQ** — installation, operational, performance qualification scripts run when the exe is installed on the Image Builder and when the image is promoted.
- **Build provenance** — pin every dependency in `requirements.txt`; archive the `.exe` + a SHA-256 hash next to the Git tag.
- **Access control** — the existing AppStream auth/stack mapping is the access control plane; the exe inherits it.
- **Change control** — Git PR + re-bundle requires QA sign-off; the new exe goes through the same image-promotion process as any other application.
- **Data integrity** — the dashboard is read-only; never write back to Benchling/Tetra.

A read-only analytics layer is far easier to validate than one that mutates source-of-truth records — keep it that way.

---

## Appendix A — Full Example App

A minimal but complete `eln_dashboard.py` you can paste into `app/eln_dashboard.py` and run:

```python
import os
from datetime import date, timedelta
import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine, text
from app.config import get_config

st.set_page_config(page_title="ELN Activity", page_icon="🧪", layout="wide")

@st.cache_resource
def engine():
    c = get_config()["benchling_warehouse"]
    url = (f"postgresql+psycopg2://{c['user']}:{c['password']}"
           f"@{c['host']}:{c['port']}/{c['dbname']}")
    return create_engine(url, pool_pre_ping=True, connect_args={"sslmode": "require"})

@st.cache_data(ttl=900)
def load_activity(start: date, end: date) -> pd.DataFrame:
    sql = text("""
        SELECT e.id              AS entry_id,
               e.name            AS entry_name,
               e.created_at,
               e.modified_at     AS reviewed_at,
               u.name            AS author_name,
               u.id              AS author_id,
               p.name            AS project,
               comp.file_registry_id$ AS compound_id,
               assay.schema_name AS analysis_type,
               assay.id          AS analysis_id,
               assay.created_at  AS run_started_at
          FROM entry e
          JOIN user_ u ON u.id = e.creator_id
          LEFT JOIN project p ON p.id = e.project_id
          LEFT JOIN entry_link el ON el.entry_id = e.id
          LEFT JOIN custom_entity$raw comp ON comp.id = el.entity_id
          LEFT JOIN assay_result$raw assay ON assay.entry_id$ = e.id
         WHERE e.created_at >= :start AND e.created_at < :end
           AND e.archived = false
    """)
    with engine().connect() as conn:
        return pd.read_sql(sql, conn, params={"start": start, "end": end},
                           parse_dates=["created_at", "reviewed_at", "run_started_at"])

end   = st.sidebar.date_input("End",   value=date.today())
start = st.sidebar.date_input("Start", value=end - timedelta(days=90))
df = load_activity(start, end)

projects = st.sidebar.multiselect("Project", sorted(df["project"].dropna().unique()))
if projects:
    df = df[df["project"].isin(projects)]

st.title("ELN Activity Dashboard")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Entries",           df["entry_id"].nunique())
c2.metric("Unique compounds",  df["compound_id"].nunique())
c3.metric("Analyses",          df["analysis_id"].nunique())
c4.metric("Active scientists", df["author_id"].nunique())

tab1, tab2, tab3, tab4 = st.tabs(["Trend", "Compounds", "Analyses", "Users"])

with tab1:
    weekly = (df.dropna(subset=["created_at"])
                .assign(week=lambda d: d["created_at"].dt.to_period("W").dt.start_time)
                .groupby("week").agg(entries=("entry_id", "nunique"),
                                     analyses=("analysis_id", "nunique"))
                .reset_index())
    st.plotly_chart(px.line(weekly, x="week", y=["entries", "analyses"],
                            markers=True, title="Weekly activity"),
                    use_container_width=True)

with tab2:
    top = (df.groupby("compound_id")["analysis_id"].nunique()
             .sort_values(ascending=False).head(25).reset_index())
    st.plotly_chart(px.bar(top, x="compound_id", y="analysis_id",
                           title="Top 25 compounds by # analyses"),
                    use_container_width=True)
    st.dataframe(top, use_container_width=True)

with tab3:
    by_type = (df.dropna(subset=["analysis_type"])
                 .groupby("analysis_type")["analysis_id"].nunique()
                 .sort_values(ascending=False).reset_index())
    st.plotly_chart(px.pie(by_type, names="analysis_type", values="analysis_id",
                           title="Analysis mix"),
                    use_container_width=True)

with tab4:
    by_user = (df.groupby("author_name")
                 .agg(entries=("entry_id", "nunique"),
                      analyses=("analysis_id", "nunique"),
                      compounds=("compound_id", "nunique"),
                      last_active=("created_at", "max"))
                 .reset_index()
                 .sort_values("analyses", ascending=False))
    st.dataframe(by_user, use_container_width=True)
```

---

## Appendix B — Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Double-clicking the exe flashes a console then exits | Missing `streamlit` metadata or static files | Re-bundle with `copy_metadata("streamlit")` and `collect_data_files("streamlit")` in the spec |
| `ModuleNotFoundError: benchling_api_client` at runtime | PyInstaller missed an implicit import | Add `collect_submodules("benchling_api_client")` to `hidden` in the spec |
| `FileNotFoundError: eln_dashboard.py` at startup | The launcher resolved the script path before `_MEIPASS` was populated | Use the `_resource_path()` helper shown in §9.1 |
| Browser opens but page is blank | Streamlit started on a different port | Pass `ELN_DASHBOARD_PORT` env var, or check that port 8501 isn't already used inside the streaming session |
| Exe runs locally but not on the Image Builder | Bitness mismatch between dev box and Image Builder | Build the exe on a 64-bit Windows machine matching the Image Builder OS |
| Antivirus quarantines `ELN_Dashboard.exe` | Unsigned PyInstaller binary | Code-sign the exe with your org's certificate before handoff |
| `SSL: CERTIFICATE_VERIFY_FAILED` to Warehouse | Bundled `certifi` cacert.pem not used | Ensure `certifi` is listed in `requirements.txt` and `collect_data_files("certifi")` is in the spec |
| Charts show counts but no compound IDs | Linked entity column name differs by tenant | Inspect `custom_entity$raw` columns: `SELECT column_name FROM information_schema.columns WHERE table_name='custom_entity$raw'` |
| Streamlit reruns explode latency | `@st.cache_data` missing on a connector function | Wrap every connector function and pick a TTL that matches data freshness needs |
| Filter dropdowns are empty | Token expired between cached calls | Cache the *client object* with `@st.cache_resource`, but cache *results* with `@st.cache_data(ttl=…)` |

---

### Further reading

- Streamlit docs — https://docs.streamlit.io
- Benchling Developer Portal — https://docs.benchling.com/docs/getting-started
- Benchling Warehouse schema reference (tenant-specific) — your Benchling admin → Warehouse browser
- TetraScience Developer Hub — https://developers.tetrascience.com
- PyInstaller docs — https://pyinstaller.org/

---

*Maintainer: ABaghai • Last updated: 2026-05-27*
