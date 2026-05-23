from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from golf.models import Course, Leaderboard, Player, PlayerScore, Tournament, TournamentRound
from golf.scraper.espn import fetch_scoreboard, fetch_tournament_venue

BASE_URL = settings.ESPN_API_BASE_URL


class Command(BaseCommand):
    help = 'Scrape PGA Tour scoreboard data from ESPN and save to database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--season',
            type=int,
            metavar='YEAR',
            help='Scrape all events for the given season year (e.g. 2026)',
        )

    def handle(self, *args, **options):
        season = options.get('season')

        if season:
            self.stdout.write(f'Fetching all {season} PGA Tour events...')
            try:
                r = requests.get(
                    f'https://sports.core.api.espn.com/v2/sports/golf/leagues/pga/seasons/{season}/types/2/events',
                    params={'limit': 100},
                    timeout=15,
                )
                r.raise_for_status()
                refs = r.json().get('items', [])
                self.stdout.write(f'  Found {len(refs)} events\n')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Failed to fetch season calendar: {e}'))
                return

            for ref in refs:
                try:
                    event_r = requests.get(ref['$ref'], timeout=10)
                    event_r.raise_for_status()
                    event_meta = event_r.json()
                    name = event_meta.get('name', '?')
                    start_date = _parse_date(event_meta.get('date', ''))
                    if not start_date:
                        continue
                    date_str = start_date.strftime('%Y%m%d')
                    self.stdout.write(f'  Fetching {name} ({date_str})...', ending=' ')
                    self.stdout.flush()
                    scoreboard_r = requests.get(
                        f'{BASE_URL}/scoreboard',
                        params={'dates': date_str},
                        timeout=30,
                    )
                    scoreboard_r.raise_for_status()
                    events = scoreboard_r.json().get('events', [])
                    self.stdout.write(f'got {len(events)} event(s), saving...', ending=' ')
                    self.stdout.flush()
                    for event in events:
                        self._process_event(event, skip_venue=True)
                    self.stdout.write('done')
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f'  Skipped ({e})'))
            return

        self.stdout.write('\nFetching current scoreboard...')
        data = fetch_scoreboard()
        events = data.get('events', [])
        self.stdout.write(f'Found {len(events)} event(s)\n')
        for event in events:
            self._process_event(event)

        self.stdout.write(self.style.SUCCESS('\nScrape complete.'))

    def _process_event(self, event, skip_venue=False):
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

        if not skip_venue and tournament.course is None:
            try:
                venue_name = fetch_tournament_venue(name)
                if venue_name:
                    course, _ = Course.objects.get_or_create(name=venue_name)
                    tournament.course = course
                    tournament.save(update_fields=['course'])
                    self.stdout.write(f'    Venue: {venue_name}')
            except Exception:
                pass

        for competition in event.get('competitions', []):
            self._process_competition(tournament, competition)

    def _process_competition(self, tournament, competition):
        competitors = competition.get('competitors', [])
        if not competitors:
            return

        # Bulk upsert players
        player_rows = []
        for c in competitors:
            espn_id = str(c.get('id', ''))
            if not espn_id:
                continue
            athlete = c.get('athlete') or c.get('team') or {}
            display_name = athlete.get('displayName', '')
            if not display_name:
                continue
            parts = display_name.rsplit(' ', 1)
            player_rows.append(Player(
                espn_id=espn_id,
                display_name=display_name,
                first_name=parts[0] if len(parts) > 1 else '',
                last_name=parts[-1],
                country=athlete.get('flag', {}).get('alt', ''),
            ))
        Player.objects.bulk_create(
            player_rows,
            update_conflicts=True,
            unique_fields=['espn_id'],
            update_fields=['display_name', 'first_name', 'last_name', 'country'],
        )
        player_map = {p.espn_id: p for p in Player.objects.filter(espn_id__in=[r.espn_id for r in player_rows])}

        # Fetch tee times from ESPN core API (scoreboard omits them)
        core_tee_times = _fetch_core_tee_times(tournament.espn_id)

        # Collect round numbers needed — rounds with actual strokes OR a tee time
        round_numbers = set()
        for c in competitors:
            espn_id_c = str(c.get('id', ''))
            for ls in c.get('linescores', []):
                rn = ls.get('period')
                if not rn or rn > 4:
                    continue
                raw = ls.get('value')
                has_strokes = raw is not None and raw > 0
                has_tee_time = rn in core_tee_times.get(espn_id_c, {})
                if has_strokes or has_tee_time:
                    round_numbers.add(rn)
        for rn in round_numbers:
            TournamentRound.objects.get_or_create(tournament=tournament, round_number=rn)
        round_map = {r.round_number: r for r in TournamentRound.objects.filter(tournament=tournament)}

        # Bulk upsert leaderboard
        now = datetime.now(timezone.utc)
        lb_rows = []
        for c in competitors:
            espn_id = str(c.get('id', ''))
            player = player_map.get(espn_id)
            if not player:
                continue
            score_field = c.get('score', '')
            total_display = score_field if isinstance(score_field, str) else score_field.get('displayValue', '')
            lb_rows.append(Leaderboard(
                tournament=tournament,
                player=player,
                position=str(c.get('order', '')),
                total_score_to_par=_parse_score(total_display),
                rounds_completed=len(c.get('linescores', [])),
                last_updated=now,
            ))
        Leaderboard.objects.bulk_create(
            lb_rows,
            update_conflicts=True,
            unique_fields=['tournament', 'player'],
            update_fields=['position', 'total_score_to_par', 'rounds_completed', 'last_updated'],
        )

        # Bulk upsert player scores
        score_rows = []
        for c in competitors:
            espn_id = str(c.get('id', ''))
            player = player_map.get(espn_id)
            if not player:
                continue
            player_tee_times = core_tee_times.get(espn_id, {})
            for ls in c.get('linescores', []):
                rn = ls.get('period')
                if not rn or rn > 4:
                    continue
                raw_strokes = ls.get('value')
                has_strokes = raw_strokes is not None and raw_strokes > 0
                tee_time = player_tee_times.get(rn)
                if not has_strokes and not tee_time:
                    continue
                round_obj = round_map.get(rn)
                if not round_obj:
                    continue
                hole_scores = ls.get('linescores', [])
                score_rows.append(PlayerScore(
                    tournament=tournament,
                    player=player,
                    round=round_obj,
                    strokes=int(raw_strokes) if has_strokes else None,
                    score_to_par=_parse_score(ls.get('displayValue', '')) if has_strokes else None,
                    thru=len(hole_scores) if hole_scores else None,
                    tee_time=tee_time,
                ))
        PlayerScore.objects.bulk_create(
            score_rows,
            update_conflicts=True,
            unique_fields=['tournament', 'player', 'round'],
            update_fields=['strokes', 'score_to_par', 'thru', 'tee_time'],
        )


def _parse_date(date_str):
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
    except (ValueError, AttributeError):
        return None


def _parse_datetime(dt_str):
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


def _fetch_core_tee_times(espn_id: str) -> dict:
    """Fetch upcoming-round tee times for all competitors from ESPN core API.
    Returns {player_espn_id: {round_number: tee_time_datetime}}.
    Rounds that already have scores are excluded."""
    try:
        r = requests.get(
            f'https://sports.core.api.espn.com/v2/sports/golf/leagues/pga/events/{espn_id}'
            f'/competitions/{espn_id}/competitors',
            params={'limit': 200},
            timeout=15,
        )
        r.raise_for_status()
        items = r.json().get('items', [])
    except Exception:
        return {}

    def _fetch_ls(item):
        pid = item.get('id', '')
        ls_ref = item.get('linescores', {})
        if not isinstance(ls_ref, dict):
            return pid, {}
        url = ls_ref.get('$ref', '')
        if not url:
            return pid, {}
        try:
            r2 = requests.get(url, timeout=10)
            if not r2.ok:
                return pid, {}
            tee_map = {}
            for ls in r2.json().get('items', []):
                rn = ls.get('period')
                tt = ls.get('teeTime')
                # Only include rounds without a score (upcoming rounds)
                if rn and tt and not (ls.get('value', 0) or 0):
                    tee_map[rn] = _parse_datetime(tt)
            return pid, tee_map
        except Exception:
            return pid, {}

    result = {}
    with ThreadPoolExecutor(max_workers=20) as ex:
        for pid, tee_map in ex.map(_fetch_ls, items):
            if tee_map:
                result[pid] = tee_map
    return result


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
