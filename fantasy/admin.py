from django.contrib import admin

from .models import DraftOrder, DraftPick, League, LeagueMember, WeeklyDraft


class DraftOrderInline(admin.TabularInline):
    model = DraftOrder
    extra = 0


class DraftPickInline(admin.TabularInline):
    model = DraftPick
    extra = 0
    readonly_fields = ['picked_at']


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ['name', 'commissioner', 'roster_size', 'invite_code']
    search_fields = ['name', 'commissioner__username']


@admin.register(LeagueMember)
class LeagueMemberAdmin(admin.ModelAdmin):
    list_display = ['user', 'league', 'team_name', 'joined_at']
    search_fields = ['user__username', 'league__name']


@admin.register(WeeklyDraft)
class WeeklyDraftAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'status', 'draft_time', 'pick_time_limit']
    list_filter = ['status']
    search_fields = ['league__name', 'tournament__name']
    inlines = [DraftOrderInline, DraftPickInline]


@admin.register(DraftPick)
class DraftPickAdmin(admin.ModelAdmin):
    list_display = ['draft', 'pick_number', 'member', 'player', 'picked_at']
    list_filter = ['draft']
