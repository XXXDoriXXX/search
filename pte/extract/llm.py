"""Optional LLM extractor (Anthropic). Emits (field, raw, span) with mandatory verbatim evidence; grounding is verified by the caller.

Disabled automatically when ANTHROPIC_API_KEY is absent. Never used as a truth source: its claims carry extractor_confidence 0.7
and go through the same voting as everything else.
"""
from __future__ import annotations

import json
import os

from ..ontology import AttrSpec

TOOL = {
    "name": "emit_claims",
    "description": "Emit product attribute claims found VERBATIM in the text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_about_target": {"type": "boolean"},
            "claims": {"type": "array", "items": {"type": "object", "properties": {
                "field": {"type": "string"}, "raw": {"type": "string", "description": "value exactly as written"},
                "evidence": {"type": "string", "description": "verbatim sentence/line containing the value"},
                "context": {"type": "string"}}, "required": ["field", "raw", "evidence"]}},
        },
        "required": ["is_about_target", "claims"],
    },
}


class LLMExtractor:
    id = "llm"

    def __init__(self, model: str = "claude-sonnet-5", api_key: str | None = None, max_chars: int = 12000):
        self.key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model, self.max_chars = model, max_chars
        self._client = None

    def available(self) -> bool:
        return bool(self.key)

    async def extract(self, text: str, target: str, specs: list[AttrSpec]) -> tuple[bool, list[dict]]:
        if not self.available():
            return True, []
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self.key)
        fields = "\n".join(f"- {s.key} ({s.kind}{', ' + s.unit if s.unit else ''}): {', '.join(s.synonyms[:4])}" for s in specs)
        prompt = (f"Target product: {target}\n\nExtract attributes for the TARGET product only. If the text is about a different model or "
                  f"variant, set is_about_target=false and emit nothing. Copy values verbatim; the evidence must be a verbatim line from the text.\n\n"
                  f"Fields:\n{fields}\n\nTEXT:\n{text[: self.max_chars]}")
        resp = await self._client.messages.create(model=self.model, max_tokens=2000, temperature=0, tools=[TOOL],
                                                  tool_choice={"type": "tool", "name": "emit_claims"},
                                                  messages=[{"role": "user", "content": prompt}])
        for block in resp.content:
            if block.type == "tool_use":
                data = block.input if isinstance(block.input, dict) else json.loads(block.input)
                return bool(data.get("is_about_target", True)), list(data.get("claims", []))
        return True, []
