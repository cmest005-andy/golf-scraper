from django.db import models


class Player(models.Model):
    espn_id = models.CharField(max_length=50, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    display_name = models.CharField(max_length=200)
    country = models.CharField(max_length=100, blank=True)
    world_ranking = models.IntegerField(null=True, blank=True)
    headshot_url = models.URLField(blank=True)
    # Bio fields populated from ESPN web API
    birthdate = models.DateField(null=True, blank=True)
    birthplace = models.CharField(max_length=200, blank=True)
    height = models.CharField(max_length=20, blank=True)
    weight = models.CharField(max_length=20, blank=True)
    turned_pro = models.IntegerField(null=True, blank=True)
    earnings = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    fedex_points = models.IntegerField(null=True, blank=True)
    bio_note = models.TextField(blank=True)
    wiki_bio = models.TextField(blank=True)
    bio_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return self.display_name

    @property
    def headshot(self):
        return f'https://a.espncdn.com/i/headshots/golf/players/full/{self.espn_id}.png'


class Course(models.Model):
    name = models.CharField(max_length=200)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    par = models.IntegerField(null=True, blank=True)
    yardage = models.IntegerField(null=True, blank=True)
    wiki_bio = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class CourseHole(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='holes')
    number = models.IntegerField()
    par = models.IntegerField()
    yardage = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = ['course', 'number']
        ordering = ['number']

    def __str__(self):
        return f'{self.course.name} — Hole {self.number}'


class Tournament(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = 'scheduled', 'Scheduled'
        IN_PROGRESS = 'in_progress', 'In Progress'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'

    espn_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    season = models.IntegerField()
    start_date = models.DateField()
    end_date = models.DateField()
    course = models.ForeignKey(
        Course, on_delete=models.SET_NULL, null=True, blank=True, related_name='tournaments'
    )
    purse = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    tour = models.CharField(max_length=100, default='PGA Tour')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.name} ({self.season})"


class TournamentRound(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name='rounds')
    round_number = models.IntegerField()
    status = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['tournament', 'round_number']
        ordering = ['round_number']

    def __str__(self):
        return f"{self.tournament.name} - Round {self.round_number}"


class PlayerScore(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        CUT = 'cut', 'Cut'
        WITHDRAWN = 'withdrawn', 'Withdrawn'
        DISQUALIFIED = 'disqualified', 'Disqualified'

    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name='scores')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='scores')
    round = models.ForeignKey(TournamentRound, on_delete=models.CASCADE, related_name='scores')
    position = models.CharField(max_length=10, blank=True)  # e.g. "T1", "2", "CUT"
    strokes = models.IntegerField(null=True, blank=True)
    score_to_par = models.IntegerField(null=True, blank=True)
    thru = models.IntegerField(null=True, blank=True)  # holes completed in current round
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['tournament', 'player', 'round']

    def __str__(self):
        return f"{self.player} - {self.tournament} R{self.round.round_number}"


class Leaderboard(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name='leaderboard')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='leaderboard_entries')
    position = models.CharField(max_length=10, blank=True)
    total_strokes = models.IntegerField(null=True, blank=True)
    total_score_to_par = models.IntegerField(null=True, blank=True)
    rounds_completed = models.IntegerField(default=0)
    status = models.CharField(max_length=20, blank=True)
    prize_money = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    fedex_points = models.IntegerField(null=True, blank=True)
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['tournament', 'player']
        ordering = ['position']

    def __str__(self):
        return f"{self.player} - {self.tournament} ({self.position})"


class Odds(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name='odds')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='odds')
    bookmaker = models.CharField(max_length=100)
    win_odds = models.CharField(max_length=20, blank=True)       # American format e.g. "+1500"
    top_5_odds = models.CharField(max_length=20, blank=True)
    top_10_odds = models.CharField(max_length=20, blank=True)
    top_20_odds = models.CharField(max_length=20, blank=True)
    make_cut_odds = models.CharField(max_length=20, blank=True)
    timestamp = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.player} - {self.tournament} ({self.bookmaker})"
