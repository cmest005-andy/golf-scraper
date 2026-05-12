import re
import unicodedata
from datetime import date

import requests
from django.core.management.base import BaseCommand
from django.utils import timezone

from golf.models import Course, Leaderboard, Odds, Player, Tournament
from golf.scraper.espn import fetch_major_odds, fetch_tournament_field, fetch_tournament_venue


def _slug(name: str) -> str:
    """Normalize a player name for fuzzy matching: strip accents, punctuation, lowercase."""
    nfkd = unicodedata.normalize('NFKD', name)
    ascii_ = nfkd.encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z]', '', ascii_.lower())


class Command(BaseCommand):
    help = 'Sync player field and odds for an upcoming tournament.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--espn-id',
            type=str,
            help='ESPN event ID. Defaults to next scheduled tournament.',
        )

    def handle(self, *args, **options):
        espn_id = options.get('espn_id')

        if espn_id:
            tournament = Tournament.objects.filter(espn_id=espn_id).first()
            if not tournament:
                tournament = self._fetch_and_create_tournament(espn_id)
        else:
            tournament = (
                Tournament.objects.filter(status=Tournament.Status.SCHEDULED)
                .order_by('start_date')
                .first()
            )
            if not tournament:
                self.stdout.write('No scheduled tournaments found. Provide --espn-id.')
                return

        self.stdout.write(f'Tournament: {tournament.name} ({tournament.espn_id})')

        # ── Odds (majors only) ─────────────────────────────────────────────
        self.stdout.write('Fetching odds...')
        odds_map = fetch_major_odds(tournament.name)

        if not odds_map:
            self.stdout.write('  No odds available (non-major). World rankings will be used in draft.')

        # ── Field ──────────────────────────────────────────────────────────
        self.stdout.write('Fetching player field from ESPN...')
        try:
            espn_ids = fetch_tournament_field(tournament.espn_id)
        except Exception as e:
            self.stdout.write(f'  ERROR fetching field: {e}')
            espn_ids = []

        # Build slug → Player lookup for all players in DB
        slug_to_player = {_slug(p.display_name): p for p in Player.objects.all()}

        added = 0
        if espn_ids:
            for athlete_id in espn_ids:
                player = Player.objects.filter(espn_id=athlete_id).first()
                if not player:
                    continue
                _, created = Leaderboard.objects.get_or_create(tournament=tournament, player=player)
                if created:
                    added += 1
            self.stdout.write(f'  {len(espn_ids)} in ESPN field, {added} new Leaderboard entries created.')
        elif odds_map:
            # ESPN field not announced yet — fall back to odds player names
            self.stdout.write('  ESPN field empty, building from odds list...')
            unmatched = []
            for name_key in odds_map:
                player = slug_to_player.get(_slug(name_key))
                if not player:
                    unmatched.append(name_key)
                    continue
                _, created = Leaderboard.objects.get_or_create(tournament=tournament, player=player)
                if created:
                    added += 1
            self.stdout.write(f'  {added} players added from odds list.')
            if unmatched:
                self.stdout.write(f'  {len(unmatched)} not found in DB (not yet scraped): {", ".join(sorted(unmatched)[:10])}{"..." if len(unmatched) > 10 else ""}')
        else:
            self.stdout.write('  No field data available from ESPN or odds.')

        if not odds_map:
            return

        # Match odds to players already in the tournament field
        players = list(Player.objects.filter(
            leaderboard_entries__tournament=tournament
        ).distinct())

        # Build slug → odds lookup
        slug_odds = {_slug(k): v for k, v in odds_map.items()}

        matched = 0
        now = timezone.now()
        for player in players:
            win_odds = slug_odds.get(_slug(player.display_name))
            if not win_odds:
                continue
            Odds.objects.update_or_create(
                tournament=tournament,
                player=player,
                bookmaker='DraftKings',
                defaults={'win_odds': win_odds, 'timestamp': now},
            )
            matched += 1

        self.stdout.write(f'  Odds matched for {matched}/{len(players)} players.')

    def _fetch_and_create_tournament(self, espn_id):
        """Fetch tournament metadata from ESPN and create DB record."""
        resp = requests.get(
            f'https://sports.core.api.espn.com/v2/sports/golf/leagues/pga/events/{espn_id}',
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        from golf.management.commands.scrape_pga import _parse_date
        name       = data.get('name', f'Event {espn_id}')
        start_date = _parse_date(data.get('date', ''))
        end_date   = _parse_date(data.get('endDate', ''))
        season     = data.get('season', {}).get('year', start_date.year if start_date else date.today().year)

        tournament, _ = Tournament.objects.get_or_create(
            espn_id=espn_id,
            defaults={
                'name':       name,
                'season':     season,
                'start_date': start_date or date.today(),
                'end_date':   end_date or date.today(),
                'status':     Tournament.Status.SCHEDULED,
            },
        )
        self.stdout.write(f'  Created tournament: {tournament.name}')

        # Fetch venue
        if not tournament.course:
            try:
                venue_name = fetch_tournament_venue(name)
                if venue_name:
                    course, _ = Course.objects.get_or_create(name=venue_name)
                    tournament.course = course
                    tournament.save(update_fields=['course'])
            except Exception:
                pass

        return tournament
