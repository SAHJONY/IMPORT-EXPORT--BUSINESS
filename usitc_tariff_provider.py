from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx


class USITCTariffProvider:
    """Authoritative U.S. HTS research with official-source failover.

    Primary path uses the documented USITC REST API. Some serverless networks can be
    blocked or throttled by that endpoint, so the fallback uses the official HTS web
    search on the same USITC system. Fallback results are research candidates only;
    final classification remains a governed human/compliance decision.
    """

    REST_SEARCH = "https://hts.usitc.gov/reststop/search"
    WEB_SEARCH = "https://hts.usitc.gov/search"
    USER_AGENT = "SAHJONY-Global-Trade-OS/3.0 (+https://www.sahjony.com)"

    @staticmethod
    def _stamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    async def _get(self, url: str, *, timeout: int = 20) -> httpx.Response:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": self.USER_AGENT,
                    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                },
            )
            response.raise_for_status()
            return response

    async def health(self) -> dict[str, Any]:
        rest_url = f"{self.REST_SEARCH}?keyword=cotton"
        try:
            response = await self._get(rest_url, timeout=10)
            if "json" in response.headers.get("content-type", "").lower():
                return {
                    "reachable": True,
                    "mode": "REST",
                    "source": "United States International Trade Commission Harmonized Tariff Schedule",
                    "checked_at": self._stamp(),
                }
        except (httpx.HTTPError, ValueError):
            pass

        try:
            response = await self._get(f"{self.WEB_SEARCH}?query=cotton", timeout=10)
            text = response.text.lower()
            ok = "harmonized tariff schedule" in text and ("search results" in text or "cotton" in text)
            return {
                "reachable": bool(ok),
                "mode": "OFFICIAL_WEB_FALLBACK" if ok else "UNAVAILABLE",
                "source": "United States International Trade Commission Harmonized Tariff Schedule",
                "checked_at": self._stamp(),
            }
        except (httpx.HTTPError, ValueError):
            return {
                "reachable": False,
                "mode": "UNAVAILABLE",
                "source": "United States International Trade Commission Harmonized Tariff Schedule",
                "checked_at": self._stamp(),
            }

    @staticmethod
    def _plain_text(raw_html: str) -> str:
        text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw_html)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", html.unescape(text)).strip()

    @staticmethod
    def _candidate_numbers(text: str, limit: int = 100) -> list[str]:
        # HTS display forms commonly contain 4, 6, 8, or 10 digits with optional dots.
        found = re.findall(r"(?<!\d)(?:\d{4}(?:\.\d{2}){0,3}|\d{6}|\d{8}|\d{10})(?!\d)", text)
        result: list[str] = []
        seen: set[str] = set()
        for value in found:
            normalized = value.strip()
            if normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
            if len(result) >= limit:
                break
        return result

    async def search(self, keyword: str) -> dict[str, Any]:
        keyword = keyword.strip()
        if len(keyword) < 2:
            raise ValueError("HTS keyword must contain at least two characters")

        rest_url = f"{self.REST_SEARCH}?keyword={quote_plus(keyword)}"
        try:
            response = await self._get(rest_url, timeout=20)
            if "json" in response.headers.get("content-type", "").lower():
                return {
                    "query": keyword,
                    "results": response.json(),
                    "source": "United States International Trade Commission Harmonized Tariff Schedule REST API",
                    "source_mode": "REST",
                    "scope": "US_IMPORTS",
                    "checked_at": self._stamp(),
                    "notice": "Search results assist classification research; final classification and duty treatment require verification against the current HTS and transaction facts.",
                }
        except (httpx.HTTPError, ValueError):
            pass

        web_url = f"{self.WEB_SEARCH}?query={quote_plus(keyword)}"
        response = await self._get(web_url, timeout=20)
        plain = self._plain_text(response.text)
        if "harmonized tariff schedule" not in plain.lower():
            raise RuntimeError("Official USITC HTS fallback returned an unexpected response")
        candidates = self._candidate_numbers(plain)
        return {
            "query": keyword,
            "results": [{"hts_candidate": value} for value in candidates],
            "candidate_count": len(candidates),
            "official_search_url": web_url,
            "source": "United States International Trade Commission Harmonized Tariff Schedule",
            "source_mode": "OFFICIAL_WEB_FALLBACK",
            "scope": "US_IMPORTS",
            "checked_at": self._stamp(),
            "notice": "Fallback candidates come from the official USITC HTS search page. They support research only; verify the exact article description, legal notes and duty treatment before release.",
        }


usitc_tariff_provider = USITCTariffProvider()
