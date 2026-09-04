"""Evaluation harness: runs PTE on golden items and computes the acceptance metrics from docs/01.

Usage: python eval/run_eval.py [--golden eval/golden.jsonl] [--live] [--baseline eval/baselines/out/perplexity.jsonl]
Offline by default (fixtures). --live adds real connectors (needs network and, optionally, API keys).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pte import pipeline as pl  # noqa: E402
from pte.connectors import BraveConnector, ConnectorRegistry, DuckDuckGoConnector, FixtureConnector, SerperConnector, WikidataConnector  # noqa: E402
from pte.fetch import Fetcher  # noqa: E402
from pte.guard import grounded  # noqa: E402
from pte.normalize import canonical_string  # noqa: E402
from pte.pipeline import Pipeline  # noqa: E402
from pte.serialize import to_document  # noqa: E402


def same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= 0.03 * max(abs(float(a)), abs(float(b)), 1e-9)
    if isinstance(a, list) and isinstance(b, list):
        return sorted(map(str, a)) == sorted(map(str, b))
    return canonical_string(str(a)) == canonical_string(str(b))


def get_field(doc: dict, path: str) -> dict | None:
    sec, key = path.split(".", 1)
    return doc.get(sec, {}).get(key)


def score_doc(doc: dict, item: dict) -> dict:
    exp = item["expected"]
    m = {"entity_ok": 0, "fields_expected": 0, "covered": 0, "verified_total": 0, "verified_correct": 0, "single_total": 0, "single_correct": 0,
         "fabricated": 0, "values_total": 0, "forbidden_hits": 0, "status_expected": 0, "status_ok": 0}
    idn = doc["identity"]
    e_id = exp.get("identity", {})
    m["entity_ok"] = int(all(same(idn.get(k, {}).get("value"), v) for k, v in e_id.items()))
    for path, truth in exp.get("fields", {}).items():
        m["fields_expected"] += 1
        f = get_field(doc, path)
        if not f or f.get("value") is None:
            continue
        m["covered"] += 1
        ok = same(f["value"], truth)
        if f["status"] == "verified":
            m["verified_total"] += 1
            m["verified_correct"] += ok
        elif f["status"] == "single_source":
            m["single_total"] += 1
            m["single_correct"] += ok
    for sec in ("core", "attributes"):
        for key, f in doc.get(sec, {}).items():
            if f.get("value") is None:
                continue
            m["values_total"] += 1
            if not any(grounded(r, s.get("snippet", "")) for r in f.get("raw", []) for s in f.get("sources", [])):
                m["fabricated"] += 1
            for bad in exp.get("forbidden", {}).get(f"{sec}.{key}", []):
                if same(f["value"], bad):
                    m["forbidden_hits"] += 1
    for path, st in exp.get("expected_status", {}).items():
        m["status_expected"] += 1
        f = get_field(doc, path)
        m["status_ok"] += int(bool(f) and f.get("status") == st)
    return m


def score_baseline(doc: dict, item: dict) -> dict:
    """Baseline docs are flat {path: value}; no statuses, no provenance -> every value counts as an assertion."""
    exp = item["expected"]
    m = {"fields_expected": 0, "covered": 0, "correct": 0, "forbidden_hits": 0, "entity_ok": 0}
    m["entity_ok"] = int(all(same(doc.get(f"identity.{k}"), v) for k, v in exp.get("identity", {}).items()))
    for path, truth in exp.get("fields", {}).items():
        m["fields_expected"] += 1
        v = doc.get(path)
        if v is None:
            continue
        m["covered"] += 1
        m["correct"] += same(v, truth)
    for path, bads in exp.get("forbidden", {}).items():
        v = doc.get(path)
        if v is not None and any(same(v, b) for b in bads):
            m["forbidden_hits"] += 1
    return m


async def run_item(item: dict, live: bool, cache: Path) -> dict:
    connectors, local = [], {}
    if item.get("fixtures"):
        fx = FixtureConnector(ROOT / item["fixtures"])
        connectors.append(fx)
        local = fx.local_map()
        for l in fx.index["leads"]:
            if l.get("tier"):
                pl.TIER_BY_DOMAIN[l["url"].split("/")[2].removeprefix("www.")] = l["tier"]
    if live:
        connectors += [DuckDuckGoConnector(), WikidataConnector()] + [c for c in (BraveConnector(), SerperConnector()) if c.available()]
    for d, t in item.get("tiers", {}).items():
        pl.TIER_BY_DOMAIN[d] = t
    fetcher = Fetcher(cache, offline=not live, local_map=local)
    async with fetcher:
        out = await Pipeline(ConnectorRegistry(connectors), fetcher).run(item["name"], hints=item.get("hints"))
    return to_document(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default=str(ROOT / "eval/golden.jsonl"))
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--baseline", help="jsonl of {id, fields:{path:value}} from eval/baselines/*.py")
    ap.add_argument("--cache", default=str(ROOT / ".pte_cache"))
    ap.add_argument("--out", default=str(ROOT / "eval/out"))
    args = ap.parse_args()
    items = [json.loads(l) for l in Path(args.golden).read_text().splitlines() if l.strip()]
    base = {}
    if args.baseline and Path(args.baseline).exists():
        base = {json.loads(l)["id"]: json.loads(l)["fields"] for l in Path(args.baseline).read_text().splitlines() if l.strip()}
    Path(args.out).mkdir(parents=True, exist_ok=True)
    tot = {}
    btot = {}
    for it in items:
        doc = asyncio.run(run_item(it, args.live, Path(args.cache)))
        (Path(args.out) / f"{it['id']}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2))
        m = score_doc(doc, it)
        for k, v in m.items():
            tot[k] = tot.get(k, 0) + v
        if it["id"] in base:
            for k, v in score_baseline(base[it["id"]], it).items():
                btot[k] = btot.get(k, 0) + v
    n = len(items)

    def pct(a, b):
        return f"{100 * a / b:.1f}%" if b else "n/a"

    print(f"items: {n}")
    print(f"AC-C1 entity accuracy:           {pct(tot['entity_ok'], n)}")
    print(f"AC-C2 precision@verified:        {pct(tot['verified_correct'], tot['verified_total'])}  ({tot['verified_correct']}/{tot['verified_total']})")
    print(f"AC-C3 precision@single_source:   {pct(tot['single_correct'], tot['single_total'])}  ({tot['single_correct']}/{tot['single_total']})")
    print(f"AC-C4 fabrication rate:          {pct(tot['fabricated'], tot['values_total'])}  ({tot['fabricated']}/{tot['values_total']})")
    print(f"AC-C7 variant/sibling leakage:   {tot['forbidden_hits']} forbidden values emitted")
    print(f"AC-C5 expected statuses:         {pct(tot['status_ok'], tot['status_expected'])}")
    print(f"AC-R  coverage of golden fields: {pct(tot['covered'], tot['fields_expected'])}")
    if btot:
        print("--- baseline (same golden, flat answers, no provenance) ---")
        print(f"entity accuracy: {pct(btot['entity_ok'], n)} | precision: {pct(btot['correct'], btot['covered'])} | coverage: {pct(btot['covered'], btot['fields_expected'])} | forbidden hits: {btot['forbidden_hits']}")
    blocking = tot["fabricated"] == 0 and tot["forbidden_hits"] == 0 and tot["verified_correct"] == tot["verified_total"]
    print("BLOCKING ACs:", "PASS" if blocking else "FAIL")
    return 0 if blocking else 1


if __name__ == "__main__":
    sys.exit(main())
