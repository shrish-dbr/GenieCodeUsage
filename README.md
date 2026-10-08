# Genie Code Usage Patterns

An AI/BI (Lakeview) dashboard showing how people use **Genie Code** (formerly Databricks Assistant) across all workspaces in an account: who uses it, and what the agent does for them (code development, data discovery, SQL analysis, dashboards, data engineering, ML, external tools, or read-only Q&A).

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

All four keep the last 90 days. They refresh daily at 02:00 (01, 02), 04:00 (03) and 06:00 (04) UTC, so each view refreshes after the views it reads.

### Dashboard pages

- **Overview:** KPIs, weekly active users, monthly sessions by category, category mix
- **Usage Patterns:** day × hour heatmap, category by surface, session depth, multi-category sessions, a table of agent activities
- **Workspaces & Users:** workspace × category pivot, user directory, top workspaces
- **User Detail:** top 20 users, per-user KPIs, trends, activities, workspaces and a session log
- **Filters:** date, workspace, user, user type, surface, primary category, client type

## Deploy

Prerequisites:
- The Databricks CLI, authenticated for the target workspace profile
- Python 3
- Access to the `system.access` tables
- A SQL warehouse
- An **existing** catalog and schema where you can create materialized views. The deploy never creates a schema.

There are three ways to deploy. Each creates the views in your existing schema and then creates the dashboard.

### Option A: notebook in the workspace (no local setup)

1. Add this repo to the workspace: **Workspace → Create → Git folder**, then paste the repo URL.
2. Open `deploy_notebook` in the Git folder and attach it to serverless or any compute.
3. Fill in the widgets: catalog, schema and warehouse ID. Then choose **Run all**.
4. The last cell prints the published link and the new dashboard ID. Put that ID into the `dashboard_id` widget so later runs update the same dashboard.

To skip the view step on a later run, for example after a dashboard-only change, set the `create_views` widget to `no`.

### Option B: command line

```bash
python3 deploy.py --profile <profile> --warehouse-id <warehouse-id> \
  --catalog <catalog> --schema <schema>
```

The script checks that the schema exists, renders the files into `build/` (git-ignored), creates the four views in dependency order, then creates the dashboard and publishes it. By default the dashboard goes in `/Workspace/Users/<you>/GenieCodeUsage`; change this with `--parent-path`. The script prints the dashboard ID and the published link. On later runs:

```bash
python3 deploy.py ... --dashboard-id <dashboard-id>                 # update views and dashboard
python3 deploy.py ... --dashboard-id <dashboard-id> --skip-views    # dashboard-only change
```

### Option C: by hand

1. **Get the SQL with your names filled in.** The files in `sql/` are templates using `${catalog}` and `${schema}`, so they won't run as-is. Do one of:
   - run steps 1–2 of `deploy_notebook`, which print the SQL
   - run `python3 build_dashboard.py --catalog <catalog> --schema <schema>`, which writes `build/sql/*.sql`
2. **Run the four statements in order** (`01` → `04`) in the SQL editor on a SQL warehouse.
3. **Import the dashboard.** Generate `build/genie_code_usage_dashboard.json` with `build_dashboard.py` (above). Each dataset in it already points at your catalog and schema. In the UI: **Dashboards → Create dashboard → Import dashboard from file**. Then publish it.

### After deploying

`02` scans 90 days of audit logs and takes a few minutes. The views refresh themselves daily, so you only need to re-run the view step after editing the SQL.

## Access and privacy

- System tables are account-wide, so the dashboard shows usage across **every workspace in the account**, including individual user emails.
- The dashboard is published without embedded credentials, so each viewer queries with their own permissions. Viewers need `SELECT` on the four views and access to the warehouse. Choose carefully who gets that.

## Limitations

- **Categories describe what the agent did, not what the user asked.** No system table holds Genie Code prompts or replies.
- **Python can't be split by purpose.** `commandText` in the audit log is redacted, so every Python cell counts as Code Development; SQL cells are identified from `commandLanguage`.
- **Session-level data starts in late July 2026**, when the `sid/` tag first appeared in the user agent.
- **New action types need a rule.** Agent actions not covered by the rules in `sql/02_gc_agent_activity_mv.sql` fall into *Context / Background* until one is added.
- **Refresh order is by timing, not guaranteed.** If one view's refresh runs for more than about two hours, the next view reads the previous day's data.
