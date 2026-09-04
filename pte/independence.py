"""Independence detection: pages that copied the same spec block (or share an owner) vote once."""
from __future__ import annotations

import re
from collections import defaultdict

from .models import Claim

DOMAIN_OWNERS = {  # affiliates / same operator; extend from config
    "rozetka.com.ua": "rozetka", "prom.ua": "rozetka", "bigl.ua": "rozetka",
    "allegro.pl": "allegro", "ceneo.pl": "allegro",
    "shop-a.example": "groupA", "shop-c.example": "groupA",
}


def _shingles(s: str, k: int = 4) -> set[str]:
    toks = re.findall(r"\w+", s.lower())
    return {" ".join(toks[i:i + k]) for i in range(max(0, len(toks) - k + 1))}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def assign_clusters(claims: list[Claim], threshold: float = 0.8) -> dict[str, str]:
    """Returns url -> cluster id. Spec-block fingerprint = concatenation of that page's (field=raw) claims."""
    by_url: dict[str, list[Claim]] = defaultdict(list)
    for c in claims:
        by_url[c.url].append(c)
    urls = sorted(by_url)
    fp = {u: _shingles(" ; ".join(f"{c.field}={c.raw}" for c in sorted(by_url[u], key=lambda c: c.field))) for u in urls}
    parent = {u: u for u in urls}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    for i, a in enumerate(urls):
        for b in urls[i + 1:]:
            da, db = by_url[a][0].domain, by_url[b][0].domain
            same_owner = DOMAIN_OWNERS.get(da) is not None and DOMAIN_OWNERS.get(da) == DOMAIN_OWNERS.get(db)
            copied = len(fp[a]) >= 6 and _jaccard(fp[a], fp[b]) >= threshold
            if same_owner or copied:
                union(a, b)
    roots = {}
    out = {}
    for u in urls:
        r = find(u)
        roots.setdefault(r, f"c{len(roots) + 1}")
        out[u] = roots[r]
    return out
