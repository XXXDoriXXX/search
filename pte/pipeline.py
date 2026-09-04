"""Orchestrator: R0 understand -> R1 anchor -> R2 harvest -> R3 hole-driven rounds -> R4 truth -> R5 guard -> R6 assemble/learn."""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .connectors.base import ConnectorRegistry
from .extract.llm import LLMExtractor
from .extract.structured import extract_structured, page_kind
from .extract.tables import extract_kv, split_hard_soft
from .fetch import Fetcher
from .gtin import find_gtins
from .guard import check_identity, cross_field, prefilter_claims
from .independence import assign_clusters
from .match import entity_match, model_presence
from .models import (Anchor, Claim, Identifiers, Lead, Output, Page, QueryHypothesis, QueryVariant, ResolvedField, Resolution,
                     RunMeta, SourceRef, Unresolved)
from .normalize import normalize_value
from .ontology import AttrSpec, category_path, spec_index, synonym_index
from .query import hole_queries, normalize_model, understand
from .truth import Ledger, truth_discovery

TIER_BY_DOMAIN: dict[str, str] = {}  # filled from config: manufacturer domains -> A, icecat -> B ...
CONTEXT_HINTS = [
    (re.compile(r"(?i)excl\.?\s*batt|without batt|ohne akku|без акум|без батар|net"), "net_without_battery"),
    (re.compile(r"(?i)incl\.?\s*batt|with batt|mit akku|з акум|с акум|gross"), "with_battery"),
    (re.compile(r"(?i)package|packag|упаков|verpack"), "package"),
]


@dataclass
class Budget:
    max_rounds: int = 3
    max_pages: int = 60
    max_seconds: float = 60.0
    gain_eps: float = 0.05


@dataclass
class Trace:
    events: list[str] = field(default_factory=list)
    search_log: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def log(self, msg: str):
        self.events.append(msg)


def tier_for(page: Page, lead_hint: str | None) -> str:
    return TIER_BY_DOMAIN.get(page.domain) or lead_hint or "C"


def _key_norm(k: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", k.lower())).strip()


def map_key(key: str, syn: list[tuple[str, AttrSpec]]) -> AttrSpec | None:
    k = _key_norm(key)
    for s, spec in syn:
        s = _key_norm(s)
        if k == s or k.startswith(s + " ") or k.endswith(" " + s) or (len(s) > 5 and s in k):
            return spec
    return None


def context_of(key: str, raw: str) -> str | None:
    blob = f"{key} {raw}"
    for rx, ctx in CONTEXT_HINTS:
        if rx.search(blob):
            return ctx
    return None


class Pipeline:
    def __init__(self, registry: ConnectorRegistry, fetcher: Fetcher, ledger: Ledger | None = None, llm: LLMExtractor | None = None,
                 budget: Budget | None = None, on_event: Callable[[str, Any], None] | None = None):
        self.registry, self.fetcher = registry, fetcher
        self.ledger = ledger or Ledger()
        self.llm = llm or LLMExtractor()
        self.budget = budget or Budget()
        self.on_event = on_event or (lambda kind, data: None)

    # ---------- R1 ----------
    async def anchor(self, h: QueryHypothesis, trace: Trace) -> tuple[Anchor, list[Page]]:
        queries = [v for v in h.variants if v.purpose == "anchor"][:6]
        leads = await self.registry.search_all(queries) + await self.registry.lookup_all(h.identifiers)
        for q in queries:
            trace.search_log["_anchor"].append(q.text)
        pages = await self.fetcher.fetch_many([l.url for l in leads][: self.budget.max_pages // 2])
        hints = {l.url: l.tier_hint for l in leads}
        tn = h.model_normalized or ""
        cands = []
        for p in pages:
            st = extract_structured(p.html)
            ids = Identifiers(gtins=st["identity"].get("gtins") or find_gtins(p.text[:4000]), mpn=st["identity"].get("mpn"))
            title = st["identity"].get("name") or ""
            head = (title + " " + p.text[:400]).upper()
            n_exact, sibs = model_presence(head, tn)
            exact, sib = n_exact > 0, bool(sibs)
            tier = tier_for(p, hints.get(p.url))
            score = (0.9 if exact else 0.2) * (1.0 if tier == "A" else 0.8 if tier == "B" else 0.6) * (0.7 if sib and not exact else 1.0)
            cands.append((p, ids, title, score, tier))
        # cluster by identifiers / exact model
        key_ids: dict[str, Identifiers] = {}
        support: dict[str, list[str]] = defaultdict(list)
        score_sum: dict[str, float] = defaultdict(float)
        for p, ids, title, score, tier in cands:
            key = ids.mpn and normalize_model(ids.mpn) or (ids.gtins[0] if ids.gtins else None) or ("MODEL:" + tn if score >= 0.5 else "OTHER:" + p.domain)
            key_ids.setdefault(key, Identifiers())
            key_ids[key].gtins = sorted(set(key_ids[key].gtins) | set(ids.gtins))
            key_ids[key].mpn = key_ids[key].mpn or ids.mpn
            support[key].append(p.url)
            score_sum[key] += score
        # merge MODEL cluster into the identifier cluster it co-occurs with (pages carrying both)
        ranked = sorted(score_sum.items(), key=lambda kv: -kv[1])
        best_key, best_score = (ranked[0] if ranked else (None, 0.0))
        ids = key_ids.get(best_key, Identifiers()) if best_key else Identifiers()
        # absorb gtins/mpn seen on any exact-model page
        for p, pids, title, score, tier in cands:
            if score >= 0.5:
                ids.gtins = sorted(set(ids.gtins) | set(pids.gtins))
                ids.mpn = ids.mpn or pids.mpn
        for g in h.identifiers.gtins:
            if g not in ids.gtins:
                ids.gtins.append(g)
        conf = min(0.99, 0.4 + 0.15 * len(support.get(best_key, []))) if best_key and not best_key.startswith("OTHER") else 0.2
        axes = {t.split("=")[0]: t.split("=", 1)[1] for t in h.variant_tokens}
        anchor = Anchor(brand=h.brand, model=h.model, model_normalized=h.model_normalized, identifiers=ids, category=h.category, variant_axes=axes,
                        canonical_name=" ".join(x for x in [h.brand, h.model] if x), confidence=round(conf, 3),
                        supporting_urls=support.get(best_key, []),
                        alternatives=[{"key": k, "score": round(s, 2), "urls": support[k][:3]} for k, s in ranked[1:4] if not k.startswith("OTHER")],
                        langs=["en"] + [l for l in ("de", "uk") if any(v.lang == l for v in h.variants)])
        trace.log(f"anchor: {anchor.canonical_name} ids={ids.model_dump()} conf={conf:.2f} support={len(anchor.supporting_urls)}")
        self.on_event("anchor_found", anchor.model_dump())
        return anchor, pages

    # ---------- R2 ----------
    async def harvest(self, anchor: Anchor, pages: list[Page], hints: dict[str, str | None], trace: Trace) -> tuple[list[Claim], list[dict], list[dict]]:
        specs = spec_index(anchor.category)
        syn = synonym_index(anchor.category)
        claims: list[Claim] = []
        offers, images = [], []
        for p in pages:
            st = extract_structured(p.html)
            ids = Identifiers(gtins=st["identity"].get("gtins") or [], mpn=st["identity"].get("mpn"))
            tier = tier_for(p, hints.get(p.url))
            m = entity_match(p, anchor, ids, st["identity"].get("name") or "", tier=tier)
            kind = page_kind(p.html, p.text)
            spec_w = 1.0 if kind in ("product", "document") else 0.6
            trace.log(f"page {p.domain} tier={tier} match={m.score} ({m.reason}) kind={kind}")
            if m.score < 0.5:
                continue
            for o in st["offers"]:
                offers.append({**o, "url": p.url, "seller": o.get("seller") or p.domain, "as_of": p.fetched_at})
            images += [{"url": u, "source": p.domain, "entity_match": m.score} for u in st["images"][:3]]
            raw_pairs: list[tuple[str, str, str, float, str]] = []  # key, raw, span, conf, extractor
            for k, v in st["raw_fields"].items():
                raw_pairs.append((k, v, f"{k}: {v}", 0.95, "jsonld"))
            for k, v, span in extract_kv(p.text):
                for k2, v2 in split_hard_soft(k, v):
                    raw_pairs.append((k2, v2, span, 0.85 if p.mime == "text/html" else 0.9, "kv"))
            if self.llm.available() and tier in ("A", "B"):
                about, llm_claims = await self.llm.extract(p.text, anchor.canonical_name, list(specs.values()))
                if about:
                    raw_pairs += [(c["field"], c["raw"], c["evidence"], 0.7, "llm") for c in llm_claims]
            for key, raw, span, conf, ext in raw_pairs:
                spec = specs.get(key) or map_key(key, syn)
                if spec is None:
                    continue
                nv = normalize_value(raw, spec)
                if nv is None:
                    continue
                value, unit = nv
                if spec.variant_specific and not m.variant_ok:
                    continue
                claims.append(Claim(field=spec.key, value=value, unit=unit, raw=raw, span=span, context=context_of(key, raw), url=p.url, domain=p.domain,
                                    tier=tier, extractor=ext, extractor_confidence=conf, entity_match=m.score, variant_ok=m.variant_ok,
                                    snapshot=p.snapshot, fetched_at=p.fetched_at, page_specificity=spec_w))
        return claims, offers, images

    # ---------- R3 ----------
    def holes(self, fields: dict[str, ResolvedField], specs: dict[str, AttrSpec]) -> list[AttrSpec]:
        out = []
        for key, spec in specs.items():
            rf = fields.get(key)
            if rf is None or rf.status in ("unknown", "single_source", "conflict"):
                out.append((spec.weight * (1 - (rf.confidence if rf else 0.0)), spec))
        return [s for _, s in sorted(out, key=lambda t: -t[0])]

    # ---------- run ----------
    async def run(self, name: str, hints: dict | None = None, mode: str = "standard") -> Output:
        t0 = time.monotonic()
        trace = Trace()
        run_id = "run_" + uuid.uuid4().hex[:12]
        h = understand(name, hints)
        trace.log(f"understand: brand={h.brand} model={h.model} category={h.category} variant={h.variant_tokens}")
        specs = spec_index(h.category)
        anchor, pages = await self.anchor(h, trace)
        lead_hints: dict[str, str | None] = {}
        # harvest leads: anchor pages + harvest queries + id lookups
        hq = [v for v in h.variants if v.purpose in ("anchor", "harvest")]
        leads = await self.registry.search_all(hq) + await self.registry.lookup_all(anchor.identifiers)
        for l in leads:
            lead_hints[l.url] = l.tier_hint
        seen_urls = {p.url for p in pages}
        more = await self.fetcher.fetch_many([l.url for l in leads if l.url not in seen_urls][: self.budget.max_pages])
        pages = pages + more
        claims, offers, images = await self.harvest(anchor, pages, lead_hints, trace)
        claims = prefilter_claims(claims, specs, trace.events)
        clusters = assign_clusters(claims)
        for c in claims:
            c.independence_cluster = clusters.get(c.url)
        fields = truth_discovery(claims, specs, self.ledger, h.category)
        self.on_event("round_done", {"round": 1, "fields": {k: v.status for k, v in fields.items()}})
        rounds = 1
        prev_conf = {k: f.confidence for k, f in fields.items()}
        # hole-driven rounds
        while rounds < self.budget.max_rounds and (time.monotonic() - t0) < self.budget.max_seconds:
            holes = self.holes(fields, specs)[:10]
            if not holes:
                break
            queries: list[QueryVariant] = []
            for spec in holes:
                for q in hole_queries(anchor.brand, anchor.model or h.raw, anchor.identifiers.mpn, spec.key, h.category, anchor.langs)[:2]:
                    queries.append(q)
                    trace.search_log[spec.key].append(q.text)
            new_leads = await self.registry.search_all(queries)
            for l in new_leads:
                lead_hints.setdefault(l.url, l.tier_hint)
            urls = [l.url for l in new_leads if l.url not in {p.url for p in pages}]
            if not urls:
                trace.log(f"round {rounds + 1}: no new leads for holes {[s.key for s in holes]}")
                break
            new_pages = await self.fetcher.fetch_many(urls[: self.budget.max_pages])
            pages += new_pages
            nc, no, ni = await self.harvest(anchor, new_pages, lead_hints, trace)
            nc = prefilter_claims(nc, specs, trace.events)
            claims += nc
            offers += no
            images += ni
            clusters = assign_clusters(claims)
            for c in claims:
                c.independence_cluster = clusters.get(c.url)
            fields = truth_discovery(claims, specs, self.ledger, h.category)
            rounds += 1
            conf = {k: f.confidence for k, f in fields.items()}
            gain = sum(abs(conf[k] - prev_conf.get(k, 0.0)) for k in conf)   # any movement (new evidence or new conflict) counts
            trace.log(f"round {rounds}: +{len(nc)} claims, gain={gain:.3f}")
            self.on_event("round_done", {"round": rounds, "gain": gain})
            prev_conf = conf
            if gain < self.budget.gain_eps:
                break
        # guard + assemble
        warnings = cross_field(fields, trace.events)
        identity = self._identity(anchor, pages, lead_hints, trace)
        warnings += check_identity(identity, trace.events)
        warnings += [f"connector {c} failed" for c in sorted(self.registry.failed)]
        core = {k: v for k, v in fields.items() if specs[k].section == "core"}
        attrs = {k: v for k, v in fields.items() if specs[k].section == "attributes"}
        for key, spec in specs.items():
            if key not in fields:
                (core if spec.section == "core" else attrs)[key] = ResolvedField(status="unknown")
        unresolved = []
        for key, rf in {**core, **attrs}.items():
            if rf.status in ("unknown", "conflict"):
                reason = ("no claims after %d round(s)" % rounds) if rf.status == "unknown" else self._conflict_reason(rf)
                unresolved.append(Unresolved(field=f"{specs[key].section}.{key}", status=rf.status, reason=reason, candidates=rf.candidates,
                                             search_log=trace.search_log.get(key, [])))
        # learn: ledger update
        for c in claims:
            rf = fields.get(c.field)
            if rf and rf.status in ("verified", "single_source"):
                from .normalize import equivalent
                self.ledger.update(c.domain, h.category, c.field, equivalent(rf.value, c.value, specs[c.field]))
        meta = RunMeta(run_id=run_id, mode=mode, rounds=rounds, duration_ms=int((time.monotonic() - t0) * 1000),
                       sources_consulted=len({p.domain for p in pages}), pages_fetched=len(pages), connectors_failed=sorted(self.registry.failed))
        out = Output(identity=identity, core=core, attributes=attrs, extra={}, media={"images": images[:10], "documents": [
            {"url": p.url, "kind": "datasheet", "snapshot": p.snapshot} for p in pages if p.mime == "application/pdf"], "videos": []},
            offers=offers, relations={"variants": [], "accessories": [], "compatible_with": [], "replaces": [], "replaced_by": []},
            unresolved=unresolved, warnings=warnings, meta=meta)
        out.__dict__["_trace"] = trace.events
        return out

    def _identity(self, anchor: Anchor, pages: list[Page], hints: dict, trace: Trace) -> dict:
        def fld(value, urls: list[str], tier="A", snippet="") -> ResolvedField:
            refs = []
            for u in urls[:3]:
                p = next((p for p in pages if p.url == u), None)
                if p:
                    refs.append(SourceRef(url=u, tier=tier_for(p, hints.get(u)), snippet=snippet or str(value), fetched_at=p.fetched_at, snapshot=p.snapshot))
            st = "verified" if len(refs) >= 2 or any(r.tier == "A" for r in refs) else "single_source" if refs else "unknown"
            return ResolvedField(value=value, status=st, confidence=0.95 if st == "verified" else 0.7 if refs else 0.0, sources=refs,
                                 resolution=Resolution(method="identifier" if refs else "none", independent_votes=len(refs), margin=1.0))
        sup = anchor.supporting_urls
        return {
            "status": "resolved" if anchor.confidence >= 0.6 else "resolved_with_ambiguity" if anchor.confidence >= 0.4 else "unresolved",
            "confidence": anchor.confidence,
            "brand": fld(anchor.brand, sup), "model": fld(anchor.model, sup), "model_normalized": anchor.model_normalized,
            "variant": {"axes": {k: fld(v, sup) for k, v in anchor.variant_axes.items()}},
            "mpn": fld(anchor.identifiers.mpn, sup) if anchor.identifiers.mpn else ResolvedField(status="unknown"),
            "gtins": fld(anchor.identifiers.gtins, sup) if anchor.identifiers.gtins else ResolvedField(status="unknown"),
            "category_path": category_path(anchor.category), "canonical_name": anchor.canonical_name,
            "aliases": [], "lifecycle": {}, "alternatives_considered": anchor.alternatives,
        }

    @staticmethod
    def _conflict_reason(rf: ResolvedField) -> str:
        parts = []
        for c in rf.candidates[:3]:
            parts.append(f"{c.value}{' ' + c.unit if c.unit else ''} ({c.score:.2f}; {len(c.sources)} page(s){'; ' + c.rejected_reason if c.rejected_reason else ''})")
        return "candidates: " + " vs ".join(parts)


async def resolve(name: str, registry: ConnectorRegistry, fetcher: Fetcher, **kw) -> Output:
    async with fetcher:
        return await Pipeline(registry, fetcher, **kw).run(name, **{k: v for k, v in kw.items() if k in ("hints", "mode")})
