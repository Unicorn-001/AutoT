"""Index catalogue: identifiers and source configuration, never constituent lists."""

from dataclasses import dataclass


@dataclass(frozen=True)
class IndexDefinition:
    index_id: str
    country: str
    market: str
    index_name: str
    constituent_provider: str
    exchange: str
    benchmark_symbol: str
    expected_size: int
    source_key: str
    public_page: str = ""
    benchmark_display_name: str = ""


_DEFINITIONS = [
    IndexDefinition("sp500", "United States", "US", "S&P 500", "wikipedia", "US", "SPY", 500, "List_of_S%26P_500_companies", benchmark_display_name="SPDR S&P 500 ETF Trust"),
    IndexDefinition("nasdaq100", "United States", "US", "Nasdaq-100", "nasdaq", "US", "^NDX", 100, "nasdaq100", "List_of_NASDAQ-100_companies", benchmark_display_name="Nasdaq-100"),
    IndexDefinition("dow30", "United States", "US", "Dow Jones Industrial Average", "wikipedia", "US", "^DJI", 30, "List_of_Dow_Jones_Industrial_Average_companies", benchmark_display_name="Dow Jones Industrial Average"),
    IndexDefinition("ftse100", "United Kingdom", "UK", "FTSE 100", "lse", "LSE", "^FTSE", 100, "ftse-100", "FTSE_100_Index", benchmark_display_name="FTSE 100"),
    IndexDefinition("ftse250", "United Kingdom", "UK", "FTSE 250", "lse", "LSE", "^FTMC", 250, "ftse-250", "FTSE_250_Index", benchmark_display_name="FTSE 250"),
    # Web V1 intentionally uses NIFTY 50 for every Indian universe.
    *[IndexDefinition(index_id, "India", "IN", name, "nse", "NSE", "^NSEI", size, filename, benchmark_display_name="NIFTY 50")
      for index_id, name, size, filename in [
          ("nifty50", "NIFTY 50", 50, "ind_nifty50list.csv"),
          ("niftynext50", "NIFTY Next 50", 50, "ind_niftynext50list.csv"),
          ("nifty100", "NIFTY 100", 100, "ind_nifty100list.csv"),
          ("nifty200", "NIFTY 200", 200, "ind_nifty200list.csv"),
          ("nifty500", "NIFTY 500", 500, "ind_nifty500list.csv"),
      ]],
]
INDICES = {definition.index_id: definition for definition in _DEFINITIONS}
COUNTRIES = tuple(dict.fromkeys(item.country for item in _DEFINITIONS))


def indices_for_country(country: str) -> list[IndexDefinition]:
    return [item for item in INDICES.values() if item.country == country]
