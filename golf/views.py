import logging
from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Max
from django.db.models.expressions import RawSQL
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .models import Leaderboard, Player, PlayerScore, Tournament, TournamentRound
from .scraper.espn import fetch_player_bio, fetch_wikipedia_bio

logger = logging.getLogger(__name__)


def index(request):
    tournaments = Tournament.objects.order_by('-start_date')

    tournament_id = request.GET.get('tournament')
    if tournament_id:
        tournament = get_object_or_404(Tournament, pk=tournament_id)
    else:
        tournament = (
            tournaments.filter(status=Tournament.Status.IN_PROGRESS).first()
            or tournaments.first()
        )

    leaderboard_data = []
    round_numbers = []

    if tournament:
        round_numbers = list(
            TournamentRound.objects
            .filter(tournament=tournament)
            .order_by('round_number')
            .values_list('round_number', flat=True)
        )

        score_map = {
            (s.player_id, s.round.round_number): s
            for s in PlayerScore.objects
                .filter(tournament=tournament)
                .select_related('round')
        }

        leaderboard = (
            Leaderboard.objects
            .filter(tournament=tournament)
            .select_related('player')
            .annotate(pos_int=RawSQL("CAST(NULLIF(position, '') AS INTEGER)", []))
            .order_by('total_score_to_par', 'pos_int')
        )

        for entry in leaderboard:
            round_scores = [score_map.get((entry.player_id, rn)) for rn in round_numbers]
            latest = next((s for s in reversed(round_scores) if s is not None and s.thru is not None), None)
            thru = latest.thru if latest else None
            leaderboard_data.append((entry, round_scores, thru))

    paginator = Paginator(leaderboard_data, 10)
    page = paginator.get_page(request.GET.get('page'))

    last_updated = None
    if tournament:
        last_updated = Leaderboard.objects.filter(tournament=tournament).aggregate(
            latest=Max('last_updated')
        )['latest']

    return render(request, 'golf/index.html', {
        'last_updated_iso': last_updated.isoformat() if last_updated else '',
        'tournament': tournament,
        'tournaments': tournaments,
        'page': page,
        'round_numbers': round_numbers,
        'last_updated': last_updated,
    })


def player_detail(request, espn_id):
    player = get_object_or_404(Player, espn_id=espn_id)

    stale = (
        player.bio_updated_at is None or
        timezone.now() - player.bio_updated_at > timedelta(hours=24) or
        not player.wiki_bio
    )

    if stale:
        try:
            data = fetch_player_bio(espn_id)
            athlete = data.get('athlete', {})

            from datetime import date
            birthdate = None
            dob_str = athlete.get('displayDOB', '')
            if dob_str:
                try:
                    birthdate = date.fromisoformat(dob_str[:10])
                except ValueError:
                    try:
                        from datetime import datetime
                        birthdate = datetime.strptime(dob_str, '%m/%d/%Y').date()
                    except ValueError:
                        pass

            stats = {
                s['name']: s
                for s in athlete.get('statsSummary', {}).get('statistics', [])
                if s.get('name')
            }

            player.birthdate      = birthdate
            player.birthplace     = athlete.get('displayBirthPlace', '')
            player.height         = athlete.get('displayHeight', '')
            player.weight         = athlete.get('displayWeight', '')
            player.turned_pro     = athlete.get('turnedPro')
            player.earnings       = stats.get('amount', {}).get('value')
            player.fedex_points   = int(stats.get('cupPoints', {}).get('value', 0) or 0) or None
            player.bio_updated_at = timezone.now()
            player.save()
        except Exception:
            logger.exception('Failed to fetch ESPN bio for player %s', espn_id)

        try:
            wiki = fetch_wikipedia_bio(player.display_name)
            if wiki:
                player.wiki_bio = wiki
                player.save(update_fields=['wiki_bio'])
        except Exception:
            logger.exception('Failed to fetch Wikipedia bio for player %s', espn_id)

    recent_scores = (
        PlayerScore.objects
        .filter(player=player)
        .select_related('tournament', 'round')
        .order_by('-tournament__start_date', 'round__round_number')[:20]
    )

    return render(request, 'golf/player_detail.html', {
        'player': player,
        'recent_scores': recent_scores,
    })


def last_updated_api(request):
    tournament_id = request.GET.get('tournament')
    qs = Leaderboard.objects
    if tournament_id:
        qs = qs.filter(tournament_id=tournament_id)
    result = qs.aggregate(latest=Max('last_updated'))['latest']
    ts = result.isoformat() if result else None
    logger.info('Poll from %s — last_updated: %s', request.META.get('REMOTE_ADDR'), ts)
    return JsonResponse({'last_updated': ts})
