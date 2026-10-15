"""All website-specific parsing and URLs for current index constituents.

No browser automation, hidden credentials, or disabled certificate verification.
Public HTML/website APIs are not guaranteed contracts; callers validate complete
lists and record the actual source, including any public-source fallback.
"""

import csv
from dataclasses import dataclass
import io

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    format: str
    unofficial: bool = False


def sources_for(definition):
    kind = definition.constituent_provider
    if kind == "nse":
        return [Source("NSE Indices", f"https://www.niftyindices.com/IndexConstituent/{definition.source_key}", "nse"),
                Source("NSE Archives", f"https://archives.nseindia.com/content/indices/{definition.source_key}", "nse")]
    public = Source("Wikipedia (unofficial)", "https://en.wikipedia.org/wiki/" + (definition.public_page or definition.source_key), "wikipedia", True)
    if kind == "nasdaq":
        return [Source("Nasdaq", "https://api.nasdaq.com/api/quote/list-type/nasdaq100", "nasdaq"), public]
    if kind == "lse":
        return [Source("London Stock Exchange", f"https://www.londonstockexchange.com/indices/{definition.source_key}/constituents/table", "lse"), public]
    return [public]


def parse_source(source, response):
    """Return raw (source symbol, company name) pairs, including malformed rows.

    Row validation/normalization is centralized in IndexUniverseProvider. Strict
    table headers keep historic changes and unrelated tables out of the list.
    """
    if source.format == "nse":
        reader = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")))
        if not {"Symbol", "Company Name", "Series"}.issubset(reader.fieldnames or []):
            raise ValueError("NSE CSV is missing constituent headers")
        return [(row.get("Symbol"), row.get("Company Name"))
                if None not in row and all(v is not None for v in row.values()) and row.get("Series")
                else (None, None) for row in reader]
    if source.format == "nasdaq":
        try:
            data = response.json()["data"]
            rows = data["data"]["rows"]
        except (KeyError, TypeError) as error:
            raise ValueError("Nasdaq constituent response has changed") from error
        if not isinstance(rows, list):
            raise ValueError("Missing Nasdaq constituent rows")
        if "totalrecords" in data:
            try:
                complete = int(data["totalrecords"]) == len(rows)
            except (ValueError, TypeError) as error:
                raise ValueError("Invalid Nasdaq constituent total") from error
            if not complete:
                raise ValueError("Incomplete Nasdaq constituent response")
        return [(r.get("symbol"), r.get("companyName")) if isinstance(r, dict) else (None, None) for r in rows]

    soup = BeautifulSoup(response.text, "html.parser")
    for note in soup.select("sup"):
        note.decompose()
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [cell.get_text(" ", strip=True) for cell in rows[0].find_all(["th", "td"])]
        symbol_headers = ("Code",) if source.format == "lse" else ("Symbol", "Ticker", "Ticker symbol")
        name_headers = ("Name",) if source.format == "lse" else ("Security", "Company")
        symbol_col = next((headers.index(h) for h in symbol_headers if h in headers), None)
        name_col = next((headers.index(h) for h in name_headers if h in headers), None)
        if symbol_col is None or name_col is None:
            continue
        result = []
        for row in rows[1:]:
            cells = row.find_all(["td", "th"], recursive=False)
            if len(cells) != len(headers):
                result.append((None, None))
                continue
            result.append((cells[symbol_col].get_text(" ", strip=True), cells[name_col].get_text(" ", strip=True)))
        return result
    raise ValueError("No recognizable constituent table; page may require JavaScript")
