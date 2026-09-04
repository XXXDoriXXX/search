"""R0: Query understanding. Turns a noisy product name into a structured hypothesis + query variants."""
from __future__ import annotations

import re

from .gtin import find_gtins
from .models import Identifiers, QueryHypothesis, QueryVariant
from .ontology import BRAND_LEXICON, CATEGORIES, specs_for

ASIN_RE = re.compile(r"\b(B0[A-Z0-9]{8})\b")
MODEL_TOKEN_RE = re.compile(r"[A-Za-z]{1,6}[- ]?\d{1,5}[A-Za-z0-9\-/.]*|\d+[A-Za-z][A-Za-z0-9\-/.]{2,}")
SERIES_WORDS = {"professional"}
STORAGE_BARE_RE = re.compile(r"^(64|128|256|512|1024|2048)$")
VARIANT_WORDS = {
    "color": ["black", "white", "blue", "red", "green", "gray", "grey", "silver", "gold", "чорний", "білий", "синій", "сірий", "черный", "белый", "серый", "schwarz", "weiß", "blau"],
    "kit": ["solo", "body only", "bare tool", "без акб", "без акумулятора", "l-boxx", "kit", "набір", "набор"],
    "storage_gb": [r"\b(\d{2,4})\s?(gb|гб|tb|тб)\b", r"(?<![\w.])(64|128|256|512|1024|2048)(?![\w.])"],
}
TRANSLIT = str.maketrans({"а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t", "х": "x", "у": "y",
                          "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X", "У": "Y"})


def normalize_model(m: str | None) -> str | None:
    if not m:
        return None
    return re.sub(r"[\s\-_/.]", "", m).upper()


def detect_brand(text: str) -> str | None:
    low = text.lower()
    for brand, info in BRAND_LEXICON.items():
        for a in info["aliases"]:
            if re.search(rf"(?<![a-z]){re.escape(a)}(?![a-z])", low):
                return brand.title() if brand != "dewalt" else "DeWalt"
    # heuristic: first capitalized token that is not a model code
    for tok in text.split():
        if tok[:1].isupper() and not re.search(r"\d", tok) and len(tok) > 2:
            return tok
    return None


def detect_category(text: str, brand: str | None) -> tuple[str, float]:
    low = text.lower()
    best, score = "generic", 0.0
    for cat, info in CATEGORIES.items():
        hits = sum(1 for k in info["keywords"] if k in low)
        if hits > score:
            best, score = cat, hits
    return best, min(1.0, 0.5 + 0.25 * score) if score else 0.3


def extract_model(text: str, brand: str | None) -> tuple[str | None, list[str]]:
    t = text
    if brand:
        t = re.sub(re.escape(brand), " ", t, flags=re.I)
    # fix mixed-script codes like "GSR 12V-35" typed with Cyrillic letters: translit only tokens that mix digits and Cyrillic
    t_lat = " ".join(tok.translate(TRANSLIT) if re.search(r"[А-Яа-я]", tok) and re.search(r"\d", tok) else tok for tok in t.split())
    variant_tokens = []
    for axis, words in VARIANT_WORDS.items():
        for w in words:
            if w.startswith(r"\b") or w.startswith("(?<!"):
                m = re.search(w, t_lat, re.I)
                if m:
                    variant_tokens.append(f"{axis}={m.group(1)}")
            elif re.search(rf"(?<!\w){re.escape(w)}(?!\w)", t_lat, re.I):
                variant_tokens.append(f"{axis}={w.lower()}")
    codes = MODEL_TOKEN_RE.findall(t_lat)
    if not codes:
        # fallback: strip variant words and take the remainder
        rem = t_lat
        for vt in variant_tokens:
            rem = re.sub(re.escape(vt.split("=", 1)[1]), " ", rem, flags=re.I)
        rem = re.sub(r"\s+", " ", rem).strip(" ,.-")
        return (rem or None), variant_tokens
    # model = longest contiguous span starting at first code, up to 4 tokens, excluding variant words
    start = t_lat.find(codes[0])
    tail = t_lat[start:].split()
    keep = []
    for tok in tail[:4]:
        tl = tok.lower().strip(",.")
        if STORAGE_BARE_RE.match(tl) or any(tl == w for ws in VARIANT_WORDS.values() for w in ws if not (w.startswith(r"\b") or w.startswith("(?<!"))):
            break
        if tl in SERIES_WORDS:
            continue
        keep.append(tok)
    model = " ".join(keep).strip(" ,.-")
    return model, variant_tokens


def generate_variants(brand: str | None, model: str | None, model_norm: str | None, category: str, langs: list[str], raw: str) -> list[QueryVariant]:
    out: list[QueryVariant] = []
    seen = set()

    def add(text: str, purpose="anchor", lang="en", target=None):
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(QueryVariant(text=text, purpose=purpose, lang=lang, target_field=target))

    b = brand or ""
    if model:
        add(f'{b} "{model}"'.strip())
        add(f"{b} {model}".strip())
        add(f'"{model}" specifications')
        add(f'"{model}" datasheet pdf')
        add(f"{b} {model} technical data".strip())
        if model_norm and model_norm != model.replace(" ", ""):
            add(f"{b} {model_norm}".strip())
        if "de" in langs:
            add(f"{b} {model} technische Daten".strip(), lang="de")
        if "uk" in langs:
            add(f"{b} {model} характеристики".strip(), lang="uk")
    add(raw)
    return out


def understand(name: str, hints: dict | None = None) -> QueryHypothesis:
    hints = hints or {}
    raw = name.strip()
    norm = re.sub(r"\s+", " ", raw)
    ids = Identifiers(gtins=find_gtins(norm), asin=(ASIN_RE.search(norm) or [None, None])[1] if ASIN_RE.search(norm) else None)
    text_wo_ids = norm
    for g in ids.gtins:
        text_wo_ids = text_wo_ids.replace(g, " ")
    brand = hints.get("brand") or detect_brand(text_wo_ids)
    category, cat_conf = (hints["category"], 1.0) if hints.get("category") else detect_category(text_wo_ids, brand)
    model, variant_tokens = extract_model(text_wo_ids, brand)
    langs = BRAND_LEXICON.get((brand or "").lower(), {}).get("langs", ["en"])
    model_norm = normalize_model(model)
    return QueryHypothesis(
        raw=raw, normalized=norm, brand=brand, model=model, model_normalized=model_norm,
        variant_tokens=variant_tokens, identifiers=ids, category=category, category_confidence=cat_conf,
        variants=generate_variants(brand, model, model_norm, category, langs, norm),
    )


def hole_queries(brand: str | None, model: str, mpn: str | None, field_key: str, category: str, langs: list[str]) -> list[QueryVariant]:
    spec = next((s for s in specs_for(category) if s.key == field_key), None)
    words = spec.human if spec and spec.human else {"en": (spec.synonyms[0] if spec and spec.synonyms else field_key.replace("_", " "))}
    out = [QueryVariant(text=f'"{model}" {words.get("en", field_key)}', purpose="hole", lang="en", target_field=field_key)]
    for lang in langs:
        if lang != "en" and lang in words:
            out.append(QueryVariant(text=f'"{model}" {words[lang]}', purpose="hole", lang=lang, target_field=field_key))
    if mpn:
        out.append(QueryVariant(text=f'"{mpn}" {words.get("en", field_key)}', purpose="hole", target_field=field_key))
    if spec and "datasheet" in spec.expected_in:
        out.append(QueryVariant(text=f"{brand or ''} {model} datasheet".strip(), purpose="hole", target_field=field_key))
    return out
