"""
File: market_data_manager.py
Project: AutoT

Purpose:
    Central access point for market data.
"""

import pandas as pd

from autot.data.market_data import (
    download_stock_data,
    download_batch_stock_data,
)


class MarketDataManager:
    """
    Provides single-stock and batch market data access.
    Later this can support cache, live data, and broker data.
    """

    @staticmethod
    def get_stock_data(
        symbol: str,
        period: str,
        interval: str,
    ) -> pd.DataFrame:
        return download_stock_data(
            symbol=symbol,
            period=period,
            interval=interval,
        )

    @staticmethod
    def get_batch_stock_data(
        symbols: list[str],
        period: str,
        interval: str,
    ) -> dict[str, pd.DataFrame]:
        return download_batch_stock_data(
            symbols=symbols,
            period=period,
            interval=interval,
        )