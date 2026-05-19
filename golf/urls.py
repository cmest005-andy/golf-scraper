from django.urls import path
from . import views

app_name = 'golf'

urlpatterns = [
    path('', views.home, name='home'),
    path('leaderboard/', views.index, name='index'),
    path('players/<str:espn_id>/', views.player_detail, name='player_detail'),
    path('schedule/', views.schedule, name='schedule'),
    path('courses/<int:pk>/', views.course_detail, name='course_detail'),
    path('news/', views.news, name='news'),
    path('news/archive/', views.news_archive, name='news_archive'),
    path('api/leaderboard/', views.leaderboard_api, name='leaderboard_api'),
    path('api/last-updated/', views.last_updated_api, name='last_updated_api'),
]
