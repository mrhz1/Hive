import os, subprocess, sys
import cmlapi

APP_NAME = "CHSS"   # change to your Application's exact name
REPO = "/home/cdsw"

def head():
    return subprocess.check_output(["git", "-C", REPO, "rev-parse", "HEAD"]).decode().strip()

before = head()
subprocess.run(["git", "-C", REPO, "pull", "origin", "main"], check=True)
after = head()

if before == after:
    print("No new changes.")
    sys.exit(0)

client = cmlapi.default_client()
project_id = os.environ["CDSW_PROJECT_ID"]
for app in client.list_applications(project_id).applications:
    if app.name == APP_NAME:
        client.restart_application(project_id, app.id)
        print(f"Updated and restarted {app.name}")