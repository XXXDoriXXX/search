"""End-to-end on the offline demo corpus. Asserts the behaviours that distinguish PTE from answer engines."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures" / "demo" / "index.json"


@pytest.fixture(scope="module")
def output(tmp_path_factory):
    if not FIX.exists():
        subprocess.run([sys.executable, str(ROOT / "fixtures/demo/build.py")], check=True)
    from pte import pipeline as pl
    from pte.connectors import ConnectorRegistry, FixtureConnector
    from pte.fetch import Fetcher
    from pte.pipeline import Pipeline
    fx = FixtureConnector(FIX)
    for l in fx.index["leads"]:
        pl.TIER_BY_DOMAIN[l["url"].split("/")[2].removeprefix("www.")] = l["tier"]
    fetcher = Fetcher(tmp_path_factory.mktemp("cache"), offline=True, local_map=fx.local_map())

    async def go():
        async with fetcher:
            return await Pipeline(ConnectorRegistry([fx]), fetcher).run("Bosch GSR 12V-35 FC")
    return asyncio.run(go())


def test_identity_anchored(output):
    idn = output.identity
    assert idn["status"] == "resolved" and idn["mpn"].value == "06019H3002" and idn["gtins"].value == ["3165140876643"]


def test_copied_retailer_error_does_not_win(output):
    f = output.attributes["max_torque_hard_nm"]
    assert f.status == "verified" and f.value == 35
    assert any(c.value == 30 and "copy-chain" in (c.rejected_reason or "") for c in f.candidates)


def test_sibling_model_excluded(output):
    for section in (output.core, output.attributes):
        for f in section.values():
            assert all("shop-d.example" not in s.url for s in f.sources)


def test_weight_context_and_votes(output):
    f = output.core["weight_g"]
    assert f.status == "verified" and f.value == 590 and f.resolution.independent_votes >= 2
    assert any(c.value == 800 for c in f.candidates)


def test_hole_driven_round_found_forum_and_abstained(output):
    f = output.core["warranty_months"]
    assert output.meta.rounds >= 2
    assert f.status == "conflict" and f.value is None and {c.value for c in f.candidates} == {24, 36}
    assert any(u.field == "core.warranty_months" and u.search_log for u in output.unresolved)


def test_zero_fabrication(output):
    """Every non-null value is backed by a source whose snippet literally contains one of the raw strings."""
    from pte.guard import grounded
    for section in (output.core, output.attributes):
        for key, f in section.items():
            if f.value is None:
                continue
            assert f.sources, key
            assert any(grounded(r, s.snippet) for r in f.raw for s in f.sources), (key, f.raw, [s.snippet for s in f.sources])


def test_output_validates_against_schema(output):
    schema = json.loads((ROOT / "schema/product.schema.json").read_text())
    from pte.serialize import to_document
    doc = to_document(output)
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(doc)
