"""Truth Engine: equivalence classes -> independence-aware weighted voting (CRH-style iterations) -> statuses."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from .models import TIER_PRIOR, Candidate, Claim, ResolvedField, Resolution, SourceRef
from .normalize import display_value, equivalent
from .ontology import AttrSpec


@dataclass
class Group:
    value: object
    unit: str | None
    claims: list[Claim] = field(default_factory=list)
    score: float = 0.0

    @property
    def clusters(self) -> dict[str, list[Claim]]:
        d: dict[str, list[Claim]] = defaultdict(list)
        for c in self.claims:
            d[c.independence_cluster or c.url].append(c)
        return d


class Ledger:
    """Per (domain, category, field) Beta posterior of agreement with final truth. In-memory for the prototype."""

    def __init__(self):
        self.ab: dict[tuple[str, str, str], list[float]] = defaultdict(lambda: [1.0, 1.0])

    def weight(self, domain: str, category: str, fld: str) -> float:
        a, b = self.ab[(domain, category, fld)]
        return a / (a + b)

    def update(self, domain: str, category: str, fld: str, agree: bool):
        self.ab[(domain, category, fld)][0 if agree else 1] += 1


def local_weight(c: Claim, ledger: Ledger, category: str) -> float:
    return TIER_PRIOR[c.tier] * (2 * ledger.weight(c.domain, category, c.field)) * c.entity_match * c.extractor_confidence * c.page_specificity


def group_claims(claims: list[Claim], spec: AttrSpec) -> list[Group]:
    groups: list[Group] = []
    for c in sorted(claims, key=lambda c: -TIER_PRIOR[c.tier]):
        for g in groups:
            if equivalent(g.value, c.value, spec):
                g.claims.append(c)
                break
        else:
            groups.append(Group(value=c.value, unit=c.unit, claims=[c]))
    return groups


def resolve_field(spec: AttrSpec, claims: list[Claim], ledger: Ledger, category: str, source_w: dict[str, float]) -> ResolvedField:
    if not claims:
        return ResolvedField(status="unknown")
    groups = group_claims(claims, spec)
    for g in groups:
        s = 0.0
        for cl, cs in g.clusters.items():
            best = max(local_weight(c, ledger, category) * source_w.get(c.domain, 1.0) for c in cs)
            s += best * (1 + 0.1 * math.log(len(cs)))   # copies add a little, not a lot
        g.score = s
    groups.sort(key=lambda g: -g.score)
    total = sum(g.score for g in groups) or 1.0
    win = groups[0]
    margin = (win.score - (groups[1].score if len(groups) > 1 else 0.0)) / total
    indep = len(win.clusters)
    tiers_win = {c.tier for c in win.claims}
    tier_a_against = any(c.tier == "A" for g in groups[1:] for c in g.claims)
    tier_b_plus_against = sum(1 for g in groups[1:] for cl in g.clusters)

    def refs(g: Group) -> list[SourceRef]:
        seen, out = set(), []
        for c in sorted(g.claims, key=lambda c: (-TIER_PRIOR[c.tier], c.url)):
            if c.url in seen:
                continue
            seen.add(c.url)
            out.append(SourceRef(url=c.url, tier=c.tier, snippet=c.span[:300], fetched_at=c.fetched_at, snapshot=c.snapshot,
                                 independence_cluster=c.independence_cluster, entity_match=c.entity_match, extractor=c.extractor))
        return out

    cands = [Candidate(value=display_value(g.value, spec), unit=g.unit, score=round(g.score / total, 3), sources=sorted({c.url for c in g.claims}),
                       rejected_reason=None if g is win else _reject_reason(g, win)) for g in groups]
    raw = sorted({c.raw for c in win.claims})
    contexts = {c.context for c in win.claims if c.context}
    base = dict(value=display_value(win.value, spec), unit=win.unit, raw=raw, sources=refs(win), candidates=cands[1:] if len(cands) > 1 else [],
                context=next(iter(contexts)) if len(contexts) == 1 else None,
                applies_to="variant" if spec.variant_specific else "shared_across_variants")
    conf = min(0.99, 0.5 + 0.5 * margin) * (1.0 if indep >= 2 or "A" in tiers_win else 0.8)

    if "A" in tiers_win and not tier_a_against and margin >= 0.3:
        method = "tier_a_override" if indep == 1 else "weighted_vote"
        return ResolvedField(status="verified", confidence=round(max(conf, 0.9 if indep >= 2 else 0.86), 3),
                             resolution=Resolution(method=method, independent_votes=indep, margin=round(margin, 3)), **base)
    if indep >= 2 and margin >= 0.6 and not tier_a_against:
        return ResolvedField(status="verified", confidence=round(max(conf, 0.85), 3),
                             resolution=Resolution(method="weighted_vote", independent_votes=indep, margin=round(margin, 3)), **base)
    if len(groups) == 1 and indep == 1:
        return ResolvedField(status="single_source", confidence=round(min(conf, 0.8), 3),
                             resolution=Resolution(method="weighted_vote", independent_votes=1, margin=1.0), **base)
    # conflict
    return ResolvedField(status="conflict", value=None, unit=win.unit, raw=raw, sources=[], candidates=cands, confidence=round(conf * 0.6, 3),
                         resolution=Resolution(method="weighted_vote", independent_votes=indep, margin=round(margin, 3)),
                         applies_to=base["applies_to"])


def _reject_reason(g: Group, win: Group) -> str:
    n = sum(len(v) for v in g.clusters.values())
    k = len(g.clusters)
    ctx = {c.context for c in g.claims if c.context}
    parts = [f"outvoted ({k} independent vote{'s' if k != 1 else ''} from {n} page{'s' if n != 1 else ''})"]
    if k < n:
        parts.append("pages share an identical spec block (copy-chain)")
    if ctx and ctx != {c.context for c in win.claims if c.context}:
        parts.append(f"context {'/'.join(sorted(ctx))}")
    return "; ".join(parts)


def truth_discovery(claims: list[Claim], specs: dict[str, AttrSpec], ledger: Ledger, category: str, iters: int = 5) -> dict[str, ResolvedField]:
    """CRH-style: alternate between field truths and per-domain agreement weights within this run."""
    by_field: dict[str, list[Claim]] = defaultdict(list)
    for c in claims:
        by_field[c.field].append(c)
    source_w: dict[str, float] = defaultdict(lambda: 1.0)
    result: dict[str, ResolvedField] = {}
    for _ in range(iters):
        result = {f: resolve_field(specs[f], cs, ledger, category, source_w) for f, cs in by_field.items() if f in specs}
        agree: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for f, rf in result.items():
            if rf.status not in ("verified", "single_source"):
                continue
            for c in by_field[f]:
                ok = equivalent(rf.value, c.value, specs[f])
                agree[c.domain][0 if ok else 1] += 1
        new_w = {d: (1 + a) / (2 + a + b) * 2 for d, (a, b) in agree.items()}   # smoothed, in (0,2)
        if all(abs(new_w[d] - source_w[d]) < 1e-3 for d in new_w):
            break
        source_w.update(new_w)
    return result
