from __future__ import annotations

from citesentry.llm.base import LLMClient


class OllamaClient(LLMClient):
    """Ollama local LLM via its OpenAI-compatible endpoint (http://localhost:11434/v1)."""

    def __init__(self, base_url: str, model: str) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ImportError(
                "Install citesentry[cli-llm] for LLM support: pip install citesentry[cli-llm]"
            ) from e
        # Ollama requires no real API key; use a placeholder
        self._client = AsyncOpenAI(api_key="ollama", base_url=base_url)
        self._model = model

    async def complete(self, prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        return response.choices[0].message.content or ""

    async def is_available(self) -> bool:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(self._client.base_url.rstrip("/").replace("/v1", "") + "/api/tags")
                return r.status_code == 200
        except Exception:
            return False


def make_ollama_client() -> OllamaClient | None:
    from citesentry.config import get_settings

    s = get_settings()
    if not s.ollama_model:
        return None
    return OllamaClient(base_url=s.ollama_base_url, model=s.ollama_model)
