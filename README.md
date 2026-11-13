# Genie Code Usage Patterns

An AI/BI (Lakeview) dashboard showing how people use **Genie Code** (formerly Databricks Assistant) across all workspaces in an account: who uses it, what the agent does for them (code development, data discovery, SQL analysis, dashboards, data engineering, ML, external tools, or read-only Q&A), why its actions fail and how to reduce that, how many DBUs it uses per user and category, and data-driven action items for using it more effectively.

The [dashboard guide](docs/dashboard_guide.md) explains how to use the dashboard and what every KPI and visual means ([sections 1–3](docs/dashboard_guide.md#2-how-to-use-the-dashboard)), and how every number is derived (sections 4–12).

## Repository contents

| Path | What it is |
|---|---|
| `sql/01`–`06_*.sql` | The six materialized views, as templates with `${catalog}` and `${schema}` placeholders |
| `build_dashboard.py` | Defines the dashboard (datasets, pages, widgets, filters, error fixes, action-item and suggested-action rules) and fills in the SQL templates. Both deploy routes use it. |
| `deploy_notebook.py` | Deploys from inside the workspace (Git folder), with no local setup |
| `deploy.py` | Deploys from the command line with a Databricks CLI profile |
| `docs/dashboard_guide.md` | How to use the dashboard, and the full technical reference |

## How it works

Genie Code's agent actions are recorded in `system.access.audit` like any other API call, with a user agent of the form:

```
databricks-background-genie Chrome/... group/<surface> sid/<session-id>
```

The views in `sql/` keep only those events and classify each one by `service_name`, `action_name` and a few request parameters. They then roll the events up into sessions.

| Source | Used for |
|---|---|
| `system.access.assistant_events` | Active users and workspaces (one row per user-submitted Genie Code interaction) |
| `system.access.audit` | Agent actions, which drive the usage categories |
| `system.access.workspaces_latest` | Workspace names |
| `system.billing.usage` | Genie Code DBUs per user |

### Categories

| Category | Examples of actions that count |
|---|---|
| Code Development | Notebook and file edits, notebook creation, Python cell runs, git, apps |
| Data Analysis (SQL) | SQL cell runs, Databricks SQL actions |
| Data Discovery & Governance | Unity Catalog table, schema and catalog lookups; lineage; permissions; tags |
| Dashboards & BI | Lakeview dashboards, Genie spaces |
| Data Engineering & Jobs | Pipelines, jobs, Lakebase |
| ML & AI | Registered models, feature store, MLflow, serving, vector search |
| External Tools (MCP) | MCP `tools/call` requests |
| Q&A / Read-only | Sessions where the agent only read context and changed nothing |

Setup calls the agent makes in almost every session (credential checks, connection listing, context reads) are labelled *Context / Background* and don't count toward any category.

Each session's **primary category** is the one with the most distinct active minutes. Minutes are used instead of raw action counts because notebook edits stream hundreds of events. Sessions owned by non-email identities, and user-days with more than 50 sessions, are labelled `Automated / eval`. The dashboard defaults to `Human`.

### Views

| File | View | Grain |
|---|---|---|
| `sql/01_gc_daily_users_mv.sql` | `gc_daily_users` | day × workspace × user × client type |
| `sql/02_gc_agent_activity_mv.sql` | `gc_agent_activity` | minute × session × action, with category |
| `sql/03_gc_sessions_mv.sql` | `gc_sessions` | one row per agent session |
| `sql/04_gc_session_activity_mv.sql` | `gc_session_activity` | session × category × activity |
| `sql/05_gc_session_errors_mv.sql` | `gc_session_errors` | session × category × activity × error cause (failed events only) |
| `sql/06_gc_cost_mv.sql` | `gc_cost` | day × workspace × user × session (Genie Code spend allocated to sessions) |

All six cover as much history as the system tables retain (`02` reads audit events from 2026-07-01, before which Genie Code agent events don't exist). Events that age out of a system table drop out of the views on the next refresh. They refresh daily at 02:00 (01, 02), 04:00 (03) and 06:00 (04, 05, 06) UTC, so each view refreshes after the views it reads. The dashboard shows a **common window**: every dataset starts on the first agent session date, so user counts and DBUs cover the same period as the session visuals.

### Errors and DBUs

- **Errors** are agent events with HTTP status 400 or above, or a gRPC-style code from 1 to 199. That includes failed notebook cells, which the audit log records as `runCommand` with status `1` rather than 400+. Each error gets one of 19 causes, such as a failed cell, a table not found, permission denied, an external tool failure, a rate limit, a write conflict or one of five dashboard causes, each with why it happens and how to reduce it. The agent's routine existence checks (files, credentials, built-in connectors such as `system_ai_agent_glean_mcp`, `system.ai` connections) return "not found" by design; they are labelled *Expected background probe* and left out of every number. About 97% of raw agent error events are such checks.
- **DBUs** are Genie Code usage from `system.billing.usage` (`usage_metadata.genie.surface = 'GENIE_CODE'`), free tier included. The dashboard shows DBUs only, never dollars. Billing has no session ID, so each workspace's user-day DBUs are split across that user's sessions in the same workspace by active minutes (or across that day's sessions in any workspace if there were none there). DBUs on days without agent sessions show as *Chat only (no agent actions)*.

### Dashboard pages

- **Overview:** KPIs, monthly sessions by category, monthly active users, a category summary table (primary vs. any sessions, users, actions, error rate), and a workspace × category pivot
- **Usage Patterns:** day × hour heatmap, category by surface, session depth, multi-category sessions, a table of agent activities
- **User Detail:** a user scorecard (usage, errors, DBUs, a suggested action quoting the user's own numbers, and other rules that apply), and a profile for the picked users: usage, DBU and error KPIs, a category-mix donut, workspaces and surfaces, a user × category pivot, a category breakdown, error causes with fixes, and a session log
- **Errors & Fixes:** failed-cell rate and share of sessions with errors, error causes with why they happen and how to reduce them, monthly trend, where errors happen, and a user × cause pivot
- **Action Items & DBUs:** DBU KPIs, prioritised action items generated from the data (top error causes, chat-only DBUs, retry loops, long sessions, usage concentration, read-only Q&A share, DBUs per productive session), monthly DBUs by category, and a user × category DBU pivot
- **Filters:** date, workspace, user, user type, surface, primary category, client type

### Filters and cross-filtering

Almost every visual reads one shared dataset of sessions and activities (`ds_main`). So:
- **Filters:** every filter on the Filters page, applies to all of these visuals. The User Detail page's user picker applies to that page only.
- **Cross-filtering:** clicking a bar, slice, heatmap cell, pivot cell or table row filters the other session and activity visuals on the same page. Line charts and KPI tiles don't start cross-filters, but they do respond to them.

Exceptions:
- **User-count visuals** ("Active Genie Code users", "Active workspaces", "Monthly active users", "Days with Genie Code use") read `system.access.assistant_events`, which has no category or surface. They follow the date, workspace, user, user type and client filters, but not the surface or category filters, and they don't respond to clicks on session visuals.
- **The action items and the user scorecard** aggregate inside their own queries. They follow every filter except surface, and they don't cross-filter.
- **Error and cost visuals** use their own datasets (`ds_errors`, `ds_cost`). They follow the filters, and cross-filter only with visuals on the same dataset.

## Deploy

Prerequisites for every route:
- An **existing** catalog and schema, with `USE CATALOG`, `USE SCHEMA`, `CREATE MATERIALIZED VIEW` and `CREATE TABLE` on it for whoever deploys. The deploy never creates a schema.
- Read access to `system.access.audit`, `system.access.assistant_events`, `system.access.workspaces_latest` and `system.billing.usage` (the `access` and `billing` system schemas must be enabled)
- A serverless or Pro SQL warehouse the deployer can use

The views refresh on a schedule under the deployer's identity, so that person or service principal must keep these permissions. Option B also needs Python 3 and the Databricks CLI, authenticated for the target workspace.

There are three ways to deploy. Each creates the views in your existing schema and then creates the dashboard.

### Option A: notebook in the workspace (no local setup)

1. Add this repo to the workspace: **Workspace → Create → Git folder**, then paste the repo URL and pick the branch to deploy. To update an existing deployment, pull the latest changes into the Git folder first.
2. Open `deploy_notebook` in the Git folder and attach it to serverless or any compute.
3. Fill in the widgets: catalog, schema and warehouse ID. Then choose **Run all**.
4. The last cell prints the published link. Later runs update the same dashboard: with the `dashboard_id` widget blank, the notebook finds the dashboard in the dashboard folder (`Genie Code Usage Patterns`) and updates it. Step 1 prints **Will UPDATE** or **Will CREATE** before anything changes; if it says CREATE but you expected an update, stop and check the `parent_path` widget (it must be the folder the dashboard is in) or paste the dashboard ID into `dashboard_id`.

To skip the view step on a later run, for example after a dashboard-only change, set the `create_views` widget to `no`. Keep it `yes` whenever anything in `sql/` changed.

### Option B: command line

```bash
python3 deploy.py --profile <profile> --warehouse-id <warehouse-id> \
  --catalog <catalog> --schema <schema>
```

The script checks that the schema exists, renders the files into `build/` (git-ignored), creates the six views in dependency order, then creates or updates the dashboard and publishes it. By default the dashboard goes in `/Workspace/Users/<you>/GenieCodeUsage`; change this with `--parent-path`. If a dashboard already exists in that folder, it's updated instead of copied. The script prints the dashboard ID and the published link. On later runs:

```bash
python3 deploy.py ...                                               # update views and the dashboard in the folder
python3 deploy.py ... --skip-views                                  # dashboard-only change
python3 deploy.py ... --dashboard-id <dashboard-id>                 # update a dashboard somewhere else
```

### Option C: by hand

1. **Get the SQL with your names filled in.** The files in `sql/` are templates using `${catalog}` and `${schema}`, so they won't run as-is. Do one of:
   - run steps 1–2 of `deploy_notebook`, which print the SQL
   - run `python3 build_dashboard.py --catalog <catalog> --schema <schema>`, which writes `build/sql/*.sql`
2. **Run the six statements in order** (`01` → `06`) in the SQL editor on a SQL warehouse.
3. **Import the dashboard.** Generate `build/genie_code_usage_dashboard.json` with `build_dashboard.py` (above). Each dataset in it already points at your catalog and schema. In the UI: **Dashboards → Create dashboard → Import dashboard from file**. Then publish it.

### After deploying

`02` scans all retained audit logs and can take several minutes. The views refresh themselves daily, so you only need to re-run the view step after editing the SQL. Then grant viewers `SELECT` on the six views and access to the warehouse (see below).

## Access and privacy

- System tables are account-wide, so the dashboard shows usage across **every workspace in the account**, including individual user emails.
- The dashboard is published without embedded credentials, so each viewer queries with their own permissions. Viewers need `SELECT` on the six views and access to the warehouse. The views also read `system.billing`, so whoever creates them needs access to it. Choose carefully who gets that.

## Limitations

- **Categories describe what the agent did, not what the user asked.** No system table holds Genie Code prompts or replies.
- **Python can't be split by purpose.** `commandText` in the audit log is redacted, so every Python cell counts as Code Development; SQL cells are identified from `commandLanguage`.
- **History starts with the agent.** Every visual starts when Genie Code agent events first appear in the audit log (2 July 2026 in the reference account). `assistant_events` and billing keep longer history, which stays in the views but is left off the dashboard so all numbers cover the same period.
- **DBUs by session and category are an estimate.** Compute for cells the agent runs bills to the notebook's compute and isn't included.
- **New action types need a rule.** Agent actions not covered by the rules in `sql/02_gc_agent_activity_mv.sql` fall into *Context / Background* until one is added.
- **Failed cells have no recorded reason.** The audit log doesn't store the exception, so failed cells can't be split by root cause.
- **The latest day is partial.** The views refresh once a day overnight (UTC), so the last day, week and month on trends hold only part of their data.
- **Refresh order is by timing, not guaranteed.** If one view's refresh runs for more than about two hours, the next view reads the previous day's data.
