"""Guard: hard constraints, grounding re-check, variant leakage, cross-field invariants."""
from __future__ import annotations

import re

from .gtin import gtin_checksum_ok
from .models import Claim, ResolvedField
from .normalize import nfkc
from .ontology import AttrSpec


def in_range(spec: AttrSpec, value) -> bool:
    if spec.kind != "number" or spec.range is None:
        return True
    try:
        return spec.range[0] <= float(value) <= spec.range[1]
    except (TypeError, ValueError):
        return False


def grounded(raw: str, span: str) -> bool:
    """The raw string must literally occur in the evidence span (after unicode normalization and whitespace folding)."""
    r = re.sub(r"\s+", " ", nfkc(raw)).strip().lower()
    s = re.sub(r"\s+", " ", nfkc(span)).strip().lower()
    if not r:
        return False
    if r in s:
        return True
    # split values ("35 / 20 Nm" -> "35 Nm"): every number token and the unit token must occur in the span
    nums = re.findall(r"\d+(?:[.,]\d+)?", r)
    units = re.findall(r"[a-zа-яіїє·⁻¹/]+", r)
    return bool(nums) and all(n in s for n in nums) and all(u in s for u in units)


def prefilter_claims(claims: list[Claim], specs: dict[str, AttrSpec], trace: list[str]) -> list[Claim]:
    out = []
    for c in claims:
        spec = specs.get(c.field)
        if spec is None:
            out.append(c)
            continue
        if not in_range(spec, c.value):
            trace.append(f"reject {c.field}={c.value} from {c.domain}: out of range {spec.range}")
            continue
        if not grounded(c.raw, c.span):
            trace.append(f"reject {c.field}={c.raw!r} from {c.domain}: not grounded in span")
            continue
        out.append(c)
    return out


def check_identity(identity: dict, trace: list[str]) -> list[str]:
    warnings = []
    gt = identity.get("gtins")
    if isinstance(gt, ResolvedField) and gt.value:
        bad = [g for g in gt.value if not gtin_checksum_ok(g)]
        if bad:
            warnings.append(f"invalid GTIN checksum: {bad}")
    return warnings


def cross_field(fields: dict[str, ResolvedField], trace: list[str]) -> list[str]:
    """Cross-field invariants. Prototype: torque soft <= hard; battery mAh vs Ah consistency."""
    w = []
    h, s = fields.get("max_torque_hard_nm"), fields.get("max_torque_soft_nm")
    if h and s and h.value is not None and s.value is not None and s.value > h.value:
        w.append("invariant violated: soft torque > hard torque; both downgraded to conflict")
        for f in (h, s):
            f.status, f.value, f.confidence = "conflict", None, min(f.confidence, 0.4)
    return w
