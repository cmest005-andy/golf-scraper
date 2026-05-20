"""
Management command: fetch_rankings
-----------------------------------
Scrapes player world rankings from an OWGR event page URL and updates
the ``world_ranking`` field on matching ``Player`` records.

Usage
-----
    python manage.py fetch_rankings --url "https://www.owgr.com/events/the-cj-cup-byron-nelson-11360"
"""

import re

import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand, CommandError

from golf.models import Player


# Browser-like User-Agent so OWGR does not reject the request.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Matches a row that begins with a ranking number followed by a player name
# composed of two or more Title-cased words, e.g.:
#   "1 Scottie Scheffler ..."
#   "14 Rory McIlroy ..."
# Group 1 → rank (integer string)
# Group 2 → player display name (two or more Title-cased words)
_RANKING_RE = re.compile(r"^(\d+)\s+([A-Z][a-zA-Z-]+(?:\s[A-Z][a-zA-Z-]+)+)")

# OWGR name → ESPN display_name for known mismatches
_NAME_MAP = {
    'Seungyul Noh':       'S.Y. Noh',
    'Rasmus Hojgaard':    'Rasmus Højgaard',
    'John Keefer':        'Johnny Keefer',
    'McClure Meissner':   'Mac Meissner',
    'Thorbjorn Olesen':   'Thorbjørn Olesen',
    'Vincent Whaley':     'Vince Whaley',
    'Adrien Dumont':      'Adrien Dumont de Chassart',
    'Zachary Bauchou':    'Zach Bauchou',
    'Richard Hoey':      'Rico Hoey',
    'Marty Dou Zecheng':  'Zecheng Dou',
    'Seamus Power':       'Séamus Power',
    'Cameron Davis':      'Cam Davis',
    'Kristoffer Ventura': 'Kristoffer Reitan',
    'William Gordon':     'Will Gordon',
    'Fabian Gomez':       'Fabián Gómez',
    'Kyoung-Hoon Lee':   'K.H. Lee',
    'Chun-an Yu':        'Kevin Yu',
}


class Command(BaseCommand):
    help = "Scrape OWGR event page and update player world rankings."

    # ------------------------------------------------------------------ #
    # Argument definition
    # ------------------------------------------------------------------ #

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            type=str,
            required=True,
            metavar="URL",
            help="OWGR event page URL (e.g. https://www.owgr.com/events/the-cj-cup-byron-nelson-11360).",
        )

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #

    def handle(self, *args, **options):
        url = options["url"]

        # ------------------------------------------------------------------ #
        # Step 1 — Fetch the OWGR event page
        # ------------------------------------------------------------------ #
        self.stdout.write(f"Fetching   : {url}")
        try:
            response = requests.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=15,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError(f"Failed to fetch OWGR page: {exc}") from exc

        # ------------------------------------------------------------------ #
        # Step 2 — Parse HTML and collect all <tr> rows
        # ------------------------------------------------------------------ #
        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.find_all("tr")
        self.stdout.write(f"Table rows : {len(rows)}")

        # ------------------------------------------------------------------ #
        # Step 3 — Build a case-insensitive Player lookup dict (single query)
        # ------------------------------------------------------------------ #
        player_lookup: dict[str, Player] = {
            p.display_name.lower(): p for p in Player.objects.all()
        }

        # ------------------------------------------------------------------ #
        # Step 4 — Walk each row, extract rank + name, update Player records
        # ------------------------------------------------------------------ #
        total_rows = 0
        matched = 0
        unmatched = 0
        unmatched_names: list[str] = []

        for row in rows:
            # Strip HTML tags and collapse internal whitespace into a single
            # clean string so the regex can anchor reliably at position 0.
            row_text = re.sub(r"\s+", " ", row.get_text(separator=" ")).strip()
            total_rows += 1

            match = _RANKING_RE.match(row_text)
            if not match:
                continue

            rank: str = match.group(1)
            name: str = match.group(2).strip()

            resolved = _NAME_MAP.get(name, name)
            player = player_lookup.get(resolved.lower())

            if player is not None:
                player.world_ranking = int(rank)
                player.save(update_fields=["world_ranking"])
                matched += 1
            else:
                unmatched_names.append(name)
                unmatched += 1

        # ------------------------------------------------------------------ #
        # Step 5 — Print summary
        # ------------------------------------------------------------------ #
        self.stdout.write(
            self.style.SUCCESS(
                f"\nSummary\n"
                f"  Total rows parsed   : {total_rows}\n"
                f"  Matched and updated : {matched}\n"
                f"  Unmatched names     : {unmatched}"
            )
        )

        if unmatched_names:
            self.stdout.write(self.style.WARNING("  Unmatched player names:"))
            for name in unmatched_names:
                self.stdout.write(f"  - {name}")
