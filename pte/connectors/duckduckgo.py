"""DuckDuckGo HTML endpoint: no API key. Rate-limit friendly; used as the zero-cost baseline index."""
from __future__ import annotations

import httpx
from selectolax.parser import HTMLParser

from ..models import Identifiers, Lead, QueryVariant


class DuckDuckGoConnector:
    id = "duckduckgo"
    tier = "C"
    capabilities = {"search", "lookup_by_id"}

    def __init__(self, max_results: int = 10):
        self.max_results = max_results

    async def _search(self, text: str) -> list[Lead]:
        async with httpx.AsyncClient(timeout=12, trust_env=True, follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0 PTE/0.1"}) as c:
            r = await c.post("https://html.duckduckgo.com/html/", data={"q": text})
            r.raise_for_status()
        tree = HTMLParser(r.text)
        out = []
        for res in tree.css("div.result")[: self.max_results]:
            a = res.css_first("a.result__a")
            sn = res.css_first("a.result__snippet")
            if a and a.attributes.get("href"):
                out.append(Lead(url=a.attributes["href"], title=a.text(strip=True), snippet=sn.text(strip=True) if sn else "",
                                connector=self.id, query=text))
        return out

    async def search(self, q: QueryVariant) -> list[Lead]:
        return await self._search(q.text)

    async def lookup(self, ids: Identifiers) -> list[Lead]:
        out = []
        for key in ids.gtins + ([ids.mpn] if ids.mpn else []):
            out += await self._search(f'"{key}"')
        return out
