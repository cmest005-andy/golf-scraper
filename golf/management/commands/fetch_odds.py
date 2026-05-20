"""
Management command: fetch_odds
-------------------------------
Scrapes PGA Tour winner odds from a CBS Sports article URL and upserts
the results into the Odds model.

Usage
-----
    python manage.py fetch_odds --url "<CBS Sports article URL>"
    python manage.py fetch_odds --url "<CBS Sports article URL>" --tournament 401580350
"""

import re
import requests
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from golf.models import Odds, Player, Tournament


# Browser-like User-Agent so CBS Sports does not reject the request.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Matches patterns like:
#   Scottie Scheffler: +300
#   Rory McIlroy -150
#   Jon Rahm +1200
#   Xander Schauffele : +2500
# Group 1 → player name (Title-cased, 2-4 words)
# Group 2 → American odds string (+/-  followed by 3-4 digits)
ODDS_RE = re.compile(
    r"([A-Z][a-z]+(?:\s[A-Z][a-z]+){1,3})\s*[:\-]?\s*([+-]\d{3,4})"
)

BOOKMAKER = "CBS Sports"


class Command(BaseCommand):
    help = (
        "Scrape PGA Tour winner odds from a CBS Sports article URL "
        "and upsert into the Odds model."
    )

    # ------------------------------------------------------------------ #
    # Argument definition
    # ------------------------------------------------------------------ #

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            type=str,
            required=True,
            metavar="URL",
            help="Full URL of the CBS Sports article containing winner odds.",
        )
        parser.add_argument(
            "--tournament",
            type=str,
            required=False,
            default=None,
            metavar="ESPN_ID",
            help=(
                "ESPN tournament ID to attach odds to. "
                "If omitted, the current in-progress tournament is used; "
                "if none is in progress the next scheduled tournament is used."
            ),
        )

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #

    def handle(self, *args, **options):
        article_url = options["url"]
        tournament_id = options["tournament"]

        # ------------------------------------------------------------------ #
        # Step 1 — Resolve tournament
        # ------------------------------------------------------------------ #
        tournament = self._resolve_tournament(tournament_id)
        self.stdout.write(
            f"Tournament : {tournament} (espn_id={tournament.espn_id})"
        )

        # ------------------------------------------------------------------ #
        # Step 2 — Fetch article HTML
        # ------------------------------------------------------------------ #
        self.stdout.write(f"Fetching   : {article_url}")
        html = self._fetch_html(article_url)

        # ------------------------------------------------------------------ #
        # Step 3 — Parse player names + American odds from the raw HTML
        # ------------------------------------------------------------------ #
        raw_matches = ODDS_RE.findall(html)
        # Deduplicate while preserving first-occurrence order; a name may
        # appear multiple times in the page (e.g. in meta tags and body).
        seen: dict[str, str] = {}
        for raw_name, raw_odds in raw_matches:
            key = raw_name.strip().lower()
            if key not in seen:
                seen[key] = (raw_name.strip(), raw_odds.strip())

        total_found = len(seen)
        self.stdout.write(f"Odds found : {total_found}")

        if total_found == 0:
            self.stdout.write(
                self.style.WARNING(
                    "No odds matched the regex. "
                    "Verify the URL points to a CBS Sports odds article."
                )
            )
            return

        # ------------------------------------------------------------------ #
        # Step 4 — Build a case-insensitive Player lookup map
        # ------------------------------------------------------------------ #
        # One DB query for all players; cheaper than one query per scraped name.
        player_map: dict[str, Player] = {
            p.display_name.strip().lower(): p
            for p in Player.objects.all()
        }

        # ------------------------------------------------------------------ #
        # Step 5 — Upsert matched odds
        # ------------------------------------------------------------------ #
        now = timezone.now()
        matched_count = 0
        upserted_count = 0
        unmatched_names: list[str] = []

        for _key, (display_name, odds_str) in seen.items():
            player = player_map.get(display_name.lower())

            if player is None:
                unmatched_names.append(display_name)
                continue

            matched_count += 1

            # update_or_create on the three natural-key fields.
            # 'timestamp' is required (no auto_now_add); set it to now on
            # both create and update so it always reflects the latest scrape.
            obj, created = Odds.objects.update_or_create(
                player=player,
                tournament=tournament,
                bookmaker=BOOKMAKER,
                defaults={
                    "win_odds": odds_str,
                    "top_5_odds": "",
                    "top_10_odds": "",
                    "top_20_odds": "",
                    "make_cut_odds": "",
                    "timestamp": now,
                },
            )

            upserted_count += 1
            action = "Created" if created else "Updated"
            self.stdout.write(f"  {action}: {player.display_name} → {odds_str}")

        # ------------------------------------------------------------------ #
        # Step 6 — Print summary
        # ------------------------------------------------------------------ #
        self.stdout.write(
            self.style.SUCCESS(
                f"\nSummary\n"
                f"  Odds entries found  : {total_found}\n"
                f"  Matched to players  : {matched_count}\n"
                f"  Upserted            : {upserted_count}"
            )
        )

        if unmatched_names:
            self.stdout.write(
                self.style.WARNING(
                    f"  Unmatched names ({len(unmatched_names)}): "
                    + ", ".join(unmatched_names)
                )
            )

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _fetch_html(self, url: str) -> str:
        """HTTP GET *url* with a browser User-Agent and return the response text."""
        try:
            response = requests.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=15,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError(f"Failed to fetch article: {exc}") from exc
        return response.text

    def _resolve_tournament(self, tournament_id: str | None) -> Tournament:
        """
        Return the relevant Tournament instance.

        Resolution order
        ----------------
        1. If *tournament_id* is supplied, look up by ``espn_id``.
        2. The current in-progress tournament (``status = 'in_progress'``).
        3. The earliest upcoming scheduled tournament.
        4. Raise ``CommandError`` if nothing is found.
        """
        if tournament_id is not None:
            try:
                return Tournament.objects.get(espn_id=tournament_id)
            except Tournament.DoesNotExist:
                raise CommandError(
                    f"No Tournament found with espn_id='{tournament_id}'. "
                    "Run 'python manage.py scrape_pga' to populate tournaments."
                )

        # In-progress: use the dedicated status field which is kept up to date
        # by the existing scrape_pga command.
        in_progress = (
            Tournament.objects.filter(status=Tournament.Status.IN_PROGRESS)
            .order_by("start_date")
            .first()
        )
        if in_progress:
            return in_progress

        # Fall back to the next scheduled event.
        today = timezone.now().date()
        upcoming = (
            Tournament.objects.filter(
                status=Tournament.Status.SCHEDULED,
                start_date__gte=today,
            )
            .order_by("start_date")
            .first()
        )
        if upcoming:
            return upcoming

        raise CommandError(
            "No in-progress or upcoming tournament found in the database. "
            "Pass --tournament <espn_id> explicitly, or run 'python manage.py scrape_pga' "
            "to populate the tournament schedule."
        )
