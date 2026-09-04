"""Wikidata as identifier hub (tier B): entity search + GTIN (P3962), MPN-ish (P2359? no: uses 'model number' P1072 rarely), manufacturer (P176)."""
from __future__ import annotations

import httpx

from ..models import Identifiers, Lead, QueryVariant

API = "https://www.wikidata.org/w/api.php"


class WikidataConnector:
    id = "wikidata"
    tier = "B"
    capabilities = {"search"}

    async def search(self, q: QueryVariant) -> list[Lead]:
        text = q.text.replace('"', "")
        async with httpx.AsyncClient(timeout=12, trust_env=True, headers={"User-Agent": "PTE/0.1 (product resolver)"}) as c:
            r = await c.get(API, params={"action": "wbsearchentities", "search": text, "language": "en", "format": "json", "limit": 5})
            r.raise_for_status()
            hits = r.json().get("search", [])
            out = []
            for h in hits:
                # fetch sitelink to English Wikipedia for a readable page; the entity JSON itself is the evidence carrier
                out.append(Lead(url=f"https://www.wikidata.org/wiki/Special:EntityData/{h['id']}.json", title=h.get("label", ""),
                                snippet=h.get("description", ""), connector=self.id, tier_hint="B", query=q.text))
        return out

    async def lookup(self, ids: Identifiers) -> list[Lead]:
        return []
