"""
Management command: fetch_rankings
-----------------------------------
Scrapes player world rankings from an OWGR event page URL and updates
the ``world_ranking`` field on matching ``Player`` records.

Usage
-----
    python manage.py fetch_rankings --url "https://www.owgr.com/events/the-cj-cup-byron-nelson-11360"
"""

import requests
from django.core.management.base import BaseCommand, CommandError

from golf.rankings import fetch_rankings_from_url


class Command(BaseCommand):
    help = "Scrape OWGR event page and update player world rankings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            type=str,
            required=True,
            metavar="URL",
            help="OWGR event page URL.",
        )

    def handle(self, *args, **options):
        url = options["url"]
        self.stdout.write(f"Fetching   : {url}")
        try:
            matched, unmatched = fetch_rankings_from_url(url)
        except requests.RequestException as exc:
            raise CommandError(f"Failed to fetch OWGR page: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSummary\n"
                f"  Matched and updated : {matched}\n"
                f"  Unmatched names     : {len(unmatched)}"
            )
        )
        if unmatched:
            self.stdout.write(self.style.WARNING("  Unmatched player names:"))
            for name in unmatched:
                self.stdout.write(f"  - {name}")
