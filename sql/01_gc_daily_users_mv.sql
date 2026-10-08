-- Daily Genie Code interaction events per workspace x user x client type.
CREATE OR REPLACE MATERIALIZED VIEW serverless_stable_12edvn_catalog.genie_code_usage.gc_daily_users
SCHEDULE CRON '0 0 2 * * ?' AT TIME ZONE 'UTC'
COMMENT 'Daily Genie Code events per workspace and user from system.access.assistant_events (last 90 days)'
AS
SELECT
  e.event_date,
  e.workspace_id,
  coalesce(w.workspace_name, e.workspace_id) AS workspace_name,
  e.initiated_by AS user_email,
  CASE
    WHEN e.user_agent LIKE 'Mozilla%' THEN 'Interactive (browser)'
    WHEN e.user_agent LIKE 'databricks-background-genie%' THEN 'Background agent'
    WHEN e.user_agent = 'node' THEN 'Genie Code service'
    ELSE 'Other client'
  END AS client_type,
  count(*) AS events
FROM system.access.assistant_events e
LEFT JOIN system.access.workspaces_latest w ON e.workspace_id = w.workspace_id
WHERE e.event_date >= date_sub(current_date(), 90)
GROUP BY ALL
