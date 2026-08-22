from __future__ import annotations

import csv
import io
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

from credentialed_providers import airwallex_provider, fx_execution_provider, maersk_provider
from market_intelligence import census_trade_feed, un_comtrade_preview_feed


@dataclass(frozen=True)
class ConnectorHealth:
    name: str
    configured: bool
    reachable: bool
    authoritative: bool
    detail: str
    source: str
    checked_at: str
    scope: str = "GLOBAL"


class TradeConnectorRegistry:
    OFAC_SDN_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV"
    OFAC_NON_SDN_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/CONSOLIDATED.CSV"
    CSL_INFO_URL = "https://www.trade.gov/consolidated-screening-list"
    ITA_API_CATALOG_URL = "https://developer.trade.gov/apis"
    USITC_HTS_SEARCH = "https://hts.usitc.gov/reststop/search"
    ECB_FX_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
    FED_H10_URL = "https://www.federalreserve.gov/datadownload/choose.aspx?rel=h10"
    USER_AGENT = "SAHJONY-Global-Trade-OS/2.5 (+https://import-export-business.vercel.app)"

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}

    @staticmethod
    def _stamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    async def _get(self, url: str, *, timeout: int = 15) -> httpx.Response:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": self.USER_AGENT})
            response.raise_for_status()
            return response

    async def _reachable(self, url: str) -> bool:
        try:
            await self._get(url, timeout=10)
            return True
        except (httpx.HTTPError, ValueError):
            return False

    async def _cached_text(self, key: str, url: str, ttl_seconds: int) -> tuple[str, str]:
        now = time.time()
        cached = self._cache.get(key)
        if cached and now - cached[0] < ttl_seconds:
            return cached[1][0], cached[1][1]
        response = await self._get(url, timeout=20)
        fetched_at = self._stamp()
        value = (response.text, fetched_at)
        self._cache[key] = (now, value)
        return value

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    async def ofac_screen(self, name: str, *, limit: int = 25) -> dict[str, Any]:
        query = self._normalize(name)
        if len(query) < 2:
            raise ValueError("screening name must contain at least two characters")
        matches: list[dict[str, Any]] = []
        datasets = [("SDN", self.OFAC_SDN_URL, "ofac_sdn"), ("NON_SDN", self.OFAC_NON_SDN_URL, "ofac_non_sdn")]
        fetched: dict[str, str] = {}
        for dataset, url, cache_key in datasets:
            text, fetched_at = await self._cached_text(cache_key, url, 6 * 60 * 60)
            fetched[dataset] = fetched_at
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                searchable = self._normalize(" ".join(str(v or "") for v in row.values()))
                if query in searchable:
                    matches.append({"dataset": dataset, "record": row})
                    if len(matches) >= limit:
                        break
            if len(matches) >= limit:
                break
        return {
            "query": name,
            "candidate_match": bool(matches),
            "match_count": len(matches),
            "matches": matches,
            "datasets_fetched_at": fetched,
            "source": "U.S. Treasury OFAC Sanctions List Service",
            "release_effect": "REVIEW" if matches else "NO_CANDIDATE_MATCH",
            "notice": "A no-match is not legal clearance. Candidate matches require official-record review and additional due diligence.",
        }

    async def usitc_hts_search(self, keyword: str) -> dict[str, Any]:
        keyword = keyword.strip()
        if len(keyword) < 2:
            raise ValueError("HTS keyword must contain at least two characters")
        response = await self._get(f"{self.USITC_HTS_SEARCH}?keyword={quote_plus(keyword)}", timeout=20)
        return {
            "query": keyword,
            "results": response.json(),
            "source": "United States International Trade Commission Harmonized Tariff Schedule REST API",
            "scope": "US_IMPORTS",
            "checked_at": self._stamp(),
            "notice": "Search results assist classification research; final classification and applicable duty treatment must be verified against the current HTS and trade-specific legal facts.",
        }

    async def ecb_reference_rates(self) -> dict[str, Any]:
        xml_text, fetched_at = await self._cached_text("ecb_fx", self.ECB_FX_URL, 60 * 60)
        root = ET.fromstring(xml_text)
        observation_date: str | None = None
        rates: dict[str, float] = {"EUR": 1.0}
        for element in root.iter():
            if "time" in element.attrib:
                observation_date = element.attrib.get("time")
            currency = element.attrib.get("currency")
            rate = element.attrib.get("rate")
            if currency and rate:
                rates[currency.upper()] = float(rate)
        return {
            "base": "EUR",
            "observation_date": observation_date,
            "fetched_at": fetched_at,
            "rates": rates,
            "source": "European Central Bank euro foreign exchange reference rates",
            "usage": "planning_reference_only",
            "notice": "ECB reference rates are informational and are not settlement/execution quotes.",
        }

    async def fx_reference(self, base: str, quote: str) -> dict[str, Any]:
        data = await self.ecb_reference_rates()
        base = base.upper().strip()
        quote = quote.upper().strip()
        rates = data["rates"]
        if base not in rates or quote not in rates:
            raise ValueError(f"Unsupported ECB reference currency pair: {base}/{quote}")
        return {
            "base": base,
            "quote": quote,
            "rate": rates[quote] / rates[base],
            "observation_date": data["observation_date"],
            "fetched_at": data["fetched_at"],
            "source": data["source"],
            "usage": data["usage"],
            "notice": data["notice"],
        }

    async def health(self) -> dict[str, Any]:
        checked_at = self._stamp()
        checks: list[ConnectorHealth] = []

        checks.append(ConnectorHealth("ofac_sanctions_data", True, await self._reachable(self.OFAC_SDN_URL), True, "Direct SDN/non-SDN datasets with automated-request User-Agent.", "U.S. Treasury OFAC Sanctions List Service", checked_at))
        checks.append(ConnectorHealth("trade_gov_csl_public", True, await self._reachable(self.CSL_INFO_URL), True, "Official CSL source; authenticated API mode remains optional for fuzzy API search.", "U.S. International Trade Administration Consolidated Screening List", checked_at))

        trade_key = os.getenv("TRADE_GOV_API_KEY", "").strip()
        checks.append(ConnectorHealth("trade_gov_authenticated_api", bool(trade_key), bool(trade_key) and await self._reachable(self.ITA_API_CATALOG_URL), True, "Optional authenticated ITA API access for CSL/FTA tariff APIs.", "U.S. International Trade Administration Data Services Platform", checked_at))

        usitc_health_url = f"{self.USITC_HTS_SEARCH}?keyword=cotton"
        checks.append(ConnectorHealth("tariff_classification", True, await self._reachable(usitc_health_url), True, "Official USITC HTS REST API. U.S. imports only; other jurisdictions remain corridor-specific and fail-closed.", "United States International Trade Commission", checked_at, "US_IMPORTS"))

        checks.append(ConnectorHealth("ecb_fx_reference", True, await self._reachable(self.ECB_FX_URL), True, "Daily official reference rates for planning; not transaction execution rates.", "European Central Bank", checked_at))
        checks.append(ConnectorHealth("federal_reserve_h10", True, await self._reachable(self.FED_H10_URL), True, "Official Federal Reserve H.10 FX reference dataset discovery source.", "Board of Governors of the Federal Reserve System", checked_at))

        comtrade_ok = await un_comtrade_preview_feed.health()
        checks.append(ConnectorHealth("market_trade_feed", True, comtrade_ok, True, "Credential-free UN Comtrade preview provides global aggregate trade flows for first-look demand/supply intelligence. Limited to preview caps/rate limits and not individual counterparty verification.", "United Nations Comtrade", checked_at, "GLOBAL_AGGREGATE_PREVIEW"))

        census_ok = await census_trade_feed.health()
        checks.append(ConnectorHealth("census_trade_feed", census_trade_feed.configured, census_ok, True, "Optional higher-specificity U.S. import/export feed by HS and country. Requires Census API key.", "U.S. Census International Trade API", checked_at, "US_TRADE"))

        maersk_ok = await maersk_provider.health()
        checks.append(ConnectorHealth("logistics_tracking", maersk_provider.configured, maersk_ok, True, "Maersk server-to-server tracking adapter. ChatGPT Maersk app is installed separately; production backend still requires approved API credentials.", "A.P. Moller - Maersk Developer Portal", checked_at))

        fx_provider = os.getenv("FX_EXECUTION_PROVIDER", "").strip().lower()
        if fx_provider == "airwallex":
            fx_configured = airwallex_provider.configured
            fx_ok = await airwallex_provider.health()
            fx_source = "Airwallex"
            fx_detail = "Airwallex Client API adapter using server-side Client ID/API key authentication; production requires approved account/KYC and scoped credentials."
        else:
            fx_configured = fx_execution_provider.configured
            fx_ok = await fx_execution_provider.health()
            fx_source = os.getenv("FX_EXECUTION_PROVIDER", "configured provider") or "configured provider"
            fx_detail = "Generic executable/settlement FX adapter; provider account must be KYC-approved and explicitly configured."
        checks.append(ConnectorHealth("fx_execution", fx_configured, fx_ok, False, fx_detail, fx_source, checked_at))

        serialized = [asdict(check) for check in checks]
        by_name = {item.name: item for item in checks}
        return {
            "connectors": serialized,
            "by_name": {name: asdict(item) for name, item in by_name.items()},
            "configured_count": sum(1 for item in checks if item.configured),
            "reachable_count": sum(1 for item in checks if item.reachable),
            "all_configured_reachable": all((not item.configured) or item.reachable for item in checks),
        }


trade_connectors = TradeConnectorRegistry()
