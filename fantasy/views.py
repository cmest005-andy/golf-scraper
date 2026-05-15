import datetime
import json
import random

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from golf.models import Leaderboard, PlayerScore, Tournament

from .models import DraftMessage, DraftOrder, DraftPick, League, LeagueMember, WeeklyDraft


@login_required
def my_leagues(request):
    leagues = League.objects.filter(members=request.user).order_by('-created_at')
    return render(request, 'fantasy/my_leagues.html', {'leagues': leagues})


@login_required
def create_league(request):
    error = None
    if request.method == 'POST':
        name        = request.POST.get('name', '').strip()
        roster_size = request.POST.get('roster_size', '6').strip()
        if not name:
            error = 'League name is required.'
        else:
            try:
                roster_size = int(roster_size)
                if not (1 <= roster_size <= 20):
                    raise ValueError
            except ValueError:
                error = 'Roster size must be a number between 1 and 20.'

        if not error:
            league = League.objects.create(
                name=name,
                commissioner=request.user,
                roster_size=roster_size,
            )
            LeagueMember.objects.create(league=league, user=request.user)
            return redirect('fantasy:league_detail', pk=league.pk)

    return render(request, 'fantasy/create_league.html', {'error': error})


@login_required
def join_league(request):
    error = None
    if request.method == 'POST':
        code   = request.POST.get('invite_code', '').strip().upper()
        league = League.objects.filter(invite_code=code).first()
        if not league:
            error = 'Invalid invite code.'
        elif LeagueMember.objects.filter(league=league, user=request.user).exists():
            error = 'You are already a member of this league.'
        else:
            LeagueMember.objects.create(league=league, user=request.user)
            return redirect('fantasy:league_detail', pk=league.pk)

    return render(request, 'fantasy/join_league.html', {'error': error})


@login_required
def league_detail(request, pk):
    league = get_object_or_404(League, pk=pk)
    if not LeagueMember.objects.filter(league=league, user=request.user).exists():
        return redirect('fantasy:join_league')

    members         = LeagueMember.objects.filter(league=league).select_related('user', 'user__profile').order_by('joined_at')
    drafts          = WeeklyDraft.objects.filter(league=league).select_related('tournament').order_by('-tournament__start_date')
    is_commissioner = league.commissioner == request.user

    drafted_ids      = drafts.values_list('tournament_id', flat=True)
    can_create_draft = is_commissioner and Tournament.objects.exclude(pk__in=drafted_ids).filter(end_date__gte=datetime.date.today()).exists()
    show_invite_code = not drafts.filter(status__in=('open', 'locked')).exists()

    from golf.models import Leaderboard as LB
    draft_rosters = {}
    for draft in drafts:
        order = list(draft.order.select_related('member__user', 'member__user__profile').order_by('position'))
        if not order:
            continue
        has_scores = PlayerScore.objects.filter(tournament=draft.tournament).exists()
        lb_map = {e.player_id: e.total_score_to_par for e in LB.objects.filter(tournament=draft.tournament)} if has_scores else {}
        all_picks = DraftPick.objects.filter(draft=draft).select_related('player').order_by('pick_number')
        by_member = {}
        for pick in all_picks:
            by_member.setdefault(pick.member_id, []).append(pick)
        teams = []
        seen = set()
        for o in order:
            member = o.member
            if member.pk in seen:
                continue
            seen.add(member.pk)
            member_picks = by_member.get(member.pk, [])
            team_score = None
            pick_data = []
            for pick in member_picks:
                stp = lb_map.get(pick.player_id)
                if stp is not None:
                    team_score = (team_score or 0) + stp
                pick_data.append({'player': pick.player, 'score_to_par': stp})
            teams.append({'member': member, 'picks': pick_data, 'team_score': team_score})
        draft_rosters[draft.pk] = teams

    from django.utils import timezone as tz
    now = tz.now()
    today = datetime.date.today()

    # Any open draft shows the banner (lobby or in-progress)
    active_draft = next(
        (d for d in drafts if d.status == WeeklyDraft.Status.OPEN),
        None
    )

    draft_meta = {}
    for draft in drafts:
        if draft.draft_time:
            lobby_open    = draft.draft_time - datetime.timedelta(hours=1)
            local_dt      = tz.localtime(draft.draft_time)
            draft_meta[draft.pk] = {
                'is_draft_day':    local_dt.date() == today,
                'lobby_is_open':   now >= lobby_open,
                'lobby_open_time': lobby_open,
                'draft_started':   now >= draft.draft_time,
            }
        else:
            draft_meta[draft.pk] = {
                'is_draft_day': False, 'lobby_is_open': False,
                'lobby_open_time': None, 'draft_started': False,
            }

    return render(request, 'fantasy/league_detail.html', {
        'league': league,
        'members': members,
        'drafts': drafts,
        'is_commissioner': is_commissioner,
        'today': today,
        'draft_rosters': draft_rosters,
        'draft_meta': draft_meta,
        'can_create_draft': can_create_draft,
        'show_invite_code': show_invite_code,
        'my_membership':          members.filter(user=request.user).first(),
        'active_draft':           active_draft,
        'active_draft_total_picks': active_draft.picks.count() if active_draft else 0,
    })


@login_required
def my_team(request, pk):
    league = get_object_or_404(League, pk=pk)
    membership = get_object_or_404(LeagueMember, league=league, user=request.user)
    return redirect('fantasy:team_detail', league_pk=pk, member_pk=membership.pk)


@login_required
def team_detail(request, league_pk, member_pk):
    league = get_object_or_404(League, pk=league_pk)
    get_object_or_404(LeagueMember, league=league, user=request.user)
    membership = get_object_or_404(LeagueMember, pk=member_pk, league=league)
    is_mine = membership.user == request.user
    saved = False
    error = None

    if is_mine and request.method == 'POST':
        team_name = request.POST.get('team_name', '').strip()
        if len(team_name) > 100:
            error = 'Team name must be 100 characters or fewer.'
        else:
            membership.team_name = team_name
            membership.save()
            saved = True

    drafts_with_picks = []
    for draft in WeeklyDraft.objects.filter(league=league).select_related('tournament').order_by('-tournament__start_date'):
        picks = DraftPick.objects.filter(draft=draft, member=membership).select_related('player').order_by('pick_number')
        if not picks.exists():
            continue
        has_scores = PlayerScore.objects.filter(tournament=draft.tournament).exists()
        lb_map = {e.player_id: e.total_score_to_par for e in Leaderboard.objects.filter(tournament=draft.tournament)} if has_scores else {}
        pick_data = []
        team_score = None
        for pick in picks:
            stp = lb_map.get(pick.player_id)
            if stp is not None:
                team_score = (team_score or 0) + stp
            pick_data.append({'player': pick.player, 'score_to_par': stp})
        drafts_with_picks.append({
            'draft': draft,
            'picks': pick_data,
            'has_scores': has_scores,
            'team_score': team_score,
        })

    return render(request, 'fantasy/team_detail.html', {
        'league': league,
        'membership': membership,
        'is_mine': is_mine,
        'saved': saved,
        'error': error,
        'drafts_with_picks': drafts_with_picks,
    })


@login_required
def league_settings(request, pk):
    league = get_object_or_404(League, pk=pk)
    if league.commissioner != request.user:
        return redirect('fantasy:league_detail', pk=pk)

    error = None
    if request.method == 'POST':
        name        = request.POST.get('name', '').strip()
        roster_size = request.POST.get('roster_size', '').strip()
        if not name:
            error = 'League name is required.'
        else:
            try:
                roster_size = int(roster_size)
                if not (1 <= roster_size <= 20):
                    raise ValueError
            except ValueError:
                error = 'Roster size must be a number between 1 and 20.'

        if not error:
            league.name        = name
            league.roster_size = roster_size
            league.save(update_fields=['name', 'roster_size'])
            return redirect('fantasy:league_detail', pk=pk)

    return render(request, 'fantasy/league_settings.html', {'league': league, 'error': error})


@login_required
def create_draft(request, league_pk):
    league = get_object_or_404(League, pk=league_pk)
    if league.commissioner != request.user:
        return redirect('fantasy:league_detail', pk=league_pk)

    drafted_ids  = WeeklyDraft.objects.filter(league=league).values_list('tournament_id', flat=True)
    tournaments  = Tournament.objects.exclude(pk__in=drafted_ids).order_by('-start_date')
    error        = None

    if request.method == 'POST':
        from django.utils.dateparse import parse_datetime
        from django.utils import timezone as tz
        tournament = get_object_or_404(Tournament, pk=request.POST.get('tournament'))
        if WeeklyDraft.objects.filter(league=league, tournament=tournament).exists():
            error = 'A draft already exists for this tournament.'
        else:
            draft_time_raw = request.POST.get('draft_time', '').strip()
            draft_time = None
            if draft_time_raw:
                dt = parse_datetime(draft_time_raw)
                draft_time = tz.make_aware(dt) if dt and tz.is_naive(dt) else dt
            try:
                pick_time_limit = max(30, int(request.POST.get('pick_time_limit', 120)))
            except ValueError:
                pick_time_limit = 120
            draft = WeeklyDraft.objects.create(
                league=league, tournament=tournament,
                draft_time=draft_time, pick_time_limit=pick_time_limit,
            )
            return redirect('fantasy:draft_room', pk=draft.pk)

    return render(request, 'fantasy/create_draft.html', {
        'league': league,
        'tournaments': tournaments,
        'error': error,
    })


@login_required
def draft_room(request, pk):
    draft  = get_object_or_404(WeeklyDraft, pk=pk)
    league = draft.league

    try:
        my_membership = LeagueMember.objects.get(league=league, user=request.user)
    except LeagueMember.DoesNotExist:
        return redirect('fantasy:my_leagues')

    from django.utils import timezone as tz
    is_commissioner = league.commissioner == request.user

    # Lobby gate: block entry until 1 hour before draft_time
    if draft.draft_time:
        lobby_open = draft.draft_time - datetime.timedelta(hours=1)
        if tz.now() < lobby_open:
            return render(request, 'fantasy/draft_lobby_closed.html', {
                'draft':          draft,
                'league':         league,
                'lobby_open':     lobby_open,
                'is_commissioner': is_commissioner,
            })

    # Randomize draft order the first time the lobby is accessed
    if not draft.order.exists():
        from django.db import transaction
        with transaction.atomic():
            if not draft.order.exists():
                members = list(LeagueMember.objects.filter(league=league))
                random.shuffle(members)
                for i, member in enumerate(members, 1):
                    DraftOrder.objects.create(draft=draft, member=member, position=i)

    # Whether the draft clock has started (picks are allowed)
    draft_started = not draft.draft_time or tz.now() >= draft.draft_time

    member_count   = league.memberships.count()
    total_picks    = draft.picks.count()
    picks_needed   = member_count * league.roster_size
    draft_complete = total_picks >= picks_needed
    on_the_clock   = draft.current_pick_member()
    my_turn        = (on_the_clock == my_membership if on_the_clock else False) and draft_started

    # Players available to pick (in tournament field, not yet taken)
    taken_ids = draft.picks.values_list('player_id', flat=True)
    has_round_scores = PlayerScore.objects.filter(tournament=draft.tournament).exists()
    available = (
        Leaderboard.objects
        .filter(tournament=draft.tournament)
        .exclude(player_id__in=taken_ids)
        .select_related('player')
        .order_by('total_score_to_par' if has_round_scores else 'player__world_ranking')
    )

    # Odds map: player_id → win_odds string (majors); fall back to world ranking
    from golf.models import Odds as OddsModel
    odds_qs  = OddsModel.objects.filter(tournament=draft.tournament, bookmaker='DraftKings').values('player_id', 'win_odds')
    odds_map = {o['player_id']: o['win_odds'] for o in odds_qs}
    has_odds = bool(odds_map)

    # Sort by odds when available (best pre-tournament signal); fall back to live scores or world ranking
    if has_odds:
        def _odds_key(entry):
            try:
                return int(odds_map.get(entry.player_id, '') or '99999')
            except ValueError:
                return 99999
        available = sorted(available, key=_odds_key)

    picks_by_member = draft.picks_by_member()
    draft_order     = list(draft.order.select_related('member__user'))

    # Current round and pick-within-round for display
    current_round     = (total_picks // member_count) + 1 if not draft_complete else league.roster_size
    pick_in_round     = (total_picks % member_count) + 1 if not draft_complete else member_count

    # Build teams JSON for client-side team switching (unique members in draft order)
    teams_data = []
    seen_member_ids = set()
    for order in draft_order:
        member = order.member
        if member.pk in seen_member_ids:
            continue
        seen_member_ids.add(member.pk)
        member_picks = picks_by_member.get(member, [])
        pick_list = []
        for pick in member_picks:
            if has_odds:
                odds_str = odds_map.get(pick.player_id) or odds_map.get(str(pick.player_id)) or ''
            else:
                odds_str = ('#' + str(pick.player.world_ranking)) if pick.player.world_ranking else ''
            pick_list.append({
                'pick_number': pick.pick_number,
                'player_name': pick.player.display_name,
                'odds': odds_str,
            })
        teams_data.append({
            'member_id':   member.pk,
            'username':    member.display(),
            'is_mine':     member == my_membership,
            'is_on_clock': on_the_clock is not None and member == on_the_clock,
            'picks':       pick_list,
        })

    return render(request, 'fantasy/draft_room.html', {
        'draft':            draft,
        'league':           league,
        'my_membership':    my_membership,
        'on_the_clock':     on_the_clock,
        'my_turn':          my_turn,
        'is_commissioner':  is_commissioner,
        'draft_complete':   draft_complete,
        'available':        available,
        'odds_map':         odds_map,
        'has_odds':         has_odds,
        'has_round_scores': has_round_scores,
        'teams_json':       json.dumps(teams_data),
        'current_round':    current_round,
        'pick_in_round':    pick_in_round,
        'total_picks':      total_picks,
        'picks_needed':     picks_needed,
        'draft_open':       draft.status == WeeklyDraft.Status.OPEN and not draft_complete,
        'draft_started':    draft_started,
    })


@login_required
@require_POST
def make_pick(request, pk):
    draft = get_object_or_404(WeeklyDraft, pk=pk)
    if draft.status != WeeklyDraft.Status.OPEN:
        return JsonResponse({'error': 'Draft is not open.'}, status=400)

    from django.utils import timezone as tz
    if draft.draft_time and tz.now() < draft.draft_time:
        return JsonResponse({'error': 'Draft has not started yet.'}, status=400)

    try:
        membership = LeagueMember.objects.get(league=draft.league, user=request.user)
    except LeagueMember.DoesNotExist:
        return JsonResponse({'error': 'Not a league member.'}, status=403)

    on_the_clock = draft.current_pick_member()
    if on_the_clock != membership:
        return JsonResponse({'error': 'Not your turn.'}, status=400)

    player_id = request.POST.get('player_id')
    try:
        entry = Leaderboard.objects.select_related('player').get(
            tournament=draft.tournament, player_id=player_id
        )
    except Leaderboard.DoesNotExist:
        return JsonResponse({'error': 'Player not in tournament field.'}, status=400)

    if DraftPick.objects.filter(draft=draft, player_id=player_id).exists():
        return JsonResponse({'error': 'Player already picked.'}, status=400)

    pick_number = draft.picks.count() + 1
    DraftPick.objects.create(
        draft=draft,
        member=membership,
        player=entry.player,
        pick_number=pick_number,
    )
    DraftMessage.objects.create(
        draft=draft,
        is_system=True,
        text=f'⛳ {membership.display()} drafted {entry.player.display_name} (Pick #{pick_number})',
    )

    # Reset pick timer and auto-lock when all picks are made
    from django.utils import timezone as tz
    member_count = draft.league.memberships.count()
    if pick_number >= member_count * draft.league.roster_size:
        draft.status = WeeklyDraft.Status.LOCKED
        draft.current_pick_started_at = None
        draft.save(update_fields=['status', 'current_pick_started_at'])
    else:
        draft.current_pick_started_at = tz.now()
        draft.save(update_fields=['current_pick_started_at'])

    return JsonResponse({'ok': True, 'pick_number': pick_number})


@login_required
def set_draft_time(request, pk):
    draft = get_object_or_404(WeeklyDraft, pk=pk)
    if draft.league.commissioner != request.user:
        return redirect('fantasy:draft_room', pk=pk)

    error = None
    if request.method == 'POST':
        from django.utils.dateparse import parse_datetime
        from django.utils import timezone as tz
        raw = request.POST.get('draft_time', '').strip()
        try:
            pick_time_limit = max(30, int(request.POST.get('pick_time_limit', 120)))
        except ValueError:
            pick_time_limit = 120
        dt = parse_datetime(raw) if raw else None
        if raw and not dt:
            error = 'Invalid date/time format.'
        else:
            if dt and tz.is_naive(dt):
                dt = tz.make_aware(dt)
            draft.draft_time = dt
            draft.pick_time_limit = pick_time_limit
            draft.save(update_fields=['draft_time', 'pick_time_limit'])
            return redirect('fantasy:draft_room', pk=pk)

    from django.utils import timezone as tz
    current = tz.localtime(draft.draft_time).strftime('%Y-%m-%dT%H:%M') if draft.draft_time else ''
    return render(request, 'fantasy/set_draft_time.html', {'draft': draft, 'current': current, 'error': error})


@login_required
@require_POST
def lock_draft(request, pk):
    draft = get_object_or_404(WeeklyDraft, pk=pk)
    if draft.league.commissioner != request.user:
        return JsonResponse({'error': 'Not the commissioner.'}, status=403)
    draft.status = WeeklyDraft.Status.LOCKED
    draft.save(update_fields=['status'])
    return redirect('fantasy:draft_room', pk=pk)


@login_required
def draft_state_api(request, pk):
    """Lightweight poll endpoint for the live draft room."""
    draft        = get_object_or_404(WeeklyDraft, pk=pk)
    on_the_clock = draft.current_pick_member()
    try:
        my_membership = LeagueMember.objects.get(league=draft.league, user=request.user)
    except LeagueMember.DoesNotExist:
        my_membership = None
    picks = list(
        draft.picks.select_related('member__user', 'player')
        .order_by('pick_number')
        .values('pick_number', 'member_id', 'member__user__username',
                'player__display_name', 'player__espn_id', 'player_id', 'player__world_ranking')
    )
    from golf.models import Odds as OddsModel
    odds_qs  = OddsModel.objects.filter(tournament=draft.tournament, bookmaker='DraftKings').values('player_id', 'win_odds')
    odds_map = {o['player_id']: o['win_odds'] for o in odds_qs}
    for p in picks:
        pid = p['player_id']
        if odds_map:
            p['odds_str'] = odds_map.get(pid) or ''
        elif p['player__world_ranking']:
            p['odds_str'] = '#' + str(p['player__world_ranking'])
        else:
            p['odds_str'] = ''
    from django.utils import timezone as tz
    seconds_remaining = None
    if draft.status == WeeklyDraft.Status.OPEN:
        if draft.timer_paused and draft.seconds_at_pause is not None:
            seconds_remaining = draft.seconds_at_pause
        elif draft.current_pick_started_at:
            elapsed = (tz.now() - draft.current_pick_started_at).total_seconds()
            seconds_remaining = max(0, draft.pick_time_limit - elapsed)

    member_count  = draft.league.memberships.count()
    total_p       = draft.picks.count()
    draft_done    = member_count > 0 and total_p >= member_count * draft.league.roster_size
    current_round = (total_p // member_count) + 1 if member_count and not draft_done else draft.league.roster_size
    pick_in_round = (total_p % member_count) + 1 if member_count and not draft_done else member_count

    since_id = int(request.GET.get('since', 0))
    messages = list(
        draft.messages.filter(id__gt=since_id)
        .values('id', 'user__username', 'text', 'is_system', 'created_at')
    )
    for m in messages:
        m['created_at'] = m['created_at'].strftime('%H:%M')

    return JsonResponse({
        'status':                 draft.status,
        'total_picks':            draft.picks.count(),
        'on_the_clock':           on_the_clock.display() if on_the_clock else None,
        'on_the_clock_member_id': on_the_clock.pk if on_the_clock else None,
        'my_turn':                on_the_clock == my_membership if my_membership else False,
        'picks':                  picks,
        'seconds_remaining':      seconds_remaining,
        'pick_time_limit':        draft.pick_time_limit,
        'timer_paused':           draft.timer_paused,
        'current_round':          current_round,
        'pick_in_round':          pick_in_round,
        'messages':               messages,
    })


@login_required
@require_POST
def send_message(request, pk):
    draft = get_object_or_404(WeeklyDraft, pk=pk)
    if not LeagueMember.objects.filter(league=draft.league, user=request.user).exists():
        return JsonResponse({'error': 'Not a member.'}, status=403)
    text = request.POST.get('text', '').strip()[:500]
    if not text:
        return JsonResponse({'error': 'Empty message.'}, status=400)
    msg = DraftMessage.objects.create(draft=draft, user=request.user, text=text)
    return JsonResponse({
        'ok': True,
        'id': msg.pk,
        'username': request.user.username,
        'text': msg.text,
        'created_at': msg.created_at.strftime('%H:%M'),
    })


@login_required
@require_POST
def autopick(request, pk):
    from django.utils import timezone as tz
    draft = get_object_or_404(WeeklyDraft, pk=pk)

    if draft.status != WeeklyDraft.Status.OPEN:
        return JsonResponse({'error': 'Draft not open.'}, status=400)

    if not LeagueMember.objects.filter(league=draft.league, user=request.user).exists():
        return JsonResponse({'error': 'Not a league member.'}, status=403)

    # Verify time has actually expired server-side
    if draft.timer_paused:
        return JsonResponse({'error': 'Timer is paused.'}, status=400)
    if not draft.current_pick_started_at:
        return JsonResponse({'error': 'No pick in progress.'}, status=400)
    elapsed = (tz.now() - draft.current_pick_started_at).total_seconds()
    if elapsed < draft.pick_time_limit:
        return JsonResponse({'error': 'Time not expired yet.'}, status=400)

    member = draft.current_pick_member()
    if not member:
        return JsonResponse({'error': 'Draft complete.'}, status=400)

    from fantasy.scheduler import _best_available
    taken_ids = draft.picks.values_list('player_id', flat=True)
    available = list(
        Leaderboard.objects
        .filter(tournament=draft.tournament)
        .exclude(player_id__in=taken_ids)
        .select_related('player')
    )
    best = _best_available(available, draft.tournament)

    if not best:
        return JsonResponse({'error': 'No players available.'}, status=400)

    pick_number = draft.picks.count() + 1
    DraftPick.objects.create(
        draft=draft, member=member, player=best.player, pick_number=pick_number,
    )

    member_count = draft.league.memberships.count()
    if pick_number >= member_count * draft.league.roster_size:
        draft.status = WeeklyDraft.Status.LOCKED
        draft.current_pick_started_at = None
        draft.save(update_fields=['status', 'current_pick_started_at'])
    else:
        draft.current_pick_started_at = tz.now()
        draft.save(update_fields=['current_pick_started_at'])

    return JsonResponse({'ok': True, 'player': best.player.display_name, 'pick_number': pick_number})


@login_required
@require_POST
def toggle_timer(request, pk):
    from django.utils import timezone as tz
    draft = get_object_or_404(WeeklyDraft, pk=pk)
    if draft.league.commissioner != request.user:
        return JsonResponse({'error': 'Not the commissioner.'}, status=403)
    if draft.status != WeeklyDraft.Status.OPEN:
        return JsonResponse({'error': 'Draft not open.'}, status=400)

    if draft.timer_paused:
        # Resume: recalculate current_pick_started_at so remaining time is preserved
        remaining = draft.seconds_at_pause or draft.pick_time_limit
        draft.current_pick_started_at = tz.now() - datetime.timedelta(seconds=draft.pick_time_limit - remaining)
        draft.timer_paused = False
        draft.seconds_at_pause = None
        draft.save(update_fields=['current_pick_started_at', 'timer_paused', 'seconds_at_pause'])
        return JsonResponse({'paused': False})
    else:
        # Pause: record how many seconds were left
        if draft.current_pick_started_at:
            elapsed = (tz.now() - draft.current_pick_started_at).total_seconds()
            draft.seconds_at_pause = max(0, int(draft.pick_time_limit - elapsed))
        else:
            draft.seconds_at_pause = draft.pick_time_limit
        draft.timer_paused = True
        draft.save(update_fields=['timer_paused', 'seconds_at_pause'])
        return JsonResponse({'paused': True})


@login_required
def draft_standings(request, pk):
    draft  = get_object_or_404(WeeklyDraft, pk=pk)
    league = draft.league

    if not LeagueMember.objects.filter(league=league, user=request.user).exists():
        return redirect('fantasy:my_leagues')

    # Pre-fetch all leaderboard entries and round scores for this tournament
    lb_map = {
        e.player_id: e
        for e in Leaderboard.objects.filter(tournament=draft.tournament)
    }
    # round scores keyed by (player_id, round_number) → strokes
    round_map = {}
    for ps in PlayerScore.objects.filter(
        tournament=draft.tournament,
        round__round_number__lte=4,
    ).select_related('round'):
        round_map[(ps.player_id, ps.round.round_number)] = ps.strokes

    # Determine how many rounds the tournament has
    max_rounds = max((rn for _, rn in round_map), default=4) if round_map else 4
    round_numbers = list(range(1, max_rounds + 1))

    standings = []
    for order in draft.order.select_related('member__user'):
        member = order.member
        picks  = draft.picks.filter(member=member).select_related('player').order_by('pick_number')
        team_score = None
        players = []

        for pick in picks:
            entry  = lb_map.get(pick.player_id)
            missed_cut = entry and entry.status in ('cut', 'withdrawn', 'disqualified')
            rounds_completed = entry.rounds_completed if entry else 0

            round_scores = []
            for rn in round_numbers:
                strokes = round_map.get((pick.player_id, rn))
                if strokes is not None:
                    round_scores.append(strokes)
                elif missed_cut and rn > rounds_completed:
                    round_scores.append('MC')
                else:
                    round_scores.append(None)

            score_to_par = entry.total_score_to_par if entry and entry.total_score_to_par is not None else None
            if score_to_par is not None:
                team_score = (team_score or 0) + score_to_par

            players.append({
                'player':       pick.player,
                'entry':        entry,
                'round_scores': round_scores,
                'missed_cut':   missed_cut,
            })

        standings.append({
            'member':      member,
            'players':     players,
            'team_score':  team_score,
        })

    standings.sort(key=lambda x: x['team_score'] if x['team_score'] is not None else 9999)

    return render(request, 'fantasy/draft_standings.html', {
        'draft':         draft,
        'league':        league,
        'standings':     standings,
        'round_numbers': round_numbers,
    })
