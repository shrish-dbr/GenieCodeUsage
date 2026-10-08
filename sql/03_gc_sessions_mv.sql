-- One row per Genie Code agent session (sid in the agent's user agent). A session can include
-- account-level events (workspace_id 0) and internal platform service principals, so the owner is
-- the human email with the most actions and the workspace is the non-zero workspace with the most actions.
-- Primary category = signal category with the most active minutes (minutes normalise high-volume
-- streaming notebook edits). Sessions with no signal actions are 'Q&A / Read-only'.
-- user_type flags sessions owned by non-human identities and user-days with > 50 sessions as automated / eval.
CREATE OR REPLACE MATERIALIZED VIEW ${catalog}.${schema}.gc_sessions
-- Refreshes after gc_agent_activity (02:00 UTC), which it reads.
SCHEDULE CRON '0 0 4 * * ?' AT TIME ZONE 'UTC'
COMMENT 'Genie Code agent sessions with owner, workspace and primary usage category (last 90 days)'
AS
WITH act AS (
  SELECT * FROM ${catalog}.${schema}.gc_agent_activity
  WHERE session_id <> ''
),
owner AS (
  SELECT session_id,
         coalesce(max_by(CASE WHEN user_email LIKE '%@%' THEN user_email END,
                         CASE WHEN user_email LIKE '%@%' THEN action_count END),
                  max_by(user_email, action_count)) AS user_email,
         coalesce(max_by(CASE WHEN workspace_id <> '0' THEN workspace_id END,
                         CASE WHEN workspace_id <> '0' THEN action_count END), '0') AS workspace_id
  FROM act
  GROUP BY session_id
),
cat_minutes AS (
  SELECT session_id, category,
         count(DISTINCT event_minute) AS active_minutes,
         sum(action_count) AS actions
  FROM act
  WHERE is_signal
  GROUP BY ALL
),
primary_cat AS (
  SELECT session_id,
         max_by(category, active_minutes * 1000000 + actions) AS primary_category,
         count(*) AS categories_used,
         array_sort(collect_list(category)) AS categories
  FROM cat_minutes
  GROUP BY session_id
),
sess AS (
  SELECT session_id,
         max_by(agent_context, action_count) AS agent_context,
         min(event_minute) AS session_start,
         max(event_minute) AS session_end,
         count(DISTINCT event_minute) AS active_minutes,
         sum(action_count) AS total_actions,
         sum(CASE WHEN is_signal THEN action_count ELSE 0 END) AS signal_actions,
         sum(error_count) AS error_count,
         sum(CASE WHEN action_name = 'runCommand' THEN action_count ELSE 0 END) AS cells_run,
         sum(CASE WHEN activity = 'Create notebook' THEN action_count ELSE 0 END) AS notebooks_created
  FROM act
  GROUP BY session_id
)
SELECT
  s.session_id,
  o.workspace_id,
  coalesce(w.workspace_name, CASE WHEN o.workspace_id = '0' THEN 'Account-level' ELSE o.workspace_id END) AS workspace_name,
  o.user_email,
  CASE s.agent_context
    WHEN 'assistant' THEN 'Genie Code panel'
    WHEN 'embed' THEN 'Embedded'
    WHEN 'document' THEN 'Document'
    WHEN 'viz' THEN 'Visualization'
    ELSE coalesce(s.agent_context, 'Unknown')
  END AS surface,
  CASE
    WHEN o.user_email NOT LIKE '%@%' THEN 'Automated / eval'
    WHEN count(*) OVER (PARTITION BY o.user_email, to_date(s.session_start)) > 50 THEN 'Automated / eval'
    ELSE 'Human'
  END AS user_type,
  to_date(s.session_start) AS session_date,
  s.session_start,
  s.session_end,
  (unix_timestamp(s.session_end) - unix_timestamp(s.session_start)) / 60.0 + 1 AS duration_minutes,
  s.active_minutes,
  s.total_actions,
  s.signal_actions,
  s.error_count,
  s.cells_run,
  s.notebooks_created,
  coalesce(p.primary_category, 'Q&A / Read-only') AS primary_category,
  coalesce(p.categories_used, 0) AS categories_used,
  p.categories
FROM sess s
JOIN owner o USING (session_id)
LEFT JOIN primary_cat p USING (session_id)
LEFT JOIN system.access.workspaces_latest w ON o.workspace_id = w.workspace_id
