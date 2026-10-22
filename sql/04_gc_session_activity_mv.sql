-- Genie Code agent activity at session x category x activity grain (signal actions only),
-- enriched with session attributes. Use COUNT(DISTINCT session_id) for session counts.
-- errors excludes the agent's expected background probes. category_minutes (distinct minutes with any
-- action in the category) is set only on each session x category's first activity row, so SUM() over it
-- gives correct per-category minutes; active_minutes is per activity and overlaps across activities.
CREATE OR REPLACE MATERIALIZED VIEW ${catalog}.${schema}.gc_session_activity
-- Refreshes after gc_agent_activity (02:00 UTC) and gc_sessions (04:00 UTC), which it reads.
SCHEDULE CRON '0 0 6 * * ?' AT TIME ZONE 'UTC'
COMMENT 'Genie Code agent activity by session, category and activity (all retained history)'
AS
WITH cat_minutes AS (
  SELECT session_id, category, count(DISTINCT event_minute) AS category_minutes
  FROM ${catalog}.${schema}.gc_agent_activity
  WHERE is_signal
  GROUP BY ALL
),
act AS (
SELECT
  s.session_date AS event_date,
  s.workspace_id,
  s.workspace_name,
  s.user_email,
  s.session_id,
  s.user_type,
  s.surface,
  s.primary_category,
  a.category,
  a.activity,
  count(DISTINCT a.event_minute) AS active_minutes,
  sum(a.action_count) AS actions,
  sum(CASE WHEN coalesce(a.error_cause, '') <> 'Expected background probe' THEN a.error_count ELSE 0 END) AS errors
FROM ${catalog}.${schema}.gc_agent_activity a
JOIN ${catalog}.${schema}.gc_sessions s
  ON a.session_id = s.session_id
WHERE a.is_signal
GROUP BY ALL
)
SELECT act.*,
       CASE WHEN row_number() OVER (PARTITION BY act.session_id, act.category ORDER BY act.activity) = 1
            THEN m.category_minutes ELSE 0 END AS category_minutes
FROM act
JOIN cat_minutes m USING (session_id, category)
