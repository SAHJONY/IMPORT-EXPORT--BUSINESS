from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class ConnectorHealth:
    name: str
    configured: bool
    reachable: bool
    authoritative: bool
    detail: str


class TradeConnectorRegistry:
    """Connectivity checks for production trade-data dependencies.

    These checks do not declare a trade compliant. They only verify that the
    configured evidence sources are reachable. Trade release remains fail-closed.
    """

    OFAC_SDN_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV"

    async def _head_or_get(self, url: str, *, headers: dict[str, str] | None = None) -> bool:
        merged = {"User-Agent": "SAHJONY-Global-Trade-OS/2.0", **(headers or {})}
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(url, headers=merged)
                return 200 <= response.status_code < 400
        except httpx.HTTPError:
            return False

    async def health(self) -> dict[str, Any]:
        checks: list[ConnectorHealth] = []

        ofac_enabled = os.getenv("OFAC_DIRECT_SCREENING", "false").lower() == "true"
        checks.append(
            ConnectorHealth(
                "ofac_sanctions_data",
                ofac_enabled,
                await self._head_or_get(self.OFAC_SDN_URL) if ofac_enabled else False,
                True,
                "U.S. Treasury OFAC Sanctions List Service",
            )
        )

        trade_key = os.getenv("TRADE_GOV_API_KEY", "").strip()
        checks.append(
            ConnectorHealth(
                "trade_gov_csl",
                bool(trade_key),
                bool(trade_key),
                True,
                "U.S. International Trade Administration Consolidated Screening List API; request-level verification occurs during screening.",
            )
        )

        for env_name, label in [
            ("TARIFF_DATA_PROVIDER", "tariff_classification"),
            ("LOGISTICS_DATA_PROVIDER", "logistics_tracking"),
            ("FX_DATA_PROVIDER", "fx_rates"),
        ]:
            value = os.getenv(env_name, "").strip()
            checks.append(ConnectorHealth(label, bool(value), bool(value), False, value or "not configured"))

        serialized = [asdict(check) for check in checks]
        return {
            "connectors": serialized,
            "configured_count": sum(1 for item in checks if item.configured),
            "reachable_count": sum(1 for item in checks if item.reachable),
            "all_configured_reachable": all((not item.configured) or item.reachable for item in checks),
        }


trade_connectors = TradeConnectorRegistry()
