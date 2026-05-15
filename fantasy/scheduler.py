import logging
import threading
import time
from django.utils import timezone as tz

logger = logging.getLogger(__name__)


def _best_available(available, tournament):
    """Return the best available Leaderboard entry using odds > score > world ranking."""
    from golf.models import Odds as OddsModel, PlayerScore
    has_scores = PlayerScore.objects.filter(tournament=tournament).exists()
    if has_scores:
        return min(
            available,
            key=lambda e: (e.total_score_to_par if e.total_score_to_par is not None else 9999,
                           e.player.world_ranking or 9999),
            default=None,
        )

    odds_qs  = OddsModel.objects.filter(tournament=tournament, bookmaker='DraftKings').values('player_id', 'win_odds')
    odds_map = {o['player_id']: o['win_odds'] for o in odds_qs}
    if odds_map:
        def _key(e):
            try:
                return int(odds_map.get(e.player_id, '') or '99999')
            except ValueError:
                return 99999
        return min(available, key=_key, default=None)

    return min(available, key=lambda e: e.player.world_ranking or 9999, default=None)


def autopick_expired_picks():
    """Advance any open draft whose pick timer has expired with no connected client."""
    try:
        from fantasy.models import DraftPick, WeeklyDraft
        from golf.models import Leaderboard

        from django.db.models import Q
        now = tz.now()
        stale = WeeklyDraft.objects.filter(
            status=WeeklyDraft.Status.OPEN,
            timer_paused=False,
        ).filter(
            Q(draft_time__isnull=True) | Q(draft_time__lte=now)
        )

        for draft in stale:
            # Initialize pick timer the first time the draft goes live
            if not draft.current_pick_started_at:
                draft.current_pick_started_at = now
                draft.save(update_fields=['current_pick_started_at'])
                continue

            elapsed = (now - draft.current_pick_started_at).total_seconds()
            if elapsed < draft.pick_time_limit:
                continue

            member = draft.current_pick_member()
            if not member:
                continue

            taken_ids = list(draft.picks.values_list('player_id', flat=True))
            available = list(
                Leaderboard.objects
                .filter(tournament=draft.tournament)
                .exclude(player_id__in=taken_ids)
                .select_related('player')
            )
            best = _best_available(available, draft.tournament)

            if not best:
                logger.warning('autopick: no available players for draft %s', draft.pk)
                continue

            pick_number = draft.picks.count() + 1
            DraftPick.objects.create(
                draft=draft,
                member=member,
                player=best.player,
                pick_number=pick_number,
            )
            from fantasy.models import DraftMessage
            DraftMessage.objects.create(
                draft=draft,
                is_system=True,
                text=f'⛳ {member.display()} drafted {best.player.display_name} (Pick #{pick_number})',
            )
            logger.info(
                'autopick: draft %s pick #%s → %s for %s',
                draft.pk, pick_number, best.player.display_name, member.display(),
            )

            member_count = draft.league.memberships.count()
            if pick_number >= member_count * draft.league.roster_size:
                draft.status = WeeklyDraft.Status.LOCKED
                draft.current_pick_started_at = None
                draft.save(update_fields=['status', 'current_pick_started_at'])
                logger.info('autopick: draft %s locked', draft.pk)
            else:
                draft.current_pick_started_at = tz.now()
                draft.save(update_fields=['current_pick_started_at'])

    except Exception:
        logger.exception('autopick_expired_picks failed')


def _run_loop():
    while True:
        autopick_expired_picks()
        time.sleep(5)


def start():
    print('Fantasy scheduler started', flush=True)
    t = threading.Thread(target=_run_loop, daemon=True)
    t.start()
