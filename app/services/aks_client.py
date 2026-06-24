from __future__ import annotations

import json
from typing import Any

import httpx


class AKSClient:
    def __init__(self, access_token: str, subscription_id: str) -> None:
        self.access_token = access_token
        self.subscription_id = subscription_id
        self.base_url = "https://management.azure.com"

    async def list_clusters(self) -> list[dict[str, Any]]:
        """List all AKS clusters in subscription."""
        url = f"{self.base_url}/subscriptions/{self.subscription_id}/providers/Microsoft.ContainerService/managedClusters?api-version=2024-02-02-preview"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                body = response.json()
            clusters = []
            for item in body.get("value", []):
                clusters.append(
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "resource_group": item["id"].split("/")[4] if "id" in item else "",
                        "location": item.get("location"),
                        "fqdn": item.get("properties", {}).get("fqdn", ""),
                        "state": item.get("properties", {}).get("provisioningState", "Unknown"),
                    }
                )
            return clusters
        except Exception as exc:
            print(f"Failed to list AKS clusters: {exc}")
            return []

    async def get_cluster_credentials(self, resource_group: str, cluster_name: str) -> dict[str, str] | None:
        """Get kubeconfig for AKS cluster."""
        url = f"{self.base_url}/subscriptions/{self.subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.ContainerService/managedClusters/{cluster_name}/listClusterUserCredential?api-version=2024-02-02-preview"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, headers=headers)
                response.raise_for_status()
                body = response.json()
            kubeconfigs = body.get("kubeconfigs", [])
            if kubeconfigs:
                return {"kubeconfig": kubeconfigs[0].get("value")}
        except Exception as exc:
            print(f"Failed to get cluster credentials: {exc}")
        return None
