import json

from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .auth_utils import user_needs_phone_link
from .forms import CompleteProfileForm, SignInForm, SignUpForm
from .google_auth import GoogleAuthError, get_or_create_user_from_google, verify_google_credential
from .ratelimit import throttle_google_auth, throttle_login_attempt


def _resolve_post_login_redirect(request, user, next_url=None):
    next_url = next_url or request.GET.get('next') or request.POST.get('next')

    if user_needs_phone_link(user):
        profile_url = reverse('users:complete_profile')
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return f'{profile_url}?{urlencode({"next": next_url})}'
        return profile_url

    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url

    return reverse('users:profile')


def _auth_page_context(**extra):
    client_id = ''
    ids = getattr(settings, 'GOOGLE_CLIENT_IDS', None) or []
    if ids:
        client_id = ids[0]
    else:
        client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '') or ''
    return {
        'google_client_id': client_id,
        'google_signin_enabled': bool(client_id),
        **extra,
    }


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('home:landing')

    next_url = request.GET.get('next', '')

    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            raw_password = form.cleaned_data['password1']
            authenticated_user = authenticate(request, phone=user.phone, password=raw_password)
            if authenticated_user:
                auth_login(request, authenticated_user)
                messages.success(request, f'Welcome, {user.first_name}! Your account is ready.')
                return redirect(_resolve_post_login_redirect(request, authenticated_user, next_url))
            messages.warning(request, 'Registration successful. Please sign in.')
            return redirect('users:signin')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = SignUpForm()

    return render(request, 'users/signup.html', _auth_page_context(form=form, next=next_url))


def signin_view(request):
    if request.user.is_authenticated:
        return redirect(_resolve_post_login_redirect(request, request.user))

    next_url = request.GET.get('next', '')

    if request.method == 'POST':
        phone_raw = (request.POST.get('phone') or '').strip()
        throttle_msg = throttle_login_attempt(request, phone_raw)
        if throttle_msg:
            messages.error(request, throttle_msg)
            form = SignInForm(request.POST)
            return render(request, 'users/signin.html', _auth_page_context(form=form, next=next_url))

        form = SignInForm(request.POST)
        if form.is_valid():
            phone = form.cleaned_data['phone']
            password = form.cleaned_data['password']
            user = authenticate(request, phone=phone, password=password)
            if user is not None:
                auth_login(request, user)
                messages.success(request, f'Welcome back, {user.first_name}!')
                return redirect(_resolve_post_login_redirect(request, user, next_url))
            messages.error(request, 'Invalid phone number or password.')
        else:
            messages.error(request, 'Please enter your phone number and password.')
    else:
        form = SignInForm()

    return render(request, 'users/signin.html', _auth_page_context(form=form, next=next_url))


@require_POST
def google_auth_view(request):
    if request.user.is_authenticated:
        return JsonResponse({
            'ok': True,
            'redirect': _resolve_post_login_redirect(request, request.user),
        })

    throttle_msg = throttle_google_auth(request)
    if throttle_msg:
        return JsonResponse({'ok': False, 'error': throttle_msg}, status=429)

    try:
        payload = json.loads(request.body.decode('utf-8')) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid request payload.'}, status=400)

    credential = payload.get('credential') or request.POST.get('credential')
    if not credential:
        return JsonResponse({'ok': False, 'error': 'Missing Google credential.'}, status=400)

    try:
        idinfo = verify_google_credential(credential)
        user, created = get_or_create_user_from_google(idinfo)
    except GoogleAuthError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    if not user.is_active:
        return JsonResponse({'ok': False, 'error': 'This account is inactive.'}, status=403)

    auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    if created:
        messages.success(request, f'Welcome, {user.first_name}!')
    else:
        messages.success(request, f'Welcome back, {user.first_name}!')

    return JsonResponse({
        'ok': True,
        'redirect': _resolve_post_login_redirect(request, user, payload.get('next')),
    })


@login_required(login_url='users:signin')
def complete_profile_view(request):
    if not user_needs_phone_link(request.user):
        return redirect(_resolve_post_login_redirect(request, request.user))

    next_url = request.GET.get('next', '')

    if request.method == 'POST':
        form = CompleteProfileForm(request.POST, user=request.user)
        if form.is_valid():
            user = request.user
            user.phone = form.cleaned_data['phone']
            user.set_password(form.cleaned_data['password1'])
            user.save(update_fields=['phone', 'password'])
            update_session_auth_hash(request, user)
            messages.success(
                request,
                'Your phone number is linked. You can sign in with Google or your password anytime.',
            )
            return redirect(
                _resolve_post_login_redirect(
                    request,
                    user,
                    request.POST.get('next') or next_url,
                )
            )
    else:
        form = CompleteProfileForm(user=request.user)

    return render(request, 'users/complete_profile.html', {
        'form': form,
        'next': next_url,
        'user': request.user,
    })


def signout_view(request):
    auth_logout(request)
    messages.success(request, 'You have been signed out.')
    return redirect('home:landing')


from .user_dashboard import get_user_dashboard_context


@login_required(login_url='users:signin')
def profile_view(request):
    context = {'user': request.user}
    context.update(get_user_dashboard_context(request.user))
    return render(request, 'users/profile.html', context)
