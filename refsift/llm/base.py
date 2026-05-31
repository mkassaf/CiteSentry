from __future__ import annotations

from abc import ABC, abstractmethod


class LLMClient(ABC):
    @abstractmethod
    async def complete(self, prompt: str) -> str:
        """Send prompt, return text response."""
        ...

    async def is_available(self) -> bool:
        return True
