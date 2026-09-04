"""Structured extractors: JSON-LD schema.org/Product + Offer, OpenGraph. Highest extractor confidence."""
from __future__ import annotations

import json
import re
from typing import Any

from selectolax.parser import HTMLParser

from ..gtin import normalize_gtin


def _iter_jsonld(html: str):
    tree = HTMLParser(html)
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text())
        except json.JSONDecodeError:
            continue
        stack = [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
            elif isinstance(d, dict):
                yield d
                for v in d.values():
                    if isinstance(v, (dict, list)):
                        stack.append(v)


def _qv(x: Any) -> str | None:
    """schema.org QuantitativeValue or plain -> 'value unit' string."""
    if x is None:
        return None
    if isinstance(x, dict):
        v, u = x.get("value"), x.get("unitCode") or x.get("unitText")
        return f"{v} {u or ''}".strip() if v is not None else None
    return str(x)


def extract_structured(html: str | None) -> dict[str, Any]:
    """Returns {'identity': {...}, 'raw_fields': {key: raw_string}, 'offers': [...], 'images': [...]}"""
    out: dict[str, Any] = {"identity": {}, "raw_fields": {}, "offers": [], "images": [], "kind": None}
    if not html:
        return out
    for d in _iter_jsonld(html):
        t = d.get("@type")
        types = t if isinstance(t, list) else [t]
        if "Product" in types:
            out["kind"] = "Product"
            idn = out["identity"]
            brand = d.get("brand")
            idn["brand"] = brand.get("name") if isinstance(brand, dict) else brand
            manu = d.get("manufacturer")
            idn["manufacturer"] = manu.get("name") if isinstance(manu, dict) else manu
            idn["name"] = d.get("name")
            idn["model"] = _qv(d.get("model"))
            idn["mpn"] = d.get("mpn")
            idn["sku"] = d.get("sku")
            for k in ("gtin", "gtin8", "gtin12", "gtin13", "gtin14"):
                if d.get(k):
                    g = normalize_gtin(str(d[k]))
                    if g:
                        idn.setdefault("gtins", []).append(g)
            if d.get("color"):
                out["raw_fields"]["color"] = str(d["color"])
            if d.get("weight"):
                out["raw_fields"]["weight"] = _qv(d["weight"])
            for k in ("width", "height", "depth"):
                if d.get(k):
                    out["raw_fields"]["length" if k == "depth" else k] = _qv(d[k])
            for prop in d.get("additionalProperty", []) or []:
                if isinstance(prop, dict) and prop.get("name") and prop.get("value") is not None:
                    out["raw_fields"][str(prop["name"])] = _qv(prop.get("value")) + (f" {prop['unitText']}" if prop.get("unitText") else "")
            imgs = d.get("image")
            out["images"] += [imgs] if isinstance(imgs, str) else list(imgs or [])
            offers = d.get("offers")
            for o in (offers if isinstance(offers, list) else [offers] if offers else []):
                if isinstance(o, dict) and o.get("price") is not None:
                    try:
                        price = float(str(o["price"]).replace(",", "."))
                    except ValueError:
                        continue
                    out["offers"].append({"price": price, "currency": o.get("priceCurrency"), "availability": (o.get("availability") or "").split("/")[-1],
                                          "seller": (o.get("seller") or {}).get("name") if isinstance(o.get("seller"), dict) else o.get("seller")})
    tree = HTMLParser(html)
    for m in tree.css('meta[property^="og:"], meta[property^="product:"]'):
        p, c = m.attributes.get("property", ""), m.attributes.get("content", "")
        if p == "og:title" and not out["identity"].get("name"):
            out["identity"]["name"] = c
        if p == "product:retailer_item_id":
            out["identity"].setdefault("sku", c)
    return out


def page_kind(html: str | None, text: str) -> str:
    """'product' | 'listing' | 'document' | 'other' — used for page specificity weighting."""
    if html is None:
        return "document"
    if extract_structured(html)["kind"] == "Product":
        return "product"
    if len(re.findall(r"(?i)add to (cart|basket)|купити|в кошик|in den warenkorb", text)) > 3:
        return "listing"
    return "other"
