"""Reusable universe providers and adapter for the scanner's injected loader."""

from dataclasses import dataclass, field
from io import BytesIO
import re
from typing import Protocol

import pandas as pd

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
    index_id: str = ""
    country: str = ""
    index_name: str = ""
    source_url: str = ""
    fetched_at: float | None = None
    warnings: list[str] = field(default_factory=list)


class UniverseProvider(Protocol):
    def load(self) -> UniverseResult: ...


class CustomCSVProvider:
    """Wrap the legacy loader without changing its ordering or duplicate behavior."""

    def __init__(self, path: str):
        self.path = path

    def load(self) -> UniverseResult:
        symbols = load_universe(self.path)
        return UniverseResult(symbols, self.path, len(symbols), 0)


class UploadedCSVProvider:
    """Parse browser bytes in memory; never interpret a filename as a path."""

    MAX_BYTES = 1024 * 1024
    MAX_SYMBOLS = 10000

    def __init__(self, content: bytes):
        self.content = content

    def load(self) -> UniverseResult:
        if not self.content or len(self.content) > self.MAX_BYTES:
            raise ValueError("Upload a non-empty CSV no larger than 1 MB.")
        try:
            frame = pd.read_csv(BytesIO(self.content), encoding="utf-8-sig", dtype=str)
        except (ValueError, UnicodeError, pd.errors.ParserError) as error:
            raise ValueError("Upload a valid UTF-8 CSV with a symbol column.") from error
        if "symbol" not in frame.columns:
            raise ValueError("CSV file must contain a 'symbol' column.")
        symbols = frame["symbol"].dropna().str.strip().str.upper().tolist()
        if not symbols or len(symbols) > self.MAX_SYMBOLS:
            raise ValueError("Upload between 1 and 10,000 symbols.")
        if any(not re.fullmatch(r"[A-Z0-9^][A-Z0-9.&^=$-]{0,31}", symbol) for symbol in symbols):
            raise ValueError("The symbol column contains a blank or invalid ticker.")
        return UniverseResult(symbols, "Uploaded CSV", len(symbols), 0)


class ProviderUniverseLoader:
    """Callable adapter accepted by run_scan; diagnostics remain outside scanner."""

    def __init__(self, provider: UniverseProvider):
        self.provider = provider
        self.result: UniverseResult | None = None

    def __call__(self, universe: str) -> list[str]:
        self.result = self.provider.load()
        return self.result.symbols
