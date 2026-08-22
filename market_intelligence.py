from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

import httpx


class MarketFeedConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketSignal:
    direction: str
    hs_code: str
    country_code: str
    country_name: str
    monthly_value_usd: int
    year_to_date_value_usd: int
    period: str
    source: str


class UNComtradePreviewFeed:
    """Anonymous global trade preview feed from UN Comtrade.

    The preview API requires no account or subscription key, but is intentionally
    rate-limited and capped. It is suitable for first-look market intelligence, not
    exhaustive commercial due diligence or individual counterparty verification.
    """

    BASE_URL = "https://comtradeapi.un.org/public/v1/preview/C"

    async def query(
        self,
        *,
        period: str,
        reporter_code: str,
        flow_code: str,
        hs_code: str,
        partner_code: str = "0",
        frequency: str = "A",
        max_records: int = 500,
    ) -> dict[str, Any]:
        max_records = max(1, min(int(max_records), 500))
        url = f"{self.BASE_URL}/{frequency}/HS"
        params = {
            "period": period,
            "reporterCode": reporter_code,
            "flowCode": flow_code,
            "cmdCode": hs_code,
            "partnerCode": partner_code,
            "maxRecords": str(max_records),
        }
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data", []) if isinstance(payload, dict) else []
        return {
            "period": period,
            "reporter_code": reporter_code,
            "partner_code": partner_code,
            "flow_code": flow_code,
            "hs_code": hs_code,
            "count": len(data),
            "data": data,
            "source": "UN Comtrade public preview API",
            "scope": "GLOBAL_AGGREGATE_PREVIEW",
            "notice": "Preview is capped/rate-limited aggregate trade intelligence and does not identify or verify individual buyers or suppliers.",
        }

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(
                    f"{self.BASE_URL}/A/HS",
                    params={
                        "period": "2023",
                        "reporterCode": "156",
                        "flowCode": "X",
                        "cmdCode": "TOTAL",
                        "partnerCode": "0",
                        "maxRecords": "1",
                    },
                )
                return 200 <= response.status_code < 300
        except httpx.HTTPError:
            return False


class CensusTradeFeed:
    """Live U.S. import/export market feed from the Census International Trade API.

    This is aggregate market-demand/supply intelligence. It does not identify or
    verify individual buyers or suppliers, so counterparty verification remains a
    separate production gate.
    """

    IMPORT_URL = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
    EXPORT_URL = "https://api.census.gov/data/timeseries/intltrade/exports/hs"

    def __init__(self) -> None:
        self.api_key = os.getenv("CENSUS_TRADE_API_KEY", "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def _query(self, url: str, params: dict[str, str]) -> list[list[str]]:
        if not self.configured:
            raise MarketFeedConfigurationError("Census International Trade API key is not configured")
        params = {**params, "key": self.api_key}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, list) or not payload:
            return []
        return payload

    async def us_import_origins(self, hs_code: str, period: str) -> list[MarketSignal]:
        rows = await self._query(
            self.IMPORT_URL,
            {
                "get": "CTY_CODE,CTY_NAME,I_COMMODITY,GEN_VAL_MO,GEN_VAL_YR",
                "I_COMMODITY": hs_code,
                "time": period,
            },
        )
        if not rows:
            return []
        headers = rows[0]
        signals: list[MarketSignal] = []
        for raw in rows[1:]:
            row = dict(zip(headers, raw))
            signals.append(MarketSignal(
                direction="US_IMPORT",
                hs_code=row.get("I_COMMODITY", hs_code),
                country_code=row.get("CTY_CODE", ""),
                country_name=row.get("CTY_NAME", ""),
                monthly_value_usd=int(row.get("GEN_VAL_MO", "0") or 0),
                year_to_date_value_usd=int(row.get("GEN_VAL_YR", "0") or 0),
                period=period,
                source="U.S. Census International Trade API",
            ))
        return sorted(signals, key=lambda item: item.monthly_value_usd, reverse=True)

    async def us_export_destinations(self, hs_code: str, period: str) -> list[MarketSignal]:
        rows = await self._query(
            self.EXPORT_URL,
            {
                "get": "CTY_CODE,CTY_NAME,E_COMMODITY,ALL_VAL_MO,ALL_VAL_YR",
                "E_COMMODITY": hs_code,
                "time": period,
            },
        )
        if not rows:
            return []
        headers = rows[0]
        signals: list[MarketSignal] = []
        for raw in rows[1:]:
            row = dict(zip(headers, raw))
            signals.append(MarketSignal(
                direction="US_EXPORT",
                hs_code=row.get("E_COMMODITY", hs_code),
                country_code=row.get("CTY_CODE", ""),
                country_name=row.get("CTY_NAME", ""),
                monthly_value_usd=int(row.get("ALL_VAL_MO", "0") or 0),
                year_to_date_value_usd=int(row.get("ALL_VAL_YR", "0") or 0),
                period=period,
                source="U.S. Census International Trade API",
            ))
        return sorted(signals, key=lambda item: item.monthly_value_usd, reverse=True)

    async def health(self) -> bool:
        if not self.configured:
            return False
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(
                    "https://api.census.gov/data/timeseries/intltrade/imports/hs/variables.json"
                )
                return 200 <= response.status_code < 300
        except httpx.HTTPError:
            return False


un_comtrade_preview_feed = UNComtradePreviewFeed()
census_trade_feed = CensusTradeFeed()
