"""RunPod Pod 作成スクリプト - ブラウザアクセス可能な Next.js UI
利用可能なGPUをすべて試すフォールバックロジック付き
"""
import os
import requests
import json
import sys

API_KEY = os.environ.get("RUNPOD_API_KEY", "").strip()
if not API_KEY:
    print("Set RUNPOD_API_KEY in the environment.", file=sys.stderr)
    sys.exit(1)

API_URL = "https://api.runpod.io/graphql"
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

IMAGE = "ghcr.io/miya390831-a11y/aibo-studio-v8-ui:latest"
# GHCR private 時は RunPod の containerRegistryAuthId が必要（ghcr-miya）
REGISTRY_AUTH_ID = "cmp8hgy2x000dl2076m4ck734"
# 48GB GPU 優先順（無印 48GB クラス）
PREFERRED_GPU_IDS = [
    "NVIDIA A40",
    "NVIDIA RTX A6000",
    "NVIDIA RTX 6000 Ada Generation",
    "NVIDIA L40S",
    "NVIDIA L40",
]

def graphql(query, variables=None):
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = requests.post(API_URL, json=payload, headers=HEADERS)
    return resp.json()

# Step 1: Get all available GPUs
print("=== Step 1: Fetching GPU types ===")
gpu_query = """
{
  gpuTypes {
    id
    displayName
    maxGpuCount
    securePrice
    communityPrice
    clusterPrice
  }
}
"""
result = graphql(gpu_query)
gpus = result["data"]["gpuTypes"]

available = [g for g in gpus if g["maxGpuCount"] >= 1]
# Sort by price ascending
available.sort(key=lambda x: x.get("securePrice", 999) if x.get("securePrice") else 999)

print(f"Total GPU types with availability: {len(available)}")

# Step 2: Try to create Pod with each GPU until success
create_mutation = """
mutation CreatePod($input: PodFindAndDeployOnDemandInput!) {
  podFindAndDeployOnDemand(input: $input) {
    id
    name
    machineId
    costPerHr
    desiredStatus
    runtime {
      ports {
        ip
        isIpPublic
        privatePort
        publicPort
        type
      }
    }
    machine {
      podHostId
    }
  }
}
"""

# 48GB クラスを優先
preferred = [g for gid in PREFERRED_GPU_IDS for g in available if g["id"] == gid]
rest = [g for g in available if g["id"] not in {x["id"] for x in preferred}]
try_order = preferred + rest

for i, gpu in enumerate(try_order):
    gpu_id = gpu["id"]
    gpu_name = gpu["displayName"]
    price = gpu.get("securePrice", "N/A")
    count = gpu["maxGpuCount"]
    
    print(f"\n[{i+1}/{len(try_order)}] Trying: {gpu_id} | {gpu_name} | ${price}/hr | avail: {count}")
    
    variables = {
        "input": {
            "gpuTypeId": gpu_id,
            "gpuCount": 1,
            "name": "aibo-studio-v8-ui",
            "imageName": IMAGE,
            "containerDiskInGb": 50,
            "ports": "3000/http",
            "containerRegistryAuthId": REGISTRY_AUTH_ID,
            "env": [
                {"key": "NODE_ENV", "value": "production"},
                {"key": "PORT", "value": "3000"},
                {"key": "HOSTNAME", "value": "0.0.0.0"}
            ],
            "startSsh": False
        }
    }
    
    try:
        result = graphql(create_mutation, variables)
        
        if "errors" not in result:
            pod = result["data"]["podFindAndDeployOnDemand"]
            pod_id = pod["id"]
            machine_id = pod.get("machineId", "N/A")
            cost = pod.get("costPerHr", "N/A")
            status = pod.get("desiredStatus", "N/A")
            
            print(f"\n=== SUCCESS! Pod Created ===")
            print(f"  Pod ID: {pod_id}")
            print(f"  GPU: {gpu_name}")
            print(f"  Machine: {machine_id}")
            print(f"  Cost/hr: ${cost}")
            print(f"  Status: {status}")
            
            # Get access URL
            if pod.get("machine") and pod["machine"].get("podHostId"):
                url = f"https://{pod['machine']['podHostId']}-3000.proxy.runpod.io"
                print(f"\n  ACCESS URL: {url}")
                print(f"  (may take 2-5 min to start)")
            elif pod.get("runtime") and pod["runtime"].get("ports"):
                for port in pod["runtime"]["ports"]:
                    if port.get("isIpPublic"):
                        url = f"https://{port['ip']}-3000.proxy.runpod.io"
                        print(f"\n  ACCESS URL: {url}")
                        print(f"  (may take 2-5 min to start)")
            break
        else:
            err_msg = result["errors"][0].get("message", str(result["errors"]))
            err_code = result["errors"][0].get("extensions", {}).get("code", "UNKNOWN")
            print(f"  FAILED [{err_code}]: {err_msg[:100]}")
            
    except Exception as e:
        print(f"  EXCEPTION: {e}")

else:
    print("\n=== ALL GPUS FAILED ===")
    print("No GPU available. Try again later or use a different region.")

print("\n=== Done ===")