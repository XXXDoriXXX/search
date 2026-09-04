"""Perplexity baseline: asks sonar-pro for the same fields with JSON output. Needs PERPLEXITY_API_KEY and network.

Writes eval/baselines/out/perplexity.jsonl as {id, fields:{path:value}, raw}. Compare with:
    python eval/run_eval.py --baseline eval/baselines/out/perplexity.jsonl
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pte.ontology import specs_for  # noqa: E402
from pte.query import understand  # noqa: E402

API = "https://api.perplexity.ai/chat/completions"


def ask(name: str, category: str, key: str, model: str = "sonar-pro") -> dict:
    specs = specs_for(category)
    fields = {f"{s.section}.{s.key}": (f"number in {s.unit}" if s.unit else s.kind) for s in specs}
    fields.update({"identity.mpn": "string", "identity.gtins": "array of strings"})
    prompt = (f"Product: {name}\nReturn a JSON object with exactly these keys (null when unknown). Numbers only, in the stated unit, no text.\n"
              f"{json.dumps(fields, ensure_ascii=False)}")
    r = httpx.post(API, headers={"Authorization": f"Bearer {key}"}, timeout=120, trust_env=True,
                   json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0,
                         "response_format": {"type": "json_schema", "json_schema": {"schema": {"type": "object", "properties": {k: {} for k in fields}}}}})
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"_unparsed": content}


def main():
    key = os.getenv("PERPLEXITY_API_KEY")
    if not key:
        print("PERPLEXITY_API_KEY not set; nothing done", file=sys.stderr)
        return 2
    out = ROOT / "eval/baselines/out/perplexity.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        for line in (ROOT / "eval/golden.jsonl").read_text().splitlines():
            if not line.strip():
                continue
            it = json.loads(line)
            cat = (it.get("hints") or {}).get("category") or understand(it["name"]).category
            ans = ask(it["name"], cat, key)
            fh.write(json.dumps({"id": it["id"], "fields": {k: v for k, v in ans.items() if not k.startswith("_")}, "raw": ans}, ensure_ascii=False) + "\n")
            print(it["id"], "done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
