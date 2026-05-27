# Building a Streamlit ELN Dashboard as a Server-Hosted SharePoint Embed (v2)

**A step-by-step guide for delivering a persistent ELN analytics dashboard from Benchling (and optionally TetraScience) using Python + Streamlit, deployed as a Windows service on an internal server and embedded as a live web part inside an internal SharePoint site.**

> **v2 vs v1.** v1 (`Streamlit_ELN_Dashboard_Guide.md`) bundles Streamlit into a desktop-style exe that the user double-clicks inside AppStream. **v2 (this guide) is the opposite shape**: one always-on server hosts the dashboard, terminates TLS, persists user inputs in a database, and SharePoint embeds it as an iframe so scientists never leave their team site. Choose v2 when you want shared state, low click-cost discovery, and a single URL to govern.

---

## Table of Contents

1. [Overview & Architecture](#1-overview--architecture)
2. [Prerequisites](#2-prerequisites)
3. [Server Provisioning](#3-server-provisioning)
4. [Project Layout & Dependencies](#4-project-layout--dependencies)
5. [Persistence Layer: Storing User Inputs](#5-persistence-layer-storing-user-inputs)
6. [Connecting to the Benchling ELN Data Source](#6-connecting-to-the-benchling-eln-data-source)
7. [Streamlit Configuration for Reverse-Proxy + Iframe Embedding](#7-streamlit-configuration-for-reverse-proxy--iframe-embedding)
8. [Building the Dashboard with User-Input Forms](#8-building-the-dashboard-with-user-input-forms)
9. [Visualizations: Tracking, Trending, KPIs](#9-visualizations-tracking-trending-kpis)
10. [Bundling the App into a Windows Service Executable](#10-bundling-the-app-into-a-windows-service-executable)
11. [Reverse Proxy: IIS ARR (or nginx) with TLS](#11-reverse-proxy-iis-arr-or-nginx-with-tls)
12. [Single Sign-On with Azure AD / Entra ID](#12-single-sign-on-with-azure-ad--entra-id)
13. [Embedding the Dashboard in SharePoint](#13-embedding-the-dashboard-in-sharepoint)
14. [Operations: Logs, Restarts, Backups, Monitoring](#14-operations-logs-restarts-backups-monitoring)
15. [Validation Considerations (GxP / 21 CFR Part 11)](#15-validation-considerations-gxp--21-cfr-part-11)
16. [Appendix A — Full Example App with Persisted Annotations](#appendix-a--full-example-app-with-persisted-annotations)
17. [Appendix B — Troubleshooting](#appendix-b--troubleshooting)

---

## 1. Overview & Architecture

The dashboard runs as a **persistent Windows service** on an internal application server. A reverse proxy (IIS with ARR, or nginx) terminates TLS at `https://eln-dashboard.corp.local`, sits in front of Streamlit's HTTP + WebSocket endpoints, and injects the security headers that allow the page to be embedded as an iframe inside SharePoint Online (or on-prem). User inputs — annotations, watchlists, tag overrides, saved views — are written to a local SQLite or central Postgres database so they survive restarts and are shared across viewers.

```
┌────────────────────────────────────────────────────────────────────────────┐
│   Internal user's browser (inside SharePoint team site)                   │
│   ┌──────────────────────────────────────────────────────────────────┐    │
│   │  SharePoint page  ┌─────────────────────────────────────────┐    │    │
│   │                   │ Embed web part →                        │    │    │
│   │                   │ <iframe src="https://eln-dashboard       │    │    │
│   │                   │              .corp.local/?embed=true"/> │    │    │
│   │                   └─────────────────────────────────────────┘    │    │
│   └──────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────┬─────────────────────────────────────────────┘
                               │ HTTPS (TLS, SSO cookie)
                               ▼
┌────────────────────────────────────────────────────────────────────────────┐
│   App server (Windows Server 2022 or RHEL 9, on-prem or EC2)              │
│                                                                            │
│   ┌──────────────────────┐    ┌──────────────────────────────────────┐    │
│   │ Reverse proxy        │───►│  ELN_Dashboard_Service.exe           │    │
│   │ (IIS+ARR or nginx)   │    │  ├─ Streamlit on 127.0.0.1:8501      │    │
│   │ - TLS termination    │    │  ├─ Benchling SDK + Warehouse pool   │    │
│   │ - SSO (oauth2-proxy  │    │  ├─ Tetra client (optional)          │    │
│   │   / Azure App Proxy) │    │  └─ Local SQLite for user inputs     │    │
│   │ - CSP / frame headers│    │     (or → corporate Postgres)        │    │
│   └──────────────────────┘    └──────────────────────────────────────┘    │
│           ▲                                  │                              │
│           │                                  ▼                              │
│           │                  ┌────────────────────────────┐                 │
│           │                  │  Windows Service Manager   │                 │
│           │                  │  (auto-start, restart,     │                 │
│           │                  │  rotating logs)            │                 │
│           │                  └────────────────────────────┘                 │
└───────────┼─────────────────────────────────────────────────────────────────┘
            │
            ▼
   ┌─────────────────────────────┐    ┌─────────────────────────────┐
   │ Benchling (REST + Warehouse)│    │ TetraScience TDP (optional) │
   └─────────────────────────────┘    └─────────────────────────────┘
```

**Key shape differences from v1:**

| Concern | v1 (AppStream exe) | **v2 (server + SharePoint)** |
|---|---|---|
| Lifetime | One process per user session | **One process for everyone, 24/7** |
| Discovery | AppStream catalog icon | **Embedded in the team's SharePoint page** |
| User state | Lost when the session ends | **Persisted in SQLite/Postgres, shared** |
| Auth | Inherited from AppStream | **SSO via reverse proxy / Azure AD** |
| Network | Egress from the streaming instance | **Server ↔ Benchling/Tetra, browser ↔ server** |
| Updates | Re-bundle exe, rebuild image | **Stop service → swap exe → start service** |

---

## 2. Prerequisites

| Item | Notes |
|---|---|
| Windows Server 2022 (or RHEL 9) VM, 4 vCPU / 16 GB RAM | Sized for ~50 concurrent viewers |
| Internal DNS name + TLS certificate | `eln-dashboard.corp.local` from your internal PKI |
| Outbound network from server → Benchling / Tetra (HTTPS 443) | Through corp proxy if applicable |
| Inbound 443 from corp network to server | Restrict to corp CIDRs |
| Azure AD / Entra ID tenant admin willing to register an App Registration | For SSO |
| SharePoint Online (or on-prem) site with Edit rights on a page | To insert the embed |
| Benchling tenant URL + API key (and Warehouse creds if used) | Read-only service account |
| A Windows account or gMSA the service will run as | Used by the Windows service |
| Git + Python 3.11 (64-bit) on a build workstation | Same arch as the server |

---

## 3. Server Provisioning

### 3.1 Base OS hardening (Windows)

1. Apply the latest cumulative updates.
2. Join the server to AD; place it in the `Tier-2 App Servers` OU (or equivalent).
3. Install only: Python 3.11 (64-bit), Git, the IIS role with **URL Rewrite** + **Application Request Routing (ARR)** features, and your AV agent.
4. Create directories:
   ```
   C:\Apps\eln-dashboard\          ← application files
   C:\Apps\eln-dashboard\data\     ← SQLite DB, scratch
   C:\Apps\eln-dashboard\logs\     ← rotating logs
   C:\Apps\eln-dashboard\config\   ← TOML config + cert paths
   ```
5. Set NTFS ACLs so only the service account and `Administrators` can read `config\`.

### 3.2 Service account

Create or request `svc_eln_dashboard` (gMSA preferred). Grant **Log on as a service**. Grant read on `C:\Apps\eln-dashboard\` and read/write on `data\` and `logs\`.

### 3.3 Firewall

- Inbound `443/TCP` from corp CIDRs → server (handled by IIS).
- Inbound `8501/TCP` **closed externally**; only `127.0.0.1` reaches Streamlit.
- Outbound `443/TCP` → Benchling tenant, Warehouse host, TetraScience API, and Azure AD endpoints.

---

## 4. Project Layout & Dependencies

```
eln-dashboard/
├── app/
│   ├── eln_dashboard.py          # Streamlit entrypoint
│   ├── service.py                # Windows-service wrapper (pywin32)
│   ├── launcher.py               # Streamlit bootstrap (also usable standalone)
│   ├── config.py
│   ├── persistence/
│   │   ├── __init__.py
│   │   ├── db.py                 # SQLAlchemy engine + session
│   │   └── models.py             # annotations, watchlists, saved views
│   ├── connectors/
│   │   ├── benchling_api.py
│   │   ├── benchling_warehouse.py
│   │   └── tetra_client.py
│   ├── transforms/
│   └── components/
├── .streamlit/
│   └── config.toml
├── build/
│   └── eln_service.spec
├── deploy/
│   ├── install_service.ps1
│   ├── uninstall_service.ps1
│   ├── web.config                # IIS ARR rewrite rules
│   └── nginx.conf                # alternative reverse proxy
├── requirements.txt
└── README.md
```

`requirements.txt`:

```
streamlit==1.36.0
pandas==2.2.2
plotly==5.22.0
altair==5.3.0
requests==2.32.3
sqlalchemy==2.0.30
psycopg2-binary==2.9.9
benchling-sdk==1.16.0
pyarrow==16.1.0
pywin32==306
pyinstaller==6.8.0
python-dotenv==1.0.1
alembic==1.13.2
```

---

## 5. Persistence Layer: Storing User Inputs

Because the server is shared, user inputs (annotations, watchlists, saved filter views, manual tags) must outlive the process.

### 5.1 Schema (`app/persistence/models.py`)

```python
from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey, JSON, func
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class Annotation(Base):
    __tablename__ = "annotations"
    id           = Column(Integer, primary_key=True)
    target_type  = Column(String(32), nullable=False)   # 'compound' | 'entry' | 'analysis'
    target_id    = Column(String(128), nullable=False, index=True)
    author       = Column(String(128), nullable=False)
    body         = Column(Text, nullable=False)
    created_at   = Column(DateTime, server_default=func.now())

class Watchlist(Base):
    __tablename__ = "watchlists"
    id        = Column(Integer, primary_key=True)
    owner     = Column(String(128), nullable=False, index=True)
    name      = Column(String(128), nullable=False)
    compound_ids = Column(JSON, nullable=False, default=list)
    created_at   = Column(DateTime, server_default=func.now())

class SavedView(Base):
    __tablename__ = "saved_views"
    id        = Column(Integer, primary_key=True)
    owner     = Column(String(128), nullable=False, index=True)
    name      = Column(String(128), nullable=False)
    filters   = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
```

### 5.2 Engine & session (`app/persistence/db.py`)

```python
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import get_config
from app.persistence.models import Base

@st.cache_resource
def engine():
    cfg = get_config()["persistence"]
    eng = create_engine(cfg["url"], pool_pre_ping=True, future=True)
    Base.metadata.create_all(eng)  # idempotent — fine for SQLite/dev
    return eng

def session():
    return sessionmaker(bind=engine(), expire_on_commit=False, future=True)()
```

Config:

```toml
[persistence]
# SQLite for single-server installs:
url = "sqlite:///C:/Apps/eln-dashboard/data/eln.db"
# Or central Postgres for multi-server / HA:
# url = "postgresql+psycopg2://svc_eln:${PG_PW}@pg-corp.corp.local:5432/eln"
```

> **Production note.** Use Alembic migrations (`alembic init`, `alembic revision --autogenerate`) once the schema is in active use. `create_all` is fine for the first release only.

### 5.3 Capture inputs from the UI

```python
import streamlit as st
from app.persistence.db import session
from app.persistence.models import Annotation

def annotation_panel(target_type: str, target_id: str, user: str):
    with session() as s:
        existing = (s.query(Annotation)
                     .filter_by(target_type=target_type, target_id=target_id)
                     .order_by(Annotation.created_at.desc()).all())
    for a in existing:
        st.markdown(f"**{a.author}** · _{a.created_at:%Y-%m-%d %H:%M}_\n\n{a.body}")
        st.divider()
    with st.form(key=f"ann_{target_type}_{target_id}", clear_on_submit=True):
        body = st.text_area("Add a note")
        if st.form_submit_button("Save") and body.strip():
            with session() as s:
                s.add(Annotation(target_type=target_type, target_id=target_id,
                                 author=user, body=body.strip()))
                s.commit()
            st.rerun()
```

---

## 6. Connecting to the Benchling ELN Data Source

Connector code is **identical to v1** (REST/SDK and/or Warehouse). The only deployment-level change: the connector pool now lives in a long-running process, so increase `pool_size` and ensure `pool_pre_ping=True` so idle connections don't break overnight.

```python
# app/connectors/benchling_warehouse.py — server-tuned engine
@st.cache_resource
def get_engine():
    c = get_config()["benchling_warehouse"]
    return create_engine(
        f"postgresql+psycopg2://{c['user']}:{c['password']}@{c['host']}:{c['port']}/{c['dbname']}",
        pool_size=10, max_overflow=10, pool_recycle=1800,
        pool_pre_ping=True, connect_args={"sslmode": "require"},
    )
```

The SDK-based client (`benchling_api.py`) and the Tetra client (`tetra_client.py`) are unchanged from v1 — refer to §4 and §5 there. Refresh API tokens by restarting the service when the secret rotates (or wire in a credential-refresh thread).

---

## 7. Streamlit Configuration for Reverse-Proxy + Iframe Embedding

This is where v2 diverges sharply from v1. Streamlit is going to sit behind a reverse proxy and be embedded inside another origin (SharePoint). Three things must be right:

### 7.1 `.streamlit/config.toml`

```toml
[server]
port = 8501
address = "127.0.0.1"            # never bind to 0.0.0.0 on the corp network
headless = true
enableCORS = false                # the reverse proxy handles CORS
enableXsrfProtection = false      # required when embedded in a foreign origin
baseUrlPath = "/eln"              # if you proxy under /eln on the hostname
fileWatcherType = "none"          # services should not auto-reload
runOnSave = false
maxUploadSize = 50

[browser]
gatherUsageStats = false
serverAddress = "eln-dashboard.corp.local"
serverPort = 443

[theme]
base = "light"
primaryColor = "#0B6FA4"
```

> **Why disable XSRF?** Streamlit's XSRF check requires the page's Origin header to match its own server address. When SharePoint embeds the page in an iframe, the parent Origin is the SharePoint host, which breaks the check. Disable XSRF only when the reverse proxy enforces SSO — otherwise you've removed the only client-side gate.

### 7.2 Detect embed mode

When the iframe loads, SharePoint appends nothing useful by default — so add a query string ourselves. The Embed web part URL will be `https://eln-dashboard.corp.local/eln?embed=true`. The app reads that to hide the sidebar/header inside the embed:

```python
import streamlit as st

EMBEDDED = st.query_params.get("embed", "false").lower() == "true"
if EMBEDDED:
    st.markdown(
        "<style>header, footer, #MainMenu {visibility: hidden;}</style>",
        unsafe_allow_html=True,
    )
    st.set_page_config(layout="wide", initial_sidebar_state="collapsed")
```

### 7.3 Headers the reverse proxy must inject

For an iframe inside SharePoint (origin e.g. `https://contoso.sharepoint.com`), the response from the Streamlit endpoint **must** include:

```
Content-Security-Policy: frame-ancestors 'self' https://contoso.sharepoint.com https://*.sharepoint.com;
X-Frame-Options: <remove or replace with ALLOW-FROM equivalent CSP>
```

Modern browsers ignore `X-Frame-Options: ALLOW-FROM`; the CSP `frame-ancestors` directive is what actually allows the embed. Remove any conflicting `X-Frame-Options: SAMEORIGIN` that Streamlit or the proxy adds by default.

WebSocket support is required — Streamlit uses `ws://…/_stcore/stream`. Both IIS ARR and nginx need WebSocket forwarding enabled (shown in §11).

---

## 8. Building the Dashboard with User-Input Forms

The non-persisted KPI / trend tabs from v1 carry over verbatim. v2 adds three input-driven tabs that write to the database.

### 8.1 Watchlist tab

```python
import streamlit as st
from app.persistence.db import session
from app.persistence.models import Watchlist

def watchlist_tab(current_user: str, all_compound_ids: list[str]):
    st.subheader("My watchlists")
    with session() as s:
        my_lists = s.query(Watchlist).filter_by(owner=current_user).all()

    for wl in my_lists:
        with st.expander(f"{wl.name} ({len(wl.compound_ids)})"):
            st.write(wl.compound_ids)
            if st.button("Delete", key=f"del_{wl.id}"):
                with session() as s:
                    s.query(Watchlist).filter_by(id=wl.id).delete()
                    s.commit()
                st.rerun()

    with st.form("new_watchlist", clear_on_submit=True):
        name = st.text_input("New watchlist name")
        picks = st.multiselect("Compounds", all_compound_ids)
        if st.form_submit_button("Create") and name and picks:
            with session() as s:
                s.add(Watchlist(owner=current_user, name=name, compound_ids=picks))
                s.commit()
            st.rerun()
```

### 8.2 Annotations tab

Reuses `annotation_panel()` from §5.3. Attach it to any compound / entry / analysis detail view.

### 8.3 Saved views

Lets a user freeze the current sidebar filter set and reload it later — useful for "Q2 lead-opt program" or "MedChem oncology weekly review."

```python
from app.persistence.models import SavedView

def saved_views_sidebar(current_user: str, current_filters: dict):
    with st.sidebar.expander("Saved views"):
        with session() as s:
            views = s.query(SavedView).filter_by(owner=current_user).all()
        for v in views:
            if st.button(f"Load: {v.name}", key=f"sv_{v.id}"):
                st.session_state["loaded_filters"] = v.filters
                st.rerun()
        new = st.text_input("Save current as")
        if st.button("Save view") and new:
            with session() as s:
                s.add(SavedView(owner=current_user, name=new, filters=current_filters))
                s.commit()
            st.rerun()
```

---

## 9. Visualizations: Tracking, Trending, KPIs

Visualization functions are identical to v1 §8 (`weekly_activity`, `top_compounds`, `heatmap_compound_x_assay`, `scientist_throughput`, `cycle_time`, `experiment_calendar`). The only addition is overlaying the user's watchlist on `top_compounds`:

```python
def top_compounds(analyses_df, watchlist_ids: set[str], top_n=25):
    df = (analyses_df.groupby("compound_id").size()
          .reset_index(name="analyses").nlargest(top_n, "analyses"))
    df["on_watchlist"] = df["compound_id"].isin(watchlist_ids)
    fig = px.bar(df, x="compound_id", y="analyses", color="on_watchlist",
                 color_discrete_map={True: "#0B6FA4", False: "#B0BEC5"},
                 title=f"Top {top_n} compounds — yours highlighted")
    fig.update_layout(xaxis_tickangle=-45)
    st.plotly_chart(fig, use_container_width=True)
```

---

## 10. Bundling the App into a Windows Service Executable

The deliverable is **`ELN_Dashboard_Service.exe`** — a PyInstaller bundle that exposes a `pywin32` service so Windows manages start/stop/restart natively.

### 10.1 The service wrapper (`app/service.py`)

```python
import os
import sys
import socket
import threading
import time
from pathlib import Path

import servicemanager
import win32service
import win32serviceutil
import win32event

from streamlit.web import bootstrap
from streamlit import config as st_config


def _resource_path(rel: str) -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return str(base / rel)


def _run_streamlit() -> None:
    st_config.set_option("server.port", int(os.environ.get("ELN_PORT", "8501")))
    st_config.set_option("server.address", "127.0.0.1")
    st_config.set_option("server.headless", True)
    st_config.set_option("server.enableCORS", False)
    st_config.set_option("server.enableXsrfProtection", False)
    st_config.set_option("server.fileWatcherType", "none")
    st_config.set_option("browser.gatherUsageStats", False)
    bootstrap.run(_resource_path("app/eln_dashboard.py"),
                  is_hello=False, args=[], flag_options={})


class ELNDashboardService(win32serviceutil.ServiceFramework):
    _svc_name_         = "ELNDashboard"
    _svc_display_name_ = "ELN Dashboard (Streamlit)"
    _svc_description_  = "Hosts the internal ELN analytics dashboard for SharePoint embedding."

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.worker = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        servicemanager.LogInfoMsg("ELNDashboard starting")
        self.worker = threading.Thread(target=_run_streamlit, daemon=True)
        self.worker.start()
        win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
        servicemanager.LogInfoMsg("ELNDashboard stopping")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(ELNDashboardService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(ELNDashboardService)
```

### 10.2 PyInstaller spec (`build/eln_service.spec`)

```python
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata

hidden = (
    collect_submodules("streamlit")
    + collect_submodules("altair")
    + collect_submodules("plotly")
    + collect_submodules("benchling_sdk")
    + collect_submodules("benchling_api_client")
    + collect_submodules("sqlalchemy.dialects")
    + ["win32timezone", "win32service", "win32event", "servicemanager"]
)

datas = (
    collect_data_files("streamlit")
    + collect_data_files("altair")
    + collect_data_files("plotly")
    + copy_metadata("streamlit")
    + copy_metadata("altair")
    + copy_metadata("plotly")
    + copy_metadata("benchling-sdk")
    + copy_metadata("pandas")
    + [("../app", "app"), ("../.streamlit", ".streamlit")]
)

a = Analysis(
    ["../app/service.py"], pathex=["../"], datas=datas, hiddenimports=hidden,
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6"],
)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas,
    name="ELN_Dashboard_Service",
    console=True,           # services run console-style; logs go to Event Viewer + files
    onefile=True,
    icon=None,
)
```

Build:

```powershell
.\.venv\Scripts\activate
pyinstaller build\eln_service.spec --clean --noconfirm
copy dist\ELN_Dashboard_Service.exe C:\Apps\eln-dashboard\
```

### 10.3 Install & start the service

`deploy/install_service.ps1`:

```powershell
Param(
  [string]$ExePath = "C:\Apps\eln-dashboard\ELN_Dashboard_Service.exe",
  [string]$ServiceAccount = "CORP\svc_eln_dashboard$"   # gMSA
)

& $ExePath install
sc.exe config ELNDashboard obj= $ServiceAccount start= auto
sc.exe failure ELNDashboard reset= 86400 actions= restart/5000/restart/5000/restart/10000
sc.exe description ELNDashboard "ELN analytics dashboard (Streamlit) — embedded in SharePoint."
Start-Service ELNDashboard
Get-Service ELNDashboard
```

The service now listens on `127.0.0.1:8501` and will auto-restart on crash and after server reboots.

> **Linux alternative.** Skip pywin32 and ship the same launcher (`launcher.py` from v1 §9.1) plus a `systemd` unit (`/etc/systemd/system/eln-dashboard.service`) with `Restart=on-failure` and `ExecStart=/opt/eln-dashboard/ELN_Dashboard`.

---

## 11. Reverse Proxy: IIS ARR (or nginx) with TLS

### 11.1 IIS + URL Rewrite + ARR (Windows path)

`deploy/web.config` placed at `C:\inetpub\wwwroot\eln\web.config` (after creating an IIS site bound to `eln-dashboard.corp.local:443` with the corp TLS cert):

```xml
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <!-- WebSocket upgrade for /_stcore/stream -->
        <rule name="StreamlitWS" stopProcessing="true">
          <match url="(.*)" />
          <conditions>
            <add input="{HTTP_UPGRADE}" pattern="websocket" />
          </conditions>
          <action type="Rewrite" url="http://127.0.0.1:8501/{R:1}" />
        </rule>
        <!-- All other traffic -->
        <rule name="StreamlitHTTP" stopProcessing="true">
          <match url="(.*)" />
          <action type="Rewrite" url="http://127.0.0.1:8501/{R:1}" />
        </rule>
      </rules>
      <outboundRules>
        <!-- Replace SAMEORIGIN with frame-ancestors CSP for SharePoint -->
        <rule name="StripXFO" preCondition="IsHTML">
          <match serverVariable="RESPONSE_X-Frame-Options" pattern=".*" />
          <action type="Rewrite" value="" />
        </rule>
        <rule name="AddCSP" preCondition="IsHTML">
          <match serverVariable="RESPONSE_Content-Security-Policy" pattern=".*" />
          <action type="Rewrite" value="frame-ancestors 'self' https://*.sharepoint.com https://contoso.sharepoint.com;" />
        </rule>
        <preConditions>
          <preCondition name="IsHTML">
            <add input="{RESPONSE_CONTENT_TYPE}" pattern="^text/html" />
          </preCondition>
        </preConditions>
      </outboundRules>
    </rewrite>
    <security>
      <requestFiltering removeServerHeader="true" />
    </security>
  </system.webServer>
</configuration>
```

In IIS Manager → Server → **Application Request Routing Cache** → **Server Proxy Settings**: tick **Enable proxy**. Reboot IIS. Verify by browsing `https://eln-dashboard.corp.local/` from a corp laptop.

### 11.2 nginx (Linux path) — equivalent

`deploy/nginx.conf`:

```nginx
server {
    listen 443 ssl http2;
    server_name eln-dashboard.corp.local;

    ssl_certificate     /etc/pki/tls/certs/eln-dashboard.crt;
    ssl_certificate_key /etc/pki/tls/private/eln-dashboard.key;

    add_header Content-Security-Policy
        "frame-ancestors 'self' https://*.sharepoint.com https://contoso.sharepoint.com;" always;
    proxy_hide_header X-Frame-Options;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
```

---

## 12. Single Sign-On with Azure AD / Entra ID

Streamlit has no built-in auth. Put auth at the reverse proxy. Two reliable patterns:

### 12.1 Pattern A — Azure AD Application Proxy (cleanest if you have it)

If your org already uses Entra ID Application Proxy, register the internal URL as a published app and let it enforce conditional access. The proxy sets headers like `X-MS-CLIENT-PRINCIPAL-NAME` that the Streamlit app reads:

```python
import streamlit as st
from streamlit.web.server.websocket_headers import _get_websocket_headers

def current_user() -> str:
    h = _get_websocket_headers() or {}
    return h.get("X-Ms-Client-Principal-Name") or "anonymous"
```

### 12.2 Pattern B — `oauth2-proxy` sidecar

Run `oauth2-proxy` between the public TLS endpoint and Streamlit. It performs the OIDC dance with Entra ID, sets a session cookie, and forwards `X-Forwarded-User` to Streamlit.

```
Browser ──HTTPS──► IIS/nginx (TLS) ──► oauth2-proxy (OIDC) ──► Streamlit
```

Either way, the **user identity is trustworthy** by the time it reaches `eln_dashboard.py`, and you can attribute every `Annotation`, `Watchlist`, and `SavedView` to a real principal.

### 12.3 Wire identity into the app

```python
user = current_user()
st.sidebar.markdown(f"Signed in as **{user}**")
# Pass `user` into annotation_panel(), watchlist_tab(), saved_views_sidebar(), etc.
```

---

## 13. Embedding the Dashboard in SharePoint

### 13.1 SharePoint Online — Embed web part (simplest)

1. Open the team site → **Edit** the page where the dashboard should live.
2. Add a section → **+** → **Embed**.
3. Paste:
   ```html
   <iframe
     src="https://eln-dashboard.corp.local/?embed=true"
     width="100%" height="900"
     style="border:0;"
     allow="fullscreen"
     title="ELN Dashboard">
   </iframe>
   ```
4. Republish the page.
5. SharePoint sanitizes the iframe but allows the host because it's added to the tenant's **HTML Field Security → Allowed iframe domains** list. Ask your SharePoint admin to add `eln-dashboard.corp.local` there if the embed shows a blocked-content notice.

### 13.2 SharePoint Online — modern Page Viewer / SPFx web part

For richer integration (auto-size, theme matching), use a small SPFx web part that renders the iframe and listens for `postMessage` from Streamlit for height resizing. Streamlit-side:

```python
import streamlit.components.v1 as components
components.html(
    """<script>
       const h = document.documentElement.scrollHeight;
       parent.postMessage({type: 'eln-dashboard-height', height: h}, '*');
       </script>""",
    height=0,
)
```

SPFx-side, listen for the message and adjust the iframe height.

### 13.3 SharePoint on-prem (2019 / Subscription Edition)

The classic **Page Viewer Web Part** still works:

1. Edit page → **Insert → Web Part → Media and Content → Page Viewer**.
2. Set the link to `https://eln-dashboard.corp.local/?embed=true`.
3. Save. Confirm the CSP header from §11 lists your on-prem SharePoint hostname.

### 13.4 First-time troubleshooting (embedding)

Open the embedded page in a new tab first (`https://eln-dashboard.corp.local/?embed=true`) and confirm it loads standalone. If it does, but the SharePoint page shows a blank frame, open browser DevTools → **Console** and look for `Refused to display … because an ancestor violates …`. That is always a `frame-ancestors` CSP mismatch — fix the value in §11.

---

## 14. Operations: Logs, Restarts, Backups, Monitoring

### 14.1 Logging

Streamlit logs to stdout. Capture it from the service:

```python
# inside app/service.py, before bootstrap.run()
import logging, logging.handlers
handler = logging.handlers.TimedRotatingFileHandler(
    r"C:\Apps\eln-dashboard\logs\eln.log", when="midnight", backupCount=30
)
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)
```

Forward to Splunk / Sentinel / Elastic via your existing log shipper.

### 14.2 Health check

Add a tiny `/_health` endpoint via Streamlit's static routes, or simply use the proxy's TCP probe on 8501. The reverse proxy should return `503` if Streamlit doesn't respond within 5s.

### 14.3 Backups

- **SQLite:** snapshot `C:\Apps\eln-dashboard\data\eln.db` nightly to the corporate backup share. Annotations and watchlists are the only irreplaceable data.
- **Postgres (if used):** rely on the central DBA backup policy; verify the dashboard schema is in scope.

### 14.4 Restart cadence

- Auto-restart on crash via `sc.exe failure` (see §10.3).
- Manual restart after deploying a new exe:
  ```powershell
  Stop-Service ELNDashboard
  Copy-Item .\ELN_Dashboard_Service_v1.1.0.exe C:\Apps\eln-dashboard\ELN_Dashboard_Service.exe
  Start-Service ELNDashboard
  ```

### 14.5 Monitoring

Send to your existing platform:
- `ELNDashboard` service state (alert on `Stopped`).
- HTTP 5xx rate from the reverse proxy.
- Benchling Warehouse query p95 latency (instrument inside `benchling_warehouse.query`).
- DB file size growth (SQLite).

---

## 15. Validation Considerations (GxP / 21 CFR Part 11)

Compared with v1, v2 introduces *write paths* (annotations, watchlists, saved views). Treat those as user-generated records:

- **Audit trail.** Every `Annotation` row already has `author + created_at`. Add an `Annotation` `History` table on update/delete to preserve the prior state — or make annotations append-only.
- **e-signature.** If annotations contribute to GxP decisions, gate the save form behind a re-authentication step (Entra ID step-up auth).
- **Access control.** SSO at the reverse proxy is the enforcement point; document the AD group → SharePoint site → embed visibility chain.
- **Backup & retention.** Persistence DB retention must match record retention policy (often 10+ years for clinical, 7+ for non-clinical).
- **Source of truth.** The dashboard never writes back to Benchling. Annotations are *commentary*, not authoritative data — make that visible in the UI.
- **Change control.** Tagged Git release → built service exe → QA-approved deployment to the production server. Roll back by swapping the exe and restarting.

---

## Appendix A — Full Example App with Persisted Annotations

A self-contained `eln_dashboard.py` showing the v2 shape: identity from the proxy header, persisted annotations, watchlist overlay, and embed-aware layout.

```python
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date, timedelta
from sqlalchemy import text
from streamlit.web.server.websocket_headers import _get_websocket_headers

from app.config import get_config
from app.connectors.benchling_warehouse import get_engine
from app.persistence.db import session
from app.persistence.models import Annotation, Watchlist

# ─── Embed detection ─────────────────────────────────────────────────────────
EMBEDDED = st.query_params.get("embed", "false").lower() == "true"
st.set_page_config(
    page_title="ELN Activity",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="collapsed" if EMBEDDED else "expanded",
)
if EMBEDDED:
    st.markdown("<style>header, footer, #MainMenu {visibility: hidden;}</style>",
                unsafe_allow_html=True)

# ─── Identity from reverse proxy ─────────────────────────────────────────────
def current_user() -> str:
    h = _get_websocket_headers() or {}
    return (h.get("X-Ms-Client-Principal-Name")
            or h.get("X-Forwarded-User")
            or "anonymous")

USER = current_user()

# ─── Data ────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=900)
def load_activity(start: date, end: date) -> pd.DataFrame:
    sql = text("""
        SELECT e.id AS entry_id, e.name AS entry_name, e.created_at,
               e.modified_at AS reviewed_at, u.name AS author_name,
               p.name AS project, comp.file_registry_id$ AS compound_id,
               assay.schema_name AS analysis_type, assay.id AS analysis_id
          FROM entry e
          JOIN user_ u ON u.id = e.creator_id
          LEFT JOIN project p ON p.id = e.project_id
          LEFT JOIN entry_link el ON el.entry_id = e.id
          LEFT JOIN custom_entity$raw comp ON comp.id = el.entity_id
          LEFT JOIN assay_result$raw assay ON assay.entry_id$ = e.id
         WHERE e.created_at >= :start AND e.created_at < :end AND e.archived = false
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params={"start": start, "end": end},
                           parse_dates=["created_at", "reviewed_at"])

# ─── Sidebar ─────────────────────────────────────────────────────────────────
st.sidebar.markdown(f"Signed in as **{USER}**")
end   = st.sidebar.date_input("End",   value=date.today())
start = st.sidebar.date_input("Start", value=end - timedelta(days=90))
df = load_activity(start, end)

with session() as s:
    wls = s.query(Watchlist).filter_by(owner=USER).all()
watchlist_ids = set(i for wl in wls for i in (wl.compound_ids or []))

# ─── Header ──────────────────────────────────────────────────────────────────
if not EMBEDDED:
    st.title("ELN Activity Dashboard")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Entries",          df["entry_id"].nunique())
c2.metric("Unique compounds", df["compound_id"].nunique())
c3.metric("Analyses",         df["analysis_id"].nunique())
c4.metric("On your watchlist", df["compound_id"].isin(watchlist_ids).sum())

# ─── Tabs ────────────────────────────────────────────────────────────────────
tab_trend, tab_compounds, tab_watch, tab_notes = st.tabs(
    ["Trend", "Compounds", "Watchlists", "Notes"]
)

with tab_trend:
    weekly = (df.assign(week=df["created_at"].dt.to_period("W").dt.start_time)
                .groupby("week").agg(entries=("entry_id", "nunique"),
                                     analyses=("analysis_id", "nunique"))
                .reset_index())
    st.plotly_chart(px.line(weekly, x="week", y=["entries", "analyses"],
                            markers=True, title="Weekly activity"),
                    use_container_width=True)

with tab_compounds:
    top = (df.groupby("compound_id")["analysis_id"].nunique()
             .sort_values(ascending=False).head(25).reset_index())
    top["on_watchlist"] = top["compound_id"].isin(watchlist_ids)
    st.plotly_chart(px.bar(top, x="compound_id", y="analysis_id",
                           color="on_watchlist",
                           color_discrete_map={True: "#0B6FA4", False: "#B0BEC5"},
                           title="Top 25 compounds — yours highlighted"),
                    use_container_width=True)

with tab_watch:
    st.subheader("My watchlists")
    for wl in wls:
        with st.expander(f"{wl.name} ({len(wl.compound_ids or [])})"):
            st.write(wl.compound_ids)
            if st.button("Delete", key=f"del_{wl.id}"):
                with session() as s:
                    s.query(Watchlist).filter_by(id=wl.id).delete()
                    s.commit()
                st.rerun()
    with st.form("new_watchlist", clear_on_submit=True):
        name  = st.text_input("New watchlist name")
        picks = st.multiselect("Compounds",
                               sorted(df["compound_id"].dropna().unique()))
        if st.form_submit_button("Create") and name and picks:
            with session() as s:
                s.add(Watchlist(owner=USER, name=name, compound_ids=picks))
                s.commit()
            st.rerun()

with tab_notes:
    target = st.selectbox("Compound", sorted(df["compound_id"].dropna().unique()))
    if target:
        with session() as s:
            notes = (s.query(Annotation)
                       .filter_by(target_type="compound", target_id=target)
                       .order_by(Annotation.created_at.desc()).all())
        for n in notes:
            st.markdown(f"**{n.author}** · _{n.created_at:%Y-%m-%d %H:%M}_\n\n{n.body}")
            st.divider()
        with st.form("note", clear_on_submit=True):
            body = st.text_area(f"Add a note about {target}")
            if st.form_submit_button("Save") and body.strip():
                with session() as s:
                    s.add(Annotation(target_type="compound", target_id=target,
                                     author=USER, body=body.strip()))
                    s.commit()
                st.rerun()
```

---

## Appendix B — Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| SharePoint shows blank iframe with `Refused to frame` console error | CSP `frame-ancestors` doesn't include the SharePoint host | Update the `Content-Security-Policy` rule in `web.config` / `nginx.conf` (§11) |
| Dashboard loads in iframe but charts never appear | WebSocket not proxied — Streamlit stuck on the connecting spinner | Verify the WS rewrite rule (IIS ARR) or `Upgrade`/`Connection` headers (nginx); confirm with browser DevTools → Network → WS |
| Streamlit returns `403 Forbidden — XSRF check failed` | XSRF still enabled with mismatched Origin | Set `server.enableXsrfProtection = false` *only because* SSO is enforced at the proxy |
| Page works in a normal tab but fails inside SharePoint | Third-party cookies blocked for the iframe origin | Add `eln-dashboard.corp.local` to the SharePoint tenant's allowed-iframe domain list; serve cookies with `SameSite=None; Secure` from the reverse proxy / oauth2-proxy |
| `ELNDashboard` service starts then exits within seconds | Missing PyInstaller hidden import (often `win32timezone` or a `sqlalchemy.dialects.*`) | Append the missing module to `hidden` in `eln_service.spec` and rebuild |
| Annotations vanish after deploy | SQLite file lives inside the app directory and was overwritten on redeploy | Move DB to `C:\Apps\eln-dashboard\data\` (outside the deploy artifact) and never touch it during deploys |
| All annotations attributed to `anonymous` | Reverse proxy not forwarding identity header | Confirm `oauth2-proxy --set-xauthrequest` (or App Proxy header config) and that Streamlit reads the correct header name in `current_user()` |
| Service runs but Benchling Warehouse connections drop overnight | TCP keepalive too short on the corp firewall | Set `pool_recycle=1800` on the SQLAlchemy engine (already in §6) |
| `Refused to connect to 'wss://…'` from inside SharePoint | Proxy serving HTTP not HTTPS for WS | Ensure `proxy_set_header X-Forwarded-Proto $scheme` and that Streamlit's `serverPort=443` is set in `config.toml` |
| Restarting the service kicks every user out instantly | No graceful drain | Schedule restarts in off-hours; consider running two service instances behind ARR with health-check failover |

---

### Further reading

- Streamlit deployment options — https://docs.streamlit.io/deploy
- Streamlit `frame-ancestors` discussion — https://docs.streamlit.io/library/advanced-features/configuration
- IIS Application Request Routing — https://learn.microsoft.com/iis/extensions/configuring-application-request-routing-arr/
- Microsoft Entra Application Proxy — https://learn.microsoft.com/entra/identity/app-proxy/
- oauth2-proxy — https://oauth2-proxy.github.io/oauth2-proxy/
- SharePoint Embed web part — https://support.microsoft.com/office/use-the-embed-web-part-94254944-8a01-49da-9300-30f2eba8e528
- Benchling Developer Portal — https://docs.benchling.com/docs/getting-started
- pywin32 service framework — https://timgolden.me.uk/pywin32-docs/win32serviceutil.html

---

*Maintainer: ABaghai • Version: v2 (server-hosted, SharePoint-embedded) • Last updated: 2026-05-27*
