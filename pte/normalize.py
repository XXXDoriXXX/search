"""Value normalization: numbers with units -> canonical units; strings -> canonical; equivalence tests."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from .ontology import AttrSpec

# unit -> (canonical_unit, factor)
UNIT_TABLE: dict[str, tuple[str, float]] = {
    # mass -> g
    "g": ("g", 1), "gram": ("g", 1), "grams": ("g", 1), "г": ("g", 1), "гр": ("g", 1),
    "kg": ("g", 1000), "кг": ("g", 1000), "kilogram": ("g", 1000),
    "lb": ("g", 453.592), "lbs": ("g", 453.592), "oz": ("g", 28.3495),
    # length -> mm
    "mm": ("mm", 1), "мм": ("mm", 1), "cm": ("mm", 10), "см": ("mm", 10), "m": ("mm", 1000), "м": ("mm", 1000),
    "in": ("in", 1), "inch": ("in", 1), "inches": ("in", 1), '"': ("in", 1), "″": ("in", 1), "дюйм": ("in", 1),
    # electrical
    "v": ("V", 1), "в": ("V", 1), "volt": ("V", 1), "volts": ("V", 1),
    "nm": ("Nm", 1), "н·м": ("Nm", 1), "нм": ("Nm", 1), "n·m": ("Nm", 1), "n.m": ("Nm", 1),
    "rpm": ("rpm", 1), "об/хв": ("rpm", 1), "об/мин": ("rpm", 1), "min-1": ("rpm", 1), "min⁻¹": ("rpm", 1), "/min": ("rpm", 1), "u/min": ("rpm", 1),
    "ah": ("Ah", 1), "а·г": ("Ah", 1), "mah": ("mAh", 1), "ма·г": ("mAh", 1), "мач": ("mAh", 1),
    "w": ("W", 1), "вт": ("W", 1), "kw": ("W", 1000),
    "gb": ("GB", 1), "гб": ("GB", 1), "tb": ("GB", 1024), "тб": ("GB", 1024), "mb": ("GB", 1 / 1024),
    # time -> months
    "month": ("months", 1), "months": ("months", 1), "міс": ("months", 1), "місяців": ("months", 1), "місяці": ("months", 1), "мес": ("months", 1), "monate": ("months", 1), "mo": ("months", 1),
    "year": ("months", 12), "years": ("months", 12), "yr": ("months", 12), "рік": ("months", 12), "роки": ("months", 12), "років": ("months", 12), "год": ("months", 12), "года": ("months", 12), "лет": ("months", 12), "jahre": ("months", 12), "jahr": ("months", 12), "lata": ("months", 12),
}

# convert between canonical units when the target differs (e.g. in -> mm)
CROSS: dict[tuple[str, str], float] = {("in", "mm"): 25.4, ("mm", "in"): 1 / 25.4, ("mAh", "Ah"): 0.001, ("Ah", "mAh"): 1000}

NUM_RE = re.compile(r"(?<![\w.,])([-+]?\d+(?:[ ,. ]\d{3})*(?:[.,]\d+)?)(?!\d)\s*([A-Za-zА-Яа-яЁёіІїЇєЄ·⁻¹/\"″]{0,8})")


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def parse_number(tok: str) -> float | None:
    t = tok.strip().replace(" ", "").replace(" ", "")
    # decide decimal separator
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        parts = t.split(",")
        if len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) <= 3:  # 1,750 thousands
            t = t.replace(",", "")
        else:
            t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def parse_quantity(raw: str, spec: AttrSpec) -> tuple[float, str] | None:
    """Return (value, canonical_unit) for the first number+unit in raw, converted to spec.unit."""
    text = nfkc(raw).lower()
    best = None
    for m in NUM_RE.finditer(text):
        num = parse_number(m.group(1))
        unit = m.group(2).strip().rstrip(".")
        if num is None:
            continue
        if unit in UNIT_TABLE:
            canon, factor = UNIT_TABLE[unit]
            val = num * factor
            if spec.unit and canon != spec.unit:
                if (canon, spec.unit) in CROSS:
                    val, canon = val * CROSS[(canon, spec.unit)], spec.unit
                else:
                    continue  # unit family mismatch: skip
            return (round(val, 4), canon)
        if not unit and best is None:
            best = (num, spec.unit or "")
    # bare number: accept only if the field has a unit and text mentions nothing conflicting
    return best


def canonical_string(s: str) -> str:
    s = nfkc(s).casefold().strip()
    s = re.sub(r"[\s\-_/]+", " ", s)
    s = re.sub(r"[^\w\s.]", "", s)
    return s.strip()


BOOL_TRUE = {"yes", "так", "да", "ja", "tak", "true", "1", "included", "в комплекті", "в комплекте"}
BOOL_FALSE = {"no", "ні", "нет", "nein", "nie", "false", "0", "not included", "without", "без", "solo", "body only", "bare tool"}

ENUMS = {
    "motor_type": {"brushless": ["brushless", "безщітковий", "бесщеточный", "bürstenlos", "bl"], "brushed": ["brushed", "щітковий", "щеточный", "bürsten"]},
}


def normalize_value(raw: str, spec: AttrSpec) -> tuple[Any, str | None] | None:
    raw = raw.strip()
    if not raw:
        return None
    if spec.kind == "number":
        q = parse_quantity(raw, spec)
        return (q[0], q[1] or spec.unit) if q else None
    if spec.kind == "bool":
        c = canonical_string(raw)
        if c in BOOL_TRUE or any(c.startswith(t) for t in BOOL_TRUE):
            return (True, None)
        if c in BOOL_FALSE or any(c.startswith(t) for t in BOOL_FALSE):
            return (False, None)
        return None
    if spec.kind == "enum":
        c = canonical_string(raw)
        for canon, syns in ENUMS.get(spec.key, {}).items():
            if any(s in c for s in syns):
                return (canon, None)
        return (c, None)
    if spec.kind == "list":
        items = [i.strip() for i in re.split(r"[;,\n•]+", raw) if i.strip()]
        return (items, None) if items else None
    return (re.sub(r"\s+", " ", raw).strip(), None)


def equivalent(a: Any, b: Any, spec: AttrSpec) -> bool:
    if spec.kind == "number":
        try:
            fa, fb = float(a), float(b)
        except (TypeError, ValueError):
            return False
        if fa == fb:
            return True
        tol = spec.tolerance * max(abs(fa), abs(fb))
        return abs(fa - fb) <= max(tol, 1e-9)
    if spec.kind == "list":
        sa, sb = set(map(canonical_string, a)), set(map(canonical_string, b))
        return bool(sa) and len(sa & sb) / len(sa | sb) >= 0.8
    if spec.kind == "bool":
        return a is b
    return canonical_string(str(a)) == canonical_string(str(b))


def display_value(v: Any, spec: AttrSpec) -> Any:
    if spec.kind == "number" and isinstance(v, float) and v.is_integer():
        return int(v)
    return v
