from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import RegisterForm
from .models import UserProfile


def register(request):
    if request.user.is_authenticated:
        return redirect('golf:index')
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('golf:index')
    else:
        form = RegisterForm()
    return render(request, 'users/register.html', {'form': form})


@login_required
def account_settings(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    saved = False
    error = None

    if request.method == 'POST':
        display_name = request.POST.get('display_name', '').strip()
        if len(display_name) > 100:
            error = 'Display name must be 100 characters or fewer.'
        else:
            profile.display_name = display_name
            profile.save()
            saved = True

    return render(request, 'users/account_settings.html', {
        'profile': profile,
        'saved': saved,
        'error': error,
    })
