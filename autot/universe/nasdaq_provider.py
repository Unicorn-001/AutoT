"""Nasdaq Trader HTTPS symbol directories, separate from the price-data cache.

Format: https://www.nasdaqtrader.com/Trader.aspx?id=SymbolDirDefs
"""

import csv
import io
import json
import logging
import math
import re
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

import requests

from autot.market_data.symbols import normalize_market_data_symbol
from autot.universe.providers import UniverseResult
from autot.universe.security_types import non_common_equity_reason

LOGGER = logging.getLogger(__name__)
SOURCE = "Nasdaq Trader Symbol Directory"
URLS = {
    "nasdaqlisted": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "otherlisted": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data_storage" / "universe_cache"
# ACT symbols may include preferred-share $, dot suffixes, or hyphens.
SYMBOL_PATTERN = re.compile(r"[A-Z][A-Z0-9]*(?:[.$-][A-Z0-9]+)*")
NON_NORMAL = {"D", "E", "Q", "G", "H", "J", "K"}
CACHE_VERSION = 2  # Version 1 included non-common-equity securities.


class UniverseLoadError(RuntimeError):
    """The online universe and its local fallback are unavailable."""


def parse_directory(text: str, directory: str) -> UniverseResult:
    """Parse official headers and exclude clearly identifiable non-common equity."""
    symbol_field = {"nasdaqlisted": "Symbol", "otherlisted": "ACT Symbol"}[directory]
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), delimiter="|")
    required = {symbol_field, "Security Name", "Test Issue", "ETF"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError(f"Invalid {directory} directory: missing required headers")
    records = []
    downloaded = filtered = 0
    for row in reader:
        original = (row.get(symbol_field) or "").strip()
        downloaded += 1
        malformed = None in row or any(value is None for value in row.values())
        if (
            original.startswith("File Creation Time")
            or malformed
            or len(original) > 14
            or not SYMBOL_PATTERN.fullmatch(original)
            or (row.get("Test Issue") or "").strip() != "N"
            or (row.get("ETF") or "").strip() != "N"
            or (row.get("Financial Status") or "").strip() in NON_NORMAL
            or non_common_equity_reason(row, directory) is not None
        ):
            filtered += 1
            continue
        records.append({
            "source_symbol": original,
            "symbol": normalize_market_data_symbol(original),
            "directory": directory,
            "security_name": (row.get("Security Name") or "").strip(),
        })
    return UniverseResult(
        [record["symbol"] for record in records], directory,
        downloaded, filtered, records=records,
    )


class NasdaqTraderProvider:
    def __init__(self, cache_dir=None, ttl_seconds=24 * 60 * 60, *, clock=None):
        # Resolve relative overrides against the project, not Streamlit/CLI cwd.
        path = Path(cache_dir).expanduser() if cache_dir else DEFAULT_CACHE_DIR
        self.cache_dir = path if path.is_absolute() else PROJECT_ROOT / path
        self.cache_path = self.cache_dir / f"nasdaq_us_stocks_v{CACHE_VERSION}.json"
        self.ttl_seconds = ttl_seconds
        self.clock = clock or time.time

    def _read_cache(self):
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if payload["version"] != CACHE_VERSION:
                return None
            timestamp = float(payload["downloaded_at"])
            result = UniverseResult(**payload["result"])
            if not math.isfinite(timestamp) or timestamp > self.clock():
                return None
            if result.source != SOURCE or not result.symbols:
                return None
            if any(not isinstance(s, str) or not SYMBOL_PATTERN.fullmatch(s) for s in result.symbols):
                return None
            if len(set(result.symbols)) != len(result.symbols):
                return None
            if [r["symbol"] for r in result.records] != result.symbols:
                return None
            if any(normalize_market_data_symbol(r["source_symbol"]) != r["symbol"] for r in result.records):
                return None
            if any(type(n) is not int or n < 0 for n in (result.downloaded, result.filtered, result.duplicates)):
                return None
            if result.downloaded != result.filtered + result.duplicates + len(result.symbols):
                return None
            return timestamp, result
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None

    def _write_cache(self, result):
        payload = {"version": CACHE_VERSION, "downloaded_at": self.clock(), "result": asdict(result)}
        # Atomic replace means a failed refresh cannot overwrite a usable cache.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.cache_dir, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle)
            temporary.replace(self.cache_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _download(self):
        records = []
        downloaded = filtered = duplicates = 0
        seen = set()
        for directory, url in URLS.items():
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            parsed = parse_directory(response.text, directory)
            if not parsed.symbols:
                raise ValueError(f"No usable symbols in {directory}")
            downloaded += parsed.downloaded
            filtered += parsed.filtered
            for record in parsed.records:
                if record["symbol"] in seen:
                    duplicates += 1
                else:
                    seen.add(record["symbol"])
                    records.append(record)
        return UniverseResult(
            [r["symbol"] for r in records], SOURCE, downloaded,
            filtered, duplicates, records=records,
        )

    def load(self) -> UniverseResult:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache = self._read_cache()
        if cache and self.clock() - cache[0] < self.ttl_seconds:
            result = cache[1]
            result.cached = True
        else:
            try:
                result = self._download()
            except (requests.RequestException, ValueError) as error:
                if not cache:
                    raise UniverseLoadError(
                        "Unable to download Nasdaq Trader universe and no usable cache exists. "
                        "Check connectivity or choose Custom CSV."
                    ) from error
                result = cache[1]
                result.cached = result.stale = True
                LOGGER.warning("Nasdaq refresh failed; using stale universe cache: %s", error)
            else:
                try:
                    self._write_cache(result)
                except OSError as error:
                    LOGGER.warning("Unable to save universe cache: %s", error)
        LOGGER.info(
            "Universe source=%s downloaded=%d filtered=%d duplicates=%d symbols=%d cached=%s stale=%s",
            result.source, result.downloaded, result.filtered, result.duplicates,
            len(result.symbols), result.cached, result.stale,
        )
        return result
