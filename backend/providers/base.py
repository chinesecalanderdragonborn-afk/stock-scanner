"""Data provider interface.

A provider's only job is to return raw market data (quotes + intraday bars,
news, index levels). All derived analytics live in the engine, so live and
simulated providers stay interchangeable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from backend.models import Index, NewsItem, Quote


class DataProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get_quotes(self, symbols: list[str]) -> list[Quote]:
        """Return a Quote (with session bars) for each requested symbol."""

    @abstractmethod
    def get_news(self, limit: int = 30) -> list[NewsItem]:
        """Return the most recent market/news headlines, newest first."""

    @abstractmethod
    def get_indices(self) -> list[Index]:
        """Return the major index / futures levels for the ticker strip."""
