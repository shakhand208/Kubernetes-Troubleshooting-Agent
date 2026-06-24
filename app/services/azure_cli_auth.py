"""Azure authentication using local Azure CLI credentials (no MSAL required)."""
from __future__ import annotations

import json
import subprocess
import shutil
import platform
from pathlib import Path
from typing import Any


class AzureCliAuthManager:
    """Use existing Azure CLI authentication instead of MSAL."""

    def __init__(self) -> None:
        self.kubeconfig_path = Path.home() / ".kube" / "config"
        # On Windows, az is typically installed as az.cmd or az.exe
        self.is_windows = platform.system() == "Windows"
        self.az_cmd = shutil.which("az") or shutil.which("az.cmd") or "az"
        print(f"[DEBUG] Platform: {platform.system()}, Using az command: {self.az_cmd}")

    def _run_az_command(self, args: list[str]) -> tuple[int, str, str]:
        """Run az command with proper error handling for Windows."""
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=False,
                shell=self.is_windows,
            )
            return result.returncode, result.stdout, result.stderr
        except Exception as e:
            print(f"[DEBUG] Exception running command {args}: {e}")
            return -1, "", str(e)

    def is_authenticated(self) -> bool:
        """Check if user is logged in to Azure CLI."""
        try:
            returncode, stdout, stderr = self._run_az_command(
                [self.az_cmd, "account", "show"]
            )
            success = returncode == 0
            print(f"[DEBUG] az account show - returncode: {returncode}, stdout length: {len(stdout)}, stderr: {stderr[:200] if stderr else 'empty'}")
            return success
        except Exception as e:
            print(f"[DEBUG] Exception in is_authenticated: {e}")
            return False

    def get_current_account(self) -> dict[str, Any] | None:
        """Get current Azure CLI account info."""
        try:
            returncode, stdout, stderr = self._run_az_command(
                [self.az_cmd, "account", "show"]
            )
            if returncode == 0:
                return json.loads(stdout)
            return None
        except Exception as exc:
            print(f"Failed to get account: {exc}")
            return None

    def get_subscription_id(self) -> str | None:
        """Get current subscription ID."""
        account = self.get_current_account()
        return account.get("id") if account else None

    def get_access_token(self) -> str | None:
        """Get access token from Azure CLI."""
        try:
            returncode, stdout, stderr = self._run_az_command(
                [self.az_cmd, "account", "get-access-token", "--resource", "https://management.azure.com"]
            )
            if returncode == 0:
                data = json.loads(stdout)
                return data.get("accessToken")
            return None
        except Exception as exc:
            print(f"Failed to get access token: {exc}")
            return None

    def list_aks_clusters(self) -> list[dict[str, Any]]:
        """List all AKS clusters in current subscription using Azure CLI."""
        try:
            returncode, stdout, stderr = self._run_az_command(
                [self.az_cmd, "aks", "list", "--output", "json"]
            )
            if returncode == 0:
                clusters = json.loads(stdout)
                return [
                    {
                        "id": c.get("id"),
                        "name": c.get("name"),
                        "resource_group": c.get("resourceGroup"),
                        "location": c.get("location"),
                        "fqdn": c.get("fqdn", ""),
                        "state": c.get("provisioningState", "Unknown"),
                    }
                    for c in clusters
                ]
            else:
                print(f"[DEBUG] az aks list failed with returncode {returncode}: {stderr}")
            return []
        except Exception as exc:
            print(f"Failed to list AKS clusters: {exc}")
            return []

    def get_cluster_credentials(self, resource_group: str, cluster_name: str) -> dict[str, str] | None:
        """Get kubeconfig for AKS cluster using Azure CLI."""
        try:
            print(f"[DEBUG] Getting credentials for {resource_group}/{cluster_name}")
            print(f"[DEBUG] az_cmd: {self.az_cmd}")
            print(f"[DEBUG] kubeconfig_path: {self.kubeconfig_path}")
            
            # First, ensure .kube directory exists
            self.kubeconfig_path.parent.mkdir(parents=True, exist_ok=True)
            
            # This updates local kubeconfig
            returncode, stdout, stderr = self._run_az_command(
                [self.az_cmd, "aks", "get-credentials", "--resource-group", resource_group, "--name", cluster_name, "--overwrite-existing", "--file", str(self.kubeconfig_path)]
            )
            print(f"[DEBUG] az aks get-credentials - returncode: {returncode}")
            if stdout:
                print(f"[DEBUG] stdout: {stdout}")
            if stderr:
                print(f"[DEBUG] stderr: {stderr}")
            
            if returncode != 0:
                # Try without --file parameter (let az use default location)
                print(f"[DEBUG] Trying without --file parameter")
                returncode, stdout, stderr = self._run_az_command(
                    [self.az_cmd, "aks", "get-credentials", "--resource-group", resource_group, "--name", cluster_name, "--overwrite-existing"]
                )
                print(f"[DEBUG] Retry - returncode: {returncode}, stderr: {stderr}")
                if returncode != 0:
                    return None
            
            # Read the kubeconfig file
            if self.kubeconfig_path.exists():
                print(f"[DEBUG] Reading kubeconfig from {self.kubeconfig_path} (size: {self.kubeconfig_path.stat().st_size} bytes)")
                with open(self.kubeconfig_path, "r") as f:
                    content = f.read()
                    print(f"[DEBUG] Successfully read kubeconfig ({len(content)} characters)")
                    return {"kubeconfig": content}
            else:
                print(f"[DEBUG] kubeconfig file not found at {self.kubeconfig_path}")
                # Try to list what's in .kube directory
                kube_dir = self.kubeconfig_path.parent
                if kube_dir.exists():
                    print(f"[DEBUG] Contents of {kube_dir}: {list(kube_dir.iterdir())}")
            return None
        except Exception as exc:
            print(f"[DEBUG] Failed to get cluster credentials: {exc}")
            import traceback
            traceback.print_exc()
            return None
