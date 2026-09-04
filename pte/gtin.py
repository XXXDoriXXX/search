import re

_GTIN_RE = re.compile(r"(?<!\d)(\d{8}|\d{12}|\d{13}|\d{14})(?!\d)")


def gtin_checksum_ok(s: str) -> bool:
    if not s.isdigit() or len(s) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in s]
    body, check = digits[:-1], digits[-1]
    total = 0
    for i, d in enumerate(reversed(body)):
        total += d * (3 if i % 2 == 0 else 1)
    return (10 - total % 10) % 10 == check


def normalize_gtin(s: str) -> str | None:
    s = re.sub(r"[^\d]", "", s)
    if not gtin_checksum_ok(s):
        return None
    # canonical form: strip leading zeros of GTIN-14 padding down to 13 where possible
    if len(s) == 14 and s.startswith("0"):
        s = s[1:]
    if len(s) == 12:  # UPC-A -> EAN-13
        s = "0" + s
    return s


def find_gtins(text: str) -> list[str]:
    out = []
    for m in _GTIN_RE.finditer(text):
        g = normalize_gtin(m.group(1))
        if g and g not in out:
            out.append(g)
    return out
