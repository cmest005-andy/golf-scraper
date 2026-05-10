from django.contrib import admin
from .models import Course, Leaderboard, Odds, Player, PlayerScore, Tournament, TournamentRound


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ['display_name', 'country', 'world_ranking', 'updated_at']
    search_fields = ['first_name', 'last_name', 'display_name', 'espn_id']
    list_filter = ['country']
    ordering = ['last_name']


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['name', 'city', 'state', 'country', 'par', 'yardage']
    search_fields = ['name', 'city']


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = ['name', 'season', 'start_date', 'end_date', 'status', 'tour']
    list_filter = ['status', 'tour', 'season']
    search_fields = ['name']
    ordering = ['-start_date']


@admin.register(TournamentRound)
class TournamentRoundAdmin(admin.ModelAdmin):
    list_display = ['tournament', 'round_number', 'status']
    list_filter = ['tournament']


@admin.register(PlayerScore)
class PlayerScoreAdmin(admin.ModelAdmin):
    list_display = ['player', 'tournament', 'round', 'strokes', 'score_to_par', 'status']
    list_filter = ['tournament', 'status']
    search_fields = ['player__display_name']


@admin.register(Leaderboard)
class LeaderboardAdmin(admin.ModelAdmin):
    list_display = ['player', 'tournament', 'position', 'total_strokes', 'total_score_to_par', 'status']
    list_filter = ['tournament']
    search_fields = ['player__display_name']


@admin.register(Odds)
class OddsAdmin(admin.ModelAdmin):
    list_display = ['player', 'tournament', 'bookmaker', 'win_odds', 'timestamp']
    list_filter = ['tournament', 'bookmaker']
    search_fields = ['player__display_name']
