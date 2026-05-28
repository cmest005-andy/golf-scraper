import logging
from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Case, IntegerField, Max, Q, Value, When
from django.db.models.expressions import RawSQL
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .models import Course, CourseHole, Leaderboard, NewsArticle, Player, PlayerScore, Tournament, TournamentRound
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

    # Include scheduled tournaments only if they have scraped data (tee times / field)
    scheduled_with_data = set(
        Leaderboard.objects
        .filter(tournament__season=current_season, tournament__status=Tournament.Status.SCHEDULED)
        .values_list('tournament_id', flat=True)
        .distinct()
    )

    tournaments = (
        Tournament.objects
        .filter(season=current_season)
        .exclude(status=Tournament.Status.SCHEDULED)
        .union(
            Tournament.objects.filter(pk__in=scheduled_with_data)
        )
    )

    tournament_ids = list(tournaments.values_list('pk', flat=True))
    tournaments_qs = Tournament.objects.filter(pk__in=tournament_ids)

    # Default: in-progress → soonest upcoming with data → most recently completed
    tournament_id = request.GET.get('tournament')
    if tournament_id:
        tournament = get_object_or_404(Tournament, pk=tournament_id)
    else:
        tournament = (
            tournaments_qs.filter(status=Tournament.Status.IN_PROGRESS).order_by('start_date').first()
            or Tournament.objects.filter(pk__in=scheduled_with_data).order_by('start_date').first()
            or tournaments_qs.filter(status=Tournament.Status.COMPLETED).order_by('-start_date').first()
            or tournaments_qs.first()
        )

    # Sort for dropdown: in-progress, then soonest upcoming, then most recently completed
    import datetime as _dt
    _epoch = _dt.date(2000, 1, 1)
    def _sort_key(t):
        days = (t.start_date - _epoch).days
        if t.status == Tournament.Status.IN_PROGRESS:
            return (0, days)
        if t.status == Tournament.Status.SCHEDULED:
            return (1, days)
        return (2, -days)

    tournaments = sorted(tournaments_qs, key=_sort_key)

    search = request.GET.get('search', '').strip()
    leaderboard_data = []
    round_numbers = []

    if tournament:
        existing_rounds = list(
            TournamentRound.objects
            .filter(tournament=tournament)
            .order_by('round_number')
            .values_list('round_number', flat=True)
        )
        max_round = max(max(existing_rounds, default=0), 4)
        round_numbers = list(range(1, max_round + 1))

        score_map = {
            (s.player_id, s.round.round_number): s
            for s in PlayerScore.objects
                .filter(tournament=tournament)
                .select_related('round')
        }

        from django.db.models.functions import Coalesce
        from django.db.models import IntegerField as IF
        leaderboard = (
            Leaderboard.objects
            .filter(tournament=tournament)
            .select_related('player')
            .annotate(
                pos_int=RawSQL("CAST(NULLIF(position, '') AS INTEGER)", []),
                wr=Coalesce('player__world_ranking', Value(9999, output_field=IF())),
            )
        )
        if tournament.status == Tournament.Status.SCHEDULED:
            leaderboard = leaderboard.order_by('wr')
        else:
            leaderboard = leaderboard.order_by('total_score_to_par', 'pos_int')

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


def course_detail(request, pk):
    course = get_object_or_404(Course, pk=pk)
    holes = list(course.holes.order_by('number'))
    front = [h for h in holes if h.number <= 9]
    back  = [h for h in holes if h.number >= 10]
    front_par     = sum(h.par for h in front)
    back_par      = sum(h.par for h in back)
    front_yardage = sum(h.yardage or 0 for h in front)
    back_yardage  = sum(h.yardage or 0 for h in back)
    tournaments = (
        Tournament.objects
        .filter(course=course)
        .order_by('-start_date')
    )
    return render(request, 'golf/course_detail.html', {
        'course':         course,
        'front':          front,
        'back':           back,
        'front_par':      front_par,
        'back_par':       back_par,
        'front_yardage':  front_yardage,
        'back_yardage':   back_yardage,
        'total_par':      front_par + back_par,
        'total_yardage':  front_yardage + back_yardage,
        'tournaments':    tournaments,
        'has_scorecard':  bool(holes),
    })


def schedule(request):
    from django.utils import timezone
    today = timezone.now().date()

    current_season = (
        Tournament.objects
        .filter(status=Tournament.Status.IN_PROGRESS)
        .values_list('season', flat=True)
        .first()
    ) or (
        Tournament.objects
        .aggregate(max_season=Max('season'))['max_season']
    )

    upcoming = (
        Tournament.objects
        .filter(start_date__gte=today, status=Tournament.Status.SCHEDULED, season=current_season)
        .order_by('start_date')
    )
    in_progress = (
        Tournament.objects
        .filter(status=Tournament.Status.IN_PROGRESS, season=current_season)
        .order_by('start_date')
    )
    completed = (
        Tournament.objects
        .filter(status=Tournament.Status.COMPLETED, season=current_season)
        .order_by('-start_date')
    )

    winner_map = {
        e.tournament_id: e.player
        for e in Leaderboard.objects
            .filter(tournament__in=completed, position='1')
            .select_related('player')
    }
    completed_results = [(t, winner_map.get(t.pk)) for t in completed]

    return render(request, 'golf/schedule.html', {
        'in_progress': in_progress,
        'upcoming': upcoming,
        'completed_results': completed_results,
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
                'tee_time': score.tee_time.isoformat() if score and score.tee_time else None,
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


def news(request):
    articles = NewsArticle.objects.filter(archived=False).order_by('-published_at')
    return render(request, 'golf/news.html', {
        'articles': articles,
        'page_title': 'PGA Tour News',
    })


def news_archive(request):
    archived_qs = NewsArticle.objects.filter(archived=True).order_by('-published_at')
    paginator = Paginator(archived_qs, 12)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'golf/news_archive.html', {
        'page_obj': page_obj,
        'page_title': 'News Archive',
    })
