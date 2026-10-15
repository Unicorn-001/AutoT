import json

from autot.runtime import PROJECT_ROOT


def load_watchlist(file_path=PROJECT_ROOT / "autot" / "config" / "watchlist.json"):
    with open(file_path, "r") as file:
        data = json.load(file)

    return data["stocks"]
