# Building a Streamlit ELN Dashboard on AWS AppStream

**A step-by-step guide for tracking, trending, and visualizing ELN data from Benchling and/or TetraScience using Python + Streamlit, delivered through AWS AppStream 2.0.**

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
9. [Authentication, Secrets, and Auditability](#9-authentication-secrets-and-auditability)
10. [Packaging the App for AWS AppStream 2.0](#10-packaging-the-app-for-aws-appstream-20)
11. [Publishing on AppStream: Image Builder → Fleet → Stack](#11-publishing-on-appstream-image-builder--fleet--stack)
12. [Testing, Observability, and Iteration](#12-testing-observability-and-iteration)
13. [Validation Considerations (GxP / 21 CFR Part 11)](#13-validation-considerations-gxp--21-cfr-part-11)
14. [Appendix A — Full Example App](#appendix-a--full-example-app)
15. [Appendix B — Troubleshooting](#appendix-b--troubleshooting)

---

## 1. Overview & Architecture

The goal is a self-service analytics dashboard for laboratory leadership and scientists that surfaces ELN activity in near-real-time:

- **Compound coverage** — which compound IDs (registry entries) appear across notebooks, and at what cadence.
- **Analysis distribution** — count and type of analyses (e.g., HPLC, LC-MS, NMR, bioassay) per compound, per program, per site.
- **User activity** — who is running which experiments, throughput per scientist, idle vs. active accounts.
- **Experiment timing** — start/finish timestamps, time-to-review, cycle time per workflow step.

### Reference architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                       AWS AppStream 2.0 Fleet                        │
│   ┌────────────────────────────────────────────────────────────┐     │
│   │  Windows / Amazon Linux 2 streaming instance              │     │
│   │  ├── Python 3.11 + venv                                   │     │
│   │  ├── Streamlit app (eln_dashboard.py)                     │     │
│   │  └── Launched via custom Application shortcut             │     │
│   └────────────────────────────────────────────────────────────┘     │
│                       │ HTTPS / TLS                                  │
└───────────────────────┼──────────────────────────────────────────────┘
                        │
        ┌───────────────┼────────────────────────────────────┐
        ▼                                                    ▼
┌───────────────────┐                              ┌────────────────────┐
│  Benchling Tenant │                              │ TetraScience TDP   │
│  - REST API       │                              │ - Data Lake API    │
│  - Events API     │                              │ - SQL Search       │
│  - Warehouse      │                              │ - S3 (IDS files)   │
│   (Postgres RO)   │                              │                    │
└───────────────────┘                              └────────────────────┘
        │                                                    │
        └──────────────► AWS Secrets Manager ◄───────────────┘
                       (API keys, DB creds)
```

**Why AppStream?** Many regulated environments cannot expose Benchling or Tetra credentials on user laptops. AppStream centralizes execution inside a controlled VPC, network ACLs restrict egress to Benchling/Tetra endpoints, and session logs feed audit needs.

---

## 2. Prerequisites

Before you start, confirm you have:

| Item | Notes |
|---|---|
| AWS account with rights to AppStream 2.0, IAM, S3, Secrets Manager, VPC | Org admin or delegated role |
| Benchling tenant URL + API key (or Warehouse Postgres creds) | Warehouse access is a paid add-on |
| TetraScience TDP account + API token (or SQL Search creds) | Optional if only Benchling |
| Python 3.11+ locally | For development |
| Git client | For pulling/pushing this repo |
| Code editor (VS Code recommended) | With the Python extension |
| A test compound/experiment in Benchling | To validate end-to-end |

> **Tip — least privilege:** Create read-only service accounts in Benchling and TetraScience specifically for the dashboard. Never reuse personal credentials.

---

## 3. Local Development Environment Setup

### 3.1 Create a project workspace

```bash
mkdir eln-dashboard && cd eln-dashboard
python -m venv .venv
source .venv/bin/activate            # macOS/Linux
.\.venv\Scripts\activate             # Windows PowerShell
```

### 3.2 Install dependencies

Create `requirements.txt`:

```
streamlit==1.36.0
pandas==2.2.2
plotly==5.22.0
altair==5.3.0
requests==2.32.3
sqlalchemy==2.0.30
psycopg2-binary==2.9.9
boto3==1.34.131
python-dotenv==1.0.1
benchling-sdk==1.16.0
pyarrow==16.1.0
streamlit-authenticator==0.3.2
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
│   ├── config.toml
│   └── secrets.toml              # local only — never commit
├── requirements.txt
├── run_dashboard.bat             # launcher used by AppStream
└── README.md
```

### 3.4 Local secrets

`.streamlit/secrets.toml` (do not commit; add to `.gitignore`):

```toml
[benchling]
tenant_url = "https://yourcompany.benchling.com"
api_key    = "sk_live_xxx"

[benchling_warehouse]
host = "postgres-warehouse.benchling.com"
port = 5432
dbname = "warehouse"
user = "ro_dashboard"
password = "REPLACE"

[tetra]
base_url = "https://api.tetrascience.com"
auth_token = "ts_xxx"
org_slug = "yourcompany"
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

@st.cache_resource
def get_client() -> Benchling:
    cfg = st.secrets["benchling"]
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

@st.cache_resource
def get_engine():
    c = st.secrets["benchling_warehouse"]
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

For real-time activity feeds, subscribe to Benchling Events (entry created, entry reviewed, result uploaded) and write to S3 or DynamoDB. The dashboard then reads recent events for the "live activity" panel.

---

## 5. Connecting to the TetraScience Data Lake

If your instruments stream into the Tetra Data Platform (TDP), use it to join instrument metadata (sample IDs, run timing, instrument ID, user) with the Benchling compound IDs.

`app/connectors/tetra_client.py`:

```python
import requests, streamlit as st, pandas as pd

class TetraClient:
    def __init__(self):
        c = st.secrets["tetra"]
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

Put the joins in `app/transforms/*.py` so the UI layer only consumes already-joined frames. This separation makes unit testing the data layer painless.

---

## 7. Building the Streamlit Dashboard

### 7.1 Bootstrapping `eln_dashboard.py`

```python
import streamlit as st
import pandas as pd
from datetime import date, timedelta
from connectors import benchling_warehouse as bw, tetra_client as tc
from components import filters, charts
from transforms import compounds, analyses, timing

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

### 7.3 Run locally

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

## 9. Authentication, Secrets, and Auditability

### 9.1 Secrets

- **Never** ship `.streamlit/secrets.toml` to AppStream image. Fetch at runtime from **AWS Secrets Manager**.
- Attach an IAM role to the AppStream fleet that grants `secretsmanager:GetSecretValue` for only the dashboard's secret ARN.

```python
import boto3, json, functools

@functools.lru_cache(maxsize=1)
def get_secret(name: str) -> dict:
    client = boto3.client("secretsmanager")
    return json.loads(client.get_secret_value(SecretId=name)["SecretString"])
```

Then replace `st.secrets["benchling"]` lookups with `get_secret("eln-dashboard/benchling")`.

### 9.2 User identity inside AppStream

AppStream passes the federated user's identity to the streaming session. Surface it in the app so every action is attributable:

```python
import os
streamlit_user = os.environ.get("AppStream_UserName", "unknown")
st.sidebar.markdown(f"Signed in as **{streamlit_user}**")
```

### 9.3 Audit log

Append every query to CloudWatch Logs:

```python
import logging, watchtower
logger = logging.getLogger("eln_dashboard")
logger.addHandler(watchtower.CloudWatchLogHandler(log_group_name="/eln-dashboard"))
logger.info({"user": streamlit_user, "filters": {...}, "rows": len(entries_df)})
```

---

## 10. Packaging the App for AWS AppStream 2.0

AppStream runs the Streamlit server on a streaming instance and ships the browser tab back to the user. You need a self-contained launcher.

### 10.1 Windows launcher (`run_dashboard.bat`)

```bat
@echo off
SET APP_DIR=C:\AppStream\eln-dashboard
SET PY=%APP_DIR%\.venv\Scripts\python.exe
SET PORT=8501

start "" /B %PY% -m streamlit run %APP_DIR%\app\eln_dashboard.py ^
  --server.port=%PORT% --server.headless=true

REM Wait for server then open the default browser locally inside the session.
powershell -Command "do {Start-Sleep -Milliseconds 500} until (Test-NetConnection -ComputerName localhost -Port %PORT% -InformationLevel Quiet)"
start "" "http://localhost:%PORT%"
```

### 10.2 Linux launcher (`run_dashboard.sh`)

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /opt/eln-dashboard
source .venv/bin/activate
streamlit run app/eln_dashboard.py --server.port=8501 --server.headless=true &
until curl -s http://localhost:8501 > /dev/null; do sleep 0.5; done
xdg-open http://localhost:8501
wait
```

### 10.3 Bake the image

Inside the AppStream **Image Builder** instance:

1. Install Python 3.11 (Windows: official installer; Amazon Linux: `dnf install python3.11`).
2. Clone the repo to `C:\AppStream\eln-dashboard` (or `/opt/eln-dashboard`).
3. Create venv, `pip install -r requirements.txt`.
4. Use **Image Assistant** → **Add Application** → point to `run_dashboard.bat` (or `.sh`).
5. Set display name "ELN Dashboard", icon, working directory.
6. Click **Switch user → Test User** and launch to confirm.
7. Back in admin: **Image Assistant → Create Image** with a versioned name (`eln-dash-v1.3.0`).

---

## 11. Publishing on AppStream: Image Builder → Fleet → Stack

```
Image Builder ──► Image ──► Fleet ──► Stack ──► Users
```

### 11.1 Create the Fleet

- **Fleet type:** `On-Demand` (cheaper) or `Always-On` (faster start).
- **Instance type:** `stream.standard.medium` is plenty for ~50 concurrent Streamlit users; size up if you do heavy pandas joins.
- **VPC:** the same VPC that has routes to Benchling Warehouse (via PrivateLink or NAT) and TetraScience endpoints.
- **IAM role:** attach the role with `secretsmanager:GetSecretValue` and `logs:PutLogEvents`.
- **Session duration:** 4 hours; idle disconnect 15 min.

### 11.2 Create the Stack

- Attach the fleet.
- **User settings:** disable clipboard out, file upload, printing if your validation policy requires it.
- **Storage:** enable Home Folders (S3-backed) so users can save chart exports.

### 11.3 Entitle users

Either:
- **User Pool** mode — create users by email, AppStream emails them an invite, or
- **SAML 2.0 federation** — preferred in pharma; integrate with Okta/Azure AD and map AD groups to AppStream stacks.

### 11.4 Launch URL

Users click the streaming URL → SSO → see the "ELN Dashboard" icon → click → Streamlit opens inside the streaming session.

---

## 12. Testing, Observability, and Iteration

### 12.1 Unit tests

```bash
pytest app/tests/ -v
```

Mock connectors in tests; never hit live Benchling.

### 12.2 Smoke checks on every image rebuild

- Launcher script starts the server within 30 seconds.
- Sidebar filters populate (proves Benchling auth works).
- KPI strip shows non-zero numbers (proves Warehouse query path works).
- One chart from each tab renders without exception (proves all transforms).

### 12.3 CloudWatch dashboards

Pipe these metrics:
- `streamlit_request_count` (custom metric, log-derived)
- AppStream `ActualCapacity`, `AvailableCapacity`, `InsufficientCapacityError`
- Latency of Benchling Warehouse queries (emit from `connectors/benchling_warehouse.py`)

### 12.4 Versioned releases

Tag each AppStream image to a Git commit. When you cut `v1.4.0`:
```bash
git tag -a v1.4.0 -m "Add cycle-time tab"
git push origin v1.4.0
```
Reference the tag in the Image name so rollbacks are deterministic.

---

## 13. Validation Considerations (GxP / 21 CFR Part 11)

If this dashboard informs regulated decisions, treat it as **Category 5 custom software** under GAMP 5:

- **URS / FRS / DS** — document user requirements, functional spec, design spec.
- **IQ/OQ/PQ** — installation, operational, performance qualification scripts run during AppStream image promotion.
- **Audit trail** — CloudWatch log retention ≥ record retention period.
- **Access control** — AD group → AppStream stack mapping reviewed quarterly.
- **Change control** — Git PR + image rebuild requires QA sign-off before fleet swap.
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

# ─── Config ──────────────────────────────────────────────────────────────────
st.set_page_config(page_title="ELN Activity", page_icon="🧪", layout="wide")
USER = os.environ.get("AppStream_UserName", "local-dev")

# ─── Connection ──────────────────────────────────────────────────────────────
@st.cache_resource
def engine():
    c = st.secrets["benchling_warehouse"]
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

# ─── Sidebar ─────────────────────────────────────────────────────────────────
st.sidebar.markdown(f"**User:** {USER}")
end   = st.sidebar.date_input("End",   value=date.today())
start = st.sidebar.date_input("Start", value=end - timedelta(days=90))
df = load_activity(start, end)

projects = st.sidebar.multiselect("Project", sorted(df["project"].dropna().unique()))
if projects:
    df = df[df["project"].isin(projects)]

# ─── Header KPIs ─────────────────────────────────────────────────────────────
st.title("ELN Activity Dashboard")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Entries",           df["entry_id"].nunique())
c2.metric("Unique compounds",  df["compound_id"].nunique())
c3.metric("Analyses",          df["analysis_id"].nunique())
c4.metric("Active scientists", df["author_id"].nunique())

# ─── Tabs ────────────────────────────────────────────────────────────────────
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
| Streamlit app launches but spinner never finishes | Outbound port 443 blocked from AppStream subnet | Add Benchling/Tetra hostnames to the subnet's NACL/SG allow list |
| `SSL: CERTIFICATE_VERIFY_FAILED` to Warehouse | Missing CA bundle on image | `pip install certifi` and set `SSL_CERT_FILE` env var on the fleet |
| Charts show counts but no compound IDs | Linked entity column name differs by tenant | Inspect `custom_entity$raw` columns with `SELECT column_name FROM information_schema.columns WHERE table_name='custom_entity$raw'` |
| AppStream user lands on "Application could not be launched" | Launcher returned non-zero or browser closed before server started | Increase the wait loop in `run_dashboard.bat`; check Event Viewer for stderr |
| Streamlit reruns explode latency | `@st.cache_data` missing on a connector function | Wrap every connector function and pick a TTL that matches data freshness needs |
| Filter dropdowns are empty | Token expired between cached calls | Cache the *client object* with `@st.cache_resource`, but cache *results* with `@st.cache_data(ttl=…)` |

---

### Further reading

- Streamlit docs — https://docs.streamlit.io
- Benchling Developer Portal — https://docs.benchling.com/docs/getting-started
- Benchling Warehouse schema reference (tenant-specific) — your Benchling admin → Warehouse browser
- TetraScience Developer Hub — https://developers.tetrascience.com
- AWS AppStream 2.0 Admin Guide — https://docs.aws.amazon.com/appstream2/

---

*Maintainer: ABaghai • Last updated: 2026-05-27*
