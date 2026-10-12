# Genie Code Usage Patterns: technical guide

This guide explains where every number on the dashboard comes from: the source tables, how events become sessions and categories, how each metric is calculated, and what each visual shows. It describes the code in `sql/` and `build_dashboard.py`. If you change either, update this guide.

- [1. What the dashboard measures](#1-what-the-dashboard-measures)
- [2. Data lineage](#2-data-lineage)
- [3. From audit events to categories](#3-from-audit-events-to-categories)
- [4. From events to sessions](#4-from-events-to-sessions)
- [5. Dashboard datasets](#5-dashboard-datasets)
- [6. Metric definitions](#6-metric-definitions)
- [7. Page by page](#7-page-by-page)
- [8. Filters and cross-filtering](#8-filters-and-cross-filtering)
- [9. Reconciling numbers](#9-reconciling-numbers)
- [10. Limitations](#10-limitations)
- [11. Glossary](#11-glossary)

---

## 1. What the dashboard measures

The dashboard answers two questions about **Genie Code** (formerly Databricks Assistant) across every workspace in the account:

1. **Who uses it?** Users, workspaces, and the client they use it from.
2. **What does the agent do for them?** Writing code, exploring the catalog, running SQL, building dashboards, and so on.

It covers Genie Code only. It does **not** include people chatting directly in Genie spaces (Genie Agents), "Ask Genie" in AI/BI dashboards, or Agent Bricks. It does include the times the Genie Code agent worked with a Genie space for a user (see *Dashboards & BI* in [section 3](#3-from-audit-events-to-categories)).

**Categories describe what the agent did, not what the user asked.** No system table stores Genie Code prompts or replies, so the dashboard infers purpose from the API calls the agent made.

---

## 2. Data lineage

```
system.access.assistant_events ──► gc_daily_users ──────────────────────┐
                                                                        ├─► ds_users ─────────► user-count visuals
system.access.audit ──► gc_agent_activity ──► gc_sessions ──────────────┤
  (agent events only)          │                   │                    ├─► ds_main ──────────► almost every other visual
                               └──────────► gc_session_activity ────────┘
system.access.workspaces_latest ──► workspace names (joined in 01 and 03)
                                    gc_daily_users + gc_sessions ───────► ds_top_ws_users ──► "Top 15 workspaces" bar
```

### Source system tables

| Table | What a row is | Used for |
|---|---|---|
| `system.access.assistant_events` | One Genie Code interaction submitted by a user | Active users, active workspaces, monthly active users, active days |
| `system.access.audit` | One API call made in the account | Agent actions, and from them sessions and categories |
| `system.access.workspaces_latest` | One workspace | Turning workspace IDs into names |

### How agent actions are identified

When the Genie Code agent acts for a user (edits a notebook, runs a cell, looks up a table), the API call is logged in `system.access.audit` under that **user's identity**, with a distinctive user agent:

```
databricks-background-genie Chrome/... group/<surface> sid/<session-id>
```

- `databricks-background-genie` marks the call as coming from the agent. It's the filter for the whole audit pipeline.
- `group/<surface>` says where Genie Code was invoked (side panel, embedded, and so on).
- `sid/<session-id>` ties every call in one agent session together.

### Materialized views

All four live in the target catalog and schema, cover all the history the system tables keep, and refresh on a daily schedule (UTC).

| View | Source | Grain | Refresh (UTC) |
|---|---|---|---|
| `gc_daily_users` (`sql/01`) | `assistant_events` | day × workspace × user × client type | 02:00 |
| `gc_agent_activity` (`sql/02`) | `audit` | minute × workspace × user × session × service × action | 02:00 |
| `gc_sessions` (`sql/03`) | `gc_agent_activity` | one row per agent session | 04:00 |
| `gc_session_activity` (`sql/04`) | `gc_agent_activity` + `gc_sessions` | session × category × activity (category actions only) | 06:00 |

The refresh times are staggered so each view refreshes after the views it reads. Data on the dashboard therefore runs **up to the previous day**.

### How far back the data goes

The views cover as much as the system tables retain. Events that age out of a system table drop out of the views at the next refresh. `gc_agent_activity` also has a fixed lower bound of `event_date >= '2026-07-01'`. Genie Code agent events don't exist before then, so the bound loses nothing. It lets the daily refresh skip older audit partitions instead of scanning the whole account-wide audit table. The two sources have different spans:

| Data | Typical span | Affects |
|---|---|---|
| `assistant_events` | About 1 year (the table's retention) | User-count visuals |
| Genie Code agent events in `audit` | From when the agent's user agent first appears in the account (2 July 2026 in the reference account) | Sessions, categories, activities |

So the user-count line usually goes back further than the session charts.

---

## 3. From audit events to categories

`gc_agent_activity` (`sql/02_gc_agent_activity_mv.sql`) keeps audit rows whose `user_agent` starts with `databricks-background-genie`. It drops `submitCommand` events, so each cell run is counted once, through `runCommand`. It also reads only `event_date >= '2026-07-01'`, which keeps the scan off audit partitions from before the agent existed.

### Extracted fields

| Field | Derived from |
|---|---|
| `agent_context` | `group/([a-z-]+)` in the user agent |
| `session_id` | `sid/([0-9a-f]+)` in the user agent |
| `command_language` | `request_params.commandLanguage` (for example `sql`, `python`) |
| `asset_type` | `request_params.assetType` (notebook vs. file) |
| `rpc_method`, `mcp_server` | `request_params.json_rpc_method` and `fully_qualified_name` for MCP calls |
| `status_code` | `response.status_code`. Codes of 400 and above count as errors. |

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
| `Read context only` | Added on the dashboard for read-only sessions, which have no category actions (see [section 5](#5-dashboard-datasets)) |

### Output grain

Events are grouped to the **minute** (`event_minute`) per workspace, user, session, service and action:
- `action_count`: number of events in that minute
- `error_count`: events with status 400 or above

Grouping by minute keeps the view compact. It's also the unit used for *active minutes* below.

---

## 4. From events to sessions

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
| `error_count` | All events with status 400 or above, including background events |
| `cells_run` | `runCommand` events (any language) |
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
- `active_minutes`: distinct minutes for that activity
- `actions`, `errors`

Each row also carries the session's workspace, owner, user type, surface and primary category.

---

## 5. Dashboard datasets

The dashboard runs three queries (datasets) on top of the views.

### `ds_users`: "Genie Code daily users"

These are the rows of `gc_daily_users`, plus a `user_type` column:
- **Automated / eval** if the user is null or not an email address, or if `gc_sessions` flagged that user on that day as automated / eval
- **Human** otherwise

The session-based flag only exists where there's agent data (from July 2026). Earlier user-days can only be flagged by the non-email rule, so a high-volume eval account counts as Human there. An events-per-day threshold doesn't work as a substitute, because heavy agent-mode users also log thousands of events a day. In the reference account the effect is small: only 14 of about 22,800 user-days before July 2026 had more than 1,000 events.

This way the *User type* filter applies to the user counts too.

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
- these sums only appear on pages with no category-row visuals: the User directory and User Detail
- *Action rate* uses distinct sessions instead, so it stays correct under any filter

Other derived columns:

| Column | Definition |
|---|---|
| `category`, `activity`, `actions`, `errors` | From `gc_session_activity`. **Category actions only**, so they exclude background events. |
| `categories_list` | The session's categories, comma-separated |
| `user_top_category` | The user's most frequent primary category across **all history**, ignoring Q&A. Users who only have Q&A sessions show *Q&A / Read-only*. **Filters don't change it.** |
| `user_primary_workspace` | The user's workspace with the most sessions across **all history**, ignoring Account-level. **Filters don't change it.** |
| `day_of_week`, `hour_of_day` | From `session_start`, in UTC |
| `session_length` | Active minutes in buckets: `1 min`, `2-5 min`, `6-15 min`, `16-60 min`, `60+ min` |
| `categories_bucket` | `0 (read-only)`, `1 category`, `2 categories`, `3+ categories` |

Dataset-level measures, which are recalculated for whatever a visual groups by:

| Measure | Formula | Meaning |
|---|---|---|
| **Action rate** | `COUNT(DISTINCT session_id where primary_category ≠ Q&A / Read-only) / COUNT(DISTINCT session_id)` | Share of sessions where the agent changed or ran something, i.e. not Q&A / Read-only |
| **Primary sessions** | `COUNT(DISTINCT session_id)` where `category = primary_category` | Sessions whose primary category is the row's category |
| **Error rate** | `SUM(errors) / SUM(actions)` | Share of **category actions** that returned an error |

### `ds_top_ws_users`: "Top workspaces by users"

This dataset is the distinct users per workspace from `ds_users`, with `LIMIT 15`. A visual can't limit itself to its top N rows, so the ranking happens inside the query. The filters reach it through **query parameters** instead of field filters. As a result it **can't take part in click-to-cross-filter**.

---

## 6. Metric definitions

| Metric (where shown) | Definition | Dataset |
|---|---|---|
| **Active Genie Code users** | Distinct users with any Genie Code event, from any client | `ds_users` |
| **Active workspaces** | Distinct workspaces with any Genie Code event | `ds_users` |
| **Monthly active users** | Distinct users per calendar month, split by client type | `ds_users` |
| **Active days** | Distinct days with any Genie Code event | `ds_users` |
| **Agent sessions** | Distinct `session_id`s | `ds_main` |
| **Sessions that took action** (Action rate) | Share of sessions that aren't Q&A / Read-only | `ds_main` |
| **Sessions (primary)** | Sessions whose main activity was this category. Each session counts once, so the column adds up to *Agent sessions*. | `ds_main` |
| **Sessions (any)** | Sessions that touched this category at all. A session can count under several categories, so this column adds up to **more** than *Agent sessions*. | `ds_main` |
| **Users** (activity and category tables) | Distinct session owners in that group | `ds_main` |
| **Agent actions** (activity and category tables) | Number of category actions. Background events are excluded. | `ds_main` |
| **Errors / Error rate** (activity and category tables) | Category actions with status 400 or above, and that count as a share of actions | `ds_main` |
| **Active agent minutes** / **Active min** | Sum of session active minutes, i.e. distinct minutes with any agent event | `ds_main` |
| **Duration min** | Last event minute − first event minute + 1 | `ds_main` |
| **Agent actions** (session log) | All agent events in the session, including background events | `ds_main` |
| **Errors** (session log) | All errors in the session, including background events | `ds_main` |
| **Cells run** | `runCommand` events, any language | `ds_main` |
| **Notebooks created** | Create or import notebook events | `ds_main` |

"Agent actions" and "Errors" are counted differently in the session log than in the activity and category tables. The session log is a full record of everything the agent did, while the tables describe category work. As a result, the session log totals are higher.

---

## 7. Page by page

### Overview: is it being adopted, and for what?

| Visual | Shows | Dataset |
|---|---|---|
| **Active Genie Code users** (KPI) | Distinct users, all clients | `ds_users` |
| **Active workspaces** (KPI) | Distinct workspaces | `ds_users` |
| **Agent sessions** (KPI) | Distinct sessions | `ds_main` |
| **Sessions that took action** (KPI) | Action rate | `ds_main` |
| **Monthly agent sessions by primary category** | Stacked bar: sessions per month, coloured by primary category. Shows both volume and mix. | `ds_main` |
| **Monthly active users by client** | Line: distinct users per month by client type. Usually goes back further than the session charts ([section 2](#how-far-back-the-data-goes)). | `ds_users` |
| **Category summary** | One row per category: Sessions (primary), Sessions (any), Users, Agent actions, Error rate. Sorted by Sessions (any). | `ds_main` |

**How to read the category summary:**
- *Primary* answers "what are sessions mainly for?"
- *Any* answers "how often does the agent do this at all?"
- A big gap between the two means the category usually supports other work. For example, catalog lookups happen before writing code. See [section 10](#10-limitations) for why SQL shows a particularly large gap.

### Usage Patterns: how and when it's used

| Visual | Shows |
|---|---|
| **When sessions happen (day × hour, UTC)** | Heatmap of sessions by weekday and hour of `session_start` |
| **Multi-category sessions** | Sessions by number of categories touched: 0 (read-only), 1, 2 or 3+. Sessions with 2 or more categories are multi-step workflows, e.g. explore the catalog, then write code, then build a dashboard. |
| **Category mix by surface** | 100% stacked bar: the share of each primary category per surface |
| **Session depth (active minutes)** | Sessions per active-minute bucket, coloured by primary category |
| **Agent activities by category** | Table, one row per category × activity: Sessions, Users, Workspaces, Agent actions, Errors, Error rate |

All of these use `ds_main`.

### Workspaces & Users: who the champions are

| Visual | Shows | Dataset |
|---|---|---|
| **Sessions by workspace and primary category** | Pivot table with workspaces as rows (most sessions first), primary categories as columns, and session counts colour-scaled | `ds_main` |
| **User directory** | One row per user. Top category and Primary workspace cover all history; every other column follows the filters. | `ds_main` |
| **Top 15 workspaces by active users** | Distinct users per workspace, all clients | `ds_top_ws_users` |

User directory columns:
- User, Top category, Primary workspace
- Sessions, Action rate, Active days (days with a session)
- First seen (retained data), Last seen. *First seen* is the earliest session still in the data, not necessarily the user's first use.
- Active min, Cells run, Notebooks created, Workspaces

### User Detail: one person's profile

Pick one or more users with the **User(s)** picker at the top right. With nobody selected, the page shows everyone. To see trends for the same users, use the *User* filter on the Filters page; it applies to every page.

| Visual | Shows | Dataset |
|---|---|---|
| **Agent sessions** (KPI) | Distinct sessions | `ds_main` |
| **Sessions that took action** (KPI) | Action rate | `ds_main` |
| **Active agent minutes** (KPI) | Sum of session active minutes | `ds_main` |
| **Active days** (KPI) | Days with any Genie Code event | `ds_users` |
| **Category mix** | Donut: the picked users' sessions by primary category. Clicking a slice filters the page to that category. | `ds_main` |
| **Workspaces and surfaces used** | Sessions per workspace × surface | `ds_main` |
| **Session log** | Every session, newest first, with the columns below | `ds_main` |

Session log columns:
- Started (UTC), User, Workspace, Surface
- Primary category, All categories
- Active min, Duration min, Agent actions, Cells run, Notebooks created, Errors
- Session ID

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

---

## 8. Filters and cross-filtering

### Which filters reach which datasets

| Filter (Filters page) | `ds_users` (user counts) | `ds_main` (sessions) | `ds_top_ws_users` (Top 15 bar) |
|---|---|---|---|
| Date | `event_date` | `session_date` | parameter |
| Workspace | ✓ | ✓ | parameter |
| User | ✓ | ✓ | parameter |
| User type (default **Human**) | ✓ | ✓ | parameter |
| Surface | — | ✓ | — |
| Primary category | — | ✓ | — |
| Client type (users) | ✓ | — | parameter |
| **User(s)** picker (User Detail page only) | ✓ | ✓ | — |

`ds_users` comes from `assistant_events`, which has no surface or category. So the **Surface** and **Primary category** filters don't change the user-count visuals. Likewise, **Client type** only affects the user counts.

### Cross-filtering

Click a bar, heatmap cell, pivot cell or table row, and the other `ds_main` visuals on the same page filter to that selection. For example, click a workspace in the pivot and the user directory narrows to that workspace.
- Line charts and KPI tiles don't start cross-filters, but they do respond to them.
- The user-count visuals and the Top 15 workspaces bar use other datasets, so clicks don't filter them, and clicking them doesn't filter anything else.

---

## 9. Reconciling numbers

| You might notice | Why |
|---|---|
| *Active users* is higher than the number of users in the session visuals | The two have different sources. *Active users* counts anyone with a Genie Code interaction, including plain chat that never triggers an agent action. Session visuals count only owners of agent sessions. |
| *Sessions (any)* adds up to more than *Agent sessions* | A session counts once for each category it touches. *Sessions (primary)* adds up exactly. |
| Session log *Agent actions* is higher than the activity table's | The session log includes background events; the activity table counts category actions only. |
| *Duration* is longer than *active minutes* | Duration includes idle gaps between the first and last event. Active minutes counts only minutes with activity. |
| Monthly active users goes back further than sessions | `assistant_events` keeps about a year; agent audit events start later ([section 2](#how-far-back-the-data-goes)). |
| The first and last months look low | They're partial months. The current month runs only to yesterday. |
| The heatmap peak looks shifted | All times are UTC. |
| Today is missing | The views refresh once a day, overnight UTC. |
| Totals change when *User type* includes Automated / eval | Service principals and high-volume user-days (more than 50 sessions) are hidden by default. |

---

## 10. Limitations

- **Categories describe the agent's actions, not the user's intent.** There's no prompt text in any system table. This also means the dashboard holds no conversation content.
- **Python can't be split by purpose.** `commandText` is redacted in the audit log, so every Python, Scala or R cell counts as *Code Development*. SQL cells are identified from `commandLanguage`.
- **SQL rarely wins as the primary category.** When the agent writes a SQL cell, the edit is logged as a notebook edit (*Code Development*), and editing usually takes more minutes than running the cell. SQL work is therefore mostly labelled Code Development as primary. Use **Sessions (any)** to gauge SQL usage.
- **New action types need a rule.** Agent actions with no rule fall into *Context / Background*, so a session made only of such actions shows as *Q&A / Read-only*. Add rules in `sql/02_gc_agent_activity_mv.sql`.
- **Session data depends on the `sid/` tag.** Agent events without one are excluded from sessions.
- **History is limited by system table retention.** Data that ages out of a system table drops out of the views. Keeping it longer would require writing to tables that append each day.
- **The oldest edge moves.** Once audit retention passes the fixed July 2026 lower bound, the earliest day drops out each day. A session that straddles that day loses its first events, so its start, duration and primary category can change. Sessions last minutes, so very few are affected.
- **User type is weaker before July 2026.** Earlier user-days can only be flagged as automated if the identity isn't an email (see [section 5](#5-dashboard-datasets)), so older months of the user counts may include some eval traffic.
- **Refresh order is by timing, not guaranteed.** If one view's refresh runs for more than about two hours, the next view reads the previous day's data.
- **Privacy.** System tables are account-wide, so the dashboard shows individual user emails from every workspace. It's published without embedded credentials: each viewer needs `SELECT` on the four views and access to the warehouse.

---

## 11. Glossary

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
