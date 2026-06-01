from __future__ import annotations

from citesentry.llm.base import LLMClient


class DeepSeekClient(LLMClient):
    """OpenAI-compatible endpoint; used by the CLI when DEEPSEEK_API_KEY is set."""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ImportError(
                "Install citesentry[cli-llm] for CLI LLM support: pip install citesentry[cli-llm]"
            ) from e
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def complete(self, prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        return response.choices[0].message.content or ""

    async def is_available(self) -> bool:
        return True


def make_deepseek_client() -> DeepSeekClient | None:
    from citesentry.config import get_settings

    s = get_settings()
    if not s.deepseek_api_key:
        return None
    return DeepSeekClient(
        api_key=s.deepseek_api_key,
        base_url=s.deepseek_base_url,
        model=s.deepseek_model,
    )


def make_llm_client():
    """
    Return the best available LLM client:
    1. DeepSeek — if DEEPSEEK_API_KEY is set and openai package is installed
    2. Ollama   — if OLLAMA_MODEL is set (runs locally, no key needed)
    3. None     — LLM checks are skipped
    """
    try:
        client = make_deepseek_client()
        if client:
            return client
    except ImportError:
        pass
    try:
        from citesentry.llm.ollama import make_ollama_client
        return make_ollama_client()
    except ImportError:
        return None
