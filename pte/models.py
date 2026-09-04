from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

Tier = Literal["A", "B", "C", "D", "E"]
Status = Literal["verified", "single_source", "conflict", "inferred", "unknown"]

TIER_PRIOR: dict[str, float] = {"A": 1.0, "B": 0.75, "C": 0.45, "D": 0.25, "E": 0.15}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Identifiers(BaseModel):
    gtins: list[str] = Field(default_factory=list)
    mpn: str | None = None
    asin: str | None = None
    other: dict[str, str] = Field(default_factory=dict)

    def any(self) -> bool:
        return bool(self.gtins or self.mpn or self.asin or self.other)


class QueryVariant(BaseModel):
    text: str
    purpose: Literal["anchor", "harvest", "hole"] = "anchor"
    lang: str = "en"
    target_field: str | None = None


class QueryHypothesis(BaseModel):
    raw: str
    normalized: str
    brand: str | None
    model: str | None
    model_normalized: str | None
    variant_tokens: list[str] = Field(default_factory=list)
    identifiers: Identifiers = Field(default_factory=Identifiers)
    category: str
    category_confidence: float
    variants: list[QueryVariant] = Field(default_factory=list)


class Lead(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""
    connector: str
    tier_hint: Tier | None = None
    query: str = ""


class Page(BaseModel):
    url: str
    final_url: str
    domain: str
    status: int
    mime: str
    text: str            # main readable text (or PDF text)
    html: str | None = None
    fetched_at: str
    snapshot: str        # sha256:...
    from_cache: bool = False


class EntityMatch(BaseModel):
    score: float
    variant_ok: bool = True
    reason: str = ""
    identifiers_found: Identifiers = Field(default_factory=Identifiers)


class Claim(BaseModel):
    field: str
    value: Any
    unit: str | None = None
    raw: str
    span: str                      # evidence text containing the raw value
    context: str | None = None     # e.g. weight context: net / with_battery
    url: str
    domain: str
    tier: Tier
    extractor: str
    extractor_confidence: float
    entity_match: float
    variant_ok: bool
    snapshot: str
    fetched_at: str
    page_specificity: float = 1.0
    independence_cluster: str | None = None


class SourceRef(BaseModel):
    url: str
    tier: Tier
    snippet: str
    fetched_at: str
    snapshot: str
    independence_cluster: str | None = None
    entity_match: float | None = None
    extractor: str | None = None


class Candidate(BaseModel):
    value: Any
    unit: str | None = None
    score: float
    sources: list[str]
    rejected_reason: str | None = None


class Resolution(BaseModel):
    method: Literal["identifier", "weighted_vote", "tier_a_override", "judge", "inference", "aggregate", "none"]
    independent_votes: int = 0
    margin: float = 0.0
    constraints_checked: list[str] = Field(default_factory=list)
    judge_reason: str | None = None


class ResolvedField(BaseModel):
    value: Any = None
    unit: str | None = None
    raw: list[str] = Field(default_factory=list)
    status: Status = "unknown"
    confidence: float = 0.0
    sources: list[SourceRef] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    resolution: Resolution | None = None
    applies_to: Literal["variant", "family", "shared_across_variants"] | None = None
    context: str | None = None
    inferred_from: dict[str, str] | None = None


class Unresolved(BaseModel):
    field: str
    status: Status
    reason: str
    candidates: list[Candidate] = Field(default_factory=list)
    search_log: list[str] = Field(default_factory=list)


class Anchor(BaseModel):
    brand: str | None
    model: str | None
    model_normalized: str | None
    identifiers: Identifiers
    category: str
    variant_axes: dict[str, str] = Field(default_factory=dict)
    canonical_name: str
    confidence: float
    supporting_urls: list[str] = Field(default_factory=list)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    langs: list[str] = Field(default_factory=lambda: ["en"])


class RunMeta(BaseModel):
    run_id: str
    mode: str
    rounds: int = 0
    duration_ms: int = 0
    cost_usd: float = 0.0
    sources_consulted: int = 0
    pages_fetched: int = 0
    connectors_failed: list[str] = Field(default_factory=list)
    schema_version: str = "1.0.0"
    ontology_version: str = "2026.09"
    generated_at: str = Field(default_factory=now_iso)


class Output(BaseModel):
    identity: dict[str, Any]
    core: dict[str, ResolvedField]
    attributes: dict[str, ResolvedField]
    extra: dict[str, ResolvedField]
    media: dict[str, list[dict[str, Any]]]
    offers: list[dict[str, Any]]
    relations: dict[str, list[dict[str, Any]]]
    unresolved: list[Unresolved]
    warnings: list[str]
    meta: RunMeta
