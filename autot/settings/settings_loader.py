"""
File: settings_loader.py
Project: AutoT

Purpose:
    Load application settings from CSV.
"""

import pandas as pd


class SettingsLoader:

    @staticmethod
    def load(file_path: str = "data_storage/config/app_settings.csv") -> dict:
        df = pd.read_csv(file_path)

        if "setting" not in df.columns or "value" not in df.columns:
            raise ValueError("Settings CSV must contain 'setting' and 'value' columns.")

        settings = {}

        for _, row in df.iterrows():
            settings[str(row["setting"]).strip()] = str(row["value"]).strip()

        return settings