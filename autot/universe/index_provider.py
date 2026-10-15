"""Validated, cached online index universes, independent of scanner orchestration."""

from dataclasses import asdict
import json
import logging
import math
from pathlib import Path
import tempfile
import time

import requests

from autot.market_data.symbols import normalize_index_symbol
from autot.runtime import configure_certificates, data_dir, project_path
from autot.universe.index_definitions import INDICES
from autot.universe.index_sources import parse_source, sources_for
from autot.universe.nasdaq_provider import UniverseLoadError
from autot.universe.providers import UniverseResult

LOGGER = logging.getLogger(__name__)
CACHE_VERSION = 1


class IndexUniverseProvider:
    """Bind an index to the existing zero-argument UniverseProvider protocol.

    Cache timestamps mean retrieval time, not the publisher's effective date.
    A 95%-110% cardinality envelope permits modest index transitions/share
    classes but rejects empty/error pages and common paginated fragments.
    """

    def __init__(self, index_id, cache_dir=None, ttl_seconds=86400, *, clock=None):
        if index_id not in INDICES:
            raise ValueError(f"Unknown index: {index_id}")
        self.definition = INDICES[index_id]
        self.cache_dir = project_path(cache_dir) if cache_dir else data_dir() / "universe_cache"
        self.cache_path = self.cache_dir / f"index_{index_id}_v{CACHE_VERSION}.json"
        self.ttl_seconds = ttl_seconds
        self.clock = clock or time.time

    def _validate_size(self, count):
        expected = self.definition.expected_size
        if not math.ceil(expected * .95) <= count <= math.ceil(expected * 1.10):
            raise ValueError(f"Implausible constituent count {count} for {self.definition.index_name}")

    def _normalize(self, rows, source):
        records, seen = [], set()
        filtered = duplicates = 0
        d = self.definition
        for raw_symbol, name in rows:
            try:
                if not isinstance(name, str) or not name.strip():
                    raise ValueError("Missing company name")
                symbol = normalize_index_symbol(raw_symbol, d.exchange)
            except ValueError:
                filtered += 1
                continue
            if symbol in seen:
                duplicates += 1
                continue
            seen.add(symbol)
            records.append({"source_symbol": raw_symbol, "yahoo_symbol": symbol,
                            "company_name": name.strip(), "market": d.market,
                            "index_id": d.index_id, "exchange": d.exchange})
        self._validate_size(len(records))
        warnings = []
        if source.unofficial:
            warnings.append("Constituents use an unofficial public source (Wikipedia); publication may lag index changes.")
        if filtered:
            warnings.append(f"Removed {filtered} malformed constituent rows.")
        return UniverseResult(
            symbols=[r["yahoo_symbol"] for r in records], source=source.name,
            downloaded=len(rows), filtered=filtered, duplicates=duplicates,
            records=records, index_id=d.index_id, country=d.country,
            index_name=d.index_name, source_url=source.url,
            fetched_at=self.clock(), warnings=warnings,
        )

    def _read_cache(self):
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if payload["version"] != CACHE_VERSION:
                return None
            result = UniverseResult(**payload["result"])
            d = self.definition
            if (result.index_id, result.country, result.index_name) != (d.index_id, d.country, d.index_name):
                return None
            timestamp = result.fetched_at
            if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or not 0 <= timestamp <= self.clock():
                return None
            source = next((s for s in sources_for(d) if (s.name, s.url) == (result.source, result.source_url)), None)
            if source is None or not isinstance(result.records, list):
                return None
            # Revalidate raw records, normalized symbols, deduplication, and metadata.
            rebuilt = self._normalize([(r["source_symbol"], r["company_name"]) for r in result.records], source)
            if rebuilt.records != result.records or rebuilt.symbols != result.symbols:
                return None
            if any(type(n) is not int or n < 0 for n in (result.downloaded, result.filtered, result.duplicates)):
                return None
            if result.downloaded != len(result.symbols) + result.filtered + result.duplicates:
                return None
            if not isinstance(result.warnings, list) or any(not isinstance(w, str) for w in result.warnings):
                return None
            result.cached, result.stale = True, False
            return result
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None

    def _write_cache(self, result):
        temporary = None
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.cache_dir, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump({"version": CACHE_VERSION, "result": asdict(result)}, handle)
            temporary.replace(self.cache_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _download(self):
        configure_certificates()
        sources = sources_for(self.definition)
        for position, source in enumerate(sources):
            try:
                response = requests.get(source.url, timeout=(5, 20), headers={
                    "User-Agent": "AutoT/1.0 (index constituent reader)",
                    "Accept": "application/json,text/csv,text/html;q=0.9,*/*;q=0.8",
                })
                response.raise_for_status()
                result = self._normalize(parse_source(source, response), source)
                if position:
                    result.warnings.append(f"Preferred source unavailable or incomplete; using {source.name}.")
                return result
            except (requests.RequestException, ValueError) as error:
                LOGGER.warning("Index %s source %s failed: %s", self.definition.index_id, source.name, error)
        raise UniverseLoadError(f"Unable to fetch {self.definition.index_name} constituents and no usable cache exists. Check connectivity and source availability, or upload a custom CSV.")

    def load(self):
        cache = self._read_cache()
        if cache and self.clock() - cache.fetched_at < self.ttl_seconds:
            return cache
        try:
            result = self._download()
        except UniverseLoadError:
            if cache is None:
                raise
            cache.stale = True
            cache.warnings.append("Live constituent refresh failed; using stale cache. Membership may have changed.")
            LOGGER.warning("Index %s using stale universe cache fetched at %s", self.definition.index_id, cache.fetched_at)
            return cache
        try:
            self._write_cache(result)
        except OSError:
            LOGGER.exception("Unable to save index universe cache")
            result.warnings.append("Constituents fetched, but the cache could not be saved.")
        return result
