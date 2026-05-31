from __future__ import annotations

from abc import ABC, abstractmethod

from refsift.models import Candidate, Reference


class SourceAdapter(ABC):
    name: str = "unknown"

    @abstractmethod
    async def lookup_doi(self, doi: str) -> Candidate | None:
        """Resolve a DOI to a candidate record."""
        ...

    @abstractmethod
    async def search(self, ref: Reference) -> list[Candidate]:
        """Search by title/author/year; return ranked candidates."""
        ...
