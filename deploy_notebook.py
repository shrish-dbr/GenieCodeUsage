# Databricks notebook source
# MAGIC %md
# MAGIC # Deploy: Genie Code Usage Patterns
# MAGIC
# MAGIC Creates the four materialized views in an **existing** catalog/schema, then creates (or updates) and publishes the dashboard.
# MAGIC The schema is never created.
# MAGIC
# MAGIC **Requires:** this repo added to the workspace as a Git folder (this notebook imports `build_dashboard.py` and reads `sql/` next to it),
# MAGIC access to the `system.access` tables, and a SQL warehouse.
# MAGIC
# MAGIC 1. Fill in the widgets above.
# MAGIC 2. **Run all** to deploy everything, or run cells one at a time:
# MAGIC    - **Step 2** only prints the SQL. Copy it into the SQL editor if you'd rather create the views by hand.
# MAGIC    - **Step 3** creates the views. Set `create_views` to `no` to skip it, e.g. for a dashboard-only change.
# MAGIC    - **Step 4** creates or updates the dashboard. Put the ID printed by the first run into `dashboard_id` so later runs update the same dashboard instead of creating a copy.

# COMMAND ----------

dbutils.widgets.text("catalog", "", "1. Catalog (existing)")
dbutils.widgets.text("schema", "", "2. Schema (existing)")
dbutils.widgets.text("warehouse_id", "", "3. SQL warehouse ID")
dbutils.widgets.text("dashboard_id", "", "4. Dashboard ID (blank = create new)")
dbutils.widgets.text("parent_path", "", "5. Dashboard folder (blank = your home)")
dbutils.widgets.dropdown("create_views", "yes", ["yes", "no"], "6. Create views")

# COMMAND ----------

# MAGIC %md ## Step 1: Check inputs

# COMMAND ----------

import json
import os
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound

sys.path.insert(0, os.getcwd())  # Git folder root, so build_dashboard can be imported
import build_dashboard

catalog = dbutils.widgets.get("catalog").strip()
schema = dbutils.widgets.get("schema").strip()
warehouse_id = dbutils.widgets.get("warehouse_id").strip()
dashboard_id = dbutils.widgets.get("dashboard_id").strip()
parent_path = dbutils.widgets.get("parent_path").strip()
create_views = dbutils.widgets.get("create_views") == "yes"

missing = [name for name, value in [("catalog", catalog), ("schema", schema), ("warehouse_id", warehouse_id)] if not value]
if missing:
    raise ValueError(f"Fill in the widget(s): {', '.join(missing)}")

w = WorkspaceClient()
try:
    w.schemas.get(f"{catalog}.{schema}")
except NotFound:
    raise ValueError(f"Schema {catalog}.{schema} does not exist. Create it first or pick an existing one; "
                     "this notebook never creates schemas.")
w.warehouses.get(warehouse_id)
print(f"Target: {catalog}.{schema}, warehouse {warehouse_id}")

# COMMAND ----------

# MAGIC %md ## Step 2: Render the SQL
# MAGIC Prints each view's SQL with your catalog/schema filled in. Run them in order (`01` → `04`) if you are creating the views by hand.

# COMMAND ----------

statements = build_dashboard.render_sql(catalog, schema)
for name, sql in statements:
    print(f"-- ===== {name} =====\n{sql}\n")

# COMMAND ----------

# MAGIC %md ## Step 3: Create the views
# MAGIC Runs on the SQL warehouse, in dependency order. `02` scans 90 days of audit logs and takes a few minutes.

# COMMAND ----------

def run_statement(sql):
    """Runs one statement on the warehouse, polling until it finishes; raises on failure."""
    resp = w.statement_execution.execute_statement(statement=sql, warehouse_id=warehouse_id, wait_timeout="50s")
    while resp.status.state.value in ("PENDING", "RUNNING"):
        time.sleep(10)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state.value != "SUCCEEDED":
        message = resp.status.error.message if resp.status.error else resp.status.state.value
        raise RuntimeError(message)


if create_views:
    for name, sql in statements:
        print(f"Creating view from {name} ...")
        start = time.time()
        run_statement(sql)
        print(f"  done in {time.time() - start:.0f}s")
else:
    print("Skipped (create_views = no)")

# COMMAND ----------

# MAGIC %md ## Step 4: Create or update and publish the dashboard

# COMMAND ----------

serialized = json.dumps(build_dashboard.render_dashboard(catalog, schema))

if dashboard_id:
    w.api_client.do("PATCH", f"/api/2.0/lakeview/dashboards/{dashboard_id}",
                    body={"serialized_dashboard": serialized, "warehouse_id": warehouse_id})
    print(f"Updated dashboard {dashboard_id}")
else:
    parent = parent_path or f"/Workspace/Users/{w.current_user.me().user_name}/GenieCodeUsage"
    w.workspace.mkdirs(parent)
    created = w.api_client.do("POST", "/api/2.0/lakeview/dashboards",
                              body={"display_name": "Genie Code Usage Patterns", "warehouse_id": warehouse_id,
                                    "serialized_dashboard": serialized, "parent_path": parent})
    dashboard_id = created["dashboard_id"]
    print(f"Created dashboard {dashboard_id} in {parent}")
    print(f"Put {dashboard_id} in the dashboard_id widget so later runs update it instead of creating a copy.")

w.api_client.do("POST", f"/api/2.0/lakeview/dashboards/{dashboard_id}/published",
                body={"warehouse_id": warehouse_id, "embed_credentials": False})

url = f"{w.config.host.rstrip('/')}/dashboardsv3/{dashboard_id}/published?o={w.get_workspace_id()}"
displayHTML(f'Published: <a href="{url}" target="_blank">{url}</a>')
