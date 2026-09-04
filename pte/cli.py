"""CLI: python -m pte "Bosch GSR 12V-35 FC" [--offline --fixtures fixtures/demo/index.json] [--json out.json]"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from . import pipeline as pl
from .connectors import BraveConnector, ConnectorRegistry, DuckDuckGoConnector, FixtureConnector, SerperConnector, WikidataConnector
from .fetch import Fetcher
from .pipeline import Budget, Pipeline
from .serialize import to_document


def build(args) -> tuple[ConnectorRegistry, Fetcher]:
    connectors, local = [], {}
    if args.fixtures:
        fx = FixtureConnector(Path(args.fixtures))
        connectors.append(fx)
        local = fx.local_map()
        for l in fx.index["leads"]:
            if l.get("tier"):
                from urllib.parse import urlsplit
                pl.TIER_BY_DOMAIN[urlsplit(l["url"]).netloc.lower().removeprefix("www.")] = l["tier"]
    if not args.offline:
        connectors.append(DuckDuckGoConnector())
        connectors.append(WikidataConnector())
        for C in (BraveConnector, SerperConnector):
            c = C()
            if c.available():
                connectors.append(c)
    for d in (args.tier_a or []):
        pl.TIER_BY_DOMAIN[d] = "A"
    for d in (args.tier_b or []):
        pl.TIER_BY_DOMAIN[d] = "B"
    reg = ConnectorRegistry(connectors)
    fetcher = Fetcher(Path(args.cache), offline=args.offline, local_map=local)
    return reg, fetcher


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pte")
    ap.add_argument("name")
    ap.add_argument("--mode", default="standard", choices=["fast", "standard", "deep"])
    ap.add_argument("--offline", action="store_true", help="no network; fixtures + cache only")
    ap.add_argument("--fixtures", help="path to fixture index.json")
    ap.add_argument("--cache", default=os.getenv("PTE_CACHE", ".pte_cache"))
    ap.add_argument("--tier-a", nargs="*", help="domains treated as manufacturer/tier A")
    ap.add_argument("--tier-b", nargs="*")
    ap.add_argument("--category")
    ap.add_argument("--json", help="write full output JSON here")
    ap.add_argument("--trace", action="store_true")
    args = ap.parse_args(argv)
    budget = {"fast": Budget(max_rounds=1, max_pages=20, max_seconds=8), "standard": Budget(), "deep": Budget(max_rounds=8, max_pages=200, max_seconds=300)}[args.mode]
    reg, fetcher = build(args)

    async def go():
        async with fetcher:
            p = Pipeline(reg, fetcher, budget=budget)
            return await p.run(args.name, hints={"category": args.category} if args.category else None, mode=args.mode)

    out = asyncio.run(go())
    doc = to_document(out)
    if args.json:
        Path(args.json).write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    print_summary(out)
    if args.trace:
        print("\n--- trace ---")
        print("\n".join(out.__dict__["_trace"]))
    return 0


def print_summary(out):
    idn = out.identity
    print(f"identity: {idn['canonical_name']} [{idn['status']} {idn['confidence']:.2f}] mpn={idn['mpn'].value} gtins={idn['gtins'].value}")
    for section in ("core", "attributes"):
        for k, f in getattr(out, section).items():
            v = f"{f.value}{' ' + f.unit if f.unit and f.value is not None else ''}"
            src = f" <- {len(f.sources)} src, {f.resolution.independent_votes if f.resolution else 0} indep" if f.sources else ""
            cand = f" | candidates: {[(c.value, c.score) for c in f.candidates]}" if f.candidates else ""
            print(f"  {section}.{k:24s} {f.status:14s} {f.confidence:.2f}  {v}{src}{cand}")
    if out.unresolved:
        print("unresolved:")
        for u in out.unresolved:
            print(f"  {u.field}: {u.status}: {u.reason}")
    if out.warnings:
        print("warnings:", out.warnings)
    print(f"meta: rounds={out.meta.rounds} pages={out.meta.pages_fetched} domains={out.meta.sources_consulted} {out.meta.duration_ms}ms")


if __name__ == "__main__":
    sys.exit(main())
