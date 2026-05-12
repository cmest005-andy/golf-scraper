import random
import string

from django.contrib.auth.models import User
from django.db import models

from golf.models import Tournament


def _invite_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))


class League(models.Model):
    name         = models.CharField(max_length=200)
    commissioner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='commissioner_leagues')
    members      = models.ManyToManyField(User, through='LeagueMember', related_name='leagues')
    roster_size  = models.IntegerField(default=6)
    invite_code  = models.CharField(max_length=20, unique=True, default=_invite_code)
    created_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class LeagueMember(models.Model):
    league    = models.ForeignKey(League, on_delete=models.CASCADE, related_name='memberships')
    user      = models.ForeignKey(User, on_delete=models.CASCADE, related_name='memberships')
    team_name = models.CharField(max_length=100, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['league', 'user']

    def __str__(self):
        return f'{self.user.username} — {self.league.name}'

    def display(self):
        return self.team_name or self.user.profile.get_display_name()


class WeeklyDraft(models.Model):
    class Status(models.TextChoices):
        OPEN   = 'open',   'Open'
        LOCKED = 'locked', 'Locked'
        SCORED = 'scored', 'Scored'

    league                = models.ForeignKey(League, on_delete=models.CASCADE, related_name='drafts')
    tournament            = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name='drafts')
    status                = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    draft_time            = models.DateTimeField(null=True, blank=True)
    pick_time_limit         = models.IntegerField(default=120)  # seconds per pick
    current_pick_started_at = models.DateTimeField(null=True, blank=True)
    timer_paused            = models.BooleanField(default=False)
    seconds_at_pause        = models.IntegerField(null=True, blank=True)
    created_at            = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['league', 'tournament']

    def __str__(self):
        return f'{self.league.name} — {self.tournament.name}'

    def current_pick_member(self):
        """Return the LeagueMember whose turn it is, or None if draft is complete."""
        member_count = self.order.count()
        if not member_count:
            return None
        total_picks   = self.picks.count()
        roster_size   = self.league.roster_size
        if total_picks >= member_count * roster_size:
            return None
        round_num      = total_picks // member_count
        pick_in_round  = total_picks % member_count
        position = (pick_in_round + 1) if round_num % 2 == 0 else (member_count - pick_in_round)
        return self.order.get(position=position).member

    def picks_by_member(self):
        """Return {member: [picks]} ordered by draft order."""
        result = {o.member: [] for o in self.order.select_related('member__user')}
        for pick in self.picks.select_related('member', 'player').order_by('pick_number'):
            if pick.member in result:
                result[pick.member].append(pick)
        return result


class DraftOrder(models.Model):
    draft    = models.ForeignKey(WeeklyDraft, on_delete=models.CASCADE, related_name='order')
    member   = models.ForeignKey(LeagueMember, on_delete=models.CASCADE, related_name='draft_order')
    position = models.IntegerField()  # 1-based slot in round 1

    class Meta:
        unique_together = ['draft', 'position']
        ordering = ['position']

    def __str__(self):
        return f'{self.draft} — pick {self.position}: {self.member.user.username}'


class DraftPick(models.Model):
    draft     = models.ForeignKey(WeeklyDraft, on_delete=models.CASCADE, related_name='picks')
    member    = models.ForeignKey(LeagueMember, on_delete=models.CASCADE, related_name='picks')
    player    = models.ForeignKey('golf.Player', on_delete=models.CASCADE, related_name='draft_picks')
    pick_number = models.IntegerField(default=0)
    picked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['draft', 'player']
        ordering = ['pick_number']

    def __str__(self):
        return f'Pick {self.pick_number}: {self.member.user.username} — {self.player.display_name}'
