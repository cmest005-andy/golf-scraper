import logging
from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Case, IntegerField, Max, Q, Value, When
from django.db.models.expressions import RawSQL
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .models import Leaderboard, Player, PlayerScore, Tournament, TournamentRound
from .scraper.espn import fetch_player_bio, fetch_wikipedia_bio

logger = logging.getLogger(__name__)


def home(request):
    return render(request, 'golf/home.html')


def index(request):
    current_season = (
        Tournament.objects
        .filter(status=Tournament.Status.IN_PROGRESS)
        .values_list('season', flat=True)
        .first()
    ) or (
        Tournament.objects
        .aggregate(max_season=Max('season'))['max_season']
    )

    tournaments = (
        Tournament.objects
        .filter(season=current_season)
        .exclude(status=Tournament.Status.SCHEDULED)
        .annotate(
            status_order=Case(
                When(status=Tournament.Status.IN_PROGRESS, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by('status_order', '-start_date')
    )

    tournament_id = request.GET.get('tournament')
    if tournament_id:
        tournament = get_object_or_404(Tournament, pk=tournament_id)
    else:
        tournament = (
            tournaments.filter(status=Tournament.Status.IN_PROGRESS).first()
            or tournaments.first()
        )

    search = request.GET.get('search', '').strip()
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

        if search:
            leaderboard = leaderboard.filter(
                Q(player__display_name__istartswith=search) |
                Q(player__display_name__icontains=' ' + search)
            )

        for entry in leaderboard:
            round_score_list = [score_map.get((entry.player_id, rn)) for rn in round_numbers]
            latest = next((s for s in reversed(round_score_list) if s is not None and s.thru is not None), None)
            thru = latest.thru if latest else None
            round_score_pairs = [(rn, score_map.get((entry.player_id, rn))) for rn in round_numbers]
            leaderboard_data.append((entry, round_score_pairs, thru))

    paginator = Paginator(leaderboard_data, 10)
    page = paginator.get_page(request.GET.get('page'))

    last_updated = None
    if tournament:
        last_updated = Leaderboard.objects.filter(tournament=tournament).aggregate(
            latest=Max('last_updated')
        )['latest']

    player_names = []
    if tournament:
        player_names = list(
            Leaderboard.objects
            .filter(tournament=tournament)
            .select_related('player')
            .order_by('player__display_name')
            .values_list('player__display_name', flat=True)
        )

    return render(request, 'golf/index.html', {
        'last_updated_iso': last_updated.isoformat() if last_updated else '',
        'tournament': tournament,
        'tournaments': tournaments,
        'page': page,
        'round_numbers': round_numbers,
        'last_updated': last_updated,
        'search': search,
        'player_names': player_names,
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

    leaderboard_entries = (
        Leaderboard.objects
        .filter(player=player)
        .select_related('tournament')
        .order_by('-tournament__start_date')
    )

    score_map = {
        (s.tournament_id, s.round.round_number): s
        for s in PlayerScore.objects
            .filter(player=player)
            .select_related('round')
    }

    rounds_by_tournament = {}
    for rn_obj in (
        TournamentRound.objects
        .filter(tournament__in=[e.tournament_id for e in leaderboard_entries], round_number__lte=4)
        .order_by('round_number')
    ):
        rounds_by_tournament.setdefault(rn_obj.tournament_id, []).append(rn_obj.round_number)

    max_rounds = max((len(v) for v in rounds_by_tournament.values()), default=4)

    recent_results = []
    for entry in leaderboard_entries:
        tid = entry.tournament_id
        round_numbers = rounds_by_tournament.get(tid, [])
        round_scores = [score_map.get((tid, rn)) for rn in round_numbers]
        # Detect missed cut: completed tournament has R3+ but player has no R3 score
        is_completed = entry.tournament.status == Tournament.Status.COMPLETED
        has_r1 = bool(round_scores[0]) if round_scores else False
        has_r3 = bool(round_scores[2]) if len(round_scores) > 2 else True
        missed_cut = is_completed and has_r1 and not has_r3 and len(round_numbers) > 2
        # Pad to max_rounds so columns align
        while len(round_scores) < max_rounds:
            round_scores.append(None)
        recent_results.append((entry, round_scores, missed_cut))

    round_columns = list(range(1, max_rounds + 1))

    return render(request, 'golf/player_detail.html', {
        'player': player,
        'recent_results': recent_results,
        'round_columns': round_columns,
    })


def leaderboard_api(request):
    tournament_id = request.GET.get('tournament')

    if tournament_id:
        tournament = get_object_or_404(Tournament, pk=tournament_id)
    else:
        tournament = (
            Tournament.objects.filter(status=Tournament.Status.IN_PROGRESS).first()
            or Tournament.objects.order_by('-start_date').first()
        )

    if not tournament:
        return JsonResponse({'last_updated': None, 'players': [], 'round_numbers': []})

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

    players = []
    for entry in leaderboard:
        round_score_list = [score_map.get((entry.player_id, rn)) for rn in round_numbers]
        latest = next((s for s in reversed(round_score_list) if s is not None and s.thru is not None), None)
        thru = latest.thru if latest else None

        rounds = []
        for rn, score in zip(round_numbers, round_score_list):
            rounds.append({
                'round_number': rn,
                'strokes': score.strokes if score else None,
                'score_to_par': score.score_to_par if score else None,
                'thru': score.thru if score else None,
            })

        players.append({
            'player_id': entry.player.espn_id,
            'position': entry.position or '',
            'total_score_to_par': entry.total_score_to_par,
            'thru': thru,
            'rounds': rounds,
        })

    last_updated = Leaderboard.objects.filter(tournament=tournament).aggregate(
        latest=Max('last_updated')
    )['latest']

    return JsonResponse({
        'last_updated': last_updated.isoformat() if last_updated else None,
        'tournament_status': tournament.status,
        'round_numbers': round_numbers,
        'players': players,
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
