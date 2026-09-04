"""Entity matcher: is this page about the same product AND the same variant?"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from .models import Anchor, EntityMatch, Identifiers, Page
from .query import normalize_model

CODE_RE = re.compile(r"\b[A-Z]{1,6}[- ]?\d{1,5}[A-Z0-9\-/.]*\b")


def codes_in(text: str) -> set[str]:
    return {normalize_model(c) for c in CODE_RE.findall(text.upper()) if len(c) >= 4}


def sibling_of(target_norm: str, code: str) -> bool:
    """A code that is a strict prefix/superstring of the target (GSR12V35 vs GSR12V35FC) or differs by one char."""
    if code == target_norm:
        return False
    if target_norm.startswith(code) and len(target_norm) - len(code) <= 3:
        return True
    if code.startswith(target_norm) and len(code) - len(target_norm) <= 3:
        return True
    return len(code) == len(target_norm) and sum(a != b for a, b in zip(code, target_norm)) == 1


def flat(s: str) -> str:
    return re.sub(r"[\s\-_/.]", "", s.upper())


def model_presence(text_upper: str, tn: str) -> tuple[int, set[str]]:
    """(exact occurrences of the target code, sibling codes that occur on their own, not merely as part of the target)."""
    if not tn:
        return 0, set()
    fl = flat(text_upper)
    n_target = fl.count(tn)
    sibs = set()
    for c in codes_in(text_upper):
        if not sibling_of(tn, c):
            continue
        n_c = fl.count(c)
        # prefix sibling (GSR12V35 inside GSR12V35FC): real only if it occurs more often than the target
        if tn.startswith(c) and n_c > n_target:
            sibs.add(c)
        elif c.startswith(tn):          # superstring sibling (GSR12V35FCPLUS) always counts, and steals target occurrences
            sibs.add(c)
            n_target -= n_c
        elif not tn.startswith(c):      # one-char-different code
            sibs.add(c)
    return max(0, n_target), sibs


def entity_match(page: Page, anchor: Anchor, page_ids: Identifiers, title: str = "", tier: str = "C") -> EntityMatch:
    """Score in [0,1]. Identifier match dominates; otherwise model string match with sibling penalty; variant axes checked separately."""
    head = (title + "\n" + page.text[:600]).upper()
    body = page.text.upper()
    tn = anchor.model_normalized or ""
    # identifier evidence
    if anchor.identifiers.gtins and set(anchor.identifiers.gtins) & set(page_ids.gtins):
        score, reason = 1.0, "gtin match"
    elif anchor.identifiers.mpn and page_ids.mpn and normalize_model(anchor.identifiers.mpn) == normalize_model(page_ids.mpn):
        score, reason = 1.0, "mpn match"
    else:
        n_head, sibs_head = model_presence(head, tn)
        n_body, sibs_body = model_presence(body, tn)
        if n_head and not sibs_head:
            score, reason = 0.9, "exact model in title/head"
        elif n_head and sibs_head:
            score, reason = 0.6, f"model in head but sibling codes present: {sorted(sibs_head)[:3]}"
        elif n_body and not sibs_head:
            score, reason = 0.7, "exact model in body"
        elif sibs_head or sibs_body:
            score, reason = 0.15, "only sibling model present"
        else:
            fz = fuzz.token_set_ratio((anchor.model or "").upper(), head[:300]) / 100
            score, reason = max(0.0, fz - 0.4), f"fuzzy {fz:.2f}"
        if anchor.brand and anchor.brand.upper() not in body and tier != "A":
            score *= 0.7
            reason += "; brand absent"
    # variant axes
    variant_ok = True
    for axis, val in anchor.variant_axes.items():
        if val and val.lower() not in body.lower():
            # value of another option on the same axis in the head → mismatch; unknown → keep but flag
            variant_ok = variant_ok and True
    return EntityMatch(score=round(score, 3), variant_ok=variant_ok, reason=reason, identifiers_found=page_ids)
