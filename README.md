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

- **Overview:** KPIs, weekly active users, weekly sessions by category, category mix
- **Usage Patterns:** day × hour heatmap, category by surface, session depth, multi-category sessions, a table of agent activities
- **Workspaces & Users:** workspace × category pivot, user directory, top workspaces
- **User Detail:** per-user KPIs, trends, activities, workspaces and a session log
- **Filters:** date, workspace, user, user type, surface, primary category, client type

## Deploy

Prerequisites:
- The Databricks CLI, authenticated to the target workspace
- Access to the `system.access` tables
- A SQL warehouse
- A catalog where you can create a schema

1. **Render the SQL and dashboard JSON** for your catalog and schema. The schema is created in step 2, and defaults to `genie_code_usage`:

   ```bash
   python3 build_dashboard.py --catalog <catalog> [--schema genie_code_usage]
   ```

   This writes `build/sql/00`–`04_*.sql` and `build/genie_code_usage_dashboard.json`. The files in `sql/` are templates that use `${catalog}` and `${schema}`; don't run them directly. `build/` is git-ignored.

2. **Create the schema and views**, in order:

   ```bash
   export DATABRICKS_WAREHOUSE_ID=<warehouse-id>
   for f in build/sql/*.sql; do
     databricks experimental aitools tools query --profile <profile> --file "$f"
   done
   ```

   `02` scans 90 days of audit logs and takes a few minutes.

3. **Create the dashboard and publish it.** `parent_path` must already exist; create it with `databricks workspace mkdirs <folder>` if needed.

   ```bash
   databricks lakeview create --profile <profile> \
     --display-name "Genie Code Usage Patterns" \
     --warehouse-id <warehouse-id> \
     --dataset-catalog <catalog> --dataset-schema <schema> \
     --serialized-dashboard "$(cat build/genie_code_usage_dashboard.json)" \
     --json '{"parent_path": "/Workspace/Users/<you>/GenieCodeUsage"}'
   databricks lakeview publish <dashboard-id> --profile <profile> --warehouse-id <warehouse-id>
   ```

   `lakeview create` returns the new dashboard's ID. Save it for later changes; running `create` again makes a second copy with a new link.

4. **To change an existing dashboard**, run step 1 again. Then run `databricks lakeview update <dashboard-id>` with the same `--dataset-catalog`, `--dataset-schema` and `--serialized-dashboard` flags, then `publish` again.

## Access and privacy

- System tables are account-wide, so the dashboard shows usage across **every workspace in the account**, including individual user emails.
- The dashboard is published without embedded credentials, so each viewer queries with their own permissions. Viewers need `SELECT` on the four views and access to the warehouse. Choose carefully who gets that.

## Limitations

- **Categories describe what the agent did, not what the user asked.** No system table holds Genie Code prompts or replies.
- **Python can't be split by purpose.** `commandText` in the audit log is redacted, so every Python cell counts as Code Development; SQL cells are identified from `commandLanguage`.
- **Session-level data starts in late July 2026**, when the `sid/` tag first appeared in the user agent.
- **New action types need a rule.** Agent actions not covered by the rules in `sql/02_gc_agent_activity_mv.sql` fall into *Context / Background* until one is added.
- **Refresh order is by timing, not guaranteed.** If one view's refresh runs for more than about two hours, the next view reads the previous day's data.
