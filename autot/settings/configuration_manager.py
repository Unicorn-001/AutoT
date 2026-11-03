"""
File: configuration_manager.py
Project: AutoT

Purpose:
    Central access point for AutoT configuration.
"""

from autot.settings.settings_loader import SettingsLoader


class ConfigurationManager:
    """
    Provides typed access to application settings.
    """

    def __init__(self) -> None:
        self.settings = SettingsLoader.load()
        from autot.settings.store import SettingsStore
        self.active = SettingsStore().load()
        if self.active.settings_version:
            scanner = self.active.settings.scanner
            self.settings.update(BACKTEST_PERIOD=scanner.history_period, BACKTEST_INTERVAL=scanner.interval,
                                 TOP_N_STOCKS=str(scanner.top_ranked_count))

    def get_string(self, key: str, default: str = "") -> str:
        return self.settings.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        value = self.settings.get(key)

        if value is None:
            return default

        return int(value)

    def get_float(self, key: str, default: float = 0.0) -> float:
        value = self.settings.get(key)

        if value is None:
            return default

        return float(value)

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.settings.get(key)

        if value is None:
            return default

        return str(value).strip().lower() in ["true", "1", "yes", "y"]