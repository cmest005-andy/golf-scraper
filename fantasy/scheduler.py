import logging

from apscheduler.schedulers.background import BackgroundScheduler
from django.utils import timezone as tz

logger = logging.getLogger(__name__)


def autopick_expired_picks():
    """Advance any open draft whose pick timer has expired with no connected client."""
    try:
        from fantasy.models import DraftPick, WeeklyDraft
        from golf.models import Leaderboard

        now = tz.now()
        stale = WeeklyDraft.objects.filter(
            status=WeeklyDraft.Status.OPEN,
            timer_paused=False,
            current_pick_started_at__isnull=False,
        )

        for draft in stale:
            elapsed = (now - draft.current_pick_started_at).total_seconds()
            if elapsed < draft.pick_time_limit:
                continue

            member = draft.current_pick_member()
            if not member:
                continue

            taken_ids = list(draft.picks.values_list('player_id', flat=True))
            available = (
                Leaderboard.objects
                .filter(tournament=draft.tournament)
                .exclude(player_id__in=taken_ids)
                .select_related('player')
            )
            has_scores = available.filter(total_score_to_par__isnull=False).exists()
            best = available.order_by(
                'total_score_to_par' if has_scores else 'player__world_ranking'
            ).first()

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


def start():
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        autopick_expired_picks,
        'interval',
        seconds=5,
        id='autopick_expired',
        replace_existing=True,
    )
    scheduler.start()
    logger.info('Fantasy scheduler started')
