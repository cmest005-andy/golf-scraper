import re

import requests
from bs4 import BeautifulSoup

from golf.models import Player

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# First word must start uppercase; subsequent words allow lowercase particles
# (van, de, du …) and initials with dots (A.J.) or hyphens (Kyoung-Hoon).
_RANKING_RE = re.compile(r"^(\d+)\s+([A-Z][a-zA-Z-.]+(?:\s[a-zA-Z][a-zA-Z-.]+)+)")

_NAME_MAP = {
    'Seungyul Noh':       'S.Y. Noh',
    'Rasmus Hojgaard':    'Rasmus Højgaard',
    'John Keefer':        'Johnny Keefer',
    'McClure Meissner':   'Mac Meissner',
    'Thorbjorn Olesen':   'Thorbjørn Olesen',
    'Vincent Whaley':     'Vince Whaley',
    'Adrien Dumont':      'Adrien Dumont de Chassart',
    'Zachary Bauchou':    'Zach Bauchou',
    'Richard Hoey':       'Rico Hoey',
    'Marty Dou Zecheng':  'Zecheng Dou',
    'Seamus Power':       'Séamus Power',
    'Cameron Davis':      'Cam Davis',
    'Kristoffer Ventura': 'Kris Ventura',
    'William Gordon':     'Will Gordon',
    'Fabian Gomez':       'Fabián Gómez',
    'Kyoung-Hoon Lee':    'K.H. Lee',
    'Chun-an Yu':         'Kevin Yu',
    'Ludvig Aberg':             'Ludvig Åberg',
    'Nicolas Echavarria':       'Nico Echavarria',
    'Samuel Stevens':           'Sam Stevens',
    'Rasmus Neergaard':         'Rasmus Neergaard-Petersen',
}


def fetch_rankings_from_url(url: str) -> tuple[int, list[str]]:
    """
    Fetch OWGR rankings from *url* and update Player.world_ranking.

    Returns (matched_count, unmatched_names).
    Raises requests.RequestException on HTTP failure.
    """
    response = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.find_all("tr")

    player_lookup: dict[str, Player] = {
        p.display_name.lower(): p for p in Player.objects.all()
    }

    matched = 0
    unmatched_names: list[str] = []

    for row in rows:
        row_text = re.sub(r"\s+", " ", row.get_text(separator=" ")).strip()
        m = _RANKING_RE.match(row_text)
        if not m:
            continue
        rank = int(m.group(1))
        name = m.group(2).strip()
        resolved = _NAME_MAP.get(name, name)
        player = player_lookup.get(resolved.lower())
        if player is not None:
            player.world_ranking = rank
            player.save(update_fields=["world_ranking"])
            matched += 1
        else:
            unmatched_names.append(name)

    return matched, unmatched_names
