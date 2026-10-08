"""Generates genie_code_usage_dashboard.json (AI/BI dashboard) over the genie_code_usage MVs."""
import json

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


CATALOG, SCHEMA = "serverless_stable_12edvn_catalog", "genie_code_usage"


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
    {"name": "ds_sessions", "displayName": "Genie Code agent sessions",
     "queryLines": ql("""
WITH uc AS (SELECT user_email, primary_category, count(*) AS n FROM gc_sessions
            WHERE primary_category <> 'Q&A / Read-only' GROUP BY ALL),
ut AS (SELECT user_email, max_by(primary_category, n) AS user_top_category FROM uc GROUP BY user_email),
uw AS (SELECT user_email, workspace_name, count(*) AS n FROM gc_sessions
       WHERE workspace_name <> 'Account-level' GROUP BY ALL),
up AS (SELECT user_email, max_by(workspace_name, n) AS user_primary_workspace FROM uw GROUP BY user_email)
SELECT s.session_id, s.session_date, s.session_start, s.session_end, s.workspace_name, s.user_email, s.user_type, s.surface,
       s.primary_category, s.categories_used, coalesce(array_join(s.categories, ', '), '') AS categories_list,
       s.active_minutes, round(s.duration_minutes, 1) AS duration_minutes,
       s.total_actions, s.signal_actions, s.cells_run, s.notebooks_created, s.error_count,
       coalesce(ut.user_top_category, 'Q&A / Read-only') AS user_top_category,
       coalesce(up.user_primary_workspace, 'Account-level') AS user_primary_workspace,
       CASE WHEN s.primary_category <> 'Q&A / Read-only' THEN 1 ELSE 0 END AS is_action_session,
       date_format(s.session_start, 'E') AS day_of_week,
       hour(s.session_start) AS hour_of_day,
       CASE WHEN s.active_minutes <= 1 THEN '1 min' WHEN s.active_minutes <= 5 THEN '2-5 min'
            WHEN s.active_minutes <= 15 THEN '6-15 min' WHEN s.active_minutes <= 60 THEN '16-60 min'
            ELSE '60+ min' END AS session_length,
       CASE WHEN s.categories_used = 0 THEN '0 (read-only)' WHEN s.categories_used = 1 THEN '1 category'
            WHEN s.categories_used = 2 THEN '2 categories' ELSE '3+ categories' END AS categories_bucket
FROM gc_sessions s
LEFT JOIN ut USING (user_email)
LEFT JOIN up USING (user_email)
ORDER BY s.session_start DESC""")},
    {"name": "ds_activity", "displayName": "Genie Code agent activity",
     "queryLines": ql("""
SELECT event_date, workspace_name, user_email, session_id, user_type, surface, primary_category,
       category, activity, active_minutes, actions, errors
FROM gc_session_activity""")},
]


def f(name, expr):
    return {"name": name, "expression": expr}


def q(ds, fields, disagg=False, filters=None):
    query = {"datasetName": ds, "fields": fields, "disaggregated": disagg}
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


# ---------------- Parameterised datasets (pre-aggregated flat tables / top-N bars) ----------------
# These aggregate inside SQL, so the Filters page binds to them through parameters
# instead of field filters (a field filter would only apply after aggregation).
NO_DATE = {"min": {"value": "2000-01-01"}, "max": {"value": "2099-12-31"}}


def multi_param(keyword, display, default=()):
    return {"keyword": keyword, "displayName": display, "dataType": "STRING", "complexType": "MULTI",
            "defaultSelection": {"values": {"dataType": "STRING", "values": [{"value": v} for v in default]}}}


DATE_PARAM = {"keyword": "date_range", "displayName": "Date", "dataType": "DATE", "complexType": "RANGE",
              "defaultSelection": {"range": {"dataType": "DATE", **NO_DATE}}}
P_WS, P_USER = multi_param("p_workspace", "Workspace"), multi_param("p_user", "User")
P_TYPE = multi_param("p_user_type", "User type", ["Human"])
P_SURFACE, P_CAT = multi_param("p_surface", "Surface"), multi_param("p_category", "Primary category")
P_CLIENT, P_UD_USER = multi_param("p_client", "Client type"), multi_param("p_ud_user", "User (detail page)")


def in_param(keyword, col):
    return f"(size(:{keyword}) = 0 OR array_contains(:{keyword}, {col}))"


def session_where(date_col, extra=()):
    conds = [f"{date_col} BETWEEN :date_range.min AND :date_range.max",
             in_param("p_workspace", "workspace_name"), in_param("p_user", "user_email"),
             in_param("p_user_type", "user_type"), in_param("p_surface", "surface"),
             in_param("p_category", "primary_category"), *extra]
    return "WHERE " + "\n  AND ".join(conds)


SESSION_PARAMS = [DATE_PARAM, P_WS, P_USER, P_TYPE, P_SURFACE, P_CAT]

ACTIVITY_TABLE_SQL = """
SELECT category, activity,
       count(DISTINCT session_id) AS sessions,
       count(DISTINCT user_email) AS users,
       count(DISTINCT workspace_name) AS workspaces,
       sum(actions) AS agent_actions,
       sum(errors) AS errors,
       try_divide(sum(errors), sum(actions)) AS error_rate
FROM gc_session_activity
{where}
GROUP BY category, activity
ORDER BY sessions DESC"""

USER_DIRECTORY_SQL = """
WITH uc AS (SELECT user_email, primary_category, count(*) AS n FROM gc_sessions
            WHERE primary_category <> 'Q&A / Read-only' GROUP BY ALL),
ut AS (SELECT user_email, max_by(primary_category, n) AS top_category FROM uc GROUP BY user_email),
uw AS (SELECT user_email, workspace_name, count(*) AS n FROM gc_sessions
       WHERE workspace_name <> 'Account-level' GROUP BY ALL),
up AS (SELECT user_email, max_by(workspace_name, n) AS primary_workspace FROM uw GROUP BY user_email),
s AS (SELECT * FROM gc_sessions
{where})
SELECT s.user_email,
       coalesce(ut.top_category, 'Q&A / Read-only') AS top_category,
       coalesce(up.primary_workspace, 'Account-level') AS primary_workspace,
       count(*) AS sessions,
       avg(CASE WHEN s.primary_category <> 'Q&A / Read-only' THEN 1 ELSE 0 END) AS action_rate,
       count(DISTINCT s.session_date) AS active_days,
       min(s.session_date) AS first_seen,
       max(s.session_date) AS last_seen,
       sum(s.active_minutes) AS active_minutes,
       sum(s.cells_run) AS cells_run,
       sum(s.notebooks_created) AS notebooks_created,
       count(DISTINCT s.workspace_name) AS workspaces
FROM s
LEFT JOIN ut ON s.user_email = ut.user_email
LEFT JOIN up ON s.user_email = up.user_email
GROUP BY ALL
ORDER BY sessions DESC"""

TOP_WS_USERS_SQL = USERS_TYPED_SQL + """
SELECT workspace_name, count(DISTINCT user_email) AS users
FROM users_typed
WHERE event_date BETWEEN :date_range.min AND :date_range.max
  AND """ + in_param("p_workspace", "workspace_name") + """
  AND """ + in_param("p_user", "user_email") + """
  AND """ + in_param("p_user_type", "user_type") + """
  AND """ + in_param("p_client", "client_type") + """
GROUP BY workspace_name
ORDER BY users DESC
LIMIT 15"""

UD_WORKSPACES_SQL = """
WITH s AS (SELECT workspace_name, surface, session_id FROM gc_sessions
{where}),
top_ws AS (SELECT workspace_name FROM s GROUP BY workspace_name ORDER BY count(*) DESC LIMIT 10)
SELECT s.workspace_name, s.surface, count(*) AS sessions
FROM s JOIN top_ws USING (workspace_name)
GROUP BY ALL"""

UD_EXTRA = [in_param("p_ud_user", "user_email")]
datasets += [
    {"name": "ds_activity_table", "displayName": "Agent activities (flat)",
     "queryLines": ql(ACTIVITY_TABLE_SQL.format(where=session_where("event_date"))), "parameters": SESSION_PARAMS},
    {"name": "ds_user_directory", "displayName": "User directory (flat)",
     "queryLines": ql(USER_DIRECTORY_SQL.format(where=session_where("session_date"))), "parameters": SESSION_PARAMS},
    {"name": "ds_top_ws_users", "displayName": "Top workspaces by users",
     "queryLines": ql(TOP_WS_USERS_SQL), "parameters": [DATE_PARAM, P_WS, P_USER, P_TYPE, P_CLIENT]},
    {"name": "ds_ud_activity", "displayName": "User detail: activities",
     "queryLines": ql(ACTIVITY_TABLE_SQL.format(where=session_where("event_date", UD_EXTRA))),
     "parameters": SESSION_PARAMS + [P_UD_USER]},
    {"name": "ds_ud_workspaces", "displayName": "User detail: top workspaces",
     "queryLines": ql(UD_WORKSPACES_SQL.format(where=session_where("session_date", UD_EXTRA))),
     "parameters": SESSION_PARAMS + [P_UD_USER]},
]

PCT_FMT = {"type": "number-percent", "decimalPlaces": {"type": "max", "places": 1}}
LEGEND_BOTTOM = {"position": "bottom"}


def cat_color(field="primary_category", display="Primary category", legend=True):
    enc = {"fieldName": field, "scale": CAT_SCALE, "displayName": display}
    enc["legend"] = LEGEND_BOTTOM if legend else {"hide": True}
    return enc


def flat_table(name, title, desc, ds, columns, p):
    """columns: list of (field, display, format-or-None)."""
    cols = []
    for field, display, fmt in columns:
        c = {"fieldName": field, "displayName": display}
        if fmt:
            c["format"] = fmt
        cols.append(c)
    return {"widget": {"name": name,
                       "queries": q(ds, [f(c[0], f"`{c[0]}`") for c in columns], disagg=True),
                       "spec": {"version": 2, "widgetType": "table", "encodings": {"columns": cols},
                                "frame": frame(title, desc)}},
            "position": p}


def hbar(name, title, desc, ds, cat_field, val_field, val_display, p, color=None, label=True):
    enc = {"x": {"fieldName": val_field["name"], "scale": {"type": "quantitative"}, "displayName": val_display},
           "y": {"fieldName": cat_field, "scale": {"type": "categorical", "sort": {"by": "x-reversed"}},
                 "axis": {"hideTitle": True}}}
    fields = [f(cat_field, f"`{cat_field}`"), val_field]
    if color:
        enc["color"] = color
        if color["fieldName"] != cat_field:
            fields.append(f(color["fieldName"], f"`{color['fieldName']}`"))
    if label:
        enc["label"] = {"show": True}
    return {"widget": {"name": name, "queries": q(ds, fields),
                       "spec": {"version": 3, "widgetType": "bar", "encodings": enc, "frame": frame(title, desc)}},
            "position": p}


SESSIONS = f("countdistinct(session_id)", "COUNT(DISTINCT `session_id`)")
USERS = f("countdistinct(user_email)", "COUNT(DISTINCT `user_email`)")


def pie(name, title, ds, p):
    return {"widget": {"name": name, "queries": q(ds, [f("primary_category", "`primary_category`"), SESSIONS]),
                       "spec": {"version": 3, "widgetType": "pie",
                                "encodings": {
                                    "angle": {"fieldName": SESSIONS["name"], "scale": {"type": "quantitative"}, "displayName": "Sessions"},
                                    "color": {"fieldName": "primary_category", "scale": CAT_SCALE, "displayName": "Primary category"},
                                    "label": {"show": True}},
                                "frame": frame(title)}},
            "position": p}


def weekly_cat_bar(name, title, desc, p):
    return {"widget": {"name": name,
                       "queries": q("ds_sessions", [WEEK("session_date"), f("primary_category", "`primary_category`"), SESSIONS]),
                       "spec": {"version": 3, "widgetType": "bar",
                                "encodings": {
                                    "x": {"fieldName": "weekly(session_date)", "scale": {"type": "temporal"}, "displayName": "Week"},
                                    "y": {"fieldName": SESSIONS["name"], "scale": {"type": "quantitative"}, "displayName": "Sessions"},
                                    "color": cat_color()},
                                "frame": frame(title, desc)}},
            "position": p}


ACTIVITY_COLUMNS = [("category", "Category", None), ("activity", "Activity", None),
                    ("sessions", "Sessions", None), ("users", "Users", None), ("workspaces", "Workspaces", None),
                    ("agent_actions", "Agent actions", None), ("errors", "Errors", None),
                    ("error_rate", "Error rate", PCT_FMT)]

# ---------------- Overview page ----------------
overview = [
    text("ov_header", [
        "# Genie Code Usage Patterns\n", "\n",
        "How people use **Genie Code** (formerly Databricks Assistant) across workspaces: who is using it, "
        "and what the agent is doing on their behalf: writing code, exploring the catalog, running SQL, "
        "building dashboards, data engineering, ML, or answering questions. Categories come from the actions "
        "the Genie Code agent performs (audit events tagged `databricks-background-genie`). "
        "Defaults to **human** usage; switch *User type* on the Filters page to include automated / eval traffic."],
        pos(0, 0, 12, 3)),
    counter("kpi_users", "Active Genie Code users", "Distinct users with Genie Code events (all clients)",
            "ds_users", USERS, "event_date", "Users", COUNT_FMT, pos(0, 3, 3, 3)),
    counter("kpi_workspaces", "Active workspaces", "Workspaces with Genie Code usage",
            "ds_users", f("countdistinct(workspace_name)", "COUNT(DISTINCT `workspace_name`)"), "event_date",
            "Workspaces", COUNT_FMT, pos(3, 3, 3, 3)),
    counter("kpi_sessions", "Agent sessions", "Genie Code agent sessions (sid)",
            "ds_sessions", SESSIONS, "session_date", "Sessions", COUNT_FMT, pos(6, 3, 3, 3)),
    counter("kpi_action_rate", "Sessions that took action", "Share of sessions where the agent changed or ran something (vs read-only Q&A)",
            "ds_sessions", f("avg(is_action_session)", "AVG(`is_action_session`)"), "session_date",
            "Action rate", PCT_FMT, pos(9, 3, 3, 3)),
    {"widget": {"name": "wau_by_client",
                "queries": q("ds_users", [WEEK("event_date"), f("client_type", "`client_type`"), USERS]),
                "spec": {"version": 3, "widgetType": "line",
                         "encodings": {
                             "x": {"fieldName": "weekly(event_date)", "scale": {"type": "temporal"}, "displayName": "Week"},
                             "y": {"fieldName": USERS["name"], "scale": {"type": "quantitative"}, "displayName": "Weekly active users"},
                             "color": {"fieldName": "client_type", "scale": {"type": "categorical"}, "displayName": "Client",
                                       "legend": LEGEND_BOTTOM}},
                         "frame": frame("Weekly active users by client", "From system.access.assistant_events")}},
     "position": pos(0, 13, 6, 7)},
    weekly_cat_bar("weekly_sessions_by_cat", "Weekly agent sessions by primary category",
                   "Primary category = what the agent spent the most active minutes on", pos(0, 6, 12, 7)),
    pie("pie_primary_cat", "Session mix by primary category", "ds_sessions", pos(0, 20, 6, 8)),
    hbar("sessions_touching_cat", "Sessions using each category", "A session can span several categories",
         "ds_activity", "category", SESSIONS, "Sessions", pos(6, 13, 6, 7),
         color=cat_color("category", "Category", legend=False)),
    hbar("users_per_cat", "Users by category", "Distinct users whose agent sessions touched each category",
         "ds_activity", "category", USERS, "Users", pos(6, 20, 6, 8),
         color=cat_color("category", "Category", legend=False)),
]

# ---------------- Usage patterns page ----------------
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
patterns = [
    text("pt_header", ["## Usage patterns\n", "\n",
                       "When and where Genie Code is used, how deep sessions go, and the specific agent activities behind each category. Times are UTC."],
         pos(0, 0, 12, 2)),
    {"widget": {"name": "heat_dow_hour",
                "queries": q("ds_sessions", [f("hour_of_day", "`hour_of_day`"), f("day_of_week", "`day_of_week`"), SESSIONS]),
                "spec": {"version": 3, "widgetType": "heatmap",
                         "encodings": {
                             "x": {"fieldName": "hour_of_day", "scale": {"type": "categorical"}, "displayName": "Hour (UTC)"},
                             "y": {"fieldName": "day_of_week", "scale": {"type": "categorical", "sort": {"by": "custom-order", "orderedValues": DOW}}, "axis": {"hideTitle": True}},
                             "color": {"fieldName": SESSIONS["name"], "displayName": "Sessions",
                                       "scale": {"type": "quantitative", "colorRamp": {"mode": "custom-sequential", "colors": {"start": "#E8F1F8", "end": "#0072B2"}}}}},
                         "frame": frame("When sessions happen (day x hour, UTC)")}},
     "position": pos(0, 2, 6, 7)},
    {"widget": {"name": "cat_by_surface",
                "queries": q("ds_sessions", [f("surface", "`surface`"), f("primary_category", "`primary_category`"), SESSIONS]),
                "spec": {"version": 3, "widgetType": "bar",
                         "encodings": {
                             "x": {"fieldName": SESSIONS["name"], "scale": {"type": "quantitative"}, "displayName": "Share of sessions"},
                             "y": {"fieldName": "surface", "scale": {"type": "categorical"}, "axis": {"hideTitle": True}},
                             "color": cat_color()},
                         "mark": {"layout": "stack-100"},
                         "frame": frame("Category mix by surface", "Where Genie Code was invoked: side panel, embedded, document, visualization")}},
     "position": pos(0, 9, 12, 6)},
    {"widget": {"name": "length_by_cat",
                "queries": q("ds_sessions", [f("session_length", "`session_length`"), f("primary_category", "`primary_category`"), SESSIONS]),
                "spec": {"version": 3, "widgetType": "bar",
                         "encodings": {
                             "x": {"fieldName": "session_length", "scale": {"type": "categorical", "sort": {"by": "custom-order", "orderedValues": ["1 min", "2-5 min", "6-15 min", "16-60 min", "60+ min"]}}, "displayName": "Active minutes in session"},
                             "y": {"fieldName": SESSIONS["name"], "scale": {"type": "quantitative"}, "displayName": "Sessions"},
                             "color": cat_color()},
                         "frame": frame("Session depth (active minutes)")}},
     "position": pos(0, 15, 12, 7)},
    {"widget": {"name": "cats_per_session",
                "queries": q("ds_sessions", [f("categories_bucket", "`categories_bucket`"), SESSIONS]),
                "spec": {"version": 3, "widgetType": "bar",
                         "encodings": {
                             "x": {"fieldName": "categories_bucket", "scale": {"type": "categorical", "sort": {"by": "custom-order", "orderedValues": ["0 (read-only)", "1 category", "2 categories", "3+ categories"]}}, "displayName": "Categories used in session"},
                             "y": {"fieldName": SESSIONS["name"], "scale": {"type": "quantitative"}, "displayName": "Sessions"},
                             "label": {"show": True}},
                         "frame": frame("Multi-category sessions", "E.g. explore catalog, then write code, then build a dashboard")}},
     "position": pos(6, 2, 6, 7)},
    flat_table("top_activities", "Agent activities by category",
               "What Genie Code actually did: edits, cell runs, catalog lookups, dashboard builds, MCP tool calls. One row per activity; sort by any column.",
               "ds_activity_table", ACTIVITY_COLUMNS, pos(0, 22, 12, 10)),
]

# ---------------- Workspaces & users page ----------------
people = [
    text("wu_header", ["## Workspaces & users\n", "\n",
                       "Which workspaces and people use Genie Code most, and for what. 'Account-level' = sessions with no workspace-scoped actions."],
         pos(0, 0, 12, 2)),
    {"widget": {"name": "ws_by_cat",
                "queries": q("ds_sessions", [f("workspace_name", "`workspace_name`"), f("primary_category", "`primary_category`"), SESSIONS]),
                "spec": {"version": 3, "widgetType": "pivot",
                         "encodings": {
                             "rows": [{"fieldName": "workspace_name", "displayName": "Workspace",
                                       "scale": {"type": "categorical", "sort": {"by": "cell-reversed", "field": {"index": 0}}}}],
                             "columns": [{"fieldName": "primary_category", "displayName": "Primary category", "total": {"show": True}}],
                             "cell": {"type": "multi-cell", "fields": [
                                 {"fieldName": SESSIONS["name"], "displayName": "Sessions", "cellType": "color-scale"}]}},
                         "frame": frame("Sessions by workspace and primary category")}},
     "position": pos(0, 2, 12, 9)},
    flat_table("user_directory", "User directory",
               "One row per user. Top category and primary workspace cover the full 90 days; other columns follow the filters. Use the User Detail page to drill into one user.",
               "ds_user_directory",
               [("user_email", "User", None), ("top_category", "Top category", None),
                ("primary_workspace", "Primary workspace", None), ("sessions", "Sessions", None),
                ("action_rate", "Action rate", PCT_FMT), ("active_days", "Active days", None),
                ("first_seen", "First seen", None), ("last_seen", "Last seen", None),
                ("active_minutes", "Active min", None), ("cells_run", "Cells run", None),
                ("notebooks_created", "Notebooks created", None), ("workspaces", "Workspaces", None)],
               pos(0, 11, 12, 10)),
    hbar("ws_users_bar", "Top 15 workspaces by active users", "All Genie Code clients",
         "ds_top_ws_users", "workspace_name", f("sum(users)", "SUM(`users`)"), "Users", pos(0, 21, 12, 8)),
]

# ---------------- User detail page ----------------
user_detail = [
    text("ud_header", ["## User detail\n", "\n",
                       "Pick one or more users (top right) to see their Genie Code activity: volume, what they use it for, where, "
                       "and a log of every agent session. With no user selected, the page shows everyone."],
         pos(0, 0, 8, 2)),
    None,  # page-level user filter, filled in below once gfilter exists
    counter("ud_kpi_sessions", "Agent sessions", None, "ds_sessions", SESSIONS, "session_date", "Sessions", COUNT_FMT, pos(0, 2, 3, 3)),
    counter("ud_kpi_action", "Sessions that took action", None, "ds_sessions",
            f("avg(is_action_session)", "AVG(`is_action_session`)"), "session_date", "Action rate", PCT_FMT, pos(3, 2, 3, 3)),
    counter("ud_kpi_minutes", "Active agent minutes", None, "ds_sessions",
            f("sum(active_minutes)", "SUM(`active_minutes`)"), "session_date", "Minutes", COUNT_FMT, pos(6, 2, 3, 3)),
    counter("ud_kpi_days", "Active days", "Days with any Genie Code event", "ds_users",
            f("countdistinct(event_date)", "COUNT(DISTINCT `event_date`)"), "event_date", "Days", None, pos(9, 2, 3, 3)),
    weekly_cat_bar("ud_weekly", "Weekly sessions by primary category", None, pos(0, 5, 12, 7)),
    pie("ud_cat_mix", "Category mix", "ds_sessions", pos(0, 12, 6, 8)),
    flat_table("ud_activities", "What the agent did", "One row per activity", "ds_ud_activity",
               [c for c in ACTIVITY_COLUMNS if c[0] != "workspaces"], pos(0, 20, 12, 9)),
    hbar("ud_workspaces", "Top workspaces and surfaces", "Top 10 workspaces by sessions",
         "ds_ud_workspaces", "workspace_name", f("sum(sessions)", "SUM(`sessions`)"), "Sessions", pos(6, 12, 6, 8),
         color={"fieldName": "surface", "scale": {"type": "categorical"}, "displayName": "Surface", "legend": LEGEND_BOTTOM},
         label=False),
    flat_table("ud_session_log", "Session log", "Every Genie Code agent session, newest first", "ds_sessions",
               [("session_start", "Started (UTC)", None), ("user_email", "User", None), ("workspace_name", "Workspace", None),
                ("surface", "Surface", None), ("primary_category", "Primary category", None),
                ("categories_list", "All categories", None), ("active_minutes", "Active min", None),
                ("duration_minutes", "Duration min", None), ("total_actions", "Agent actions", None),
                ("cells_run", "Cells run", None), ("notebooks_created", "Notebooks created", None),
                ("error_count", "Errors", None), ("session_id", "Session ID", None)],
               pos(0, 29, 12, 9)),
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


ALL_PARAM_DS = ["ds_activity_table", "ds_user_directory", "ds_top_ws_users", "ds_ud_activity", "ds_ud_workspaces"]
SESSION_PARAM_DS = ["ds_activity_table", "ds_user_directory", "ds_ud_activity", "ds_ud_workspaces"]
BASE3 = lambda col_users, col_sessions, col_activity: [("ds_users", col_users), ("ds_sessions", col_sessions), ("ds_activity", col_activity)]

filters = [
    gfilter("f_date", "Date", "filter-date-range-picker", BASE3("event_date", "session_date", "event_date"),
            [(d, "date_range") for d in ALL_PARAM_DS], pos(0, 0, 4, 2)),
    gfilter("f_workspace", "Workspace", "filter-multi-select", BASE3("workspace_name", "workspace_name", "workspace_name"),
            [(d, "p_workspace") for d in ALL_PARAM_DS], pos(0, 2, 4, 2)),
    gfilter("f_user", "User", "filter-multi-select", BASE3("user_email", "user_email", "user_email"),
            [(d, "p_user") for d in ALL_PARAM_DS], pos(0, 4, 4, 2)),
    gfilter("f_user_type", "User type", "filter-multi-select", BASE3("user_type", "user_type", "user_type"),
            [(d, "p_user_type") for d in ALL_PARAM_DS], pos(0, 6, 4, 2), default=["Human"]),
    gfilter("f_surface", "Surface", "filter-multi-select", [("ds_sessions", "surface"), ("ds_activity", "surface")],
            [(d, "p_surface") for d in SESSION_PARAM_DS], pos(0, 8, 4, 2)),
    gfilter("f_category", "Primary category", "filter-multi-select",
            [("ds_sessions", "primary_category"), ("ds_activity", "primary_category")],
            [(d, "p_category") for d in SESSION_PARAM_DS], pos(0, 10, 4, 2)),
    gfilter("f_client", "Client type (users)", "filter-multi-select", [("ds_users", "client_type")],
            [("ds_top_ws_users", "p_client")], pos(0, 12, 4, 2)),
]
user_detail[1] = gfilter("ud_user", "User(s)", "filter-multi-select",
                         BASE3("user_email", "user_email", "user_email"),
                         [("ds_ud_activity", "p_ud_user"), ("ds_ud_workspaces", "p_ud_user")], pos(8, 0, 4, 2))


def page(name, display, layout, ptype="PAGE_TYPE_CANVAS"):
    return {"name": name, "displayName": display, "pageType": ptype, "layoutVersion": "GRID_V1", "layout": layout}


for ds in datasets:  # queries use bare MV names; pin them to the MV catalog/schema
    ds.update({"catalog": CATALOG, "schema": SCHEMA})

dashboard = {
    "datasets": datasets,
    "pages": [page("overview", "Overview", overview),
              page("patterns", "Usage Patterns", patterns),
              page("people", "Workspaces & Users", people),
              page("user_detail", "User Detail", user_detail),
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

with open("genie_code_usage_dashboard.json", "w") as fh:
    json.dump(dashboard, fh, indent=2)
print("ok")
