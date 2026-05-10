from datetime import datetime

from django.core.management.base import BaseCommand

from golf.models import Leaderboard, Player, PlayerScore, Tournament, TournamentRound
from golf.scraper.espn import fetch_scoreboard


class Command(BaseCommand):
    help = 'Scrape PGA Tour scoreboard data from ESPN and save to database'

    def handle(self, *args, **options):
        self.stdout.write('Fetching PGA scoreboard from ESPN...')
        data = fetch_scoreboard()

        events = data.get('events', [])
        self.stdout.write(f'Found {len(events)} event(s)\n')

        for event in events:
            self._process_event(event)

        self.stdout.write(self.style.SUCCESS('\nScrape complete.'))

    def _process_event(self, event):
        espn_id = str(event['id'])
        name = event.get('name', '')
        season_year = event.get('season', {}).get('year', datetime.now().year)
        start_date = _parse_date(event.get('date', ''))
        end_date = _parse_date(event.get('endDate', ''))

        status_map = {
            'pre':      Tournament.Status.SCHEDULED,
            'in':       Tournament.Status.IN_PROGRESS,
            'post':     Tournament.Status.COMPLETED,
        }
        raw_status = event.get('status', {}).get('type', {}).get('state', 'pre')
        status = status_map.get(raw_status, Tournament.Status.SCHEDULED)

        tournament, created = Tournament.objects.update_or_create(
            espn_id=espn_id,
            defaults={
                'name': name,
                'season': season_year,
                'start_date': start_date,
                'end_date': end_date,
                'status': status,
            },
        )

        action = 'Created' if created else 'Updated'
        self.stdout.write(f'  [{action}] {name}  (status: {status})')

        for competition in event.get('competitions', []):
            self._process_competition(tournament, competition)

    def _process_competition(self, tournament, competition):
        for competitor in competition.get('competitors', []):
            player = self._upsert_player(competitor)
            if player:
                self._upsert_scores(tournament, player, competitor)

    def _upsert_player(self, competitor):
        espn_id = str(competitor.get('id', ''))
        if not espn_id:
            return None

        athlete = competitor.get('athlete', {})
        display_name = athlete.get('displayName', '')
        country = athlete.get('flag', {}).get('alt', '')

        # Split "First Last" — handles multi-word first names by taking last word as surname
        parts = display_name.rsplit(' ', 1)
        first_name = parts[0] if len(parts) > 1 else ''
        last_name = parts[-1]

        player, _ = Player.objects.update_or_create(
            espn_id=espn_id,
            defaults={
                'display_name': display_name,
                'first_name': first_name,
                'last_name': last_name,
                'country': country,
            },
        )
        return player

    def _upsert_scores(self, tournament, player, competitor):
        linescores = competitor.get('linescores', [])
        score_field = competitor.get('score', '')
        total_display = score_field if isinstance(score_field, str) else score_field.get('displayValue', '')
        position = str(competitor.get('order', ''))

        Leaderboard.objects.update_or_create(
            tournament=tournament,
            player=player,
            defaults={
                'position': position,
                'total_score_to_par': _parse_score(total_display),
                'rounds_completed': len(linescores),
            },
        )

        for linescore in linescores:
            round_number = linescore.get('period')
            if not round_number:
                continue

            round_obj, _ = TournamentRound.objects.get_or_create(
                tournament=tournament,
                round_number=round_number,
            )

            raw_strokes = linescore.get('value')
            if raw_strokes is None:
                continue  # placeholder entry for a round not yet played

            hole_scores = linescore.get('linescores', [])
            thru = len(hole_scores) if hole_scores else None

            PlayerScore.objects.update_or_create(
                tournament=tournament,
                player=player,
                round=round_obj,
                defaults={
                    'strokes': int(raw_strokes) if raw_strokes is not None else None,
                    'score_to_par': _parse_score(linescore.get('displayValue', '')),
                    'thru': thru,
                },
            )


def _parse_date(date_str):
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
    except (ValueError, AttributeError):
        return None


def _parse_score(value):
    """Convert ESPN score string to integer relative to par. 'E' → 0, '+3' → 3, '-2' → -2."""
    if not value:
        return None
    if value == 'E':
        return 0
    try:
        return int(value.replace('+', ''))
    except (ValueError, AttributeError):
        return None
