from django.urls import path
from . import views

app_name = 'fantasy'

urlpatterns = [
    path('leagues/',                          views.my_leagues,     name='my_leagues'),
    path('leagues/create/',                   views.create_league,  name='create_league'),
    path('leagues/join/',                     views.join_league,    name='join_league'),
    path('leagues/<int:pk>/',                 views.league_detail,  name='league_detail'),
    path('leagues/<int:pk>/settings/',        views.league_settings, name='league_settings'),
    path('leagues/<int:pk>/my-team/',                          views.my_team,     name='my_team'),
    path('leagues/<int:league_pk>/teams/<int:member_pk>/',     views.team_detail, name='team_detail'),
    path('leagues/<int:league_pk>/draft/',    views.create_draft,   name='create_draft'),
    path('drafts/<int:pk>/',                  views.draft_room,     name='draft_room'),
    path('drafts/<int:pk>/pick/',             views.make_pick,      name='make_pick'),
    path('drafts/<int:pk>/lock/',             views.lock_draft,      name='lock_draft'),
    path('drafts/<int:pk>/set-time/',         views.set_draft_time,  name='set_draft_time'),
    path('drafts/<int:pk>/autopick/',         views.autopick,        name='autopick'),
    path('drafts/<int:pk>/toggle-timer/',     views.toggle_timer,    name='toggle_timer'),
    path('drafts/<int:pk>/state/',            views.draft_state_api,  name='draft_state_api'),
    path('drafts/<int:pk>/chat/',             views.send_message,     name='send_message'),
    path('drafts/<int:pk>/standings/',        views.draft_standings,  name='draft_standings'),
]
