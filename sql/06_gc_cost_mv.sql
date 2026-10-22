-- Genie Code DBUs (system.billing.usage, billing_origin_product GENIE, surface GENIE_CODE) by day x
-- workspace x user. Billing has no session id, so each workspace's user-day DBUs are split across that
-- user's agent sessions in the same workspace on the same day, in proportion to their active minutes.
-- When the user had no session in that workspace that day, the DBUs are split across their sessions in any
-- workspace that day (the row keeps the billing workspace). User-days with DBUs but no agent session at all
-- (chat answers only) keep one row with category 'Chat only (no agent actions)'. is_free marks the
-- GENIE_FREE_USAGE SKU.
CREATE OR REPLACE MATERIALIZED VIEW ${catalog}.${schema}.gc_cost
-- Refreshes after gc_sessions (04:00 UTC), which it reads.
SCHEDULE CRON '0 0 6 * * ?' AT TIME ZONE 'UTC'
COMMENT 'Genie Code DBUs by day, user and session category (all retained history)'
AS
WITH bill AS (
  SELECT
    u.usage_date,
    u.workspace_id,
    u.identity_metadata.run_as AS user_email,
    u.sku_name = 'GENIE_FREE_USAGE' AS is_free,
    sum(u.usage_quantity) AS dbus
  FROM system.billing.usage u
  WHERE u.billing_origin_product = 'GENIE'
    AND u.usage_metadata.genie.surface = 'GENIE_CODE'
  GROUP BY ALL
),
sess AS (
  SELECT user_email, session_date, workspace_id, session_id, primary_category, user_type,
         active_minutes / sum(active_minutes) OVER (PARTITION BY user_email, session_date, workspace_id) AS ws_share,
         active_minutes / sum(active_minutes) OVER (PARTITION BY user_email, session_date) AS day_share
  FROM ${catalog}.${schema}.gc_sessions
),
ws_match AS (
  SELECT b.*, s.session_id, s.primary_category, s.user_type, s.ws_share AS share
  FROM bill b
  JOIN sess s ON b.user_email = s.user_email AND b.usage_date = s.session_date AND b.workspace_id = s.workspace_id
),
allocated AS (
  SELECT * FROM ws_match
  UNION ALL
  SELECT b.*, s.session_id, s.primary_category, s.user_type, s.day_share AS share
  FROM bill b
  LEFT ANTI JOIN sess w ON b.user_email = w.user_email AND b.usage_date = w.session_date AND b.workspace_id = w.workspace_id
  LEFT JOIN sess s ON b.user_email = s.user_email AND b.usage_date = s.session_date
)
SELECT
  b.usage_date,
  b.workspace_id,
  coalesce(w.workspace_name, b.workspace_id) AS workspace_name,
  b.user_email,
  coalesce(b.user_type,
           CASE WHEN b.user_email IS NULL OR b.user_email NOT LIKE '%@%' THEN 'Automated / eval' ELSE 'Human' END) AS user_type,
  b.session_id,
  coalesce(b.primary_category, 'Chat only (no agent actions)') AS cost_category,
  b.is_free,
  b.dbus * coalesce(b.share, 1) AS dbus
FROM allocated b
LEFT JOIN system.access.workspaces_latest w ON b.workspace_id = w.workspace_id
