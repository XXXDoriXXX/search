"""Offline connector backed by a local index: {"leads": [{"url","title","snippet","match_any":[...],"tier"}]}.

Used for reproducible demos/tests; also the pattern for recorded-live fixtures in eval.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..models import Identifiers, Lead, QueryVariant


class FixtureConnector:
    id = "fixture"
    tier = "C"
    capabilities = {"search", "lookup_by_id"}

    def __init__(self, index_path: Path):
        self.index = json.loads(Path(index_path).read_text())
        self.base = Path(index_path).parent

    def local_map(self) -> dict[str, Path]:
        return {l["url"]: self.base / l["file"] for l in self.index["leads"]}

    @staticmethod
    def _norm(s: str) -> str:
        return re.sub(r"[\s\-_/\"']", "", s).lower()

    async def search(self, q: QueryVariant) -> list[Lead]:
        qn = self._norm(q.text)
        out = []
        for l in self.index["leads"]:
            terms = [self._norm(t) for t in l.get("match_any", [])]
            need = [self._norm(t) for t in l.get("require_all", [])]
            if terms and not any(t in qn for t in terms):
                continue
            if need and not all(t in qn for t in need):
                continue
            out.append(Lead(url=l["url"], title=l.get("title", ""), snippet=l.get("snippet", ""), connector=self.id,
                            tier_hint=l.get("tier"), query=q.text))
        return out

    async def lookup(self, ids: Identifiers) -> list[Lead]:
        keys = set(ids.gtins) | ({ids.mpn} if ids.mpn else set())
        return [Lead(url=l["url"], title=l.get("title", ""), connector=self.id, tier_hint=l.get("tier"), query="lookup")
                for l in self.index["leads"] if keys & set(l.get("ids", []))]
