"""Deterministic prices shared by checkpoint capture and settings regression tests."""
import numpy as np
import pandas as pd


def prices(kind, symbol='TEST'):
    x = np.arange(180)
    close = {'up': 50 + x * .6, 'down': 180 - x * .6,
             'flat': 100 + np.sin(x) * 2,
             'reversal': np.r_[50 + x[:140] * .6, 134 - np.arange(40) * 2.0]}[kind]
    return pd.DataFrame({('Open', symbol): close - .2, ('High', symbol): close + 1,
                         ('Low', symbol): close - 1, ('Close', symbol): close,
                         ('Volume', symbol): 100000 + (x % 7) * 10000},
                        index=pd.date_range('2025-01-01', periods=len(x)))
