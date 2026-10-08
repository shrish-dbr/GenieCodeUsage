-- Genie Code agent activity at session x category x activity grain (signal actions only),
-- enriched with session attributes. Use COUNT(DISTINCT session_id) for session counts.
CREATE OR REPLACE MATERIALIZED VIEW ${catalog}.${schema}.gc_session_activity
-- Refreshes after gc_agent_activity (02:00 UTC) and gc_sessions (04:00 UTC), which it reads.
SCHEDULE CRON '0 0 6 * * ?' AT TIME ZONE 'UTC'
COMMENT 'Genie Code agent activity by session, category and activity (last 90 days)'
AS
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
  sum(a.error_count) AS errors
FROM ${catalog}.${schema}.gc_agent_activity a
JOIN ${catalog}.${schema}.gc_sessions s
  ON a.session_id = s.session_id
WHERE a.is_signal
GROUP BY ALL
