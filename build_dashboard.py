"""Renders the Genie Code usage SQL and AI/BI dashboard JSON for a target catalog/schema.

    python3 build_dashboard.py --catalog <catalog> --schema <schema> [--out build]

Writes <out>/sql/*.sql (from the sql/ templates) and <out>/genie_code_usage_dashboard.json.
Can also be imported (e.g. from deploy_notebook): render_sql() and render_dashboard().
"""
import argparse
import copy
import json
import pathlib
import string

CAT_COLORS = {
    "Code Development": "#0072B2",
    "Data Discovery & Governance": "#E69F00",
    "Data Analysis (SQL)": "#009E73",
    "Dashboards & BI": "#CC79A7",
    "Data Engineering & Jobs": "#D55E00",
    "ML & AI": "#56B4E9",
    "External Tools (MCP)": "#7B5EA7",
    "Q&A / Read-only": "#A0A7AE",
}
CAT_ORDER = list(CAT_COLORS)
CAT_SCALE = {"type": "categorical",
             "mappings": [{"value": k, "color": v} for k, v in CAT_COLORS.items()]}


def ql(sql):
    return [line + "\n" for line in sql.strip().split("\n")]


# user_type for gc_daily_users rows: non-email identities, plus user-days that gc_sessions flags as
# automated / eval, so the "User type" filter applies to the user-count KPIs too.
USERS_TYPED_SQL = """
WITH auto_days AS (SELECT DISTINCT user_email, session_date FROM gc_sessions WHERE user_type = 'Automated / eval'),
users_typed AS (
  SELECT d.event_date, d.workspace_name, d.user_email, d.client_type, d.events,
         CASE WHEN d.user_email IS NULL OR d.user_email NOT LIKE '%@%' OR a.user_email IS NOT NULL
              THEN 'Automated / eval' ELSE 'Human' END AS user_type
  FROM gc_daily_users d
  LEFT JOIN auto_days a ON d.user_email = a.user_email AND d.event_date = a.session_date
)"""

datasets = [
    {"name": "ds_users", "displayName": "Genie Code daily users",
     "queryLines": ql(USERS_TYPED_SQL + """
SELECT event_date, workspace_name, user_email, client_type, events, user_type
FROM users_typed""")},
    {"name": "ds_main", "displayName": "Genie Code sessions and activities",
     # One row per session x category x activity (read-only sessions get one row). session_* columns are
     # non-zero only on each session's first row, so SUM() over them counts every session exactly once.
     # A filter on `category` can hide that first row, so don't put SUM(session_*) on a page whose visuals
     # cross-filter ds_main by category (Overview, Usage Patterns). User Detail's category table uses
     # ds_user_categories for this reason.
     "queryLines": ql("""
WITH r AS (
  SELECT s.*, coalesce(a.category, s.primary_category) AS category,
         coalesce(a.activity, 'Read context only') AS activity,
         coalesce(a.actions, 0) AS actions, coalesce(a.errors, 0) AS errors,
         row_number() OVER (PARTITION BY s.session_id ORDER BY a.category, a.activity) AS rn
  FROM gc_sessions s
  LEFT JOIN gc_session_activity a ON a.session_id = s.session_id
)
SELECT r.session_id, r.session_date, r.session_start, r.workspace_name, r.user_email, r.user_type, r.surface,
       r.primary_category, coalesce(array_join(r.categories, ', '), '') AS categories_list,
       date_format(r.session_start, 'E') AS day_of_week,
       hour(r.session_start) AS hour_of_day,
       CASE WHEN r.active_minutes <= 1 THEN '1 min' WHEN r.active_minutes <= 5 THEN '2-5 min'
            WHEN r.active_minutes <= 15 THEN '6-15 min' WHEN r.active_minutes <= 60 THEN '16-60 min'
            ELSE '60+ min' END AS session_length,
       CASE WHEN r.categories_used = 0 THEN '0 (read-only)' WHEN r.categories_used = 1 THEN '1 category'
            WHEN r.categories_used = 2 THEN '2 categories' ELSE '3+ categories' END AS categories_bucket,
       r.category, r.activity, r.actions, r.errors,
       r.actionable_errors > 0 AS session_has_error,
       CASE WHEN r.rn = 1 THEN r.active_minutes ELSE 0 END AS session_active_minutes,
       CASE WHEN r.rn = 1 THEN round(r.duration_minutes, 1) ELSE 0 END AS session_duration_minutes,
       CASE WHEN r.rn = 1 THEN r.total_actions ELSE 0 END AS session_total_actions,
       CASE WHEN r.rn = 1 THEN r.cells_run ELSE 0 END AS session_cells_run,
       CASE WHEN r.rn = 1 THEN r.notebooks_created ELSE 0 END AS session_notebooks_created,
       CASE WHEN r.rn = 1 THEN r.cells_failed ELSE 0 END AS session_cells_failed,
       CASE WHEN r.rn = 1 THEN r.actionable_errors ELSE 0 END AS session_errors
FROM r"""),
     "columns": [
         # Distinct-session ratio rather than SUM(session_*): a click on a category row filters ds_main by
         # `category`, which can hide a session's first row and so drop it from any SUM(session_*) total.
         {"displayName": "Action rate", "description": "Share of sessions where the agent changed or ran something",
          "expression": "COUNT(DISTINCT CASE WHEN `primary_category` <> 'Q&A / Read-only' THEN `session_id` END) * 1.0"
                        " / NULLIF(COUNT(DISTINCT `session_id`), 0)"},
         {"displayName": "Primary sessions", "description": "Sessions whose primary category is this row's category",
          "expression": "COUNT(DISTINCT CASE WHEN `category` = `primary_category` THEN `session_id` END)"},
         {"displayName": "Error rate", "description": "Agent actions that returned an error",
          "expression": "SUM(`errors`) * 1.0 / NULLIF(SUM(`actions`), 0)"},
         # SUM(session_*) is safe: no page that shows this measure has a visual that cross-filters ds_main by `category`.
         {"displayName": "Failed cell rate", "description": "Share of agent-run notebook cells that failed",
          "expression": "SUM(`session_cells_failed`) * 1.0 / NULLIF(SUM(`session_cells_run`), 0)"},
         {"displayName": "Sessions with errors", "description": "Share of sessions with at least one actionable error",
          "expression": "COUNT(DISTINCT CASE WHEN `session_has_error` THEN `session_id` END) * 1.0"
                        " / NULLIF(COUNT(DISTINCT `session_id`), 0)"}]},
]


def f(name, expr):
    return {"name": name, "expression": expr}


def q(ds, fields, disagg=False, filters=None, orders=None):
    query = {"datasetName": ds, "fields": fields, "disaggregated": disagg}
    if orders:
        query["orders"] = [{"direction": d, "expression": e} for e, d in orders]
    if filters:
        query["filters"] = [{"expression": e} for e in filters]
    return [{"name": "main_query", "query": query}]


def frame(title, desc=None):
    fr = {"showTitle": True, "title": title}
    if desc:
        fr.update({"showDescription": True, "description": desc})
    return fr


def pos(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def text(name, lines, p):
    return {"widget": {"name": name, "multilineTextboxSpec": {"lines": lines}}, "position": p}


COUNT_FMT = {"type": "number", "abbreviation": "compact", "decimalPlaces": {"type": "max", "places": 1}}
WEEK = lambda col: f(f"weekly({col})", f'DATE_TRUNC("WEEK", `{col}`)')
MONTH = lambda col: f(f"monthly({col})", f'DATE_TRUNC("MONTH", `{col}`)')


def counter(name, title, desc, ds, value_field, period_col, display, fmt=None, p=None, filters=None):
    # The headline value re-aggregates the per-period rows, which is only correct for additive
    # measures (SUM). COUNT(DISTINCT) / AVG counters get no period, so they show the true total.
    value = {"fieldName": value_field["name"], "displayName": display}
    if fmt:
        value["format"] = fmt
    fields, enc = [value_field], {"value": value}
    if value_field["name"].startswith("sum("):
        fields.append(WEEK(period_col))
        enc["period"] = {"fieldName": f"weekly({period_col})"}
    return {"widget": {"name": name, "queries": q(ds, fields, filters=filters),
                       "spec": {"version": 2, "widgetType": "counter", "encodings": enc,
                                "frame": frame(title, desc)}},
            "position": p}


# ---------------- Parameterised datasets ----------------
# A widget can't compute findings across several views, so these datasets aggregate
# inside SQL and the filters bind to them through parameters (a field filter would only apply after aggregation).
# They can't take part in click-to-cross-filter, which only works between widgets on the same dataset.
NO_DATE = {"min": {"value": "2000-01-01"}, "max": {"value": "2099-12-31"}}


def multi_param(keyword, display, default=()):
    return {"keyword": keyword, "displayName": display, "dataType": "STRING", "complexType": "MULTI",
            "defaultSelection": {"values": {"dataType": "STRING", "values": [{"value": v} for v in default]}}}


DATE_PARAM = {"keyword": "date_range", "displayName": "Date", "dataType": "DATE", "complexType": "RANGE",
              "defaultSelection": {"range": {"dataType": "DATE", **NO_DATE}}}
P_WS, P_USER = multi_param("p_workspace", "Workspace"), multi_param("p_user", "User")
P_TYPE = multi_param("p_user_type", "User type", ["Human"])
P_CAT = multi_param("p_category", "Primary category")


def in_param(keyword, col):
    return f"(size(:{keyword}) = 0 OR array_contains(:{keyword}, {col}))"


# ---------------- Errors, DBUs and action items ----------------
# error_cause (from sql/02) -> (cause group, likely cause, how to reduce). Text lives here rather than in the
# views so it can change with a dashboard-only deploy.
ERROR_FIXES = {
    "Python / code cell failed": (
        "Failed cells", "Code the agent wrote and ran raised an exception: wrong column names, missing libraries, type errors or wrong assumptions about the data.",
        "Give exact table and column names (@-mention the tables) and the expected output. Ask for one step at a time and run it before the next. When a cell fails, use Diagnose error (/fix) instead of re-prompting from scratch. Check the notebook compute has the libraries the code needs."),
    "SQL cell failed": (
        "Failed cells", "SQL the agent ran failed: unresolved tables or columns, syntax errors or type mismatches.",
        "@-mention the tables so the agent sees their schemas, state the filters and grain you want, and use /fix on the failed cell. Put common join keys and business definitions in Genie Code workspace instructions."),
    "Cell cancelled or skipped": (
        "Failed cells", "A run was stopped by the user, or a cell was skipped after an earlier cell failed.",
        "Usually user-initiated. If frequent, prompts are probably too broad: ask for smaller steps that finish quickly."),
    "Table / schema / catalog not found": (
        "Names not found", "The agent guessed a name that does not exist, often <catalog>.default or a catalog from another workspace.",
        "Reference tables with @, set the default catalog and schema (USE CATALOG / USE SCHEMA) before asking, and list the standard catalogs and schemas in Genie Code workspace instructions."),
    "Permission denied": (
        "Access & auth", "The user lacks a privilege on the data or object the agent tried to read or change.",
        "Grant USE CATALOG / USE SCHEMA / SELECT (or BROWSE for discovery) on the data users work with, or tell users which governed tables they can use."),
    "External connection auth failed": (
        "Access & auth", "Per-user OAuth credentials for an external connection or MCP server are missing or expired.",
        "Have users sign in to the connection again (user-mapped credentials) and confirm the OAuth app's scopes and secret are still valid."),
    "External tool / MCP call failed": (
        "External tools", "A call through a Unity Catalog HTTP connection or MCP server returned an error: missing endpoint, bad request or server down.",
        "Check the connection URL and path in Catalog Explorer, remove MCP servers that are no longer used from Genie Code settings, and test the server outside Genie Code."),
    "Rate limited": (
        "External tools", "Too many requests to a model, MCP server or API in a short time.",
        "Avoid running many agent tasks in parallel and space out bulk requests. Ask an admin to review AI Gateway and endpoint rate limits."),
    "Wrong compute for cell language": (
        "Compute & conflicts", "Python cells were run on a SQL warehouse, which only runs SQL.",
        "Attach Python notebooks to serverless or an all-purpose cluster. Keep SQL warehouses for SQL-only notebooks."),
    "Notebook compute busy": (
        "Compute & conflicts", "The agent tried to attach compute while the notebook was already attaching or attached.",
        "Attach the notebook to running compute before starting a Genie Code task, and avoid switching compute mid-session."),
    "Write conflict": (
        "Compute & conflicts", "The agent tried to create a file or notebook that already exists, or wrote a file that changed underneath it.",
        "Ask the agent to edit the existing file or give a new name, and avoid editing the same file in another tab while the agent works."),
    "Dashboard request rejected": (
        "Other", "A dashboard create, update or query call was rejected, for example an unsupported dataset query or conflicting widget changes.",
        "Ask Genie Code to build dashboards on tables or views with plain SQL datasets, and don't edit the same dashboard in the UI while the agent changes it."),
    "Platform / service error": (
        "Other", "A Databricks service returned a 5xx error.",
        "Usually transient, so retry. If one service keeps failing, raise a support ticket with the time and workspace."),
    "Other request error": (
        "Other", "Other rejected requests, such as bad parameters or unsupported operations.",
        "Check the activity in the session log. If a pattern recurs, add a rule for it in sql/02_gc_agent_activity_mv.sql."),
}
CAUSE_GROUPS = ["Failed cells", "Names not found", "Access & auth", "External tools", "Compute & conflicts", "Other"]
CHAT_ONLY = "Chat only (no agent actions)"
READ_ONLY = "Q&A / Read-only"
LONG_SESSION_MINUTES = 60   # a session with more active minutes than this is a long session
RETRY_FAILED_CELLS = 3      # a session with at least this many failed cells is a retry loop
COST_CAT_SCALE = {"type": "categorical",
                  "mappings": CAT_SCALE["mappings"] + [{"value": CHAT_ONLY, "color": "#5F6B75"}]}


def sql_str(v):
    return "'" + v.replace("'", "''") + "'"


FIXES_CTE = "fixes AS (SELECT * FROM VALUES\n  " + ",\n  ".join(
    f"({sql_str(k)}, {sql_str(g)}, {sql_str(w)}, {sql_str(h)})" for k, (g, w, h) in ERROR_FIXES.items()
) + "\n  AS t(error_cause, cause_group, likely_cause, how_to_reduce))"

datasets += [
    {"name": "ds_errors", "displayName": "Genie Code agent errors",
     # Actionable errors only: the agent's expected background probes are left out.
     "queryLines": ql("WITH " + FIXES_CTE + """
SELECT e.session_date, e.workspace_name, e.user_email, e.session_id, e.user_type, e.surface, e.primary_category,
       e.category, e.activity, e.error_cause, e.errors,
       coalesce(f.cause_group, 'Other') AS cause_group,
       coalesce(f.likely_cause, '') AS likely_cause, coalesce(f.how_to_reduce, '') AS how_to_reduce
FROM gc_session_errors e
LEFT JOIN fixes f USING (error_cause)
WHERE e.is_actionable""")},
    {"name": "ds_cost", "displayName": "Genie Code DBUs",
     "queryLines": ql("""
SELECT usage_date, workspace_name, user_email, user_type, session_id, cost_category,
       CASE WHEN is_free THEN 'Free tier' ELSE 'Billable' END AS billing_tier,
       dbus
FROM gc_cost"""),
     "columns": [
         {"displayName": "DBUs per user", "description": "Genie Code DBUs per user with any DBUs",
          "expression": "SUM(`dbus`) / NULLIF(COUNT(DISTINCT `user_email`), 0)"},
         {"displayName": "Billable share", "description": "Share of Genie Code DBUs outside the free tier",
          "expression": "SUM(CASE WHEN `billing_tier` = 'Billable' THEN `dbus` ELSE 0 END) / NULLIF(SUM(`dbus`), 0)"}]},
]


datasets.append(
    {"name": "ds_user_categories", "displayName": "Genie Code activity by category",
     # Category x activity rows for User Detail's category table. It's a separate dataset so that clicking a category
     # there doesn't cross-filter ds_main by `category`, which would break that page's SUM(session_*) totals.
     # category_minutes is set on one activity row per session x category, so SUM() gives per-category minutes.
     "queryLines": ql("""
SELECT event_date AS session_date, workspace_name, user_email, user_type, surface, primary_category, session_id,
       category, activity, actions, errors, category_minutes
FROM gc_session_activity
UNION ALL
SELECT session_date, workspace_name, user_email, user_type, surface, primary_category, session_id,
       primary_category, 'Read context only', 0, 0, active_minutes
FROM gc_sessions
WHERE categories_used = 0"""),
     "columns": [c for c in datasets[1]["columns"] if c["displayName"] in ("Primary sessions", "Error rate")]})


def scoped(table, date_col, category_col):
    """SELECT over a view with the global date / workspace / user / user-type / category filters applied via parameters."""
    return f"""SELECT * FROM {table}
  WHERE {date_col} BETWEEN :date_range.min AND :date_range.max
    AND {in_param("p_workspace", "workspace_name")} AND {in_param("p_user", "user_email")}
    AND {in_param("p_user_type", "user_type")} AND {in_param("p_category", category_col)}"""


SCOPED_CTES = f"""s AS ({scoped("gc_sessions", "session_date", "primary_category")}),
e AS ({scoped("gc_session_errors", "session_date", "primary_category")} AND is_actionable),
c AS ({scoped("gc_cost", "usage_date", "cost_category")})"""

# Data-driven action items: one row per finding that applies to the filtered period. Priority thresholds are
# shares of sessions (errors, retries) or of DBUs (long sessions, concentration).
ACTIONS_SQL = "WITH " + FIXES_CTE + ",\n" + SCOPED_CTES + """,
st AS (SELECT count(*) AS sessions, sum(cells_run) AS cells, sum(cells_failed) AS cells_failed,
              count_if(primary_category = '""" + READ_ONLY + """') AS read_only,
              count_if(primary_category <> '""" + READ_ONLY + """') AS acted,
              count_if(active_minutes > """ + str(LONG_SESSION_MINUTES) + """) AS long_n, count_if(cells_failed >= """ + str(RETRY_FAILED_CELLS) + """) AS retry_n
       FROM s),
cs AS (SELECT c.*, x.active_minutes > """ + str(LONG_SESSION_MINUTES) + """ AS is_long, x.cells_failed >= """ + str(RETRY_FAILED_CELLS) + """ AS is_retry, x.acted
       FROM c LEFT JOIN (SELECT session_id, active_minutes, cells_failed,
                                primary_category <> '""" + READ_ONLY + """' AS acted FROM s) x USING (session_id)),
-- format_string's %f needs DOUBLE, not DECIMAL, so the DBU sums are cast.
co AS (SELECT CAST(sum(dbus) AS DOUBLE) AS dbus,
              CAST(sum(CASE WHEN NOT is_free THEN dbus ELSE 0 END) AS DOUBLE) AS billable_dbus,
              CAST(sum(CASE WHEN is_long THEN dbus ELSE 0 END) AS DOUBLE) AS long_dbus,
              CAST(sum(CASE WHEN is_retry THEN dbus ELSE 0 END) AS DOUBLE) AS retry_dbus,
              CAST(sum(CASE WHEN acted THEN dbus ELSE 0 END) AS DOUBLE) AS acted_dbus,
              CAST(sum(CASE WHEN cost_category = '""" + CHAT_ONLY + """' THEN dbus ELSE 0 END) AS DOUBLE) AS chat_dbus
       FROM cs),
uc AS (SELECT user_email, CAST(sum(dbus) AS DOUBLE) AS dbus FROM c WHERE user_email IS NOT NULL GROUP BY user_email),
topu AS (SELECT sum(CASE WHEN rn <= ceil(n * 0.1) THEN dbus ELSE 0 END) / nullif(sum(dbus), 0) AS top_share, max(n) AS users
        FROM (SELECT dbus, row_number() OVER (ORDER BY dbus DESC) AS rn, count(*) OVER () AS n FROM uc)),
ec AS (SELECT error_cause, sum(errors) AS errors, count(DISTINCT session_id) AS sess, count(DISTINCT user_email) AS users,
              row_number() OVER (ORDER BY count(DISTINCT session_id) DESC, sum(errors) DESC) AS rk
       FROM e GROUP BY error_cause),
-- Only the top 3 causes get their own row; the rest roll up into one row that points to the Errors & Fixes page,
-- which has the full list with explanations.
eo AS (SELECT count(DISTINCT e.error_cause) AS causes, sum(e.errors) AS errors, count(DISTINCT e.session_id) AS sess
       FROM e JOIN ec USING (error_cause) WHERE ec.rk > 3),
recs AS (
  SELECT CASE WHEN ec.sess >= 0.05 * st.sessions THEN 1 WHEN ec.sess >= 0.01 * st.sessions THEN 2 ELSE 3 END AS p,
         'Reduce errors' AS area, ec.error_cause AS topic,
         CASE WHEN ec.error_cause IN ('Python / code cell failed', 'SQL cell failed')
              THEN format_string('%,d failed cells in %,d sessions (%.1f%% of sessions), %,d users. Overall %.1f%% of agent-run cells fail.',
                                 ec.errors, ec.sess, 100 * ec.sess / st.sessions, ec.users, 100 * st.cells_failed / nullif(st.cells, 0))
              ELSE format_string('%,d errors in %,d sessions (%.1f%% of sessions), %,d users.',
                                 ec.errors, ec.sess, 100 * ec.sess / st.sessions, ec.users) END AS evidence,
         f.likely_cause, f.how_to_reduce AS action, ec.sess AS weight
  FROM ec CROSS JOIN st LEFT JOIN fixes f USING (error_cause)
  WHERE st.sessions > 0 AND ec.rk <= 3
  UNION ALL
  SELECT CASE WHEN eo.sess >= 0.05 * st.sessions THEN 1 WHEN eo.sess >= 0.01 * st.sessions THEN 2 ELSE 3 END,
         'Reduce errors', 'Other error causes',
         format_string('%,d more causes: %,d errors in %,d sessions (%.1f%% of sessions).',
                       eo.causes, eo.errors, eo.sess, 100 * eo.sess / st.sessions),
         'Smaller error causes, each with its own explanation and fix.',
         'See the Error causes table on the Errors & Fixes page.',
         0  -- sorts after the named causes of the same priority
  FROM eo CROSS JOIN st WHERE eo.causes > 0 AND st.sessions > 0
  UNION ALL
  SELECT CASE WHEN retry_n >= 0.05 * sessions THEN 1 WHEN retry_n >= 0.01 * sessions THEN 2 ELSE 3 END,
         'Cut DBUs', 'Retry loops',
         format_string('%,d sessions (%.1f%%) had """ + str(RETRY_FAILED_CELLS) + """ or more failed cells; they account for %.1f%% of allocated Genie Code DBUs.',
                       retry_n, 100 * retry_n / sessions, 100 * coalesce(retry_dbus / nullif(dbus, 0), 0)),
         'The agent kept retrying a step that kept failing, spending model turns and compute without progress.',
         'When a step fails twice, stop and give the agent the error, a few sample rows or a smaller step. Fix the root cause (names, access, compute) before asking again.',
         retry_n
  FROM st CROSS JOIN co WHERE retry_n > 0
  UNION ALL
  SELECT CASE WHEN long_dbus >= 0.3 * dbus THEN 1 WHEN long_dbus >= 0.1 * dbus THEN 2 ELSE 3 END,
         'Cut DBUs', 'Long sessions',
         format_string('%,d sessions (%.1f%%) ran more than """ + str(LONG_SESSION_MINUTES) + """ active minutes; they account for %.1f%% of allocated DBUs.',
                       long_n, 100 * long_n / sessions, 100 * coalesce(long_dbus / nullif(dbus, 0), 0)),
         'Long conversations resend more context with every turn, so each reply uses more DBUs.',
         'Start a new Genie Code chat for each task, and give the goal, tables and expected output up front instead of steering over many turns.',
         long_n
  FROM st CROSS JOIN co WHERE long_n > 0
  UNION ALL
  SELECT CASE WHEN top_share >= 0.5 THEN 2 ELSE 3 END,
         'Cut DBUs', 'Usage concentration',
         format_string('The top 10%% of users (%,d of %,d) use %.1f%% of Genie Code DBUs (%,.0f of %,.0f DBUs).',
                       CAST(ceil(topu.users * 0.1) AS BIGINT), topu.users, 100 * top_share, top_share * dbus, dbus),
         'A few heavy users account for most of the DBUs.',
         'Review the heaviest users in the User scorecard (Workspaces & Users page). Coach those with high error or retry rates; ask those with high action rates to share their prompts and workflows.',
         topu.users
  FROM topu CROSS JOIN co WHERE topu.users >= 10 AND dbus > 0
  UNION ALL
  SELECT CASE WHEN read_only >= 0.5 * sessions THEN 2 ELSE 3 END,
         'Use it effectively', 'Read-only Q&A sessions',
         format_string('%,d sessions (%.1f%%) only read context and changed nothing.', read_only, 100 * read_only / sessions),
         'Users ask questions (how-to, explain, find data) without asking the agent to do the work.',
         'Put team conventions, key tables and metric definitions in Genie Code workspace instructions so answers land in one turn, use Genie Agents for recurring business questions, and show users the agent can edit and run code for them.',
         read_only
  FROM st WHERE read_only > 0
  UNION ALL
  SELECT 3, 'Use it effectively', 'Chat-only DBUs',
         format_string('%.1f%% of DBUs (%,.0f) are on user-days with no agent tool activity.', 100 * chat_dbus / dbus, chat_dbus),
         'DBUs from answering and explaining in chat, with no actions taken in the workspace.',
         'For hands-on tasks, invoke Genie Code in the notebook, file or SQL editor so it can edit and run code directly, rather than copying code out of chat.',
         0
  FROM co WHERE chat_dbus > 0 AND dbus > 0
  UNION ALL
  SELECT 3, 'Track', 'DBUs per productive session',
         format_string('%,.1f DBUs per session that took action (%,d sessions). %.1f%% of DBUs are billable (not free tier).',
                       acted_dbus / acted, acted, 100 * coalesce(billable_dbus / nullif(dbus, 0), 0)),
         'DBUs allocated to sessions where the agent changed or ran something, divided by those sessions.',
         'Track this monthly: it should fall as failed-cell, retry and long-session rates fall.',
         0
  FROM st CROSS JOIN co WHERE acted > 0 AND dbus > 0
)
SELECT CASE p WHEN 1 THEN 'High' WHEN 2 THEN 'Medium' ELSE 'Low' END AS priority, p AS priority_rank,
       area, topic, evidence, likely_cause, action, weight
FROM recs"""

USER_ACTIONS_SQL = "WITH " + SCOPED_CTES + """,
us AS (SELECT user_email, count(*) AS sessions, count_if(primary_category <> '""" + READ_ONLY + """') AS acted,
              sum(active_minutes) AS minutes, sum(cells_run) AS cells, sum(cells_failed) AS cells_failed,
              count_if(active_minutes > """ + str(LONG_SESSION_MINUTES) + """) AS long_n, count_if(cells_failed >= """ + str(RETRY_FAILED_CELLS) + """) AS retry_n,
              sum(notebooks_created) AS notebooks, count(DISTINCT session_date) AS active_days,
              min(session_date) AS first_seen, max(session_date) AS last_seen,
              count(DISTINCT workspace_name) AS workspaces
       FROM s GROUP BY user_email),
uws AS (SELECT user_email, max_by(workspace_name, n) AS primary_workspace
        FROM (SELECT user_email, workspace_name, count(*) AS n FROM s
              WHERE workspace_name <> 'Account-level' GROUP BY ALL) GROUP BY user_email),
utop AS (SELECT user_email, max_by(primary_category, n) AS top_category
         FROM (SELECT user_email, primary_category, count(*) AS n FROM s
               WHERE primary_category <> '""" + READ_ONLY + """' GROUP BY ALL) GROUP BY user_email),
ue AS (SELECT user_email, sum(errors) AS errors, max_by(error_cause, errors) AS top_cause
       FROM (SELECT user_email, error_cause, sum(errors) AS errors FROM e GROUP BY ALL) GROUP BY user_email),
ucst AS (SELECT user_email, sum(dbus) AS dbus,
                sum(CASE WHEN cost_category = '""" + CHAT_ONLY + """' THEN dbus ELSE 0 END) AS chat_dbus,
                percent_rank() OVER (ORDER BY sum(dbus)) AS dbu_rank
         FROM c WHERE user_email IS NOT NULL GROUP BY user_email),
u AS (
  SELECT coalesce(us.user_email, ucst.user_email) AS user_email,
         coalesce(us.sessions, 0) AS sessions, us.acted, coalesce(us.minutes, 0) AS active_minutes,
         coalesce(us.cells, 0) AS cells_run, coalesce(us.cells_failed, 0) AS cells_failed,
         coalesce(us.long_n, 0) AS long_sessions, coalesce(us.retry_n, 0) AS retry_sessions,
         coalesce(us.notebooks, 0) AS notebooks_created, coalesce(us.active_days, 0) AS active_days,
         us.first_seen, us.last_seen, coalesce(us.workspaces, 0) AS workspaces,
         coalesce(uws.primary_workspace, CASE WHEN us.sessions > 0 THEN 'Account-level' END) AS primary_workspace,
         coalesce(ue.errors, 0) AS actionable_errors, ue.top_cause,
         coalesce(utop.top_category, CASE WHEN us.sessions > 0 THEN '""" + READ_ONLY + """' END) AS top_category,
         coalesce(ucst.dbus, 0) AS dbus,
         coalesce(ucst.chat_dbus, 0) AS chat_dbus, coalesce(ucst.dbu_rank, 0) AS dbu_rank
  FROM us
  FULL OUTER JOIN ucst ON us.user_email = ucst.user_email
  LEFT JOIN ue ON coalesce(us.user_email, ucst.user_email) = ue.user_email
  LEFT JOIN utop ON us.user_email = utop.user_email
  LEFT JOIN uws ON us.user_email = uws.user_email
)
SELECT user_email, coalesce(primary_workspace, '') AS primary_workspace, active_days, first_seen, last_seen,
       notebooks_created, workspaces, coalesce(top_category, '""" + CHAT_ONLY + """') AS top_category, sessions,
       acted / nullif(sessions, 0) AS action_rate, active_minutes, cells_run, cells_failed,
       cells_failed / nullif(cells_run, 0) AS failed_cell_rate, retry_sessions, long_sessions,
       actionable_errors, coalesce(top_cause, '') AS top_error_cause, dbus,
       dbus / nullif(sessions, 0) AS dbus_per_session,
       CASE
         WHEN sessions = 0 AND dbu_rank >= 0.9 THEN 'Top-10% DBUs, all chat: check the use case; for hands-on tasks use the agent in the notebook or editor'
         WHEN sessions = 0 THEN 'Chat only: no agent actions in this period'
         WHEN retry_sessions >= 3 THEN 'Retry loops: when a step keeps failing, give the agent the error and a smaller step'
         WHEN cells_run >= 10 AND cells_failed >= 0.25 * cells_run THEN 'Many failed cells: give exact table and column names, run one step at a time, use /fix'
         WHEN top_cause = 'Table / schema / catalog not found' AND actionable_errors >= 5 THEN 'Agent guesses names: @-mention tables and set the default catalog and schema'
         WHEN top_cause = 'Permission denied' AND actionable_errors >= 5 THEN 'Permission errors: request access to the data being used'
         WHEN top_cause IN ('External tool / MCP call failed', 'External connection auth failed') AND actionable_errors >= 5
           THEN 'External tool errors: re-authenticate or remove unused MCP servers'
         WHEN dbu_rank >= 0.9 AND chat_dbus >= 0.8 * dbus
           THEN 'Top-10% DBUs, mostly chat: check the use case; for hands-on tasks use the agent in the notebook or editor'
         WHEN sessions >= 5 AND long_sessions >= 0.3 * sessions THEN 'Long sessions: start a new chat per task to cut context DBUs'
         WHEN sessions >= 5 AND acted < 0.3 * sessions THEN 'Mostly Q&A: add workspace instructions or a Genie Agent for repeat questions'
         WHEN sessions >= 5 AND acted >= 0.6 * sessions AND cells_failed < 0.1 * greatest(cells_run, 1)
           THEN 'Effective user: share their prompts and workflows with the team'
         ELSE 'No action needed'
       END AS suggested_action
FROM u"""

ACTION_PARAMS = [DATE_PARAM, P_WS, P_USER, P_TYPE, P_CAT]
datasets += [
    {"name": "ds_actions", "displayName": "Genie Code action items",
     "queryLines": ql(ACTIONS_SQL), "parameters": copy.deepcopy(ACTION_PARAMS)},
    {"name": "ds_user_actions", "displayName": "Genie Code user scorecard",
     "queryLines": ql(USER_ACTIONS_SQL), "parameters": copy.deepcopy(ACTION_PARAMS)},
]

PCT_FMT = {"type": "number-percent", "decimalPlaces": {"type": "max", "places": 1}}
DBU1_FMT = {"type": "number", "decimalPlaces": {"type": "fixed", "places": 1}}
LEGEND_BOTTOM = {"position": "bottom"}


def cat_color():
    return {"fieldName": "primary_category", "scale": CAT_SCALE, "displayName": "Primary category",
            "legend": LEGEND_BOTTOM}


def agg_table(name, title, desc, ds, columns, p, orders=None, sort_fields=()):
    """Table over a shared dataset. columns: (field, display, format-or-None); field is a {name, expression}
    dict. Aggregated fields group the rows by the plain ones, so the table cross-filters with the page.
    sort_fields are queried (so orders can use them) but not shown."""
    cols = []
    for field, display, fmt in columns:
        c = {"fieldName": field["name"], "displayName": display}
        if fmt:
            c["format"] = fmt
        cols.append(c)
    return {"widget": {"name": name, "queries": q(ds, [c[0] for c in columns] + list(sort_fields), orders=orders),
                       "spec": {"version": 2, "widgetType": "table", "encodings": {"columns": cols},
                                "frame": frame(title, desc)}},
            "position": p}


SESSIONS = f("countdistinct(session_id)", "COUNT(DISTINCT `session_id`)")
USERS = f("countdistinct(user_email)", "COUNT(DISTINCT `user_email`)")
WORKSPACES = f("countdistinct(workspace_name)", "COUNT(DISTINCT `workspace_name`)")
ACTION_RATE = f("measure(Action rate)", "MEASURE(`Action rate`)")
ERROR_RATE = f("measure(Error rate)", "MEASURE(`Error rate`)")
PRIMARY_SESSIONS = f("measure(Primary sessions)", "MEASURE(`Primary sessions`)")
FAILED_CELL_RATE = f("measure(Failed cell rate)", "MEASURE(`Failed cell rate`)")
SESSIONS_WITH_ERRORS = f("measure(Sessions with errors)", "MEASURE(`Sessions with errors`)")
col = lambda c: f(c, f"`{c}`")
total = lambda c: f(f"sum({c})", f"SUM(`{c}`)")


def monthly_cat_bar(name, title, desc, p):
    return {"widget": {"name": name,
                       "queries": q("ds_main", [MONTH("session_date"), f("primary_category", "`primary_category`"), SESSIONS]),
                       "spec": {"version": 3, "widgetType": "bar",
                                "encodings": {
                                    "x": {"fieldName": "monthly(session_date)", "scale": {"type": "temporal"}, "displayName": "Month"},
                                    "y": {"fieldName": SESSIONS["name"], "scale": {"type": "quantitative"}, "displayName": "Sessions"},
                                    "color": cat_color()},
                                "frame": frame(title, desc)}},
            "position": p}


ACTIVITY_COLUMNS = [(col("category"), "Category", None), (col("activity"), "Activity", None),
                    (SESSIONS, "Sessions", None), (USERS, "Users", None), (WORKSPACES, "Workspaces", None),
                    (total("actions"), "Agent actions", None)]
BY_SESSIONS = [(SESSIONS["expression"], "DESC")]
ERROR_CAUSE_COLUMNS = [(col("error_cause"), "Cause", None), (total("errors"), "Errors", None),
                       (SESSIONS, "Sessions", None), (USERS, "Users", None),
                       (col("likely_cause"), "Why it happens", None), (col("how_to_reduce"), "How to reduce it", None)]
SCORECARD_COLUMNS = [(col("user_email"), "User", None), (col("suggested_action"), "Suggested action", None),
                     (col("top_category"), "Top category", None), (col("primary_workspace"), "Primary workspace", None),
                     (col("sessions"), "Sessions", None), (col("action_rate"), "Action rate", PCT_FMT),
                     (col("active_days"), "Active days", None), (col("first_seen"), "First seen (retained data)", None),
                     (col("last_seen"), "Last seen", None), (col("active_minutes"), "Active min", None),
                     (col("cells_run"), "Cells run", None), (col("failed_cell_rate"), "Failed cell rate", PCT_FMT),
                     (col("notebooks_created"), "Notebooks created", None),
                     (col("actionable_errors"), "Actionable errors", None), (col("top_error_cause"), "Top error cause", None),
                     (col("dbus"), "DBUs", COUNT_FMT), (col("dbus_per_session"), "DBUs / session", DBU1_FMT)]
# User Detail shows the rest of the scorecard as KPI tiles, so its table keeps only what the tiles don't.
SUGGESTION_COLUMNS = [(col("user_email"), "User", None), (col("suggested_action"), "Suggested action", None),
                      (col("top_error_cause"), "Top error cause", None), (col("retry_sessions"), "Retry sessions", None),
                      (col("long_sessions"), f"{LONG_SESSION_MINUTES}+ min sessions", None), (col("dbus_per_session"), "DBUs / session", DBU1_FMT)]
BY_DBUS = [("`dbus`", "DESC")]

# ---------------- Overview page ----------------
overview = [
    text("ov_header", [
        "# Genie Code Usage Patterns\n", "\n",
        "How people use **Genie Code** (formerly Databricks Assistant) across workspaces: who is using it, "
        "and what the agent is doing on their behalf: writing code, exploring the catalog, running SQL, "
        "building dashboards, data engineering, ML, or answering questions. Categories come from the actions "
        "the Genie Code agent performs (audit events tagged `databricks-background-genie`). "
        "Defaults to **human** usage; switch *User type* on the Filters page to include automated / eval traffic. "
        "For recommendations, see **Action Items & DBUs** (what to do, DBUs by user and category) and **Errors & Fixes** "
        "(why actions fail and how to reduce it)."],
        pos(0, 0, 12, 3)),
    counter("kpi_users", "Active Genie Code users", "Distinct users with Genie Code events (all clients)",
            "ds_users", USERS, "event_date", "Users", COUNT_FMT, pos(0, 3, 3, 3)),
    counter("kpi_workspaces", "Active workspaces", "Workspaces with Genie Code usage",
            "ds_users", f("countdistinct(workspace_name)", "COUNT(DISTINCT `workspace_name`)"), "event_date",
            "Workspaces", COUNT_FMT, pos(3, 3, 3, 3)),
    counter("kpi_sessions", "Agent sessions", "Genie Code agent sessions (sid)",
            "ds_main", SESSIONS, "session_date", "Sessions", COUNT_FMT, pos(6, 3, 3, 3)),
    counter("kpi_action_rate", "Sessions that took action", "Share of sessions where the agent changed or ran something (vs read-only Q&A)",
            "ds_main", ACTION_RATE, "session_date",
            "Action rate", PCT_FMT, pos(9, 3, 3, 3)),
    {"widget": {"name": "mau_by_client",
                "queries": q("ds_users", [MONTH("event_date"), f("client_type", "`client_type`"), USERS]),
                "spec": {"version": 3, "widgetType": "line",
                         "encodings": {
                             "x": {"fieldName": "monthly(event_date)", "scale": {"type": "temporal"}, "displayName": "Month"},
                             "y": {"fieldName": USERS["name"], "scale": {"type": "quantitative"}, "displayName": "Monthly active users"},
                             "color": {"fieldName": "client_type", "scale": {"type": "categorical"}, "displayName": "Client",
                                       "legend": LEGEND_BOTTOM}},
                         "frame": frame("Monthly active users by client", "From system.access.assistant_events")}},
     "position": pos(0, 13, 12, 7)},
    monthly_cat_bar("monthly_sessions_by_cat", "Monthly agent sessions by primary category",
                   "Primary category = what the agent spent the most active minutes on", pos(0, 6, 12, 7)),
    agg_table("category_summary", "Category summary",
              "Primary = sessions where this was the main activity (each session counted once). "
              "Any = sessions that touched the category at all (a session can span several).",
              "ds_main", [(col("category"), "Category", None), (PRIMARY_SESSIONS, "Sessions (primary)", None),
                          (SESSIONS, "Sessions (any)", None), (USERS, "Users", None),
                          (total("actions"), "Agent actions", None), (ERROR_RATE, "Error rate", PCT_FMT)],
              pos(0, 20, 12, 7), orders=BY_SESSIONS),
]

# ---------------- Usage patterns page ----------------
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
patterns = [
    text("pt_header", ["## Usage patterns\n", "\n",
                       "When and where Genie Code is used, how deep sessions go, and the specific agent activities behind each category. Times are UTC."],
         pos(0, 0, 12, 2)),
    {"widget": {"name": "heat_dow_hour",
                "queries": q("ds_main", [f("hour_of_day", "`hour_of_day`"), f("day_of_week", "`day_of_week`"), SESSIONS]),
                "spec": {"version": 3, "widgetType": "heatmap",
                         "encodings": {
                             "x": {"fieldName": "hour_of_day", "scale": {"type": "categorical"}, "displayName": "Hour (UTC)"},
                             "y": {"fieldName": "day_of_week", "scale": {"type": "categorical", "sort": {"by": "custom-order", "orderedValues": DOW}}, "axis": {"hideTitle": True}},
                             "color": {"fieldName": SESSIONS["name"], "displayName": "Sessions",
                                       "scale": {"type": "quantitative", "colorRamp": {"mode": "custom-sequential", "colors": {"start": "#E8F1F8", "end": "#0072B2"}}}}},
                         "frame": frame("When sessions happen (day x hour, UTC)")}},
     "position": pos(0, 2, 6, 7)},
    {"widget": {"name": "cat_by_surface",
                "queries": q("ds_main", [f("surface", "`surface`"), f("primary_category", "`primary_category`"), SESSIONS]),
                "spec": {"version": 3, "widgetType": "bar",
                         "encodings": {
                             "x": {"fieldName": SESSIONS["name"], "scale": {"type": "quantitative"}, "displayName": "Share of sessions"},
                             "y": {"fieldName": "surface", "scale": {"type": "categorical"}, "axis": {"hideTitle": True}},
                             "color": cat_color()},
                         "mark": {"layout": "stack-100"},
                         "frame": frame("Category mix by surface", "Where Genie Code was invoked: side panel, embedded, document, visualization")}},
     "position": pos(0, 9, 12, 6)},
    {"widget": {"name": "length_by_cat",
                "queries": q("ds_main", [f("session_length", "`session_length`"), f("primary_category", "`primary_category`"), SESSIONS]),
                "spec": {"version": 3, "widgetType": "bar",
                         "encodings": {
                             "x": {"fieldName": "session_length", "scale": {"type": "categorical", "sort": {"by": "custom-order", "orderedValues": ["1 min", "2-5 min", "6-15 min", "16-60 min", "60+ min"]}}, "displayName": "Active minutes in session"},
                             "y": {"fieldName": SESSIONS["name"], "scale": {"type": "quantitative"}, "displayName": "Sessions"},
                             "color": cat_color()},
                         "frame": frame("Session depth (active minutes)")}},
     "position": pos(0, 15, 12, 7)},
    {"widget": {"name": "cats_per_session",
                "queries": q("ds_main", [f("categories_bucket", "`categories_bucket`"), SESSIONS]),
                "spec": {"version": 3, "widgetType": "bar",
                         "encodings": {
                             "x": {"fieldName": "categories_bucket", "scale": {"type": "categorical", "sort": {"by": "custom-order", "orderedValues": ["0 (read-only)", "1 category", "2 categories", "3+ categories"]}}, "displayName": "Categories used in session"},
                             "y": {"fieldName": SESSIONS["name"], "scale": {"type": "quantitative"}, "displayName": "Sessions"},
                             "label": {"show": True}},
                         "frame": frame("Multi-category sessions", "E.g. explore catalog, then write code, then build a dashboard")}},
     "position": pos(6, 2, 6, 7)},
    agg_table("top_activities", "Agent activities by category",
              "What Genie Code actually did: edits, cell runs, catalog lookups, dashboard builds, MCP tool calls. One row per activity; sort by any column.",
              "ds_main", ACTIVITY_COLUMNS, pos(0, 22, 12, 10), orders=BY_SESSIONS),
]

# ---------------- Workspaces & users page ----------------
people = [
    text("wu_header", ["## Workspaces & users\n", "\n",
                       "Which workspaces and people use Genie Code most, and for what. 'Account-level' = sessions with no workspace-scoped actions."],
         pos(0, 0, 12, 2)),
    {"widget": {"name": "ws_by_cat",
                "queries": q("ds_main", [f("workspace_name", "`workspace_name`"), f("primary_category", "`primary_category`"), SESSIONS]),
                "spec": {"version": 3, "widgetType": "pivot",
                         "encodings": {
                             "rows": [{"fieldName": "workspace_name", "displayName": "Workspace",
                                       "scale": {"type": "categorical", "sort": {"by": "cell-reversed", "field": {"index": 0}}}}],
                             "columns": [{"fieldName": "primary_category", "displayName": "Primary category", "total": {"show": True}}],
                             "cell": {"type": "multi-cell", "fields": [
                                 {"fieldName": SESSIONS["name"], "displayName": "Sessions", "cellType": "color-scale"}]}},
                         "frame": frame("Sessions by workspace and primary category")}},
     "position": pos(0, 2, 12, 9)},
    agg_table("user_scorecard", "User scorecard",
              "One row per user, most DBUs first, for the filtered period. The suggested action is the first rule that applies: "
              "retry loops, failed cells, guessed names, permissions, external tools, chat-heavy top DBU users, long sessions, "
              "mostly Q&A, then effective users. Users with DBUs but no agent sessions are included. "
              "This table doesn't respond to clicks on other visuals; use the filters. Use the User Detail page to drill into one user.",
              "ds_user_actions", SCORECARD_COLUMNS, pos(0, 11, 12, 10), orders=BY_DBUS),
    {"widget": {"name": "user_by_cat",
                "queries": q("ds_main", [f("user_email", "`user_email`"), f("primary_category", "`primary_category`"), SESSIONS]),
                "spec": {"version": 3, "widgetType": "pivot",
                         "encodings": {
                             "rows": [{"fieldName": "user_email", "displayName": "User",
                                       "scale": {"type": "categorical", "sort": {"by": "cell-reversed", "field": {"index": 0}}}}],
                             "columns": [{"fieldName": "primary_category", "displayName": "Primary category", "total": {"show": True}}],
                             "cell": {"type": "multi-cell", "fields": [
                                 {"fieldName": SESSIONS["name"], "displayName": "Sessions", "cellType": "color-scale"}]}},
                         "frame": frame("Sessions by user and primary category",
                                        "Each user's sessions split by what the agent mainly did")}},
     "position": pos(0, 21, 12, 10)},
]

# ---------------- User detail page ----------------
user_detail = [
    text("ud_header", ["## User detail\n", "\n",
                       "Pick one or more users (top right) for a profile: activity totals, where they use Genie Code, "
                       "what they use it for, and a log of every agent session. With no user selected, the page shows everyone. "
                       "Trends for the same users are on the other pages via the *User* filter."],
         pos(0, 0, 8, 2)),
    None,  # page-level user filter, filled in below once gfilter exists
    counter("ud_kpi_sessions", "Agent sessions", None, "ds_main", SESSIONS, "session_date", "Sessions", COUNT_FMT, pos(0, 2, 3, 3)),
    counter("ud_kpi_action", "Sessions that took action", None, "ds_main",
            ACTION_RATE, "session_date", "Action rate", PCT_FMT, pos(3, 2, 3, 3)),
    counter("ud_kpi_minutes", "Active agent minutes", None, "ds_main",
            total("session_active_minutes"), "session_date", "Minutes", COUNT_FMT, pos(6, 2, 3, 3)),
    counter("ud_kpi_days", "Active days", "Days with any Genie Code event", "ds_users",
            f("countdistinct(event_date)", "COUNT(DISTINCT `event_date`)"), "event_date", "Days", None, pos(9, 2, 3, 3)),
    counter("ud_kpi_dbus", "Genie Code DBUs", "Incl. chat-only days and free tier", "ds_cost",
            total("dbus"), "usage_date", "DBUs", COUNT_FMT, pos(0, 5, 4, 3)),
    counter("ud_kpi_failed_cells", "Failed cell rate", "Agent-run notebook cells that failed", "ds_main",
            FAILED_CELL_RATE, "session_date", "Failed cells", PCT_FMT, pos(4, 5, 4, 3)),
    counter("ud_kpi_errors", "Actionable errors", "Excludes the agent's expected background probes", "ds_errors",
            total("errors"), "session_date", "Errors", COUNT_FMT, pos(8, 5, 4, 3)),
    agg_table("ud_suggestions", "Suggested action",
              "From the selected period's sessions, errors and DBUs (rules on the User scorecard, Workspaces & Users page)",
              "ds_user_actions", SUGGESTION_COLUMNS, pos(0, 8, 12, 4), orders=BY_DBUS,
              sort_fields=[col("dbus")]),
    {"widget": {"name": "ud_cat_mix",
                "queries": q("ds_main", [f("primary_category", "`primary_category`"), SESSIONS]),
                "spec": {"version": 3, "widgetType": "pie",
                         "encodings": {
                             "angle": {"fieldName": SESSIONS["name"], "scale": {"type": "quantitative"}, "displayName": "Sessions"},
                             "color": cat_color(),
                             "label": {"show": True}},
                         "frame": frame("Category mix", "Sessions by primary category")}},
     "position": pos(0, 12, 6, 8)},
    agg_table("ud_workspaces", "Workspaces and surfaces used", "Sessions per workspace and surface", "ds_main",
              [(col("workspace_name"), "Workspace", None), (col("surface"), "Surface", None), (SESSIONS, "Sessions", None)],
              pos(6, 12, 6, 8), orders=BY_SESSIONS),
    agg_table("ud_categories", "Category breakdown",
              "What the agent did for the selected users in each category. Sessions (any) counts every session that touched it. "
              "Clicking a row filters only this table.",
              "ds_user_categories",
              [(col("category"), "Category", None), (PRIMARY_SESSIONS, "Sessions (primary)", None),
               (SESSIONS, "Sessions (any)", None), (total("category_minutes"), "Active min", None),
               (total("actions"), "Agent actions", None), (total("errors"), "Errors", None),
               (ERROR_RATE, "Error rate", PCT_FMT)],
              pos(0, 20, 12, 7), orders=BY_SESSIONS),
    agg_table("ud_error_causes", "Errors and how to reduce them", "Actionable errors for the selected users, by cause",
              "ds_errors", ERROR_CAUSE_COLUMNS, pos(0, 27, 12, 7), orders=[("SUM(`errors`)", "DESC")]),
    agg_table("ud_session_log", "Session log", "Every Genie Code agent session, newest first", "ds_main",
              [(col("session_start"), "Started (UTC)", None), (col("user_email"), "User", None),
               (col("workspace_name"), "Workspace", None), (col("surface"), "Surface", None),
               (col("primary_category"), "Primary category", None), (col("categories_list"), "All categories", None),
               (total("session_active_minutes"), "Active min", None), (total("session_duration_minutes"), "Duration min", None),
               (total("session_total_actions"), "Agent actions", None), (total("session_cells_run"), "Cells run", None),
               (total("session_notebooks_created"), "Notebooks created", None),
               (total("session_cells_failed"), "Cells failed", None), (total("session_errors"), "Actionable errors", None),
               (col("session_id"), "Session ID", None)],
              pos(0, 34, 12, 12), orders=[("`session_start`", "DESC")]),
]

# ---------------- Action items & DBUs page ----------------
actions = [
    text("ac_header", ["## Action items & DBUs\n", "\n",
                       "What to do next, generated from the data for the filtered period: the biggest error causes, DBU drivers "
                       "and usage patterns, each with a recommendation. DBUs are Genie Code usage from `system.billing.usage`, "
                       "free tier included. Billing has no session ID, so each user-day's DBUs are split across that "
                       "user's sessions by active minutes; DBUs on days with no agent actions show as *" + CHAT_ONLY + "*. "
                       "Action items follow every filter except surface."],
         pos(0, 0, 12, 3)),
    counter("ac_kpi_dbus", "Genie Code DBUs", "All Genie Code usage, free tier included", "ds_cost",
            total("dbus"), "usage_date", "DBUs", COUNT_FMT, pos(0, 3, 4, 3)),
    counter("ac_kpi_dbus_user", "DBUs per user", "Per user with any Genie Code DBUs", "ds_cost",
            f("measure(DBUs per user)", "MEASURE(`DBUs per user`)"), "usage_date", "DBUs / user", COUNT_FMT, pos(4, 3, 4, 3)),
    counter("ac_kpi_billable", "Billable share of DBUs", "DBUs outside the free tier", "ds_cost",
            f("measure(Billable share)", "MEASURE(`Billable share`)"), "usage_date", "Billable", PCT_FMT, pos(8, 3, 4, 3)),
    agg_table("ac_items", "Action items",
              "Highest priority first. High = affects 5%+ of sessions (or 30%+ of DBUs); Medium = 1%+ (or 10%+).",
              "ds_actions",
              [(col("priority"), "Priority", None), (col("area"), "Area", None), (col("topic"), "Topic", None),
               (col("evidence"), "What the data shows", None), (col("likely_cause"), "Why", None),
               (col("action"), "What to do", None)],
              pos(0, 6, 12, 10), orders=[("`priority_rank`", "ASC"), ("`weight`", "DESC")],
              sort_fields=[col("priority_rank"), col("weight")]),
    {"widget": {"name": "ac_monthly_dbus",
                "queries": q("ds_cost", [MONTH("usage_date"), col("cost_category"), total("dbus")]),
                "spec": {"version": 3, "widgetType": "bar",
                         "encodings": {
                             "x": {"fieldName": "monthly(usage_date)", "scale": {"type": "temporal"}, "displayName": "Month"},
                             "y": {"fieldName": "sum(dbus)", "scale": {"type": "quantitative"}, "displayName": "DBUs",
                                   "format": COUNT_FMT},
                             "color": {"fieldName": "cost_category", "scale": COST_CAT_SCALE, "displayName": "Category",
                                       "legend": LEGEND_BOTTOM}},
                         "frame": frame("Monthly Genie Code DBUs by category",
                                        "DBUs split across each user-day's sessions by active minutes")}},
     "position": pos(0, 16, 12, 8)},
    {"widget": {"name": "ac_user_cat_dbus",
                "queries": q("ds_cost", [col("user_email"), col("cost_category"), total("dbus")]),
                "spec": {"version": 3, "widgetType": "pivot",
                         "encodings": {
                             "rows": [{"fieldName": "user_email", "displayName": "User",
                                       "scale": {"type": "categorical", "sort": {"by": "cell-reversed", "field": {"index": 0}}}}],
                             "columns": [{"fieldName": "cost_category", "displayName": "Category", "total": {"show": True}}],
                             "cell": {"type": "multi-cell", "fields": [
                                 {"fieldName": "sum(dbus)", "displayName": "DBUs", "cellType": "color-scale",
                                  "format": DBU1_FMT}]}},
                         "frame": frame("DBUs by user and category",
                                        "Column totals give DBUs by category; see the User scorecard for each user's suggested action")}},
     "position": pos(0, 24, 12, 10)},
]

# ---------------- Errors & fixes page ----------------
errors_page = [
    text("er_header", ["## Errors & fixes\n", "\n",
                       "Why Genie Code agent actions fail and how to reduce it. Errors include HTTP 4xx/5xx responses and failed "
                       "notebook cells. The agent's routine existence checks (files, credentials and connections that usually "
                       "don't exist) also return 'not found'. They are expected, so they are left out of this page and of every error rate."],
         pos(0, 0, 12, 2)),
    counter("er_kpi_cells", "Failed cell rate", "Agent-run notebook cells that failed", "ds_main",
            FAILED_CELL_RATE, "session_date", "Failed cells", PCT_FMT, pos(0, 2, 4, 3)),
    counter("er_kpi_sessions", "Sessions with an error", "Share of sessions with at least one actionable error", "ds_main",
            SESSIONS_WITH_ERRORS, "session_date", "Sessions", PCT_FMT, pos(4, 2, 4, 3)),
    counter("er_kpi_errors", "Actionable errors", None, "ds_errors",
            total("errors"), "session_date", "Errors", COUNT_FMT, pos(8, 2, 4, 3)),
    agg_table("er_causes", "Error causes and how to reduce them", "Sorted by errors. Click a row to filter the rest of the page.",
              "ds_errors", [(col("cause_group"), "Group", None)] + ERROR_CAUSE_COLUMNS,
              pos(0, 5, 12, 9), orders=[("SUM(`errors`)", "DESC")]),
    {"widget": {"name": "er_monthly",
                "queries": q("ds_errors", [MONTH("session_date"), col("cause_group"), total("errors")]),
                "spec": {"version": 3, "widgetType": "bar",
                         "encodings": {
                             "x": {"fieldName": "monthly(session_date)", "scale": {"type": "temporal"}, "displayName": "Month"},
                             "y": {"fieldName": "sum(errors)", "scale": {"type": "quantitative"}, "displayName": "Errors"},
                             "color": {"fieldName": "cause_group", "displayName": "Cause group", "legend": LEGEND_BOTTOM,
                                       "scale": {"type": "categorical", "sort": {"by": "custom-order", "orderedValues": CAUSE_GROUPS}}}},
                         "frame": frame("Monthly errors by cause group")}},
     "position": pos(0, 14, 6, 7)},
    {"widget": {"name": "er_cell_rate_trend",
                "queries": q("ds_main", [MONTH("session_date"), FAILED_CELL_RATE]),
                "spec": {"version": 3, "widgetType": "line",
                         "encodings": {
                             "x": {"fieldName": "monthly(session_date)", "scale": {"type": "temporal"}, "displayName": "Month"},
                             "y": {"fieldName": FAILED_CELL_RATE["name"], "scale": {"type": "quantitative"},
                                   "displayName": "Failed cell rate", "format": PCT_FMT}},
                         "frame": frame("Failed cell rate by month", "Should fall as prompts and instructions improve")}},
     "position": pos(6, 14, 6, 7)},
    agg_table("er_where", "Where errors happen", "Category and agent activity behind each cause", "ds_errors",
              [(col("category"), "Category", None), (col("activity"), "Activity", None), (col("error_cause"), "Cause", None),
               (total("errors"), "Errors", None), (SESSIONS, "Sessions", None), (USERS, "Users", None)],
              pos(0, 21, 12, 8), orders=[("SUM(`errors`)", "DESC")]),
    {"widget": {"name": "er_user_cause",
                "queries": q("ds_errors", [col("user_email"), col("cause_group"), total("errors")]),
                "spec": {"version": 3, "widgetType": "pivot",
                         "encodings": {
                             "rows": [{"fieldName": "user_email", "displayName": "User",
                                       "scale": {"type": "categorical", "sort": {"by": "cell-reversed", "field": {"index": 0}}}}],
                             "columns": [{"fieldName": "cause_group", "displayName": "Cause group", "total": {"show": True}}],
                             "cell": {"type": "multi-cell", "fields": [
                                 {"fieldName": "sum(errors)", "displayName": "Errors", "cellType": "color-scale"}]}},
                         "frame": frame("Errors by user and cause group", "Who to help first, and with what")}},
     "position": pos(0, 29, 12, 9)},
]


# ---------------- Filters ----------------
def gfilter(name, title, wtype, fields, params, p, default=None):
    """fields: (dataset, column) field bindings; params: (dataset, keyword) parameter bindings."""
    queries, enc = [], []
    for ds, col in fields:
        qn = f"{name}_{ds}"
        queries.append({"name": qn, "query": {"datasetName": ds, "fields": [f(col, f"`{col}`")], "disaggregated": False}})
        enc.append({"fieldName": col, "queryName": qn, "displayName": title})
    for ds, kw in params:
        qn = f"{name}_{ds}_param"
        queries.append({"name": qn, "query": {"datasetName": ds, "parameters": [{"name": kw, "keyword": kw}], "disaggregated": False}})
        enc.append({"parameterName": kw, "queryName": qn, "displayName": title})
    spec = {"version": 2, "widgetType": wtype, "encodings": {"fields": enc}, "frame": frame(title)}
    if default:
        spec["selection"] = {"defaultSelection": {"values": {"dataType": "STRING", "values": [{"value": v} for v in default]}}}
    return {"widget": {"name": name, "queries": queries, "spec": spec}, "position": p}


ALL_PARAM_DS = ["ds_actions", "ds_user_actions"]
BASE2 = lambda col_users, col_main: [("ds_users", col_users), ("ds_main", col_main)]
# ds_errors and ds_user_categories use ds_main's column names; ds_cost names its date usage_date.
BASE4 = lambda col_users, col_main, col_cost=None: (BASE2(col_users, col_main) + [("ds_errors", col_main),
                                                    ("ds_user_categories", col_main), ("ds_cost", col_cost or col_main)])

filters = [
    gfilter("f_date", "Date", "filter-date-range-picker", BASE4("event_date", "session_date", "usage_date"),
            [(d, "date_range") for d in ALL_PARAM_DS], pos(0, 0, 4, 2)),
    gfilter("f_workspace", "Workspace", "filter-multi-select", BASE4("workspace_name", "workspace_name"),
            [(d, "p_workspace") for d in ALL_PARAM_DS], pos(0, 2, 4, 2)),
    gfilter("f_user", "User", "filter-multi-select", BASE4("user_email", "user_email"),
            [(d, "p_user") for d in ALL_PARAM_DS], pos(0, 4, 4, 2)),
    gfilter("f_user_type", "User type", "filter-multi-select", BASE4("user_type", "user_type"),
            [(d, "p_user_type") for d in ALL_PARAM_DS], pos(0, 6, 4, 2), default=["Human"]),
    gfilter("f_surface", "Surface", "filter-multi-select",
            [("ds_main", "surface"), ("ds_errors", "surface"), ("ds_user_categories", "surface")], [],
            pos(0, 8, 4, 2)),
    gfilter("f_category", "Primary category", "filter-multi-select",
            [("ds_main", "primary_category"), ("ds_errors", "primary_category"), ("ds_user_categories", "primary_category"),
             ("ds_cost", "cost_category")], [(d, "p_category") for d in ALL_PARAM_DS],
            pos(0, 10, 4, 2)),
    gfilter("f_client", "Client type (users)", "filter-multi-select", [("ds_users", "client_type")], [],
            pos(0, 12, 4, 2)),
]
user_detail[1] = gfilter("ud_user", "User(s)", "filter-multi-select",
                         BASE4("user_email", "user_email") + [("ds_user_actions", "user_email")], [], pos(8, 0, 4, 2))


def page(name, display, layout, ptype="PAGE_TYPE_CANVAS"):
    return {"name": name, "displayName": display, "pageType": ptype, "layoutVersion": "GRID_V1", "layout": layout}


dashboard = {
    "datasets": datasets,
    # Descriptive pages first, then diagnosis, then recommendations.
    "pages": [page("overview", "Overview", overview),
              page("patterns", "Usage Patterns", patterns),
              page("people", "Workspaces & Users", people),
              page("user_detail", "User Detail", user_detail),
              page("errors", "Errors & Fixes", errors_page),
              page("actions", "Action Items & DBUs", actions),
              page("filters", "Filters", filters, "PAGE_TYPE_GLOBAL_FILTERS")],
    "uiSettings": {"theme": {
        "canvasBackgroundColor": {"light": "#F7F9FA", "dark": "#1F272D"},
        "widgetBackgroundColor": {"light": "#FFFFFF", "dark": "#11171C"},
        "widgetBorderColor": {"light": "#FFFFFF", "dark": "#11171C"},
        "fontColor": {"light": "#11171C", "dark": "#E8ECF0"},
        "selectionColor": {"light": "#2272B4", "dark": "#8ACAFF"},
        "visualizationColors": ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#D55E00", "#56B4E9", "#7B5EA7", "#A0A7AE"],
        "widgetHeaderAlignment": "LEFT",
        "widgetCornerRadius": 8}},
}

DISPLAY_NAME = "Genie Code Usage Patterns"
SQL_DIR = pathlib.Path(__file__).parent / "sql"


def render_sql(catalog, schema):
    """Returns [(file name, SQL)] for the view templates in sql/, in run order."""
    return [(t.name, string.Template(t.read_text()).substitute(catalog=catalog, schema=schema))
            for t in sorted(SQL_DIR.glob("*.sql"))]


def render_dashboard(catalog, schema):
    """Returns the dashboard dict with every dataset pinned to <catalog>.<schema> (queries use bare MV names)."""
    rendered = copy.deepcopy(dashboard)
    for ds in rendered["datasets"]:
        ds.update({"catalog": catalog, "schema": schema})
    return rendered


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalog", required=True, help="catalog that will hold the views")
    parser.add_argument("--schema", required=True, help="existing schema that will hold the views")
    parser.add_argument("--out", default="build", help="output directory")
    args = parser.parse_args()
    out = pathlib.Path(args.out)
    (out / "sql").mkdir(parents=True, exist_ok=True)
    for name, sql in render_sql(args.catalog, args.schema):
        (out / "sql" / name).write_text(sql)
    with open(out / "genie_code_usage_dashboard.json", "w") as fh:
        json.dump(render_dashboard(args.catalog, args.schema), fh, indent=2)
    print(f"Wrote {out}/sql/*.sql and {out}/genie_code_usage_dashboard.json for {args.catalog}.{args.schema}")


if __name__ == "__main__":
    main()
