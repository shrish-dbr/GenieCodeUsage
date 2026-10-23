-- Failed Genie Code agent events at session x category x activity x error cause grain, enriched with
-- session attributes so the dashboard filters apply. Includes the agent's expected background probes,
-- flagged is_actionable = false, so they can be shown but kept out of error rates and action items.
CREATE OR REPLACE MATERIALIZED VIEW ${catalog}.${schema}.gc_session_errors
-- Refreshes after gc_agent_activity (02:00 UTC) and gc_sessions (04:00 UTC), which it reads.
SCHEDULE CRON '0 0 6 * * ?' AT TIME ZONE 'UTC'
COMMENT 'Genie Code agent errors by session, activity and cause (all retained history)'
AS
SELECT
  s.session_date,
  s.workspace_id,
  s.workspace_name,
  s.user_email,
  s.session_id,
  s.user_type,
  s.surface,
  s.primary_category,
  a.category,
  a.activity,
  a.error_cause,
  a.error_cause <> 'Expected background probe' AS is_actionable,
  sum(a.error_count) AS errors
FROM ${catalog}.${schema}.gc_agent_activity a
JOIN ${catalog}.${schema}.gc_sessions s
  ON a.session_id = s.session_id
WHERE a.error_count > 0
GROUP BY ALL
