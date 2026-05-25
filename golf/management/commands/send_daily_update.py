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

import anthropic

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.utils import timezone

from fantasy.models import WeeklyDraft
from golf.models import Leaderboard, Tournament, TournamentRound


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _score_str(score):
    if score is None:
        return "—"
    if score < 0:
        return str(score)
    if score == 0:
        return "even par"
    return f"+{score}"


def _build_commentary(standings, tournament_name, round_label, is_final):
    """Call Claude to generate fun sports-talk commentary. Returns a list of paragraphs."""
    if not standings or all(t['team_score'] is None for t in standings):
        return [f"Scores are still rolling in from {tournament_name}. Check back soon for the full picture."]

    # Build a plain-text standings summary to feed Claude
    lines = []
    for i, team in enumerate(standings, 1):
        score = _score_str(team['team_score'])
        picks = ', '.join(
            f"{p['player_name']} ({_score_str(p['score_to_par'])})"
            for p in team['picks']
        )
        lines.append(f"{i}. {team['member_name']} — {score}  [{picks}]")
    standings_text = '\n'.join(lines)

    day_context = (
        "This is the final day — the tournament is over."
        if is_final else
        f"This is the {round_label} update — the tournament is still in progress."
    )

    prompt = (
        f"You are a witty, enthusiastic fantasy golf league announcer. "
        f"Write a short, fun sports-talk commentary recap (3–5 sentences, 2 short paragraphs max) "
        f"for the {tournament_name} fantasy league update. {day_context}\n\n"
        f"Current standings:\n{standings_text}\n\n"
        f"Be specific — mention team names and scores. Be playful, use golf metaphors, "
        f"keep it light and fun. Do not use bullet points or headers, just natural prose paragraphs."
    )

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=400,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = message.content[0].text.strip()
        # Split on blank lines to get paragraph list
        paras = [p.strip() for p in text.split('\n\n') if p.strip()]
        return paras if paras else [text]
    except Exception as e:
        # Fall back to a simple summary if the API call fails
        leader = standings[0]
        return [
            f"{leader['member_name']} leads {tournament_name} at {_score_str(leader['team_score'])}. "
            f"Full standings below."
        ]


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
        parser.add_argument(
            '--test',
            type=str,
            metavar='EMAIL',
            help='Send a sample email to the given address to verify SendGrid is working.',
        )

    def handle(self, *args, **options):
        dry_run  = options['dry_run']
        test_email = options.get('test')
        today    = timezone.localdate()
        app_name = settings.APP_NAME

        if test_email:
            self._send_test(test_email, app_name)
            return

        active_drafts = (
            WeeklyDraft.objects
            .filter(
                status__in=[WeeklyDraft.Status.OPEN, WeeklyDraft.Status.LOCKED],
                tournament__status__in=[Tournament.Status.IN_PROGRESS, Tournament.Status.COMPLETED],
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

            # Determine current round — use highest round with actual scores
            from golf.models import PlayerScore
            latest_round = (
                TournamentRound.objects
                .filter(tournament=tournament, scores__isnull=False)
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

    def _send_test(self, email, app_name):
        standings = [
            {'member_name': 'Andy',  'team_score': -8, 'picks': [
                {'player_name': 'Scottie Scheffler', 'score_to_par': -5},
                {'player_name': 'Rory McIlroy',      'score_to_par': -3},
            ]},
            {'member_name': 'Chris', 'team_score': -4, 'picks': [
                {'player_name': 'Xander Schauffele',  'score_to_par': -4},
                {'player_name': 'Jon Rahm',            'score_to_par': 0},
            ]},
            {'member_name': 'Mike',  'team_score': 2, 'picks': [
                {'player_name': 'Patrick Cantlay',    'score_to_par': 1},
                {'player_name': 'Tony Finau',          'score_to_par': 1},
            ]},
        ]
        commentary = _build_commentary(standings, 'The Memorial Tournament', 'Round 2 Recap', False)
        subject    = f"⛳ {app_name} | Test League — Round 2 Recap"
        context    = {
            'app_name':              app_name,
            'league_name':           'Test League',
            'tournament_name':       'The Memorial Tournament',
            'round_label':           'Round 2 Recap',
            'standings':             standings,
            'commentary_paragraphs': commentary,
            'is_final':              False,
            'winner_name':           '',
            'subject':               subject,
        }
        from django.template.loader import render_to_string
        html_body = render_to_string('email/daily_update.html', context)
        msg = EmailMultiAlternatives(
            subject=subject,
            body=self._plain_text(standings, commentary, 'The Memorial Tournament', 'Round 2 Recap'),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email],
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send()
        self.stdout.write(self.style.SUCCESS(f"Test email sent to {email}"))

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
