from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
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
        email        = request.POST.get('email', '').strip()
        phone        = request.POST.get('phone', '').strip()
        if len(display_name) > 100:
            error = 'Display name must be 100 characters or fewer.'
        elif len(phone) > 20:
            error = 'Phone number must be 20 characters or fewer.'
        elif email:
            try:
                validate_email(email)
            except ValidationError:
                error = 'Enter a valid email address.'

        if not error:
            profile.display_name = display_name
            profile.phone        = phone
            profile.save()
            if email:
                request.user.email = email
                request.user.save(update_fields=['email'])
            saved = True

    return render(request, 'users/account_settings.html', {
        'profile': profile,
        'saved': saved,
        'error': error,
    })
