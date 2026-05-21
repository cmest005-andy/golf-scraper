"""
Management command: send_daily_update
--------------------------------------
Sends a daily fantasy golf league update email to all members of every
league that has an active draft for an in-progress tournament.

Intended to run at 8 PM ET each day via a Railway cron job:
    0 0 * * *   python manage.py send_daily_update
    (midnight UTC = 8 PM ET)

Usage
-----
    python manage.py send_daily_update
    python manage.py send_daily_update --dry-run   (prints without sending)
"""

import random

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.utils import timezone

from fantasy.models import WeeklyDraft
from golf.models import Leaderboard, Tournament, TournamentRound


# ------------------------------------------------------------------ #
# Sports-talk commentary builders
# ------------------------------------------------------------------ #

_LEADER_LINES = [
    "{name} is running the show this week at {score}, and right now their draft sheet looks like a masterpiece.",
    "Sitting pretty at {score}, {name} is the one everyone else is chasing — and they know it.",
    "{name} has the hot hand at {score}. Bold picks, big results. That's how you do it.",
    "At {score}, {name} is in the driver's seat. Someone's going to have to make a move to knock them off.",
]

_CHASE_LINES = [
    "{name} is breathing down their neck at {score} — just {gap} stroke{s} back and very much alive.",
    "Don't sleep on {name}. They're sitting at {score}, only {gap} stroke{s} off the pace.",
    "{name} is lurking at {score}, {gap} stroke{s} back. This thing is far from over.",
]

_MID_LINES = [
    "{name} is grinding through the week at {score} — still in the mix, still dangerous.",
    "Sitting at {score}, {name} is waiting for their players to catch fire. It could happen.",
]

_LAST_LINES = [
    "{name} is having a tough go at {score} — sometimes the picks just don't fall your way.",
    "It's been a rough week for {name} at {score}. Nothing a little luck on the back nine can't fix.",
    "{name} is sitting at {score} and probably checking injury reports as we speak.",
]

_CLOSING_LINES = [
    "The tournament isn't over yet — anything can happen out there. Check back tomorrow for the latest.",
    "Still plenty of golf left to be played. Tomorrow's update could look completely different.",
    "Golf has a way of turning things upside down overnight. Stay tuned.",
]

_FINAL_CLOSING = [
    "What a week it's been. Hats off to everyone who played — see you at the next one.",
    "Another tournament in the books. The best team won and there's no arguing with the scoreboard.",
    "That's a wrap. Start scouting your picks for next week — the competition isn't letting up.",
]


def _score_str(score):
    if score is None:
        return "—"
    if score < 0:
        return str(score)
    if score == 0:
        return "even par"
    return f"+{score}"


def _build_commentary(standings, tournament_name, round_label, is_final):
    """Return a list of paragraph strings in sports-talk style."""
    paras = []

    if not standings or all(t['team_score'] is None for t in standings):
        paras.append(f"Scores are still rolling in from {tournament_name}. Check back soon for the full picture.")
        return paras

    scored = [t for t in standings if t['team_score'] is not None]
    if not scored:
        return paras

    leader = scored[0]
    paras.append(random.choice(_LEADER_LINES).format(
        name=leader['member_name'],
        score=_score_str(leader['team_score']),
    ))

    if len(scored) >= 2:
        second = scored[1]
        gap = second['team_score'] - leader['team_score']
        paras.append(random.choice(_CHASE_LINES).format(
            name=second['member_name'],
            score=_score_str(second['team_score']),
            gap=gap,
            s='s' if gap != 1 else '',
        ))

    for team in scored[2:max(2, len(scored) - 1)]:
        paras.append(random.choice(_MID_LINES).format(
            name=team['member_name'],
            score=_score_str(team['team_score']),
        ))

    if len(scored) > 2:
        last = scored[-1]
        paras.append(random.choice(_LAST_LINES).format(
            name=last['member_name'],
            score=_score_str(last['team_score']),
        ))

    if is_final:
        paras.append(random.choice(_FINAL_CLOSING))
    else:
        paras.append(random.choice(_CLOSING_LINES))

    return paras


# ------------------------------------------------------------------ #
# Standings builder
# ------------------------------------------------------------------ #

def _build_standings(draft):
    """Return a sorted list of team dicts for the given draft."""
    lb_map = {
        e.player_id: e.total_score_to_par
        for e in Leaderboard.objects.filter(tournament=draft.tournament)
    }

    picks_by_member = draft.picks_by_member()
    order = list(draft.order.select_related('member__user', 'member__user__profile').order_by('position'))
    seen = set()
    teams = []

    for entry in order:
        member = entry.member
        if member.pk in seen:
            continue
        seen.add(member.pk)

        member_picks = picks_by_member.get(member, [])
        pick_data = []
        team_score = None

        for pick in member_picks:
            stp = lb_map.get(pick.player_id)
            if stp is not None:
                team_score = (team_score or 0) + stp
            pick_data.append({'player_name': pick.player.display_name, 'score_to_par': stp})

        teams.append({
            'member_name': member.display(),
            'team_score':  team_score,
            'picks':       pick_data,
        })

    return sorted(teams, key=lambda t: t['team_score'] if t['team_score'] is not None else float('inf'))


# ------------------------------------------------------------------ #
# Command
# ------------------------------------------------------------------ #

class Command(BaseCommand):
    help = "Send daily fantasy golf league update emails via SendGrid."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print email content without sending.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today   = timezone.localdate()
        app_name = settings.APP_NAME

        active_drafts = (
            WeeklyDraft.objects
            .filter(
                status=WeeklyDraft.Status.OPEN,
                tournament__status=Tournament.Status.IN_PROGRESS,
            )
            .select_related('league', 'tournament', 'league__commissioner')
        )

        if not active_drafts.exists():
            self.stdout.write("No active drafts found — nothing to send.")
            return

        for draft in active_drafts:
            league     = draft.league
            tournament = draft.tournament
            is_final   = today >= tournament.end_date

            # Determine current round label
            latest_round = (
                TournamentRound.objects
                .filter(tournament=tournament)
                .order_by('-round_number')
                .first()
            )
            round_num   = latest_round.round_number if latest_round else 1
            round_label = f"Final Round" if is_final else f"Round {round_num} Recap"

            standings = _build_standings(draft)
            commentary = _build_commentary(standings, tournament.name, round_label, is_final)

            winner_name = standings[0]['member_name'] if standings else ''

            subject = f"⛳ {app_name} | {league.name} — {round_label}"

            context = {
                'app_name':              app_name,
                'league_name':           league.name,
                'tournament_name':       tournament.name,
                'round_label':           round_label,
                'standings':             standings,
                'commentary_paragraphs': commentary,
                'is_final':              is_final,
                'winner_name':           winner_name,
                'subject':               subject,
            }

            html_body = render_to_string('email/daily_update.html', context)

            # Collect recipient emails (members who have an email set)
            recipients = []
            for membership in league.memberships.select_related('user'):
                email = membership.user.email.strip()
                if email:
                    recipients.append(email)

            if not recipients:
                self.stdout.write(self.style.WARNING(f"  {league.name}: no member emails — skipping."))
                continue

            self.stdout.write(f"\nLeague : {league.name}")
            self.stdout.write(f"To     : {', '.join(recipients)}")
            self.stdout.write(f"Subject: {subject}")

            if dry_run:
                self.stdout.write(self.style.WARNING("  [dry-run] Not sending."))
                continue

            msg = EmailMultiAlternatives(
                subject=subject,
                body=self._plain_text(standings, commentary, tournament.name, round_label),
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=recipients,
            )
            msg.attach_alternative(html_body, 'text/html')
            msg.send()
            self.stdout.write(self.style.SUCCESS(f"  Sent to {len(recipients)} recipient(s)."))

    @staticmethod
    def _plain_text(standings, commentary, tournament_name, round_label):
        """Fallback plain-text version."""
        lines = [f"{tournament_name} — {round_label}", "=" * 40, ""]
        lines += [p for p in commentary]
        lines += ["", "STANDINGS", "-" * 20]
        for i, team in enumerate(standings, 1):
            score = _score_str(team['team_score'])
            lines.append(f"{i}. {team['member_name']}  {score}")
            for pick in team['picks']:
                pscore = _score_str(pick['score_to_par'])
                lines.append(f"   - {pick['player_name']}  {pscore}")
        return "\n".join(lines)
