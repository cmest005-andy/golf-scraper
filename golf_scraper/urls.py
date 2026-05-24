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

    # Password reset (forgot password)
    path('accounts/password-reset/',
         auth_views.PasswordResetView.as_view(
             template_name='users/password_reset.html',
             email_template_name='users/password_reset_email.txt',
             subject_template_name='users/password_reset_subject.txt',
             success_url='/accounts/password-reset/done/',
         ), name='password_reset'),
    path('accounts/password-reset/done/',
         auth_views.PasswordResetDoneView.as_view(
             template_name='users/password_reset_done.html',
         ), name='password_reset_done'),
    path('accounts/password-reset/confirm/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(
             template_name='users/password_reset_confirm.html',
             success_url='/accounts/password-reset/complete/',
         ), name='password_reset_confirm'),
    path('accounts/password-reset/complete/',
         auth_views.PasswordResetCompleteView.as_view(
             template_name='users/password_reset_complete.html',
         ), name='password_reset_complete'),

    # Change password (logged-in users)
    path('accounts/password-change/',
         auth_views.PasswordChangeView.as_view(
             template_name='users/password_change.html',
             success_url='/accounts/password-change/done/',
         ), name='password_change'),
    path('accounts/password-change/done/',
         auth_views.PasswordChangeDoneView.as_view(
             template_name='users/password_change_done.html',
         ), name='password_change_done'),
]
