"""
File: settings_loader.py
Project: AutoT

Purpose:
    Load application settings from CSV.
"""

import pandas as pd

from autot.runtime import data_dir, project_path


# Scan defaults for a fresh checkout; existing operator settings take precedence.
DEFAULT_SETTINGS = {
    "ACTIVE_UNIVERSE": "autot/universe/us_stocks.csv",
    "BACKTEST_PERIOD": "5y",
    "BACKTEST_INTERVAL": "1d",
    "TOP_N_STOCKS": "10",
}


class SettingsLoader:

    @staticmethod
    def load(file_path: str | None = None) -> dict:
        if file_path is None:
            file_path = data_dir() / "config" / "app_settings.csv"
            if not file_path.exists():
                return DEFAULT_SETTINGS.copy()
        else:
            file_path = project_path(file_path)
        df = pd.read_csv(file_path)

        if "setting" not in df.columns or "value" not in df.columns:
            raise ValueError("Settings CSV must contain 'setting' and 'value' columns.")

        settings = {}

        for _, row in df.iterrows():
            settings[str(row["setting"]).strip()] = str(row["value"]).strip()

        return settings
