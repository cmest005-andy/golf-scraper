from django.urls import path
from . import views

app_name = 'golf'

urlpatterns = [
    path('scorecard/', views.index, name='index'),
    path('players/<str:espn_id>/', views.player_detail, name='player_detail'),
    path('api/last-updated/', views.last_updated_api, name='last_updated_api'),
]
