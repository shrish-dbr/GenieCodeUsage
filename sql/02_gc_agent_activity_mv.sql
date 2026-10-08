-- Genie Code agent activity: audit events emitted by the Genie Code agent
-- (user agent 'databricks-background-genie ... group/<context> sid/<session>')
-- at minute x workspace x user x session x action grain, tagged with a usage category.
CREATE OR REPLACE MATERIALIZED VIEW serverless_stable_12edvn_catalog.genie_code_usage.gc_agent_activity
SCHEDULE CRON '0 0 2 * * ?' AT TIME ZONE 'UTC'
COMMENT 'Genie Code agent tool calls by minute/session/action with usage category (last 90 days)'
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
    a.response.status_code AS status_code
  FROM system.access.audit a
  WHERE a.event_date >= date_sub(current_date(), 90)
    AND a.user_agent LIKE 'databricks-background-genie%'
    AND a.action_name <> 'submitCommand'
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
    END AS activity
  FROM src
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
  count(*) AS action_count,
  count_if(status_code >= 400) AS error_count
FROM classified
GROUP BY ALL
