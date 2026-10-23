-- Genie Code agent activity: audit events emitted by the Genie Code agent
-- (user agent 'databricks-background-genie ... group/<context> sid/<session>')
-- at minute x workspace x user x session x action grain, tagged with a usage category and, for failed
-- events, an error cause. An event is an error when its status is HTTP 400 or above, or a gRPC-style code
-- from 1 to 199: failed notebook cells are runCommand with status_code 1, failed git calls use 4, 12 or 13.
CREATE OR REPLACE MATERIALIZED VIEW ${catalog}.${schema}.gc_agent_activity
SCHEDULE CRON '0 0 2 * * ?' AT TIME ZONE 'UTC'
COMMENT 'Genie Code agent tool calls by minute/session/action with usage category (all retained history)'
AS
WITH src AS (
  SELECT
    a.event_date,
    a.event_time,
    a.workspace_id,
    a.user_identity.email AS user_email,
    regexp_extract(a.user_agent, 'group/([a-z-]+)', 1) AS agent_context,
    regexp_extract(a.user_agent, 'sid/([0-9a-f]+)', 1) AS session_id,
    a.service_name,
    a.action_name,
    a.request_params.commandLanguage AS command_language,
    a.request_params.assetType AS asset_type,
    a.request_params.json_rpc_method AS rpc_method,
    a.request_params.fully_qualified_name AS mcp_server,
    a.request_params.name_arg AS credential_name,
    a.response.status_code AS status_code,
    a.response.error_message AS error_message
  FROM system.access.audit a
  -- Fixed floor so the scan prunes partitions: Genie Code agent events don't exist before mid-2026.
  -- Constant (not current_date()) so it never drops history the system table still retains.
  WHERE a.event_date >= '2026-07-01'
    AND a.user_agent LIKE 'databricks-background-genie%'
    AND a.action_name <> 'submitCommand'
),
flagged AS (
  SELECT *, coalesce(status_code >= 400 OR status_code BETWEEN 1 AND 199, false) AS is_error
  FROM src
),
classified AS (
  SELECT *,
    CASE
      WHEN service_name = 'notebook' AND action_name = 'runCommand' AND command_language = 'sql' THEN 'Data Analysis (SQL)'
      WHEN service_name = 'databrickssql' THEN 'Data Analysis (SQL)'
      WHEN service_name = 'notebook' AND action_name = 'runCommand' THEN 'Code Development'
      WHEN service_name = 'notebook' AND action_name IN ('modifyNotebook','createNotebook','importNotebook','renameNotebook','createFolder','modifyDesignerFile') THEN 'Code Development'
      WHEN service_name = 'workspaceFiles' AND action_name = 'wsfsStreamingWrite' THEN 'Code Development'
      WHEN service_name = 'workspace' AND action_name IN ('fileCreate','createWorkspaceNode') THEN 'Code Development'
      WHEN service_name IN ('repos','gitCredentials') AND action_name <> 'listGitCredentials' THEN 'Code Development'
      WHEN service_name = 'apps' THEN 'Code Development'
      WHEN service_name IN ('dashboards','aibiGenie','pages','discover') THEN 'Dashboards & BI'
      WHEN service_name IN ('deltaPipelines','jobs','databaseInstances','postgres') THEN 'Data Engineering & Jobs'
      WHEN service_name = 'unityCatalog' AND action_name IN ('createPipeline','getPipeline') THEN 'Data Engineering & Jobs'
      WHEN service_name = 'unityCatalog' AND action_name IN ('getRegisteredModel','listModelVersions','getModelVersion') THEN 'ML & AI'
      WHEN service_name IN ('featureStore','agentFramework','mlflowExperiment','mlflowTrace','serverlessRealTimeInference','vectorSearch','agentEvaluation') THEN 'ML & AI'
      WHEN service_name = 'unityCatalog' AND action_name IN ('getTable','listTables','getSchema','getCatalog','listSchemas','listCatalogs','listVolumes','getVolume','listFunctions','getFunction','getTableById','listTableSummaries','listShares','getEffectivePermissions','updatePermissions','getEntityTagAssignment','getTagSecurableAssignments','getTagSubentityAssignments') THEN 'Data Discovery & Governance'
      WHEN service_name IN ('lineageTracking','request-for-access','filesystem') THEN 'Data Discovery & Governance'
      WHEN service_name = 'tagging' AND action_name = 'listTagAssignments' THEN 'Data Discovery & Governance'
      WHEN service_name = 'mcpService' AND rpc_method = 'tools/call' THEN 'External Tools (MCP)'
      ELSE NULL
    END AS category,
    CASE
      WHEN action_name = 'runCommand' THEN concat('Run ', coalesce(command_language, 'code'), ' cell')
      WHEN action_name IN ('modifyNotebook') AND asset_type = 'file' THEN 'Edit workspace file'
      WHEN action_name IN ('modifyNotebook') THEN 'Edit notebook'
      WHEN action_name IN ('createNotebook','importNotebook') THEN 'Create notebook'
      WHEN action_name = 'wsfsStreamingWrite' OR action_name IN ('fileCreate','createWorkspaceNode') THEN 'Write workspace file'
      WHEN service_name = 'mcpService' THEN concat('MCP: ', regexp_replace(coalesce(mcp_server, 'unknown'), '^system[.]ai[.]', ''))
      WHEN service_name = 'dashboards' AND action_name IN ('createDashboard','updateDashboard','publishDashboard') THEN 'Build / publish dashboard'
      WHEN service_name = 'dashboards' THEN 'Read / query dashboard'
      WHEN service_name = 'aibiGenie' THEN 'Genie space'
      WHEN service_name = 'lineageTracking' THEN 'Lineage & popularity lookup'
      WHEN service_name = 'unityCatalog' THEN concat('UC: ', action_name)
      ELSE concat(service_name, ': ', action_name)
    END AS activity,
    -- Order matters: the agent's routine existence checks (files, built-in connector credentials such as
    -- system_ai_agent_slack_mcp, system.ai connections, tags)
    -- fail by design and come first so they aren't mistaken for user-facing problems.
    CASE
      WHEN NOT is_error THEN NULL
      WHEN service_name = 'workspaceFiles' AND action_name = 'wsfsStreamingRead' AND status_code = 404 THEN 'Expected background probe'
      WHEN action_name = 'getUserMappedCredential' AND (status_code = 404 OR credential_name LIKE 'system_ai_agent%') THEN 'Expected background probe'
      WHEN action_name = 'getConnection' AND error_message LIKE '%system.ai.%' THEN 'Expected background probe'
      WHEN service_name = 'secrets' AND error_message LIKE '%databricks-package-management%' THEN 'Expected background probe'
      WHEN action_name = 'getEntityTagAssignment' AND status_code = 404 THEN 'Expected background probe'
      WHEN action_name = 'runCommand' AND error_message LIKE '%only support executing SQL cells%' THEN 'Wrong compute for cell language'
      WHEN action_name = 'runCommand' AND (error_message LIKE 'CommandCancelled%' OR error_message LIKE 'CommandSkipped%') THEN 'Cell cancelled or skipped'
      WHEN action_name = 'runCommand' AND command_language = 'sql' THEN 'SQL cell failed'
      WHEN action_name = 'runCommand' THEN 'Python / code cell failed'
      WHEN status_code = 429 OR error_message LIKE '%REQUEST_LIMIT_EXCEEDED%' THEN 'Rate limited'
      WHEN error_message RLIKE '(TABLE|SCHEMA|CATALOG|VOLUME|FUNCTION)_DOES_NOT_EXIST|TABLE_OR_VIEW_NOT_FOUND|(SCHEMA|CATALOG|VOLUME|ROUTINE)_NOT_FOUND'
        THEN 'Table / schema / catalog not found'
      WHEN action_name IN ('getUserMappedCredential','getForeignCredentials','batchGetMcpServiceUserMappedCredentials')
        OR (service_name = 'ucHttpConnection' AND status_code IN (401, 403)) THEN 'External connection auth failed'
      WHEN status_code = 403 OR error_message LIKE '%PERMISSION_DENIED%' THEN 'Permission denied'
      WHEN service_name IN ('ucHttpConnection','mcpService') OR action_name IN ('getMcpService','listMcpServices') THEN 'External tool / MCP call failed'
      WHEN action_name = 'attachNotebook' THEN 'Notebook compute busy'
      WHEN service_name IN ('dashboards','pages') THEN 'Dashboard request rejected'
      WHEN status_code = 409 OR error_message LIKE '%already exists%' THEN 'Write conflict'
      WHEN status_code >= 500 THEN 'Platform / service error'
      ELSE 'Other request error'
    END AS error_cause
  FROM flagged
)
SELECT
  event_date,
  date_trunc('MINUTE', event_time) AS event_minute,
  workspace_id,
  user_email,
  agent_context,
  session_id,
  service_name,
  action_name,
  coalesce(category, 'Context / Background') AS category,
  category IS NOT NULL AS is_signal,
  activity,
  error_cause,
  count(*) AS action_count,
  count_if(is_error) AS error_count
FROM classified
GROUP BY ALL
