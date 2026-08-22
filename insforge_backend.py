from __future__ import annotations

import os
from typing import Any

import httpx


class InsForgeConfigurationError(RuntimeError):
    pass


class InsForgeBackend:
    """Minimal trusted-server adapter for InsForge's database REST API.

    Admin credentials never belong in browser code. User-facing flows should use
    InsForge Auth and user JWTs/RLS; this adapter is for owner/server operations.
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

    def _url(self, table: str) -> str:
        if not table.replace("_", "").isalnum():
            raise ValueError("Invalid table name")
        return f"{self.base_url}/api/database/records/{table}"

    async def insert(self, table: str, rows: dict[str, Any] | list[dict[str, Any]]) -> Any:
        payload = rows if isinstance(rows, list) else [rows]
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self._url(table), headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json() if response.content else None

    async def select(
        self,
        table: str,
        *,
        params: dict[str, str] | None = None,
    ) -> Any:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(self._url(table), headers=self.headers, params=params or {})
            response.raise_for_status()
            return response.json() if response.content else []

    async def patch(
        self,
        table: str,
        values: dict[str, Any],
        *,
        params: dict[str, str],
    ) -> Any:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.patch(
                self._url(table), headers=self.headers, params=params, json=values
            )
            response.raise_for_status()
            return response.json() if response.content else None


_backend: InsForgeBackend | None = None


def get_backend() -> InsForgeBackend:
    global _backend
    if _backend is None:
        _backend = InsForgeBackend()
    return _backend
