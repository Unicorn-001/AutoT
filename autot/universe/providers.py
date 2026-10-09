"""Reusable universe providers and adapter for the scanner's injected loader."""

from dataclasses import dataclass, field
from typing import Protocol

from autot.universe.universe_loader import load_universe


@dataclass
class UniverseResult:
    symbols: list[str]
    source: str
    downloaded: int
    filtered: int
    duplicates: int = 0
    cached: bool = False
    stale: bool = False
    records: list[dict[str, str]] = field(default_factory=list)


class UniverseProvider(Protocol):
    def load(self) -> UniverseResult: ...


class CustomCSVProvider:
    """Wrap the legacy loader without changing its ordering or duplicate behavior."""

    def __init__(self, path: str):
        self.path = path

    def load(self) -> UniverseResult:
        symbols = load_universe(self.path)
        return UniverseResult(symbols, self.path, len(symbols), 0)


class ProviderUniverseLoader:
    """Callable adapter accepted by run_scan; diagnostics remain outside scanner."""

    def __init__(self, provider: UniverseProvider):
        self.provider = provider
        self.result: UniverseResult | None = None

    def __call__(self, universe: str) -> list[str]:
        self.result = self.provider.load()
        return self.result.symbols
