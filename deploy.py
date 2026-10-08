"""Deploys the Genie Code usage views and dashboard into an existing catalog/schema.

    python3 deploy.py --profile <profile> --warehouse-id <id> --catalog <catalog> --schema <schema>
                      [--dashboard-id <id>] [--parent-path <folder>] [--skip-views]

Steps:
  1. Checks that <catalog>.<schema> already exists (it is never created).
  2. Renders the SQL and dashboard JSON into build/ via build_dashboard.py.
  3. Creates the four materialized views in dependency order (skipped with --skip-views).
  4. Creates the dashboard, or updates it when --dashboard-id is given, then publishes it.

Requires the Databricks CLI, authenticated for <profile>.
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).parent
BUILD = ROOT / "build"
DISPLAY_NAME = "Genie Code Usage Patterns"


def cli(*args, profile, parse=True):
    """Runs a databricks CLI command and returns its parsed JSON output; exits on failure."""
    cmd = ["databricks", *args, "--profile", profile] + (["-o", "json"] if parse else [])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"Command failed: {' '.join(cmd[:4])} ...\n{proc.stderr.strip()}")
    return json.loads(proc.stdout) if parse and proc.stdout.strip() else proc.stdout


def run_statement(sql, warehouse_id, profile):
    """Runs one SQL statement on the warehouse, polling until it finishes; exits on failure."""
    body = json.dumps({"warehouse_id": warehouse_id, "statement": sql, "wait_timeout": "50s"})
    resp = cli("api", "post", "/api/2.0/sql/statements", "--json", body, profile=profile)
    while resp["status"]["state"] in ("PENDING", "RUNNING"):
        time.sleep(10)
        resp = cli("api", "get", f"/api/2.0/sql/statements/{resp['statement_id']}", profile=profile)
    if resp["status"]["state"] != "SUCCEEDED":
        error = resp["status"].get("error", {}).get("message", resp["status"]["state"])
        sys.exit(f"SQL failed:\n{error.strip()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", required=True, help="Databricks CLI profile for the target workspace")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse for view creation and the dashboard")
    parser.add_argument("--catalog", required=True, help="existing catalog for the views")
    parser.add_argument("--schema", required=True, help="existing schema for the views (not created)")
    parser.add_argument("--dashboard-id", help="update this dashboard instead of creating a new one")
    parser.add_argument("--parent-path", help="workspace folder for a new dashboard (default: /Workspace/Users/<you>/GenieCodeUsage)")
    parser.add_argument("--skip-views", action="store_true", help="only deploy the dashboard; leave the views as they are")
    args = parser.parse_args()
    p = args.profile
    target = f"{args.catalog}.{args.schema}"

    print(f"[1/4] Checking that schema {target} exists")
    proc = subprocess.run(["databricks", "schemas", "get", target, "--profile", p], capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"Schema {target} is not available: {proc.stderr.strip()}\n"
                 "Create it first, or pass an existing --catalog/--schema. This script never creates schemas.")

    print("[2/4] Rendering SQL and dashboard JSON into build/")
    subprocess.run([sys.executable, str(ROOT / "build_dashboard.py"), "--catalog", args.catalog,
                    "--schema", args.schema, "--out", str(BUILD)], check=True)

    if args.skip_views:
        print("[3/4] Skipping view creation (--skip-views)")
    else:
        for sql_file in sorted((BUILD / "sql").glob("*.sql")):
            print(f"[3/4] Creating view from {sql_file.name} (02 scans 90 days of audit logs and takes a few minutes)")
            run_statement(sql_file.read_text(), args.warehouse_id, p)

    dashboard_json = (BUILD / "genie_code_usage_dashboard.json").read_text()
    dataset_flags = ["--dataset-catalog", args.catalog, "--dataset-schema", args.schema,
                     "--serialized-dashboard", dashboard_json]
    if args.dashboard_id:
        print(f"[4/4] Updating dashboard {args.dashboard_id}")
        cli("lakeview", "update", args.dashboard_id, *dataset_flags, profile=p)
        dashboard_id = args.dashboard_id
    else:
        parent = args.parent_path or f"/Workspace/Users/{cli('current-user', 'me', profile=p)['userName']}/GenieCodeUsage"
        print(f"[4/4] Creating dashboard in {parent}")
        cli("workspace", "mkdirs", parent, profile=p, parse=False)
        created = cli("lakeview", "create", "--display-name", DISPLAY_NAME, "--warehouse-id", args.warehouse_id,
                      *dataset_flags, "--json", json.dumps({"parent_path": parent}), profile=p)
        dashboard_id = created["dashboard_id"]
    cli("lakeview", "publish", dashboard_id, "--warehouse-id", args.warehouse_id, profile=p)

    host = cli("auth", "describe", profile=p)["details"]["host"].rstrip("/")
    workspace_id = cli("metastores", "current", profile=p).get("workspace_id")
    suffix = f"?o={workspace_id}" if workspace_id else ""
    print(f"\nDone. Dashboard ID: {dashboard_id}  (pass --dashboard-id {dashboard_id} on later runs to update it)")
    print(f"Published: {host}/dashboardsv3/{dashboard_id}/published{suffix}")


if __name__ == "__main__":
    main()
