"""Output -> JSON document that validates against schema/product.schema.json (drops None except the mandatory `value`)."""
from __future__ import annotations

import json
from typing import Any

from .models import Output

FIELD_KEYS = {"status", "confidence", "sources"}


def _restore_value(node: Any) -> Any:
    if isinstance(node, dict):
        if FIELD_KEYS <= node.keys() and "value" not in node:
            node["value"] = None
        for v in node.values():
            _restore_value(v)
    elif isinstance(node, list):
        for v in node:
            _restore_value(v)
    return node


def to_document(out: Output) -> dict:
    return _restore_value(json.loads(out.model_dump_json(exclude_none=True)))
