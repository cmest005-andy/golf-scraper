import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BASE_URL = settings.ESPN_API_BASE_URL


def fetch_scoreboard():
    """Fetch the current PGA Tour scoreboard."""
    response = requests.get(f"{BASE_URL}/scoreboard", timeout=10)
    response.raise_for_status()
    return response.json()


def fetch_tournament(espn_id: str):
    """Fetch details for a specific tournament by ESPN event ID."""
    response = requests.get(f"{BASE_URL}/summary", params={"event": espn_id}, timeout=10)
    response.raise_for_status()
    return response.json()


def fetch_leaderboard(espn_id: str):
    """Fetch the leaderboard for a specific tournament."""
    response = requests.get(
        f"{BASE_URL}/leaderboard",
        params={"event": espn_id},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def fetch_player_bio(espn_id: str):
    """Fetch player bio from ESPN web API."""
    url = f"https://site.web.api.espn.com/apis/common/v3/sports/golf/pga/athletes/{espn_id}"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


WIKI_HEADERS = {"User-Agent": "AndysFantasyGolfApp/1.0 (https://github.com/local/golf-scraper)"}


def fetch_wikipedia_bio(display_name: str) -> str:
    """Fetch a biographical extract from Wikipedia. Returns empty string if not found."""
    def _get_summary(title: str):
        return requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}",
            headers=WIKI_HEADERS,
            timeout=10,
        )

    response = _get_summary(display_name)

    if response.status_code == 404:
        search = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": display_name, "format": "json", "srlimit": 1},
            headers=WIKI_HEADERS,
            timeout=10,
        )
        results = search.json().get("query", {}).get("search", [])
        if not results:
            return ""
        response = _get_summary(results[0]["title"])

    if not response.ok:
        return ""

    data = response.json()

    # Disambiguation page — retry with "(golfer)" qualifier
    if data.get("type") == "disambiguation":
        response = _get_summary(f"{display_name} (golfer)")
        if not response.ok:
            return ""
        data = response.json()

    return data.get("extract", "")
