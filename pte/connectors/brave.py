"""Brave Search API (independent index). Needs BRAVE_API_KEY."""
from __future__ import annotations

import os

import httpx

from ..models import Identifiers, Lead, QueryVariant


class BraveConnector:
    id = "brave"
    tier = "C"
    capabilities = {"search", "lookup_by_id"}

    def __init__(self, api_key: str | None = None, count: int = 10):
        self.key = api_key or os.getenv("BRAVE_API_KEY")
        self.count = count

    def available(self) -> bool:
        return bool(self.key)

    async def _search(self, text: str) -> list[Lead]:
        async with httpx.AsyncClient(timeout=12, trust_env=True) as c:
            r = await c.get("https://api.search.brave.com/res/v1/web/search", params={"q": text, "count": self.count},
                            headers={"X-Subscription-Token": self.key, "Accept": "application/json"})
            r.raise_for_status()
        return [Lead(url=it["url"], title=it.get("title", ""), snippet=it.get("description", ""), connector=self.id, query=text)
                for it in r.json().get("web", {}).get("results", [])]

    async def search(self, q: QueryVariant) -> list[Lead]:
        return await self._search(q.text)

    async def lookup(self, ids: Identifiers) -> list[Lead]:
        out = []
        for key in ids.gtins + ([ids.mpn] if ids.mpn else []):
            out += await self._search(f'"{key}"')
        return out
