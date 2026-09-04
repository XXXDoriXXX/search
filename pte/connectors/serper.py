"""Google results via serper.dev. Needs SERPER_API_KEY. Supports site:/filetype: operators."""
from __future__ import annotations

import os

import httpx

from ..models import Identifiers, Lead, QueryVariant


class SerperConnector:
    id = "serper_google"
    tier = "C"
    capabilities = {"search", "lookup_by_id"}

    def __init__(self, api_key: str | None = None, num: int = 10, gl: str = "us", hl: str = "en"):
        self.key = api_key or os.getenv("SERPER_API_KEY")
        self.num, self.gl, self.hl = num, gl, hl

    def available(self) -> bool:
        return bool(self.key)

    async def _search(self, text: str, hl: str | None = None) -> list[Lead]:
        async with httpx.AsyncClient(timeout=12, trust_env=True) as c:
            r = await c.post("https://google.serper.dev/search", json={"q": text, "num": self.num, "gl": self.gl, "hl": hl or self.hl},
                             headers={"X-API-KEY": self.key})
            r.raise_for_status()
        return [Lead(url=it["link"], title=it.get("title", ""), snippet=it.get("snippet", ""), connector=self.id, query=text)
                for it in r.json().get("organic", [])]

    async def search(self, q: QueryVariant) -> list[Lead]:
        return await self._search(q.text, hl=q.lang)

    async def lookup(self, ids: Identifiers) -> list[Lead]:
        out = []
        for key in ids.gtins + ([ids.mpn] if ids.mpn else []):
            out += await self._search(f'"{key}"')
        return out
