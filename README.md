# Product Truth Engine (PTE)

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-2-E92063?logo=pydantic&logoColor=white)
![httpx](https://img.shields.io/badge/httpx-async_fetch-2C5BB4)
![pytest](https://img.shields.io/badge/tested_with-pytest-0A9EDC?logo=pytest&logoColor=white)
![JSON Schema](https://img.shields.io/badge/output-JSON_Schema-000000?logo=json&logoColor=white)

Given a product name, PTE collects as much data as possible about **that exact product**, resolves conflicts between sources, and returns clean JSON in which every field carries evidence (provenance), a confidence value and a verification status.

PTE does not search and paraphrase; it **establishes facts**. Every value goes through identifier anchoring, entity matching, independent source voting, hard constraints and an abstain policy. If a fact cannot be proven, the system returns `unknown` together with its candidates instead of a plausible guess.

## Features

- **Identifier-first search**: anchors on MPN, GTIN/EAN/UPC and manufacturer IDs so data about a sibling model is not mixed into the target product.
- **Hole-driven search**: after each round it finds missing or conflicting fields and generates targeted queries until the budget runs out or gains flatten.
- **Truth discovery**: iterative weighted voting (CRH style) over source authority, freshness, entity-match quality and source independence.
- **Copy-chain detection**: shops that copied the same spec block count as one vote, not several.
- **Hard constraints**: value ranges, GTIN checksum, cross-field invariants, and a grounding check that rejects values not present in the source text.
- **Abstain policy**: statuses `verified`, `single_source`, `conflict`, `inferred` and `unknown`, always with candidates and evidence.
- **Pluggable connectors**: DuckDuckGo, Brave, Serper, Wikidata, Wayback and an offline fixture connector, each behind a circuit breaker.
- **Evaluation harness**: golden set, acceptance-criteria metrics and an optional Perplexity baseline.

## Demo traps the prototype handles

| Trap | What answer engines do | What PTE does |
|---|---|---|
| Three shops copied a spec block with a wrong "30 Nm" | "Consensus" 3 vs 1 | Copies collapse into one vote; 35 Nm from the manufacturer, PDF and aggregator wins; 30 Nm stays a candidate with reason `copy-chain` |
| Page for a neighbouring model (GSR 12V-35, no FC) | Mixes specs | Entity match 0.15, no value reaches the output |
| Weight 0.8 kg (with battery) vs 0.59 kg (without) | Picks either | 590 g `verified` with 3 votes, 800 g kept as a candidate with `context` |
| Warranty: shops say 24 months, forum says 3 years | Confidently names one | `conflict`, value null, both candidates with evidence and a `search_log` |
| Field missing after round one | Nothing | Hole-driven query finds the forum in round two |
| Value not present in the source text | Hallucination | Grounding check rejects the claim before voting |

## Getting started

Requires Python 3.11 or newer. The design is documented in Ukrainian under `docs/`; the code and CLI are in English.

```bash
git clone -b claude/product-data-parser-g61ar7 https://github.com/XXXDoriXXX/search.git
cd search
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Run the offline demo (no network, no keys):

```bash
python3 fixtures/demo/build.py
python3 -m pte "Bosch GSR 12V-35 FC" --offline --fixtures fixtures/demo/index.json --trace --json out.json
```

Run the tests and the acceptance metrics:

```bash
python3 -m pytest -q        # 21 tests
python3 eval/run_eval.py    # AC-C1..C7 metrics on the golden set
```

A recorded result of the demo run is in `examples/demo-run.json` (full JSON with evidence) and `examples/demo-run.txt`.

### Live mode

Needs network access. DuckDuckGo HTML and Wikidata work without keys.

```bash
python3 -m pte "Bosch GSR 12V-35 FC" --tier-a bosch-professional.com --tier-b icecat.biz --trace --json live.json
```

Optional keys unlock more connectors and the LLM extractor:

```bash
export SERPER_API_KEY=...
export BRAVE_API_KEY=...
export ANTHROPIC_API_KEY=...
python3 -m pte "Makita DGA504Z" --tier-a makita.de makita.com --mode deep --json live.json
```

Compare with Perplexity on the same golden set:

```bash
export PERPLEXITY_API_KEY=...
python3 eval/baselines/perplexity.py
python3 eval/run_eval.py --live --baseline eval/baselines/out/perplexity.jsonl
```

Live mode was not exercised in the author's environment, so treat it as unverified.

### CLI options

| Option | Description |
|---|---|
| `name` | Product name to resolve. |
| `--mode` | `fast`, `standard` (default) or `deep`. |
| `--offline` | No network; fixtures and cache only. |
| `--fixtures` | Path to the fixture `index.json`. |
| `--cache` | Cache directory. Default `.pte_cache` or `$PTE_CACHE`. |
| `--tier-a`, `--tier-b` | Domains treated as manufacturer (tier A) or aggregator (tier B). |
| `--category` | Product category hint. |
| `--json` | Write the full output JSON to this path. |
| `--trace` | Print the search and decision trace. |

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `SERPER_API_KEY` | No | Google results via serper.dev. |
| `BRAVE_API_KEY` | No | Brave Search connector. |
| `ANTHROPIC_API_KEY` | No | Enables the LLM extractor for tier A/B pages. Requires the `anthropic` package (included in `requirements.txt`). |
| `PERPLEXITY_API_KEY` | No | Only for the Perplexity baseline in `eval/`. |
| `PTE_CACHE` | No | Default cache directory. |

## Project structure

| Module | Role |
|---|---|
| `pte/query.py` | Brand, model code, variant axes, category, query variants and hole queries |
| `pte/connectors/` | `SourceConnector` protocol and registry with circuit breaker; DuckDuckGo, Brave, Serper, Wikidata, Wayback, Fixture |
| `pte/fetch.py` | httpx with content-addressed cache, per-domain concurrency, HTML and PDF to text |
| `pte/extract/` | JSON-LD/OpenGraph, key-value and table extraction, optional LLM extractor with mandatory evidence |
| `pte/match.py` | Entity match: identifiers, exact code, sibling detection |
| `pte/independence.py` | Copy-chain detection with shingle Jaccard and domain owners |
| `pte/truth.py` | Equivalence classes with tolerance, weight iterations, statuses, ledger |
| `pte/guard.py` | Ranges, grounding, cross-field invariants, GTIN checksum |
| `pte/pipeline.py` | Round orchestration, budgets, hole-driven loop, document assembly |
| `eval/` | Golden set, acceptance metrics, Perplexity baseline |
| `schema/product.schema.json` | JSON Schema of the output document |

Not yet implemented from the design: Temporal orchestration, Common Crawl, regulatory databases, vision/OCR, an LLM arbiter for `conflict`, a persistent knowledge graph (the ledger is in-memory) and ontologies beyond two categories.

## Design documents (Ukrainian)

| # | Document | Topic |
|---|---|---|
| 01 | [Problem and acceptance criteria](docs/01-problem-and-acceptance-criteria.md) | What "100% correct" means, product tiers, modes, measurable criteria |
| 02 | [Architecture](docs/02-architecture.md) | Components, data flow, parallelism, stack |
| 03 | [Algorithm](docs/03-algorithm.md) | Adaptive multi-round search, truth discovery, pseudocode |
| 04 | [Sources and rare products](docs/04-sources-and-rare-products.md) | Source authority taxonomy, playbook for scarce products |
| 05 | [Output schema](docs/05-output-schema.md) | Field envelope, core schema, category extensions |
| 06 | [Options and trade-offs](docs/06-options-and-tradeoffs.md) | Options per layer and the recommendation |
| 07 | [Brainstorm](docs/07-brainstorm.md) | Ideas rated by impact and effort |
| 08 | [Evaluation and roadmap](docs/08-evaluation-and-roadmap.md) | Golden dataset, metrics, phases |

See also [QUICKSTART.md](QUICKSTART.md) for a two-minute check.
