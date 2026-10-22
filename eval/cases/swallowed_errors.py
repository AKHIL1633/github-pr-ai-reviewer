import json

import requests


def fetch_prices(url: str) -> dict:
    try:
        response = requests.get(url)  # expect: architecture
        return json.loads(response.text)
    except Exception:  # expect: architecture
        pass
