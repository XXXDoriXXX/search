"""Fetcher: httpx with content-addressed disk cache, per-domain concurrency, offline mode, PDF/HTML text extraction."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from selectolax.parser import HTMLParser

from .models import Page, now_iso

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 PTE/0.1"
TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid", "ref", "tag"}


def normalize_url(url: str) -> str:
    p = urlsplit(url.strip())
    q = "&".join(kv for kv in p.query.split("&") if kv and kv.split("=")[0] not in TRACKING)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", q, ""))


def domain_of(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def html_to_text(html: str) -> str:
    tree = HTMLParser(html)
    for sel in ("script", "style", "noscript", "svg", "nav", "footer", "header", "iframe"):
        for n in tree.css(sel):
            n.decompose()
    body = tree.body or tree.root
    if body is None:
        return ""
    # keep table structure readable: "key: value" lines
    for tr in body.css("tr"):
        cells = [c.text(separator=" ", strip=True) for c in tr.css("th, td")]
        if len(cells) >= 2:
            tr.replace_with(HTMLParser(f"<p>{cells[0]}: {' '.join(cells[1:])}</p>").body.child)
    for dt in body.css("dt"):
        dd = dt.next
        while dd is not None and dd.tag != "dd":
            dd = dd.next
        if dd is not None:
            dt.replace_with(HTMLParser(f"<p>{dt.text(strip=True)}: {dd.text(separator=' ', strip=True)}</p>").body.child)
            dd.decompose()
    text = body.text(separator="\n", strip=True)
    return re.sub(r"\n{2,}", "\n", text)


def pdf_to_text(data: bytes) -> str:
    import pdfplumber
    parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:40]:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


class Fetcher:
    def __init__(self, cache_dir: Path, offline: bool = False, local_map: dict[str, Path] | None = None,
                 per_domain: int = 3, timeout: float = 15.0, total_concurrency: int = 16):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.local_map = {normalize_url(k): Path(v) for k, v in (local_map or {}).items()}
        self.per_domain = per_domain
        self.timeout = timeout
        self._sem: dict[str, asyncio.Semaphore] = {}
        self._global = asyncio.Semaphore(total_concurrency)
        self.stats = {"fetched": 0, "cache_hits": 0, "failed": 0}
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(headers={"User-Agent": UA, "Accept-Language": "en,uk;q=0.8,de;q=0.6"},
                                         follow_redirects=True, timeout=self.timeout, http2=False, trust_env=True)
        return self

    async def __aexit__(self, *exc):
        if self._client:
            await self._client.aclose()

    def _sem_for(self, domain: str) -> asyncio.Semaphore:
        if domain not in self._sem:
            self._sem[domain] = asyncio.Semaphore(self.per_domain)
        return self._sem[domain]

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")

    def _build_page(self, url: str, final_url: str, status: int, mime: str, data: bytes, from_cache: bool) -> Page:
        snapshot = "sha256:" + hashlib.sha256(data).hexdigest()
        if "pdf" in mime or data[:5] == b"%PDF-":
            text, html, mime = pdf_to_text(data), None, "application/pdf"
        else:
            html = data.decode("utf-8", errors="replace")
            text = html_to_text(html)
        return Page(url=url, final_url=final_url, domain=domain_of(final_url), status=status, mime=mime, text=text,
                    html=html, fetched_at=now_iso(), snapshot=snapshot, from_cache=from_cache)

    async def fetch(self, url: str) -> Page | None:
        url = normalize_url(url)
        cp = self._cache_path(url)
        if url in self.local_map:
            data = self.local_map[url].read_bytes()
            mime = "application/pdf" if self.local_map[url].suffix == ".pdf" else "text/html"
            self.stats["cache_hits"] += 1
            return self._build_page(url, url, 200, mime, data, True)
        if cp.exists():
            rec = json.loads(cp.read_text())
            self.stats["cache_hits"] += 1
            return self._build_page(url, rec["final_url"], rec["status"], rec["mime"], bytes.fromhex(rec["data"]), True)
        if self.offline or self._client is None:
            return None
        async with self._global, self._sem_for(domain_of(url)):
            try:
                r = await self._client.get(url)
            except Exception:
                self.stats["failed"] += 1
                return None
        if r.status_code >= 400:
            self.stats["failed"] += 1
            return None
        self.stats["fetched"] += 1
        mime = r.headers.get("content-type", "text/html").split(";")[0]
        cp.write_text(json.dumps({"final_url": str(r.url), "status": r.status_code, "mime": mime, "data": r.content.hex()}))
        return self._build_page(url, str(r.url), r.status_code, mime, r.content, False)

    async def fetch_many(self, urls: list[str]) -> list[Page]:
        seen, uniq = set(), []
        for u in urls:
            n = normalize_url(u)
            if n not in seen:
                seen.add(n)
                uniq.append(n)
        pages = await asyncio.gather(*(self.fetch(u) for u in uniq))
        return [p for p in pages if p is not None and p.text.strip()]
