from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlencode

from msal import PublicClientApplication


class AzureAuthManager:
    def __init__(self) -> None:
        self.client_id = os.getenv("AZURE_CLIENT_ID", "")
        self.tenant_id = os.getenv("AZURE_TENANT_ID", "common")
        self.redirect_uri = os.getenv("AZURE_REDIRECT_URI", "http://127.0.0.1:8000/api/auth/callback")
        self.app = PublicClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
        )

    def get_auth_url(self) -> str:
        """Generate Microsoft login URL."""
        if not self.client_id:
            raise ValueError("AZURE_CLIENT_ID not configured")
        
        # Build auth URL manually for more control
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "scope": "https://management.azure.com/.default offline_access",
            "redirect_uri": self.redirect_uri,
            "response_mode": "query",
        }
        auth_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/authorize?{urlencode(params)}"
        return auth_url

    def get_token_from_code(self, code: str) -> dict[str, Any] | None:
        """Exchange auth code for access token."""
        scopes = ["https://management.azure.com/.default"]
        try:
            result = self.app.acquire_token_by_authorization_code(
                code=code,
                scopes=scopes,
                redirect_uri=self.redirect_uri,
            )
            if "access_token" in result:
                return result
        except Exception as exc:
            print(f"Token exchange failed: {exc}")
        return None

    def get_token_from_refresh(self, refresh_token: str) -> dict[str, Any] | None:
        """Refresh access token."""
        scopes = ["https://management.azure.com/.default"]
        try:
            result = self.app.acquire_token_by_refresh_token(
                refresh_token=refresh_token,
                scopes=scopes,
            )
            if "access_token" in result:
                return result
        except Exception:
            pass
        return None
