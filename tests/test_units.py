import pytest

from pte.gtin import find_gtins, gtin_checksum_ok, normalize_gtin
from pte.guard import grounded
from pte.independence import assign_clusters
from pte.match import model_presence, sibling_of
from pte.models import Claim
from pte.normalize import equivalent, normalize_value, parse_number
from pte.ontology import spec_index
from pte.query import understand
from pte.truth import Ledger, truth_discovery

SPECS = spec_index("tools/power_tools")


def test_gtin_checksum():
    assert gtin_checksum_ok("3165140876643")
    assert not gtin_checksum_ok("3165140876644")
    assert normalize_gtin("0 316514 087664 3") == "3165140876643"
    assert find_gtins("EAN 3165140876643 and junk 1234567890123") == ["3165140876643"]


@pytest.mark.parametrize("raw,expected", [("1,750", 1750), ("0.59", 0.59), ("0,59", 0.59), ("1.234,56", 1234.56), ("1,234.56", 1234.56)])
def test_parse_number(raw, expected):
    assert parse_number(raw) == pytest.approx(expected)


def test_normalize_units():
    w = SPECS["weight_g"]
    assert normalize_value("0.59 kg", w) == (590.0, "g")
    assert normalize_value("2.65 lb", w)[0] == pytest.approx(1202.0, rel=0.01)
    assert normalize_value("12 V", SPECS["voltage_v"]) == (12.0, "V")
    assert normalize_value("0 – 1,750 rpm", SPECS["no_load_speed_rpm"]) == (1750.0, "rpm")
    assert normalize_value("3 years", SPECS["warranty_months"]) == (36.0, "months")
    assert normalize_value("24 місяці", SPECS["warranty_months"]) == (24.0, "months")
    assert normalize_value("12 kg", SPECS["voltage_v"]) is None  # unit family mismatch is rejected, not coerced
    assert normalize_value("Brushless (EC)", SPECS["motor_type"]) == ("brushless", None)


def test_equivalence_tolerance():
    assert equivalent(590, 600, SPECS["weight_g"])       # 3% tolerance
    assert not equivalent(590, 800, SPECS["weight_g"])
    assert not equivalent(35, 30, SPECS["max_torque_hard_nm"])  # exact field


def test_query_understanding():
    h = understand("Шуруповерт Bosch GSR 12V-35 FC Professional solo")
    assert (h.brand, h.model, h.model_normalized, h.category) == ("Bosch", "GSR 12V-35 FC", "GSR12V35FC", "tools/power_tools")
    assert "kit=solo" in h.variant_tokens
    h = understand("iphone 15 pro 256 чорний")
    assert h.model == "iphone 15 pro" and "storage_gb=256" in h.variant_tokens and "color=чорний" in h.variant_tokens
    assert understand("Siemens 6ES7214-1AG40-0XB0").model == "6ES7214-1AG40-0XB0"


def test_sibling_logic():
    assert sibling_of("GSR12V35FC", "GSR12V35")
    assert sibling_of("GSR12V35FC", "GSB12V35FC")
    assert not sibling_of("GSR12V35FC", "GSR12V35FC")
    # the prefix code appearing only inside the full code is NOT a sibling
    n, sibs = model_presence("BOSCH GSR 12V-35 FC PROFESSIONAL", "GSR12V35FC")
    assert n == 1 and sibs == set()
    # ...but appearing on its own is
    n, sibs = model_presence("GSR 12V-35 FC. Also see GSR 12V-35 and GSB 12V-35", "GSR12V35FC")
    assert n == 1 and "GSR12V35" in sibs
    n, sibs = model_presence("BOSCH GSR 12V-35 PROFESSIONAL", "GSR12V35FC")
    assert n == 0 and "GSR12V35" in sibs


def test_grounding():
    assert grounded("0.59 kg", "Weight excl. battery: 0.59 kg")
    assert grounded("35 Nm", "Max. torque (hard/soft): 35 / 20 Nm")   # split value, tokens present
    assert not grounded("36 Nm", "Max. torque (hard/soft): 35 / 20 Nm")
    assert not grounded("590 g", "Weight: 0.59 kg")                  # normalization is not grounding: raw must be literal


def _claim(field, value, raw, url, tier, em=0.9, span=None, unit=None, domain=None):
    return Claim(field=field, value=value, unit=unit, raw=raw, span=span or f"{field}: {raw}", url=url, domain=domain or url.split("/")[2], tier=tier,
                 extractor="kv", extractor_confidence=0.85, entity_match=em, variant_ok=True, snapshot="sha256:" + "0" * 64, fetched_at="2026-09-04T00:00:00Z")


def test_copy_chain_collapses_votes():
    copies = [_claim("max_torque_hard_nm", 30.0, "30 Nm", f"https://shop-{x}.example/p", "C") for x in "xyz"]
    for c in copies:  # identical spec blocks
        c.span = "Voltage: 12 V; Max torque: 30 Nm; Weight: 0.8 kg; Warranty: 24 months; Color: Blue; Speed: 1750 rpm"
    volt = [_claim("voltage_v", 12.0, "12 V", c.url, "C") for c in copies]
    wt = [_claim("weight_g", 800.0, "0.8 kg", c.url, "C") for c in copies]
    wr = [_claim("warranty_months", 24.0, "24 months", c.url, "C") for c in copies]
    clusters = assign_clusters(copies + volt + wt + wr)
    assert len(set(clusters.values())) == 1, clusters
    a = _claim("max_torque_hard_nm", 35.0, "35 Nm", "https://maker.example/p", "A", em=1.0)
    b = _claim("max_torque_hard_nm", 35.0, "35 Nm", "https://icecat.example/p", "B")
    allc = copies + [a, b]
    for c in allc:
        c.independence_cluster = clusters.get(c.url, c.url)
    res = truth_discovery(allc, SPECS, Ledger(), "tools/power_tools")
    f = res["max_torque_hard_nm"]
    assert f.status == "verified" and f.value == 35 and f.resolution.independent_votes == 2
    assert f.candidates[0].value == 30 and "copy-chain" in f.candidates[0].rejected_reason


def test_conflict_abstains():
    c1 = _claim("warranty_months", 24.0, "24 months", "https://shop-x.example/p", "C")
    c2 = _claim("warranty_months", 36.0, "3 years", "https://forum.example/t", "D")
    res = truth_discovery([c1, c2], SPECS, Ledger(), "tools/power_tools")
    f = res["warranty_months"]
    assert f.status == "conflict" and f.value is None and len(f.candidates) == 2


def test_tier_a_alone_is_verified_but_tier_a_contradicted_is_conflict():
    a = _claim("voltage_v", 12.0, "12 V", "https://maker.example/p", "A", em=1.0)
    assert truth_discovery([a], SPECS, Ledger(), "tools/power_tools")["voltage_v"].status == "verified"
    b = _claim("voltage_v", 18.0, "18 V", "https://icecat.example/p", "B")
    c = _claim("voltage_v", 18.0, "18 V", "https://shop-q.example/p", "C")
    f = truth_discovery([a, b, c], SPECS, Ledger(), "tools/power_tools")["voltage_v"]
    assert f.status == "conflict"   # manufacturer vs two independents: abstain rather than guess
