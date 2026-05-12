from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('golf.urls')),
    path('', include('users.urls')),
    path('', include('fantasy.urls')),
    path('accounts/login/',  auth_views.LoginView.as_view(template_name='users/login.html'),  name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
]
