"""
File: relative_strength_engine.py
Project: AutoT

Purpose:
    Compare a stock's recent performance against a benchmark.
"""

import pandas as pd


class RelativeStrengthEngine:
    """
    Calculates relative strength versus a benchmark index/ETF.
    """

    @staticmethod
    def calculate(
        stock_data: pd.DataFrame,
        benchmark_data: pd.DataFrame,
        lookback: int = 60,
    ) -> dict:

        if len(stock_data) < lookback + 1 or len(benchmark_data) < lookback + 1:
            return {
                "stock_return_percent": 0.0,
                "benchmark_return_percent": 0.0,
                "relative_strength_percent": 0.0,
                "relative_strength_score": 0.0,
                "relative_strength_label": "INSUFFICIENT_DATA",
            }

        stock_close = stock_data["Close"]
        benchmark_close = benchmark_data["Close"]

        if isinstance(stock_close, pd.DataFrame):
            stock_close = stock_close.iloc[:, 0]

        if isinstance(benchmark_close, pd.DataFrame):
            benchmark_close = benchmark_close.iloc[:, 0]

        stock_close = pd.to_numeric(
            stock_close,
            errors="coerce",
        ).dropna()

        benchmark_close = pd.to_numeric(
            benchmark_close,
            errors="coerce",
        ).dropna()

        if len(stock_close) < lookback + 1 or len(benchmark_close) < lookback + 1:
            return {
                "stock_return_percent": 0.0,
                "benchmark_return_percent": 0.0,
                "relative_strength_percent": 0.0,
                "relative_strength_score": 0.0,
                "relative_strength_label": "INSUFFICIENT_DATA",
            }

        stock_start = float(stock_close.iloc[-lookback - 1])
        stock_end = float(stock_close.iloc[-1])

        benchmark_start = float(
            benchmark_close.iloc[-lookback - 1]
        )
        benchmark_end = float(
            benchmark_close.iloc[-1]
        )

        stock_return = (
            (stock_end - stock_start)
            / stock_start
            * 100
        )

        benchmark_return = (
            (benchmark_end - benchmark_start)
            / benchmark_start
            * 100
        )

        relative_strength = stock_return - benchmark_return

        if relative_strength >= 15:
            score = 100.0
            label = "VERY_STRONG_OUTPERFORMANCE"

        elif relative_strength >= 10:
            score = 85.0
            label = "STRONG_OUTPERFORMANCE"

        elif relative_strength >= 5:
            score = 70.0
            label = "OUTPERFORMING"

        elif relative_strength >= 0:
            score = 55.0
            label = "SLIGHTLY_OUTPERFORMING"

        elif relative_strength >= -5:
            score = 40.0
            label = "SLIGHTLY_UNDERPERFORMING"

        elif relative_strength >= -10:
            score = 25.0
            label = "UNDERPERFORMING"

        else:
            score = 10.0
            label = "STRONG_UNDERPERFORMANCE"

        return {
            "stock_return_percent": round(
                stock_return,
                2,
            ),
            "benchmark_return_percent": round(
                benchmark_return,
                2,
            ),
            "relative_strength_percent": round(
                relative_strength,
                2,
            ),
            "relative_strength_score": score,
            "relative_strength_label": label,
        }