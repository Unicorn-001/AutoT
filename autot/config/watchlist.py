import json


def load_watchlist(file_path="autot/config/watchlist.json"):
    with open(file_path, "r") as file:
        data = json.load(file)

    return data["stocks"]