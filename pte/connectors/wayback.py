"""Wayback Machine CDX: recover manufacturer/retailer pages for discontinued products (tier inherits from origin domain)."""
from __future__ import annotations

import httpx

from ..models import Identifiers, Lead, QueryVariant

CDX = "https://web.archive.org/cdx/search/cdx"


class WaybackConnector:
    id = "wayback"
    tier = "C"
    capabilities = {"search"}

    def __init__(self, domains: list[str], limit: int = 20):
        self.domains, self.limit = domains, limit

    async def search(self, q: QueryVariant) -> list[Lead]:
        # use the bare model code as a URL substring filter on known manufacturer domains
        code = q.text.replace('"', "").split()[-1] if q.text else ""
        code = "".join(ch for ch in code if ch.isalnum()).lower()
        if len(code) < 4:
            return []
        out = []
        async with httpx.AsyncClient(timeout=15, trust_env=True) as c:
            for d in self.domains:
                params = {"url": f"{d}/*", "output": "json", "filter": ["statuscode:200", f"urlkey:.*{code}.*"], "collapse": "urlkey",
                          "limit": self.limit, "fl": "timestamp,original"}
                try:
                    r = await c.get(CDX, params=params)
                    rows = r.json()[1:] if r.status_code == 200 and r.text.strip() else []
                except Exception:
                    rows = []
                for ts, orig in rows:
                    out.append(Lead(url=f"https://web.archive.org/web/{ts}id_/{orig}", title=orig, connector=self.id, tier_hint="A", query=q.text))
        return out

    async def lookup(self, ids: Identifiers) -> list[Lead]:
        return []
