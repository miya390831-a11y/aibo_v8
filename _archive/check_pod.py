import os
import requests
import json
import time
import sys

API_KEY = os.environ.get("RUNPOD_API_KEY", "").strip()
POD_ID = "xed64txqg15j30"

if not API_KEY:
    print("Set RUNPOD_API_KEY in the environment.", file=sys.stderr)
    sys.exit(1)

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

query = """
query {
  pod(input: {podId: "%s"}) {
    id
    name
    desiredStatus
    runtime {
      ports {
        ip
        isIpPublic
        privatePort
        publicPort
        type
      }
      uptimeInSeconds
    }
    machine {
      podHostId
      gpuDisplayName
    }
  }
}
""" % POD_ID

r = requests.post("https://api.runpod.io/graphql", 
                   json={"query": query},
                   headers=headers)
data = r.json()
print(f"Response: {json.dumps(data, indent=2)}")
if "errors" in data:
    print(f"ERROR: {data['errors']}")
    exit(1)
pod = data["data"]["pod"]

print(f"Status: {pod['desiredStatus']}")
print(f"GPU: {pod['machine']['gpuDisplayName']}")
uptime = pod['runtime'].get('uptimeInSeconds', 0) if pod.get('runtime') else 0
print(f"Uptime: {uptime}s ({uptime//60}m {uptime%60}s)")
print(f"PodHostId: {pod['machine']['podHostId']}")

if pod.get('runtime') and pod['runtime'].get('ports'):
    for p in pod['runtime']['ports']:
        print(f"Port {p['privatePort']} -> {p['publicPort']} (public={p['isIpPublic']}, ip={p['ip']})")

# Test HTTP access
url = f"https://{pod['machine']['podHostId']}-3000.proxy.runpod.io"
print(f"\nURL: {url}")