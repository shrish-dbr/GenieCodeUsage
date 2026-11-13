# Genie Code Usage Patterns: dashboard guide

This guide has two parts. **Sections 1–3 are for everyone who uses the dashboard:** what it measures, how to use it, and what every KPI and visual means. **Sections 4–12 are the technical reference:** where every number comes from, how events become sessions and categories, how each metric is calculated, and the limits of the data. The technical part describes the code in `sql/` and `build_dashboard.py`; if you change either, update this guide.

**Using the dashboard**
- [1. What the dashboard measures](#1-what-the-dashboard-measures)
- [2. How to use the dashboard](#2-how-to-use-the-dashboard)
- [3. Page by page: every KPI and visual](#3-page-by-page-every-kpi-and-visual)

**Technical reference**
- [4. Data lineage](#4-data-lineage)
- [5. From audit events to categories](#5-from-audit-events-to-categories)
- [6. From events to sessions](#6-from-events-to-sessions)
- [7. Dashboard datasets](#7-dashboard-datasets)
- [8. Metric definitions](#8-metric-definitions)
- [9. Filters and cross-filtering](#9-filters-and-cross-filtering)
- [10. Reconciling numbers](#10-reconciling-numbers)
- [11. Limitations](#11-limitations)
- [12. Glossary](#12-glossary)

---

## 1. What the dashboard measures

The dashboard answers four questions about **Genie Code** (formerly Databricks Assistant) across every workspace in the account:

1. **Who uses it?** Users, workspaces, and the client they use it from.
2. **What does the agent do for them?** Writing code, exploring the catalog, running SQL, building dashboards, and so on.
3. **Where does it fail, and why?** Error causes, each with how to reduce it.
4. **How many DBUs does it use, and what should we do?** DBUs by user and category, plus action items generated from the data.

It covers Genie Code only. It does **not** include people chatting directly in Genie spaces (Genie Agents), "Ask Genie" in AI/BI dashboards, or Agent Bricks. It does include the times the Genie Code agent worked with a Genie space for a user (see *Dashboards & BI* in [section 5](#5-from-audit-events-to-categories)).

**Categories describe what the agent did, not what the user asked.** No system table stores Genie Code prompts or replies, so the dashboard infers purpose from the API calls the agent made.

---

## 2. How to use the dashboard

### Quick start

1. **Set the scope on the Filters page.** The filters there apply to every page. By default the dashboard shows all available dates and **human** users only; change *User type* to include automated and evaluation traffic.
2. **Start on Overview** to see adoption (users, workspaces, sessions) and what the agent is mainly used for.
3. **Go to the page that matches your question** (table below), then click bars, cells or rows to narrow the other visuals on that page.
4. **To coach one person, open User Detail** and pick them with the *User(s)* picker at the top right.
5. **For what to do next, open Action Items & DBUs.** The action items are generated from the filtered data, highest priority first.

### Where to find the answer

| Question | Where to look |
|---|---|
| Is adoption growing? | Overview: *Monthly active users by client*, *Monthly agent sessions by primary category* |
| What is the agent mainly used for? | Overview: *Category summary* (Sessions primary vs any), *Monthly agent sessions by primary category* |
| Which workspaces use it, and for what? | Overview: *Sessions by workspace and primary category* |
| Do people let the agent do the work, or just ask questions? | Overview: *Sessions that took action*; Usage Patterns: *Multi-category sessions* |
| When and where is it used? | Usage Patterns: the day × hour heatmap and *Category mix by surface* |
| What exactly does the agent do? | Usage Patterns: *Agent activities by category* |
| Who are the heaviest users, and what should each one change? | User Detail: *User scorecard* (most DBUs first, with a suggested action) |
| What happened in a specific person's sessions? | User Detail: pick the user, then the *Session log* and *Errors and how to reduce them* |
| Why do agent actions fail, and how do we reduce that? | Errors & Fixes: *Error causes and how to reduce them* |
| Who needs help with errors? | Errors & Fixes: *Errors by user and cause group* |
| Where do the DBUs go? | Action Items & DBUs: *Monthly Genie Code DBUs by category*, *DBUs by user and category* |
| What should we do first? | Action Items & DBUs: *Action items* (High priority first) |
| Did a change help, for example new workspace instructions? | Compare two periods with the *Date* filter: *Failed cell rate*, *Sessions with an error*, the *not found* cause, retry loops and *Sessions that took action* |

### Interacting with the dashboard

- **Filters page:** Date, Workspace, User, User type, Surface, Primary category and Client type. Some filters don't reach every visual because the data behind them has no such field; see [section 9](#9-filters-and-cross-filtering).
- **User(s) picker (User Detail only):** narrows that page, including the scorecard, to the selected people. With nobody selected the page shows everyone.
- **Click to cross-filter:** clicking a bar, pie slice, heatmap cell, pivot cell or table row filters the other visuals on the same page that use the same data. Click it again, or clear the selection, to reset. KPI tiles and line charts respond to clicks but don't start them. The action items and the user scorecard are calculated in their own queries, so they follow the filters but not clicks.
- **KPI trend lines:** tiles whose number is a total (*Active agent minutes*, *Genie Code DBUs*, *Actionable errors*) show the weekly totals under the number. Rates and distinct counts show only the period total, because weekly values of those can't be added up to the headline.
- **Tables:** click a column header to sort. Use the widget menu to download the data behind a visual.

### Reading tips

- **Human users by default.** Service principals, and users with more than 50 sessions in a day, count as *Automated / eval* and are hidden unless you change *User type*.
- **All times and dates are UTC.**
- **The latest day, week and month are partial.** The data refreshes once a day overnight (UTC), so the last point on a trend is usually lower than the rest.
- **Categories describe what the agent did, not what the user asked.** No system table holds Genie Code prompts or replies.
- **Users and sessions come from different sources.** *Active Genie Code users* counts anyone who used Genie Code, chat included; the session visuals count only people whose sessions made the agent act.
- **DBU totals are exact; DBUs per session or category are estimates.** Billing has no session ID, so each user-day's DBUs are split across that day's sessions by active minutes.
- **Numbers don't reconcile?** See [section 10](#10-reconciling-numbers).

---

## 3. Page by page: every KPI and visual

Each page lists its KPI tiles (what the number measures and how to read it), then its visuals (what each shows and what to use it for). *(trend)* marks KPI tiles with a weekly trend line. Exact formulas are in [section 8](#8-metric-definitions).

### Overview: is it being adopted, and for what?

| KPI | What it measures | How to read it |
|---|---|---|
| **Active Genie Code users** | Distinct people with any Genie Code interaction in the period, from any client, chat included | Breadth of adoption. It's usually well above the number of people with agent sessions, because many only chat. |
| **Active workspaces** | Distinct workspaces with any Genie Code interaction | How widely it's spread across the account |
| **Agent sessions** | Distinct agent sessions: conversations in which the agent made at least one API call | Volume of agent work |
| **Sessions that took action** | Share of sessions in which the agent changed or ran something (any primary category except *Q&A / Read-only*) | Higher means people let the agent do the work. Low means it's mostly used for questions and explanations. |

| Visual | What it shows | Use it to |
|---|---|---|
| **Monthly agent sessions by primary category** | Stacked bars: sessions per month, coloured by each session's main activity | See growth and how the mix of work changes over time. The current month is partial. |
| **Monthly active users by client** | Lines: distinct users per month, by how they reached Genie Code (browser, background agent, Genie Code service, other) | Track adoption month by month |
| **Category summary** | One row per category: Sessions (primary), Sessions (any), Users, Agent actions, Error rate | Compare what sessions are mainly for (*primary*) with how often the agent does each kind of work at all (*any*). A big gap means the category usually supports other work, such as catalog lookups before writing code. Click a row to filter the page. |
| **Sessions by workspace and primary category** | Pivot: workspaces as rows (most sessions first), primary categories as columns, colour-scaled session counts | Find the most active workspaces and what each uses Genie Code for. *Account-level* means sessions with no workspace-scoped actions. Click a cell to filter the page. |

### Usage Patterns: how and when it's used

| Visual | What it shows | Use it to |
|---|---|---|
| **When sessions happen (day × hour, UTC)** | Heatmap of sessions by weekday and hour the session started | See peak days and hours, for example to time enablement sessions or support cover. Hours are UTC. |
| **Multi-category sessions** | Sessions by how many categories they touched: 0 (read-only), 1, 2 or 3+ | See how much of the usage is multi-step work, for example exploring the catalog, then writing code, then building a dashboard |
| **Category mix by surface** | 100% stacked bars: share of each primary category per surface (Genie Code panel, Embedded, Document, Visualization) | See which entry point is used for which kind of work |
| **Session depth (active minutes)** | Sessions per active-minute bucket (1, 2–5, 6–15, 16–60, 60+), coloured by primary category | Tell quick questions from long builds. Many 60+ minute sessions feed the *Long sessions* action item. |
| **Agent activities by category** | One row per category × activity (for example *Run sql cell*, *Edit notebook*, *UC: getTable*, *MCP: slack*): Sessions, Users, Workspaces, Agent actions | See exactly what the agent does inside each category, and spot new or unusual activities |

### User Detail: who the users are, and one person's profile

Use the **User scorecard** to find who to look at, then pick them with the **User(s)** picker at the top right; every visual on the page, including the scorecard, narrows to them. With nobody selected the page shows everyone. For one person's trends on the other pages, use the *User* filter on the Filters page instead.

| KPI | What it measures | How to read it |
|---|---|---|
| **Agent sessions** | The selected users' agent sessions | Volume of their agent use |
| **Sessions that took action** | Share of their sessions in which the agent changed or ran something | Low means they mostly ask questions; compare with the Overview value |
| **Active agent minutes** *(trend)* | Distinct minutes in which the agent was working for them, summed over sessions | Time the agent spent on their work. It isn't the time the person spent. |
| **Days with Genie Code use** | Days with any Genie Code interaction, chat included | How regularly they use it. It can be higher than *Days with agent sessions* in the scorecard, which counts only days with agent activity. |
| **Genie Code DBUs** *(trend)* | Their Genie Code DBUs, free tier and chat-only days included | What their use costs |
| **Failed cell rate** | Share of the notebook cells the agent ran for them that failed | High means the agent often writes code that fails for them: see their error causes |
| **Actionable errors** *(trend)* | Their failed agent actions, excluding expected background checks | Total errors to work on; the causes are in the table further down |

| Visual | What it shows | Use it to |
|---|---|---|
| **User scorecard** | One row per user, most DBUs first: usage, errors, DBUs, a **Suggested action** and **Also consider** | Decide who to coach and on what. The suggested action is the first rule that applies, quoting the user's own numbers against the overall rate; *Also consider* lists the other rules that apply. Rules and examples are in [section 7](#ds_actions-and-ds_user_actions-action-items-and-user-scorecard). It follows the filters and the picker but not clicks. |
| **Category mix** | Donut: the selected users' sessions by primary category | See what they mainly use the agent for. Click a slice to filter the page. |
| **Workspaces and surfaces used** | Sessions per workspace and surface | See where they work |
| **Sessions by user and primary category** | Pivot: users × primary categories, colour-scaled session counts | Compare the selected users' mix side by side |
| **Category breakdown** | Per category: Sessions (primary), Sessions (any), Active min, Agent actions, Errors, Error rate | Dig into one kind of work. Clicking a row filters only this table. |
| **Errors and how to reduce them** | The selected users' error causes, with why each happens and how to reduce it | Turn their errors into specific advice |
| **Session log** | Every session, newest first: start time, workspace, surface, categories, minutes, actions, cells, notebooks created, errors, session ID | Look at individual sessions; the session ID helps when raising a support ticket |

User scorecard columns:
- User, Suggested action, Also consider, Top category, Primary workspace (both within the filtered period)
- Sessions, Action rate, Days with agent sessions (chat-only days don't count)
- First seen (retained data), Last seen. *First seen* is the earliest session still in the data, not necessarily the user's first use.
- Active min, Cells run, Failed cell rate, Notebooks created
- Actionable errors, Top error cause, DBUs, DBUs / session

Session log columns:
- Started (UTC), User, Workspace, Surface
- Primary category, All categories
- Active min, Duration min, Agent actions, Cells run, Notebooks created, Cells failed, Actionable errors
- Session ID

### Errors & Fixes: why actions fail

Errors here are failed agent actions: HTTP 4xx/5xx responses and failed notebook cells. The agent's routine background checks (files, credentials and built-in connectors that usually don't exist) are left out of every number, because "not found" is their normal answer.

| KPI | What it measures | How to read it |
|---|---|---|
| **Failed cell rate** | Share of agent-run notebook cells that failed | The clearest quality signal. It should fall as prompts and instructions improve. The audit log doesn't record why a cell failed. |
| **Sessions with an error** | Share of sessions with at least one actionable error | How often users run into a failure |
| **Actionable errors** *(trend)* | Count of failed agent actions, background checks excluded | Overall error volume |

| Visual | What it shows | Use it to |
|---|---|---|
| **Error causes and how to reduce them** | One row per cause: group, errors, sessions, users, why it happens, how to reduce it | Find the biggest causes and their fixes. Click a row to filter the page to that cause. |
| **Monthly errors by cause group** | Stacked bars of errors per month by group: Failed cells, Names not found, Access & auth, External tools, Compute & conflicts, Other | See which kind of problem is growing or shrinking |
| **Failed cell rate by month** | Line of the failed cell rate | Check whether changes, such as new workspace instructions, reduce failures |
| **Where errors happen** | Category × activity × cause, with errors, sessions and users | See which agent activity each cause comes from |
| **Errors by user and cause group** | Pivot: users × cause groups | Find who to help first, and with what |

How specific the causes are: *Table / schema / catalog not found*, the dashboard causes, *Write conflict*, *Notebook compute busy*, *External connection auth failed* and *Wrong compute for cell language* come straight from the error message and are specific. *Python / code cell failed* and *SQL cell failed* are certain to be failed cells, but the reason isn't recorded, so their advice lists the common reasons. Rules for every cause are in [section 5](#error-causes).

### Action Items & DBUs: what to do next

DBUs are Genie Code usage from `system.billing.usage`, free tier included. The dashboard shows DBUs, not dollars.

| KPI | What it measures | How to read it |
|---|---|---|
| **Genie Code DBUs** *(trend)* | All Genie Code DBUs in the period, free tier included | Total consumption |
| **DBUs per user** | DBUs divided by users with any DBUs | Typical cost per user; compare periods to see whether it's rising |
| **Billable share of DBUs** | Share of DBUs outside the free tier | How much of the use is paid for |

| Visual | What it shows | Use it to |
|---|---|---|
| **Action items** | One row per finding for the filtered period: Priority, Area, Topic, What the data shows, Why, What to do | Decide what to work on first. Sorted by priority. High means 5%+ of sessions are affected (or 30%+ of DBUs), Medium 1%+ (or 10%+). Rows appear only when their condition holds, and the numbers follow the filters except *Surface*. The rules are in [section 7](#ds_actions-and-ds_user_actions-action-items-and-user-scorecard). |
| **Monthly Genie Code DBUs by category** | Stacked bars of DBUs per month by category, including *Chat only (no agent actions)* | See where the DBUs go and how that changes. The split by category is an estimate. |
| **DBUs by user and category** | Pivot: users × categories, colour-scaled DBUs; column totals give DBUs by category | Find the heaviest users and what their DBUs are spent on |

Per-user suggested actions are in the **User scorecard** on User Detail.

### Category colours

The colours are the same on every page:

| Category | Colour |
|---|---|
| Code Development | Blue `#0072B2` |
| Data Discovery & Governance | Orange `#E69F00` |
| Data Analysis (SQL) | Green `#009E73` |
| Dashboards & BI | Pink `#CC79A7` |
| Data Engineering & Jobs | Vermilion `#D55E00` |
| ML & AI | Sky blue `#56B4E9` |
| External Tools (MCP) | Purple `#7B5EA7` |
| Q&A / Read-only | Grey `#A0A7AE` |
| Chat only (no agent actions), DBU visuals only | Dark grey `#5F6B75` |

---

## 4. Data lineage

```
system.access.assistant_events ──► gc_daily_users ──────────────────────┐
                                                                        ├─► ds_users ─────────► user-count visuals
system.access.audit ──► gc_agent_activity ──► gc_sessions ──────────────┤
  (agent events only)          │                   │                    ├─► ds_main ──────────► almost every other visual
                               └──────────► gc_session_activity ────────┘
system.access.workspaces_latest ──► workspace names (joined in 01, 03 and 06)
gc_agent_activity + gc_sessions ──► gc_session_errors ──────────────────► ds_errors ────────► error visuals
system.billing.usage + gc_sessions ──► gc_cost ─────── ───────────► ds_cost ──────────► cost visuals
gc_sessions + gc_session_errors + gc_cost ──────────────────────────────► ds_actions, ds_user_actions ──► action items, user scorecard
```

### Source system tables

| Table | What a row is | Used for |
|---|---|---|
| `system.access.assistant_events` | One Genie Code interaction submitted by a user | Active users, active workspaces, monthly active users, days with Genie Code use |
| `system.access.audit` | One API call made in the account | Agent actions, and from them sessions and categories |
| `system.access.workspaces_latest` | One workspace | Turning workspace IDs into names |
| `system.billing.usage` | DBUs used by one product in one hour | Genie Code DBUs (`billing_origin_product = 'GENIE'`, `usage_metadata.genie.surface = 'GENIE_CODE'`), per user from `identity_metadata.run_as` |

### How agent actions are identified

When the Genie Code agent acts for a user (edits a notebook, runs a cell, looks up a table), the API call is logged in `system.access.audit` under that **user's identity**, with a distinctive user agent:

```
databricks-background-genie Chrome/... group/<surface> sid/<session-id>
```

- `databricks-background-genie` marks the call as coming from the agent. It's the filter for the whole audit pipeline.
- `group/<surface>` says where Genie Code was invoked (side panel, embedded, and so on).
- `sid/<session-id>` ties every call in one agent session together.

### Materialized views

All six live in the target catalog and schema, cover all the history the system tables keep, and refresh on a daily schedule (UTC).

| View | Source | Grain | Refresh (UTC) |
|---|---|---|---|
| `gc_daily_users` (`sql/01`) | `assistant_events` | day × workspace × user × client type | 02:00 |
| `gc_agent_activity` (`sql/02`) | `audit` | minute × workspace × user × session × service × action | 02:00 |
| `gc_sessions` (`sql/03`) | `gc_agent_activity` | one row per agent session | 04:00 |
| `gc_session_activity` (`sql/04`) | `gc_agent_activity` + `gc_sessions` | session × category × activity (category actions only) | 06:00 |
| `gc_session_errors` (`sql/05`) | `gc_agent_activity` + `gc_sessions` | session × category × activity × error cause (failed events only) | 06:00 |
| `gc_cost` (`sql/06`) | `billing.usage` + `gc_sessions` | day × workspace × user × session (DBUs allocated to sessions) | 06:00 |

The refresh times are staggered so each view refreshes after the views it reads. Data on the dashboard therefore runs **up to the previous day**.

### How far back the data goes

The views cover as much as the system tables retain. Events that age out of a system table drop out of the views at the next refresh. `gc_agent_activity` also has a fixed lower bound of `event_date >= '2026-07-01'`. Genie Code agent events don't exist before then, so the bound loses nothing. It lets the daily refresh skip older audit partitions instead of scanning the whole account-wide audit table. The sources have different spans:

| Data | Typical span in the views |
|---|---|
| `assistant_events` | About 1 year (the table's retention) |
| `billing.usage` | As long as billing retains |
| Genie Code agent events in `audit` | From when the agent's user agent first appears in the account |

**Common window.** The dashboard lines these up. Every dataset starts on the first agent session date, `min(session_date)` in `gc_sessions`. That cut-off is applied to `ds_users`, `ds_cost` and the DBU part of `ds_actions` / `ds_user_actions`; the session-based datasets start there anyway. So user counts, DBUs and sessions all cover the same period, and earlier user and billing history stays in the views but isn't shown.

---

## 5. From audit events to categories

`gc_agent_activity` (`sql/02_gc_agent_activity_mv.sql`) keeps audit rows whose `user_agent` starts with `databricks-background-genie`. It drops `submitCommand` events, so each cell run is counted once, through `runCommand`. It also reads only `event_date >= '2026-07-01'`, which keeps the scan off audit partitions from before the agent existed.

### Extracted fields

| Field | Derived from |
|---|---|
| `agent_context` | `group/([a-z-]+)` in the user agent |
| `session_id` | `sid/([0-9a-f]+)` in the user agent |
| `command_language` | `request_params.commandLanguage` (for example `sql`, `python`) |
| `asset_type` | `request_params.assetType` (notebook vs. file) |
| `rpc_method`, `mcp_server` | `request_params.json_rpc_method` and `fully_qualified_name` for MCP calls |
| `status_code`, `error_message` | `response.status_code` and `response.error_message`. A status of 400 or above, or a gRPC-style code from 1 to 199, is an error. That covers HTTP 4xx/5xx and failed notebook cells (the audit log records a failed `runCommand` with status `1`, not 400+) and failed git calls (4, 12, 13). Status 0, 2xx and 3xx are not errors. |

### Category rules

Each event gets a **category** from its `service_name` and `action_name`. The rules are checked **in order, and the first match wins**. That's why a SQL cell run lands in *Data Analysis (SQL)* and not *Code Development*.

| Category | Rule (audit `service_name` / `action_name`) |
|---|---|
| **Data Analysis (SQL)** | `notebook.runCommand` where `commandLanguage = 'sql'`; any `databrickssql` action |
| **Code Development** | Any other `notebook.runCommand` (Python, Scala, R); `notebook` create, edit, import, rename, `createFolder`, `modifyDesignerFile`; `workspaceFiles.wsfsStreamingWrite`; `workspace.fileCreate` and `createWorkspaceNode`; `repos` and `gitCredentials` (except `listGitCredentials`); any `apps` action |
| **Dashboards & BI** | Any `dashboards`, `aibiGenie` (Genie spaces), `pages` or `discover` action |
| **Data Engineering & Jobs** | Any `deltaPipelines`, `jobs`, `databaseInstances` or `postgres` action; `unityCatalog.createPipeline` and `getPipeline` |
| **ML & AI** | `unityCatalog.getRegisteredModel`, `listModelVersions`, `getModelVersion`; any `featureStore`, `agentFramework`, `mlflowExperiment`, `mlflowTrace`, `serverlessRealTimeInference`, `vectorSearch` or `agentEvaluation` action |
| **Data Discovery & Governance** | Unity Catalog lookups (tables, schemas, catalogs, volumes, functions, shares, table summaries); permission reads and updates; tag lookups; any `lineageTracking`, `request-for-access` or `filesystem` action; `tagging.listTagAssignments` |
| **External Tools (MCP)** | `mcpService` calls with `json_rpc_method = 'tools/call'` |
| *Context / Background* | Everything else: credential checks, listing connections, reading context, and any action type with no rule yet |

Events matching one of the first seven rows are **category actions** (`is_signal = true` in the SQL). *Context / Background* events are kept, because they count toward session length and total actions, but they **never count toward a category** and never appear as a category on the dashboard.

### Activities

Each event also gets a readable **activity** label, shown in the activity tables:

| Activity | Meaning |
|---|---|
| `Run sql cell`, `Run python cell`, ... | `runCommand`, labelled by language |
| `Edit notebook` / `Edit workspace file` | `modifyNotebook` on a notebook or a file |
| `Create notebook` | `createNotebook` or `importNotebook` |
| `Write workspace file` | Streaming writes and file or node creation |
| `MCP: <server>` | MCP tool call, with the `system.ai.` prefix removed |
| `Build / publish dashboard` | Create, update or publish a dashboard |
| `Read / query dashboard` | Any other dashboard action |
| `Genie space` | Any `aibiGenie` action |
| `Lineage & popularity lookup` | Any `lineageTracking` action |
| `UC: <action>` | Any other Unity Catalog action, for example `UC: getTable` |
| `<service>: <action>` | Anything not covered above |
| `Read context only` | Added on the dashboard for read-only sessions, which have no category actions (see [section 7](#7-dashboard-datasets)) |

### Error causes

Each failed event also gets an **error cause**, again first match wins. The dashboard attaches the *why it happens* and *how to reduce it* text in `build_dashboard.py` (`ERROR_FIXES`), so the advice can change without rebuilding the views.

| Error cause | Rule | Cause group |
|---|---|---|
| *Expected background probe* | `wsfsStreamingRead` 404; `getUserMappedCredential` 404, or any error for a built-in connector credential (`system_ai_agent_slack_mcp`, `..._github_mcp`, `..._gmail` and so on, which the agent checks in every session); a `ucHttpConnectionProxiedRequest` 404 to a built-in connector connection such as `system_ai_agent_glean_mcp` (checked at the start of many sessions); `getConnection` for a `system.ai.*` connection, the `databricks-package-management` secret scope, `getEntityTagAssignment` 404. The agent checks for things that usually don't exist; "not found" is the normal answer. | Not actionable; excluded everywhere |
| Wrong compute for cell language | `runCommand` failing with "SQL warehouses only support executing SQL cells" | Compute & conflicts |
| Cell cancelled or skipped | `runCommand` with `CommandCancelledException` / `CommandSkippedException` | Failed cells |
| SQL cell failed / Python / code cell failed | Any other failed `runCommand`, split by `commandLanguage` | Failed cells |
| Rate limited | Status 429 or `REQUEST_LIMIT_EXCEEDED` | External tools |
| Table / schema / catalog not found | `TABLE_`, `SCHEMA_`, `CATALOG_`, `VOLUME_` or `FUNCTION_DOES_NOT_EXIST`; `TABLE_OR_VIEW_NOT_FOUND`; `SCHEMA_`, `CATALOG_`, `VOLUME_` or `ROUTINE_NOT_FOUND` | Names not found |
| External connection auth failed | User-mapped / foreign credential calls, or a UC HTTP connection returning 401/403 | Access & auth |
| Permission denied | Status 403 or `PERMISSION_DENIED` | Access & auth |
| External tool / MCP call failed | Other `ucHttpConnection` / `mcpService` errors, `getMcpService`, `listMcpServices` | External tools |
| Notebook compute busy | `attachNotebook` errors (already attached or attaching) | Compute & conflicts |
| Agent internal error | `mintOAuthToken` failing with "Browser Fleet sessions cannot be exchanged for OAuth tokens" (the agent's browser tool; nothing the user can fix) | Other |
| Dashboard query not supported | `dashboards` / `pages` error "Dataset query is not supported" | Other |
| Dashboard warehouse not found | `dashboards` / `pages` error "warehouse … was not found" | Other |
| Dashboard or widget not found | `dashboards` / `pages` error "Unable to find published dashboard / widget / resource", "does not exist" or "no longer available" | Other |
| Dashboard edit conflict | `dashboards` / `pages` error mentioning an etag mismatch, widget position diffs, "already exists" or "must be unique" | Compute & conflicts |
| Dashboard definition rejected | Any other `dashboards` or `pages` error, for example a measure that doesn't match a dataset column | Other |
| Write conflict | Status 409 or "already exists" | Compute & conflicts |
| Invalid settings or missing resource | Status 500 and above with `INVALID_PARAMETER_VALUE`, `INVALID_STATE`, `RESOURCE_DOES_NOT_EXIST`, `NOT_FOUND`, `BAD_REQUEST`, `MAX_CHILD_NODE_SIZE_EXCEEDED` (folder full) or a `GIT_` error. Retrying won't help. | Other |
| Platform / service error | Any other status 500 and above, mostly timeouts | Other |
| Other request error | Anything else | Other |

Expected probes are usually the large majority of raw error events, which is why they're excluded from every rate.

### Output grain

Events are grouped to the **minute** (`event_minute`) per workspace, user, session, service, action and error cause:
- `action_count`: number of events in that minute
- `error_count`: failed events (status 400+ or 1–199), including expected probes

Grouping by minute keeps the view compact. It's also the unit used for *active minutes* below.

---

## 6. From events to sessions

`gc_sessions` (`sql/03_gc_sessions_mv.sql`) builds one row per `session_id`. Events without a `sid` are excluded.

### Session attributes

| Field | How it's derived |
|---|---|
| **Owner** (`user_email`) | The **email** identity with the most actions in the session. A session can include internal service principals, so emails are preferred. If no email identity exists, it falls back to the identity with the most actions. |
| **Workspace** | The **non-zero** workspace with the most actions. Some agent calls are account-level and logged with `workspace_id = 0`. Sessions with only account-level calls show as `Account-level`. |
| **Surface** | The `group/` value with the most actions, mapped as: `assistant` → *Genie Code panel*, `embed` → *Embedded*, `document` → *Document*, `viz` → *Visualization*. Other values pass through as-is, and a missing value shows as *Unknown*. |
| `session_date` | Date of the session's first event (UTC) |
| `session_start` / `session_end` | First and last event minute |
| `duration_minutes` | `session_end − session_start` in minutes, **+1**. A session within a single minute has a duration of 1. |
| `active_minutes` | Distinct minutes with **any** agent event, including background events |
| `total_actions` | All agent events, including background events |
| `signal_actions` | Category actions only |
| `error_count` | All failed events, including expected background probes |
| `actionable_errors` | Failed events except expected background probes |
| `cells_run` | `runCommand` events (any language) |
| `cells_failed` | Failed `runCommand` events |
| `notebooks_created` | Events with the activity *Create notebook* |

### Primary category

For each session, every category with category actions gets its **active minutes** (distinct minutes with that category's actions). The **primary category** is the one with the most active minutes. Ties go to the category with more actions.

The rule uses minutes instead of raw action counts because notebook edits stream hundreds of events per minute. Counting actions would make nearly every session look like Code Development.

- A session with **no** category actions gets the primary category **Q&A / Read-only**. The agent only read context and answered in the chat; it didn't change or run anything.
- `categories_used` is the number of distinct categories the session touched, and `categories` lists them.

### User type

| Value | Rule |
|---|---|
| **Automated / eval** | The owner isn't an email address (a service principal), **or** the owner has more than 50 sessions on that day |
| **Human** | Everything else |

The 50-a-day threshold separates scripted or evaluation traffic from real use. **The dashboard defaults to Human.**

### `gc_session_activity`

`gc_session_activity` (`sql/04`) joins category actions back to their session and groups them by session × category × activity:
- `active_minutes`: distinct minutes for that activity. Minutes overlap across activities, so don't add them up per category.
- `category_minutes`: distinct minutes with any action in the category, set only on each session × category's first activity row (zero on the others), so `SUM()` gives correct per-category minutes
- `actions`
- `errors`: actionable errors only (expected background probes excluded)

Each row also carries the session's workspace, owner, user type, surface and primary category.

### `gc_session_errors`

`gc_session_errors` (`sql/05`) keeps failed events only, grouped by session × category × activity × error cause, with the same session attributes. `is_actionable` is false for expected background probes. Unlike `gc_session_activity` it includes background events, because many real failures (external tools, credentials) happen outside category actions.

### `gc_cost`

`gc_cost` (`sql/06`) reads Genie Code DBUs from `system.billing.usage`. `is_free` marks the `GENIE_FREE_USAGE` SKU; free-tier DBUs are counted like any other. The dashboard shows DBUs only, not dollars.

Billing has no session ID, so DBUs are **allocated**. Each billing row (workspace × user × day) is split across that user's agent sessions in the **same workspace** that day, in proportion to their active minutes, and each piece takes the session's primary category. If the user had no session in that workspace that day, the row is split across their sessions in any workspace that day instead; it keeps the billing workspace, so the session's own workspace can differ. User-days with DBUs but no agent session keep one row with category **Chat only (no agent actions)**. That's often most of the DBUs, because most Genie Code turns answer in chat without calling a tool. Totals add up exactly; only the split by session and category is an estimate.

---

## 7. Dashboard datasets

The dashboard runs seven queries (datasets) on top of the views.

### `ds_users`: "Genie Code daily users"

These are the rows of `gc_daily_users`, plus a `user_type` column:
- **Automated / eval** if the user is null or not an email address, or if `gc_sessions` flagged that user on that day as automated / eval
- **Human** otherwise

The session-based flag only exists where there's agent data (from when agent events start). Earlier user-days can only be flagged by the non-email rule, so a high-volume eval account counts as Human there. An events-per-day threshold doesn't work as a substitute, because heavy agent-mode users also log thousands of events a day. In practice few user-days have that many events, so the effect is small.

This way the *User type* filter applies to the user counts too. Rows before the first agent session date are left out ([common window](#how-far-back-the-data-goes)), so user counts cover the same period as sessions.

**Client type** comes from the `assistant_events` user agent:

| Client type | User agent |
|---|---|
| Interactive (browser) | Starts with `Mozilla` |
| Background agent | Starts with `databricks-background-genie` |
| Genie Code service | Equals `node` |
| Other client | Anything else |

### `ds_main`: "Genie Code sessions and activities"

This is the main dataset. It has **one row per session × category × activity**. A read-only session gets **one row**, with `category = 'Q&A / Read-only'` and `activity = 'Read context only'`.

Because a session can span several rows, session-level numbers are stored **only on each session's first row** and are zero on the others: `session_active_minutes`, `session_duration_minutes`, `session_total_actions`, `session_cells_run`, `session_notebooks_created`, `session_errors`. A `SUM()` over any of these therefore counts each session exactly once. Session counts use `COUNT(DISTINCT session_id)`.

**Caveat:** a filter on `category`, such as clicking a row in a category table, can hide a session's first row. That row belongs to the session's alphabetically first category. While such a filter is active, `SUM(session_*)` undercounts. For this reason:
- these sums only appear on pages with no visuals that group `ds_main` by `category`: Errors & Fixes and User Detail. User Detail's *Category breakdown* reads `ds_user_categories` for this reason.
- *Action rate* uses distinct sessions instead, so it stays correct under any filter

Other derived columns:

| Column | Definition |
|---|---|
| `category`, `activity`, `actions`, `errors` | From `gc_session_activity`. **Category actions only**, so they exclude background events; `errors` also excludes expected probes. |
| `categories_list` | The session's categories, comma-separated |
| `day_of_week`, `hour_of_day` | From `session_start`, in UTC |
| `session_length` | Active minutes in buckets: `1 min`, `2-5 min`, `6-15 min`, `16-60 min`, `60+ min` |
| `categories_bucket` | `0 (read-only)`, `1 category`, `2 categories`, `3+ categories` |

Dataset-level measures, which are recalculated for whatever a visual groups by:

| Measure | Formula | Meaning |
|---|---|---|
| **Action rate** | `COUNT(DISTINCT session_id where primary_category ≠ Q&A / Read-only) / COUNT(DISTINCT session_id)` | Share of sessions where the agent changed or ran something, i.e. not Q&A / Read-only |
| **Primary sessions** | `COUNT(DISTINCT session_id)` where `category = primary_category` | Sessions whose primary category is the row's category |
| **Error rate** | `SUM(errors) / SUM(actions)` | Share of **category actions** that returned an error (including failed cells) |
| **Failed cell rate** | `SUM(session_cells_failed) / SUM(session_cells_run)` | Share of agent-run notebook cells that failed |
| **Sessions with errors** | `COUNT(DISTINCT session_id where the session has an actionable error) / COUNT(DISTINCT session_id)` | Share of sessions with at least one actionable error |

`session_errors` holds the session's **actionable** errors. Per-category minutes aren't in `ds_main`; User Detail's category breakdown gets them from `ds_user_categories`.

### `ds_user_categories`: "Genie Code activity by category"

The rows of `gc_session_activity` plus one *Read context only* row per read-only session, with `category_minutes` (the read-only row carries the session's active minutes). It backs only User Detail's *Category breakdown*, so clicking a category there filters that table alone instead of hiding rows other User Detail visuals sum over. It has the same *Primary sessions* and *Error rate* measures as `ds_main`.

### `ds_errors`: "Genie Code agent errors"

The actionable rows of `gc_session_errors` (expected probes removed), plus `cause_group`, `likely_cause` and `how_to_reduce` from `ERROR_FIXES`.

### `ds_cost`: "Genie Code DBUs"

The rows of `gc_cost` from the first agent session date onwards ([common window](#how-far-back-the-data-goes)), with `billing_tier` (*Free tier* / *Billable*). Measures: **DBUs per user** (`SUM(dbus) / COUNT(DISTINCT user_email)`) and **Billable share** (share of DBUs outside the free tier).

### `ds_actions` and `ds_user_actions`: action items and user scorecard

Both aggregate across `gc_sessions`, `gc_session_errors` and `gc_cost` inside SQL, so they take the date, workspace, user, user type and primary category filters as **parameters** and don't cross-filter. Category matches `primary_category` for sessions and errors and `cost_category` for DBUs. Rows with no user are left out of the per-user numbers (the scorecard and the top-10% share). The thresholds (`LONG_SESSION_MINUTES = 60`, `RETRY_FAILED_CELLS = 3`) are defined once in `build_dashboard.py`.

`ds_actions` returns one row per finding that applies to the filtered period:

| Area | Topic | Fires when | Priority |
|---|---|---|---|
| Reduce errors | The top 3 actionable error causes by sessions, one row each | Any errors of that cause | High if 5%+ of sessions hit it, Medium if 1%+, else Low |
| Reduce errors | Other error causes: the remaining causes in one row, pointing to Errors & Fixes | More than 3 causes | Same thresholds, on the sessions hit by any of them |
| Cut DBUs | Retry loops | Sessions with 3+ failed cells | High if 5%+ of sessions, Medium if 1%+ |
| Cut DBUs | Long sessions | Sessions with more than 60 active minutes | High if they carry 30%+ of allocated DBUs, Medium if 10%+ |
| Cut DBUs | Usage concentration | 10+ users with DBUs | Medium if the top 10% of users use 50%+ of DBUs |
| Use it effectively | Read-only Q&A sessions | Any read-only sessions | Medium if 50%+ of sessions |
| Cut DBUs | Chat-only DBUs | Any chat-only DBUs | High if they're 30%+ of DBUs, Medium if 10%+ |
| Track | DBUs per productive session | Any DBUs allocated to sessions that took action (those DBUs ÷ those sessions) | Low |

`ds_user_actions` (the **User scorecard**) returns one row per user, including users with DBUs but no agent sessions, with primary workspace, top category, active days, first and last seen, notebooks created, workspaces, sessions, action rate, failed cell rate, retry and 60+ minute sessions, actionable errors and top cause, DBUs and DBUs per session.

**Suggested action** is the first rule below that applies. **Also consider** lists the labels of the other rules that apply, so a second problem isn't hidden. Each message quotes the user's own numbers and, for rates, the rate across all filtered sessions, for example *"Retry loops: 12 of 80 sessions had 3+ failed cells (15% vs 3% overall). When a step fails twice, give the agent the error and a smaller step."*

| Order | Rule | Applies when |
|---|---|---|
| 1 | Top-10% DBUs, all chat | No agent sessions, in the top 10% of users by DBUs |
| 2 | Regular chat user | No agent sessions, DBUs on 5+ days |
| 3 | Retry loops | 3+ sessions with 3+ failed cells |
| 4 | Many failed cells | 10+ cells run, 25%+ failed |
| 5 | Agent guesses names | Top cause *not found*, 5+ actionable errors |
| 6 | Permission errors | Top cause *permission denied*, 5+ actionable errors |
| 7 | External tool errors | Top cause an external tool or connection, 5+ actionable errors |
| 8 | Top-10% DBUs, mostly chat | Has sessions, top 10% by DBUs, 80%+ of DBUs chat-only |
| 9 | Long sessions | 5+ sessions, 30%+ over 60 active minutes |
| 10 | Mostly Q&A | 5+ sessions, under 30% took action |

When none of these apply, in order:
- *Effective user*: 5+ sessions, 60%+ took action, under 10% of cells failed. It's never shown alongside a problem.
- *Occasional chat*: no agent sessions, DBUs on fewer than 5 days
- *Too little activity to assess*: 1–4 sessions
- *No action needed*: everything else, with the user's session count, action rate and failed cell rate

The rules, cutoffs and message text are defined once in `SUGGESTION_RULES` in `build_dashboard.py`.

The top-10% DBU rank is computed within the filtered users, so it means little when the *User* filter narrows to a few people.

---

## 8. Metric definitions

| Metric (where shown) | Definition | Dataset |
|---|---|---|
| **Active Genie Code users** | Distinct users with any Genie Code event, from any client | `ds_users` |
| **Active workspaces** | Distinct workspaces with any Genie Code event | `ds_users` |
| **Monthly active users** | Distinct users per calendar month, split by client type | `ds_users` |
| **Days with Genie Code use** (User Detail KPI) | Distinct days with any Genie Code event, chat included | `ds_users` |
| **Days with agent sessions** (User scorecard) | Distinct days with at least one agent session | `ds_user_actions` |
| **Agent sessions** | Distinct `session_id`s | `ds_main` |
| **Sessions that took action** (Action rate) | Share of sessions that aren't Q&A / Read-only | `ds_main` |
| **Sessions (primary)** | Sessions whose main activity was this category. Each session counts once, so the column adds up to *Agent sessions*. | `ds_main` |
| **Sessions (any)** | Sessions that touched this category at all. A session can count under several categories, so this column adds up to **more** than *Agent sessions*. | `ds_main` |
| **Users** (activity and category tables) | Distinct session owners in that group | `ds_main` |
| **Agent actions** (activity and category tables) | Number of category actions. Background events are excluded. | `ds_main` |
| **Errors / Error rate** (activity and category tables) | Failed category actions (HTTP 4xx/5xx and failed cells), and that count as a share of actions | `ds_main` |
| **Failed cell rate** | Failed agent-run cells / agent-run cells | `ds_main` |
| **Sessions with an error** | Share of sessions with at least one actionable error | `ds_main` |
| **Actionable errors** | Failed events excluding expected background probes | `ds_errors` |
| **Genie Code DBUs** | All Genie Code DBUs, including free tier | `ds_cost` |
| **DBUs per user** | Genie Code DBUs ÷ users with any DBUs | `ds_cost` |
| **Active agent minutes** / **Active min** | Sum of session active minutes, i.e. distinct minutes with any agent event | `ds_main` |
| **Duration min** | Last event minute − first event minute + 1 | `ds_main` |
| **Agent actions** (session log) | All agent events in the session, including background events | `ds_main` |
| **Actionable errors** (session log) | All actionable errors in the session, including on background events | `ds_main` |
| **Cells failed** (session log) | Failed `runCommand` events | `ds_main` |
| **Cells run** | `runCommand` events, any language | `ds_main` |
| **Notebooks created** | Create or import notebook events | `ds_main` |

"Agent actions" and "Errors" are counted differently in the session log than in the activity and category tables. The session log is a full record of everything the agent did, while the tables describe category work. As a result, the session log totals are higher.

---

## 9. Filters and cross-filtering

### Which filters reach which datasets

| Filter (Filters page) | `ds_users` (user counts) | `ds_main` (sessions), `ds_user_categories` | `ds_errors` | `ds_cost` | `ds_actions`, `ds_user_actions` |
|---|---|---|---|---|---|
| Date | `event_date` | `session_date` | `session_date` | `usage_date` | parameter |
| Workspace | ✓ | ✓ | ✓ | ✓ (billing workspace) | parameter |
| User | ✓ | ✓ | ✓ | ✓ | parameter |
| User type (default **Human**) | ✓ | ✓ | ✓ | ✓ | parameter |
| Surface | — | ✓ | ✓ | — | — |
| Primary category | — | ✓ | ✓ | `cost_category` | parameter |
| Client type (users) | ✓ | — | — | — | — |
| **User(s)** picker (User Detail page only) | ✓ | ✓ | ✓ | ✓ | `ds_user_actions` (field) |

`ds_users` comes from `assistant_events`, which has no surface or category. So the **Surface** and **Primary category** filters don't change the user-count visuals. Likewise, **Client type** only affects the user counts.

### Cross-filtering

Click a bar, heatmap cell, pivot cell or table row, and the other `ds_main` visuals on the same page filter to that selection. For example, on Overview, click a workspace in the workspace pivot and the monthly sessions chart and category summary narrow to that workspace.
- Line charts and KPI tiles don't start cross-filters, but they do respond to them.
- The user-count visuals, action items and User scorecard use other datasets, so clicks don't filter them, and clicking them doesn't filter anything else. Error and DBU visuals cross-filter only among themselves.

---

## 10. Reconciling numbers

| You might notice | Why |
|---|---|
| *Active users* is higher than the number of users in the session visuals | The two have different sources. *Active users* counts anyone with a Genie Code interaction, including plain chat that never triggers an agent action. Session visuals count only owners of agent sessions. |
| *Sessions (any)* adds up to more than *Agent sessions* | A session counts once for each category it touches. *Sessions (primary)* adds up exactly. |
| Per-category *Active min* adds up to more than the user's *Active agent minutes* | A minute with actions in two categories counts once in each. Within one category, each minute counts once. |
| Session log *Agent actions* is higher than the activity table's | The session log includes background events; the activity table counts category actions only. |
| *Duration* is longer than *active minutes* | Duration includes idle gaps between the first and last event. Active minutes counts only minutes with activity. |
| The first and last months look low | They're partial months. The current month runs only to yesterday. |
| The heatmap peak looks shifted | All times are UTC. |
| The latest day looks low | The views refresh once a day, overnight UTC, so the latest day only holds the events up to the refresh. The latest week and month are partial for the same reason. |
| Raw error counts in the audit log are far higher than *Actionable errors* | Expected background probes are excluded. |
| Error rates rose after the October 2026 update | Failed notebook cells (status `1`) and failed git calls now count as errors; before, only status 400+ did. |
| Errors and *External tool / MCP call failed* dropped sharply after the 13 November 2026 update | The agent's check for built-in connectors such as `system_ai_agent_glean_mcp` (a 404 at the start of many sessions) is now an expected background probe. *Dashboard request rejected* was split into five dashboard causes, and *Invalid settings or missing resource* and *Agent internal error* were added. |
| DBUs by category are mostly *Chat only* | Most DBUs are on user-days with no agent tool calls ([`gc_cost`](#gc_cost)). |
| Totals change when *User type* includes Automated / eval | Service principals and high-volume user-days (more than 50 sessions) are hidden by default. |

---

## 11. Limitations

- **Categories describe the agent's actions, not the user's intent.** There's no prompt text in any system table. This also means the dashboard holds no conversation content.
- **Python can't be split by purpose.** `commandText` is redacted in the audit log, so every Python, Scala or R cell counts as *Code Development*. SQL cells are identified from `commandLanguage`.
- **SQL rarely wins as the primary category.** When the agent writes a SQL cell, the edit is logged as a notebook edit (*Code Development*), and editing usually takes more minutes than running the cell. SQL work is therefore mostly labelled Code Development as primary. Use **Sessions (any)** to gauge SQL usage.
- **New action types need a rule.** Agent actions with no rule fall into *Context / Background*, so a session made only of such actions shows as *Q&A / Read-only*. Add rules in `sql/02_gc_agent_activity_mv.sql`.
- **Session data depends on the `sid/` tag.** Agent events without one are excluded from sessions.
- **History is limited by system table retention.** Data that ages out of a system table drops out of the views. Keeping it longer would require writing to tables that append each day.
- **The oldest edge moves.** Once audit retention passes the fixed July 2026 lower bound, the earliest day drops out each day. A session that straddles that day loses its first events, so its start, duration and primary category can change. Sessions last minutes, so very few are affected.
- **User type is weaker before agent events start.** Earlier user-days can only be flagged as automated if the identity isn't an email (see [section 7](#7-dashboard-datasets)), so older months of the user counts may include some eval traffic.
- **Refresh order is by timing, not guaranteed.** If one view's refresh runs for more than about two hours, the next view reads the previous day's data.
- **DBUs by session and category are an estimate.** Billing is per workspace, user and hour with no session ID, so DBUs are split across the user's sessions by active minutes, matching the workspace where possible.
- **Agent compute isn't in the DBUs.** Cells the agent runs bill to the notebook's compute (serverless or cluster) like any other run, and can't be told apart from the user's own runs in billing.
- **Failed cells have no recorded reason.** The audit log stores failed `runCommand` events as `InnerExecutionException: null`, so *Python / code cell failed* and *SQL cell failed* can't be split by root cause, and their advice lists the common reasons.
- **Some lookups may be misfiled.** Some *not found* errors are lookups of `otel` trace tables that span many tables and users. They couldn't be confirmed as automatic, so they still count.
- **Advice and thresholds are rules of thumb.** The *how to reduce it* text, the action-item thresholds and the suggested-action rules are in `build_dashboard.py` (`ERROR_FIXES`, `ACTIONS_SQL`, `SUGGESTION_RULES`); tune them for your organisation.
- **Privacy.** System tables are account-wide, so the dashboard shows individual user emails from every workspace. It's published without embedded credentials: each viewer needs `SELECT` on the six views, access to the warehouse, and the views read `system.billing`.

---

## 12. Glossary

| Term | Meaning |
|---|---|
| **Genie Code** | Databricks' in-product AI assistant and agent (formerly Databricks Assistant) |
| **Agent action** | One API call the Genie Code agent made for a user, recorded in `system.access.audit` |
| **Category action** | An agent action that matches a category rule |
| **Context / Background** | Agent actions that don't count toward any category (setup calls, context reads, unmatched actions) |
| **Session** | All agent actions sharing one `sid/` value |
| **Owner** | The email identity with the most actions in a session |
| **Primary category** | The category with the most active minutes in a session |
| **Q&A / Read-only** | A session with no category actions: the agent only answered |
| **Active minute** | A calendar minute with at least one agent event |
| **Surface** | Where Genie Code was invoked: Genie Code panel, Embedded, Document or Visualization |
| **Client type** | How the interaction reached Genie Code (browser, background agent, Genie Code service, other) |
| **Action rate** | Share of sessions that aren't Q&A / Read-only |
| **Account-level** | A session whose actions all had `workspace_id = 0` |
| **Automated / eval** | Sessions owned by a non-email identity, or user-days with more than 50 sessions |
| **Actionable error** | A failed agent event that isn't an expected background probe |
| **Expected background probe** | An agent existence check (file, credential, connection) whose "not found" answer is normal |
| **Retry session** | A session with 3 or more failed cells |
| **Chat only** | Genie Code DBUs on a user-day with no agent session |
| **Common window** | The period every dataset covers: from the first agent session date onwards |
| **Suggested action** | The first scorecard rule that applies to a user, with their numbers |
| **Also consider** | The other scorecard rules that apply to the same user |
