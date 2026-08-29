"""
Automated Render Deployment Script via Render REST API
"""

import os
import sys
import httpx

RENDER_API_BASE = "https://api.render.com/v1"
REPO_URL = "https://github.com/JorgeJoseContreras/villazzo-scraper-app"
SERVICE_NAME = "villazzo-miami-scraper"

def deploy(api_key: str):
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    with httpx.Client(headers=headers, timeout=30.0) as client:
        # 1. Fetch Owner ID
        print("Fetching Render owner account...")
        owners_res = client.get(f"{RENDER_API_BASE}/owners")
        if owners_res.status_code != 200:
            print(f"Error authenticating with Render API ({owners_res.status_code}): {owners_res.text}")
            sys.exit(1)

        owners_data = owners_res.json()
        if not owners_data:
            print("No owners found for this Render API key.")
            sys.exit(1)

        owner = owners_data[0]["owner"]
        owner_id = owner["id"]
        owner_name = owner.get("name", owner.get("email", "User"))
        print(f"Authenticated as: {owner_name} (Owner ID: {owner_id})")

        # 2. Check if service already exists
        print("Checking existing services...")
        services_res = client.get(f"{RENDER_API_BASE}/services?name={SERVICE_NAME}")
        existing_services = services_res.json() if services_res.status_code == 200 else []

        if existing_services:
            svc = existing_services[0]["service"]
            svc_id = svc["id"]
            print(f"Found existing service '{SERVICE_NAME}' (ID: {svc_id}). Triggering new deployment...")
            deploy_res = client.post(f"{RENDER_API_BASE}/services/{svc_id}/deploys")
            if deploy_res.status_code in [200, 201]:
                deploy_data = deploy_res.json()
                print("Deployment triggered successfully!")
                print(f"Service URL: {svc.get('serviceDetails', {}).get('url', 'https://dashboard.render.com')}")
                return
            else:
                print(f"Failed to trigger deploy: {deploy_res.text}")
                sys.exit(1)

        # 3. Create new Web Service on Free Plan
        print(f"Creating new free web service '{SERVICE_NAME}'...")
        payload = {
            "type": "web_service",
            "name": SERVICE_NAME,
            "ownerId": owner_id,
            "repo": REPO_URL,
            "branch": "main",
            "autoDeploy": "yes",
            "serviceDetails": {
                "env": "docker",
                "dockerfilePath": "Dockerfile",
                "dockerContext": ".",
                "plan": "free",
                "region": "oregon",
                "healthCheckPath": "/healthz",
                "envVars": [
                    {"key": "PORT", "value": "8000"},
                    {"key": "PYTHONUNBUFFERED", "value": "1"}
                ]
            }
        }

        res = client.post(f"{RENDER_API_BASE}/services", json=payload)
        if res.status_code in [200, 201]:
            data = res.json()
            svc = data.get("service", data)
            svc_id = svc.get("id")
            url = svc.get("serviceDetails", {}).get("url") or f"https://{SERVICE_NAME}.onrender.com"
            print("\n==========================================")
            print("  SUCCESSFULLY CREATED RENDER WEB SERVICE!")
            print("==========================================")
            print(f"Service ID:   {svc_id}")
            print(f"Service Name: {SERVICE_NAME}")
            print(f"Public URL:   {url}")
            print("Dashboard:    https://dashboard.render.com")
            print("Render is now building and deploying your container.")
        else:
            print(f"Failed to create service ({res.status_code}): {res.text}")

if __name__ == "__main__":
    key = os.environ.get("RENDER_API_KEY")
    if len(sys.argv) > 1:
        key = sys.argv[1]
    if not key:
        print("Please provide your Render API key: python deploy_render.py <YOUR_RENDER_API_KEY>")
        sys.exit(1)
    deploy(key)
