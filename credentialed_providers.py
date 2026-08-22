from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


class ProviderConfigurationError(RuntimeError):
    pass


@dataclass
class OAuthToken:
    access_token: str
    expires_at: float


class MaerskProvider:
    def __init__(self) -> None:
        self.client_id = os.getenv("MAERSK_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("MAERSK_CLIENT_SECRET", "").strip()
        self.token_url = os.getenv("MAERSK_TOKEN_URL", "").strip()
        self.api_base = os.getenv("MAERSK_API_BASE", "").strip().rstrip("/")
        self.health_path = os.getenv("MAERSK_HEALTH_PATH", "").strip()
        self._token: OAuthToken | None = None

    @property
    def configured(self) -> bool:
        return all([self.client_id, self.client_secret, self.token_url, self.api_base])

    async def _access_token(self) -> str:
        if not self.configured:
            raise ProviderConfigurationError("Maersk production API credentials are not configured")
        if self._token and self._token.expires_at > time.time() + 60:
            return self._token.access_token
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                self.token_url,
                data={"grant_type": "client_credentials"},
                auth=(self.client_id, self.client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise RuntimeError("Maersk token endpoint did not return access_token")
        ttl = int(payload.get("expires_in", 7200))
        self._token = OAuthToken(token, time.time() + ttl)
        return token

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = await self._access_token()
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("Consumer-Key", self.client_id)
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.request(method, f"{self.api_base}/{path.lstrip('/')}", headers=headers, **kwargs)
            response.raise_for_status()
            return response

    async def health(self) -> bool:
        if not self.configured or not self.health_path:
            return False
        try:
            await self.request("GET", self.health_path)
            return True
        except (httpx.HTTPError, RuntimeError, ProviderConfigurationError):
            return False


class AirwallexProvider:
    """Airwallex server-side FX/settlement adapter.

    Production credentials are generated only after account onboarding. API keys and
    tokens must remain server-side. Authentication tokens are reused until expiry.
    """

    def __init__(self) -> None:
        self.base_url = os.getenv("AIRWALLEX_API_BASE", "https://api.airwallex.com/api/v1").strip().rstrip("/")
        self.client_id = os.getenv("AIRWALLEX_CLIENT_ID", "").strip()
        self.api_key = os.getenv("AIRWALLEX_API_KEY", "").strip()
        self.login_as = os.getenv("AIRWALLEX_LOGIN_AS", "").strip()
        self._token: OAuthToken | None = None

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.client_id and self.api_key)

    async def _access_token(self) -> str:
        if not self.configured:
            raise ProviderConfigurationError("Airwallex production credentials are not configured")
        if self._token and self._token.expires_at > time.time() + 60:
            return self._token.access_token
        headers = {"x-client-id": self.client_id, "x-api-key": self.api_key, "Content-Type": "application/json"}
        if self.login_as:
            headers["x-login-as"] = self.login_as
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(f"{self.base_url}/authentication/login", headers=headers)
            response.raise_for_status()
            payload = response.json()
        token = payload.get("token")
        if not token:
            raise RuntimeError("Airwallex authentication did not return token")
        self._token = OAuthToken(token, time.time() + 25 * 60)
        return token

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = await self._access_token()
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.request(method, f"{self.base_url}/{path.lstrip('/')}", headers=headers, **kwargs)
            response.raise_for_status()
            return response

    async def health(self) -> bool:
        if not self.configured:
            return False
        try:
            await self.request("GET", "/balances/current")
            return True
        except (httpx.HTTPError, RuntimeError, ProviderConfigurationError):
            return False


class ExecutableFXProvider:
    def __init__(self) -> None:
        self.base_url = os.getenv("FX_EXECUTION_API_BASE", "").strip().rstrip("/")
        self.api_key = os.getenv("FX_EXECUTION_API_KEY", "").strip()
        self.health_path = os.getenv("FX_EXECUTION_HEALTH_PATH", "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.health_path)

    async def health(self) -> bool:
        if not self.configured:
            return False
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                response = await client.get(
                    f"{self.base_url}/{self.health_path.lstrip('/')}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return 200 <= response.status_code < 300
        except httpx.HTTPError:
            return False


maersk_provider = MaerskProvider()
airwallex_provider = AirwallexProvider()
fx_execution_provider = ExecutableFXProvider()
