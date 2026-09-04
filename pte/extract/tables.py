"""Key-value spec extraction from readable text (tables were flattened to 'key: value' lines by the fetcher).

Produces raw (key, value, span) triples; ontology mapping happens in the pipeline.
"""
from __future__ import annotations

import re

KV_LINE = re.compile(r"^\s*([^:\n]{2,60}?)\s*[:：]\s*(.{1,120}?)\s*$")
# inline patterns like "Weight 0.59 kg" / "Max. torque (hard/soft): 35 / 20 Nm"
INLINE = re.compile(r"(?i)\b(weight|gewicht|вага|вес|voltage|spannung|напруга|torque|drehmoment|крутний момент|no-load speed|leerlaufdrehzahl|warranty|garantie|гарантія|гарантия)\b[^\n:]{0,25}?[:\s]\s*([\d.,]+\s*(?:/\s*[\d.,]+\s*)?[A-Za-zА-Яа-я·⁻¹/]{0,8})")


def extract_kv(text: str) -> list[tuple[str, str, str]]:
    triples: list[tuple[str, str, str]] = []
    seen = set()
    for line in text.split("\n"):
        m = KV_LINE.match(line)
        if m:
            k, v = m.group(1).strip(), m.group(2).strip()
            if len(v) > 0 and (k.lower(), v.lower()) not in seen and not v.endswith(":"):
                seen.add((k.lower(), v.lower()))
                triples.append((k, v, line.strip()))
            continue
        for m in INLINE.finditer(line):
            k, v = m.group(1), m.group(2).strip()
            if (k.lower(), v.lower()) not in seen:
                seen.add((k.lower(), v.lower()))
                triples.append((k, v, line.strip()[:200]))
    return triples


def split_hard_soft(key: str, value: str) -> list[tuple[str, str]]:
    """'Max. torque (hard/soft)': '35 / 20 Nm' -> [('max torque hard','35 Nm'), ('max torque soft','20 Nm')]"""
    m = re.match(r"^\s*([\d.,]+)\s*/\s*([\d.,]+)\s*([A-Za-z·]+)?\s*$", value)
    if m and re.search(r"(?i)hard|soft|hart|weich|жорстк|м'як", key):
        unit = m.group(3) or ""
        base = re.sub(r"(?i)\(.*?\)|hard|soft|/|hart|weich", " ", key)
        base = re.sub(r"\s+", " ", base).strip()
        return [(f"{base} hard", f"{m.group(1)} {unit}".strip()), (f"{base} soft", f"{m.group(2)} {unit}".strip())]
    return [(key, value)]
