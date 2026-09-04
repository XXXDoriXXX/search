from __future__ import annotations

import asyncio
import time
from typing import Protocol, runtime_checkable

from ..models import Identifiers, Lead, QueryVariant, Tier


@runtime_checkable
class SourceConnector(Protocol):
    id: str
    tier: Tier
    capabilities: set[str]

    async def search(self, q: QueryVariant) -> list[Lead]: ...
    async def lookup(self, ids: Identifiers) -> list[Lead]: ...


class CircuitBreaker:
    def __init__(self, failures: int = 3, cooldown: float = 60.0):
        self.failures, self.cooldown = failures, cooldown
        self.count, self.open_until = 0, 0.0

    def ok(self) -> bool:
        return time.monotonic() >= self.open_until

    def success(self):
        self.count = 0

    def failure(self):
        self.count += 1
        if self.count >= self.failures:
            self.open_until = time.monotonic() + self.cooldown
            self.count = 0


class ConnectorRegistry:
    """Runs search/lookup across connectors in parallel with per-connector circuit breakers and timeouts."""

    def __init__(self, connectors: list[SourceConnector], timeout: float = 12.0):
        self.connectors = connectors
        self.timeout = timeout
        self.breakers = {c.id: CircuitBreaker() for c in connectors}
        self.failed: set[str] = set()
        self.calls = 0

    async def _run(self, c: SourceConnector, coro) -> list[Lead]:
        br = self.breakers[c.id]
        if not br.ok():
            return []
        self.calls += 1
        try:
            res = await asyncio.wait_for(coro, self.timeout)
            br.success()
            return res
        except Exception:
            br.failure()
            self.failed.add(c.id)
            return []

    async def search_all(self, queries: list[QueryVariant]) -> list[Lead]:
        tasks = [self._run(c, c.search(q)) for q in queries for c in self.connectors if "search" in c.capabilities]
        results = await asyncio.gather(*tasks)
        return [l for group in results for l in group]

    async def lookup_all(self, ids: Identifiers) -> list[Lead]:
        if not ids.any():
            return []
        tasks = [self._run(c, c.lookup(ids)) for c in self.connectors if "lookup_by_id" in c.capabilities]
        results = await asyncio.gather(*tasks)
        return [l for group in results for l in group]
