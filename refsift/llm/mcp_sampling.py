from __future__ import annotations

from refsift.llm.base import LLMClient


class MCPSamplingClient(LLMClient):
    """Delegates LLM inference to the MCP host via sampling/createMessage."""

    def __init__(self, ctx: object) -> None:
        self._ctx = ctx

    async def complete(self, prompt: str) -> str:
        result = await self._ctx.sample(prompt)  # type: ignore[attr-defined]
        return result.text

    async def is_available(self) -> bool:
        return True
