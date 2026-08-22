from __future__ import annotations

import os
from typing import Any

import httpx


class InsForgeConfigurationError(RuntimeError):
    pass


class InsForgeBackend:
    """Trusted-server adapter for InsForge admin and database APIs.

    The admin key is server-only. Browser/user flows should use InsForge Auth,
    user JWTs and RLS. This adapter is deliberately narrow so infrastructure
    health and persistence can be audited independently of generative agents.
    """

    def __init__(self) -> None:
        self.base_url = os.getenv("INSFORGE_BASE_URL", "").rstrip("/")
        self.api_key = os.getenv("INSFORGE_API_KEY", "")
        if not self.base_url or not self.api_key:
            raise InsForgeConfigurationError(
                "INSFORGE_BASE_URL and INSFORGE_API_KEY must be configured"
            )

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _records_url(self, table: str) -> str:
        if not table.replace("_", "").isalnum():
            raise ValueError("Invalid table name")
        return f"{self.base_url}/api/database/records/{table}"

    async def metadata(self) -> dict[str, Any]:
        """Verify authenticated connectivity using InsForge's admin metadata API."""
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.base_url}/api/metadata", headers=self.headers)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {"raw": payload}

    async def insert(self, table: str, rows: dict[str, Any] | list[dict[str, Any]]) -> Any:
        payload = rows if isinstance(rows, list) else [rows]
        headers = {**self.headers, "Prefer": "return=representation"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self._records_url(table), headers=headers, json=payload)
            response.raise_for_status()
            return response.json() if response.content else None

    async def select(
        self,
        table: str,
        *,
        params: dict[str, str] | None = None,
    ) -> Any:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                self._records_url(table), headers=self.headers, params=params or {}
            )
            response.raise_for_status()
            return response.json() if response.content else []

    async def patch(
        self,
        table: str,
        values: dict[str, Any],
        *,
        params: dict[str, str],
    ) -> Any:
        headers = {**self.headers, "Prefer": "return=representation"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.patch(
                self._records_url(table), headers=headers, params=params, json=values
            )
            response.raise_for_status()
            return response.json() if response.content else None


_backend: InsForgeBackend | None = None


def get_backend() -> InsForgeBackend:
    global _backend
    if _backend is None:
        _backend = InsForgeBackend()
    return _backend
