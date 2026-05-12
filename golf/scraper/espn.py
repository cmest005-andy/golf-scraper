import logging
import re

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BASE_URL = settings.ESPN_API_BASE_URL

_VENUE_PAT = re.compile(
    r'at the ([A-Z][^.,:(]+?(?:Club|Course|Golf|Links|Resort|National|Park))',
    re.IGNORECASE,
)
_COMPETITOR_ID_PAT = re.compile(r'/competitors/(\d+)')

# Odds API sport keys for major championships
MAJOR_ODDS_KEYS = {
    'pga championship':          'golf_pga_championship_winner',
    'u.s. open':                 'golf_us_open_winner',
    'us open':                   'golf_us_open_winner',
    'the open championship':     'golf_the_open_championship_winner',
    'british open':              'golf_the_open_championship_winner',
}

ODDS_API_BASE = 'https://api.the-odds-api.com/v4'


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


def fetch_tournament_venue(tournament_name: str) -> str:
    """Try to find the golf course/venue for a tournament via Wikipedia. Returns empty string if not found."""
    def _get_summary(title: str):
        return requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}",
            headers=WIKI_HEADERS,
            timeout=10,
        )

    response = _get_summary(tournament_name)

    if response.status_code == 404:
        search = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": f"{tournament_name} golf tournament", "format": "json", "srlimit": 1},
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

    if data.get("type") == "disambiguation":
        response = _get_summary(f"{tournament_name} (golf tournament)")
        if not response.ok:
            return ""
        data = response.json()

    m = _VENUE_PAT.search(data.get("extract", ""))
    return m.group(1) if m else ""


def fetch_tournament_field(espn_id: str) -> list[str]:
    """Return list of ESPN athlete IDs in the tournament field."""
    response = requests.get(
        f"https://sports.core.api.espn.com/v2/sports/golf/leagues/pga/events/{espn_id}/competitions/{espn_id}/competitors",
        params={"limit": 200},
        timeout=15,
    )
    response.raise_for_status()
    ids = []
    for item in response.json().get("items", []):
        m = _COMPETITOR_ID_PAT.search(item.get("$ref", ""))
        if m:
            ids.append(m.group(1))
    return ids


def fetch_major_odds(tournament_name: str) -> dict[str, str]:
    """Fetch tournament-winner odds from The Odds API for major championships.
    Returns {normalized_player_name: american_odds_string} or empty dict if not a major."""
    sport_key = MAJOR_ODDS_KEYS.get(tournament_name.lower().strip())
    if not sport_key or not settings.THE_ODDS_API_KEY:
        return {}
    try:
        response = requests.get(
            f"{ODDS_API_BASE}/sports/{sport_key}/odds",
            params={
                "apiKey":      settings.THE_ODDS_API_KEY,
                "regions":     "us",
                "markets":     "outrights",
                "oddsFormat":  "american",
                "bookmakers":  "draftkings",
            },
            timeout=15,
        )
        response.raise_for_status()
        events = response.json()
        if not events:
            return {}
        # Use first event (current year's major)
        bookmakers = events[0].get("bookmakers", [])
        if not bookmakers:
            return {}
        outcomes = bookmakers[0].get("markets", [{}])[0].get("outcomes", [])
        return {
            o["name"].lower().strip(): (f"+{o['price']}" if o["price"] > 0 else str(o["price"]))
            for o in outcomes
        }
    except Exception:
        logger.exception("Failed to fetch odds for %s", tournament_name)
        return {}
