from django.urls import path
from . import views

app_name = 'golf'

urlpatterns = [
    path('', views.home, name='home'),
    path('leaderboard/', views.index, name='index'),
    path('players/<str:espn_id>/', views.player_detail, name='player_detail'),
    path('api/leaderboard/', views.leaderboard_api, name='leaderboard_api'),
    path('api/last-updated/', views.last_updated_api, name='last_updated_api'),
]
