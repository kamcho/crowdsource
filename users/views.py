import json

from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .auth_utils import is_google_passwordless_account, user_needs_phone_link
from .forms import (
    CategoryPreferencesForm,
    CompleteProfileForm,
    SignInForm,
    SignUpForm,
    TwoFactorCodeForm,
)
from .google_auth import GoogleAuthError, get_or_create_user_from_google, verify_google_credential
from .ratelimit import (
    throttle_google_auth,
    throttle_login_attempt,
    throttle_two_factor_verify,
)
from .two_factor import (
    SESSION_PENDING_DISABLE,
    SESSION_PENDING_ENABLE,
    activate_totp,
    begin_totp_setup,
    clear_pending_login,
    clear_totp_setup,
    deactivate_totp,
    get_pending_login,
    get_pending_setup_secret,
    provisioning_uri,
    qr_code_data_url,
    set_pending_login,
    verify_totp_secret,
    verify_user_totp,
)


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


def _user_requires_two_factor(user):
    return bool(user.two_factor_enabled and user.totp_secret)


def _begin_login_with_optional_2fa(request, user, backend, next_url=''):
    if _user_requires_two_factor(user):
        set_pending_login(request, user, backend, next_url)
        messages.info(request, 'Enter the code from your authenticator app.')
        verify_url = reverse('users:two_factor_verify')
        if next_url:
            verify_url = f'{verify_url}?{urlencode({"next": next_url})}'
        return redirect(verify_url)

    auth_login(request, user, backend=backend)
    messages.success(request, f'Welcome back, {user.first_name}!')
    return redirect(_resolve_post_login_redirect(request, user, next_url))


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
        login_raw = (request.POST.get('login') or request.POST.get('phone') or '').strip()
        throttle_msg = throttle_login_attempt(request, login_raw)
        if throttle_msg:
            messages.error(request, throttle_msg)
            form = SignInForm(request.POST)
            return render(request, 'users/signin.html', _auth_page_context(form=form, next=next_url))

        form = SignInForm(request.POST)
        if form.is_valid():
            password = form.cleaned_data['password']
            lookup_user = getattr(form, 'lookup_user', None)
            phone = form.cleaned_data.get('login_phone')
            user = None
            if phone:
                user = authenticate(request, phone=phone, password=password)
            elif lookup_user and lookup_user.phone:
                user = authenticate(request, phone=lookup_user.phone, password=password)

            if user is not None:
                return _begin_login_with_optional_2fa(
                    request,
                    user,
                    'users.backends.PhonePasswordBackend',
                    next_url,
                )

            if is_google_passwordless_account(lookup_user):
                return render(
                    request,
                    'users/signin.html',
                    _auth_page_context(
                        form=form,
                        next=next_url,
                        google_signin_prompt=True,
                        google_signin_email=(
                            lookup_user.email or login_raw
                        ),
                    ),
                )
            messages.error(request, 'Invalid phone or email, or password.')
        else:
            messages.error(request, 'Please enter your phone or email and password.')
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

    next_url = payload.get('next') or ''
    if _user_requires_two_factor(user):
        set_pending_login(
            request,
            user,
            'django.contrib.auth.backends.ModelBackend',
            next_url,
        )
        verify_url = reverse('users:two_factor_verify')
        if next_url:
            verify_url = f'{verify_url}?{urlencode({"next": next_url})}'
        return JsonResponse({'ok': True, 'redirect': verify_url})

    auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    if created:
        messages.success(request, f'Welcome, {user.first_name}!')
    else:
        messages.success(request, f'Welcome back, {user.first_name}!')

    return JsonResponse({
        'ok': True,
        'redirect': _resolve_post_login_redirect(request, user, next_url),
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
            user.save(update_fields=['phone', 'updated_at'])
            messages.success(
                request,
                'Your phone number is saved. You can still sign in with Google anytime.',
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
    clear_pending_login(request)
    auth_logout(request)
    messages.success(request, 'You have been signed out.')
    return redirect('home:landing')


def two_factor_verify_view(request):
    if request.user.is_authenticated:
        return redirect(_resolve_post_login_redirect(request, request.user))

    user, backend, next_url = get_pending_login(request)
    if user is None:
        messages.error(request, 'Your sign-in session expired. Please sign in again.')
        return redirect('users:signin')

    next_url = next_url or request.GET.get('next', '')

    if request.method == 'POST':
        throttle_msg = throttle_two_factor_verify(request, user.pk)
        if throttle_msg:
            messages.error(request, throttle_msg)
            form = TwoFactorCodeForm(request.POST)
        else:
            form = TwoFactorCodeForm(request.POST)
            if form.is_valid():
                ok, error = verify_user_totp(user, form.cleaned_data['code'], purpose='login')
                if ok:
                    clear_pending_login(request)
                    auth_login(request, user, backend=backend)
                    messages.success(request, f'Welcome back, {user.first_name}!')
                    return redirect(_resolve_post_login_redirect(request, user, next_url))
                messages.error(request, error)
    else:
        form = TwoFactorCodeForm()

    return render(request, 'users/two_factor_verify.html', _auth_page_context(
        form=form,
        next=next_url,
    ))


@login_required(login_url='users:signin')
def two_factor_settings_view(request):
    user = request.user
    pending_enable = request.session.get(SESSION_PENDING_ENABLE) == str(user.pk)
    pending_disable = request.session.get(SESSION_PENDING_DISABLE) == str(user.pk)
    setup_secret = get_pending_setup_secret(request, user) if pending_enable else ''
    qr_data_url = ''
    manual_secret = ''
    if setup_secret:
        uri = provisioning_uri(setup_secret, user)
        qr_data_url = qr_code_data_url(uri)
        manual_secret = setup_secret

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()

        if action == 'request_enable':
            if user.two_factor_enabled:
                messages.info(request, 'Two-factor authentication is already enabled.')
            else:
                begin_totp_setup(request, user)
                messages.info(
                    request,
                    'Scan the QR code with Google Authenticator, Authy, or another TOTP app.',
                )
            return redirect('users:two_factor_settings')

        elif action == 'confirm_enable':
            setup_secret = get_pending_setup_secret(request, user)
            if not setup_secret:
                messages.error(request, 'Setup expired. Start again.')
                clear_totp_setup(request)
                return redirect('users:two_factor_settings')
            form = TwoFactorCodeForm(request.POST)
            if form.is_valid():
                throttle_msg = throttle_two_factor_verify(request, user.pk)
                if throttle_msg:
                    messages.error(request, throttle_msg)
                else:
                    ok, error = verify_totp_secret(
                        setup_secret,
                        form.cleaned_data['code'],
                        user.pk,
                        'enable',
                    )
                    if ok:
                        activate_totp(user, setup_secret)
                        clear_totp_setup(request)
                        messages.success(request, 'Authenticator app is now linked.')
                        return redirect('users:two_factor_settings')
                    messages.error(request, error)
            pending_enable = True
            uri = provisioning_uri(setup_secret, user)
            qr_data_url = qr_code_data_url(uri)
            manual_secret = setup_secret

        elif action == 'request_disable':
            if not user.two_factor_enabled:
                messages.info(request, 'Two-factor authentication is not enabled.')
            else:
                request.session[SESSION_PENDING_DISABLE] = str(user.pk)
                messages.info(request, 'Enter a code from your authenticator app to turn off 2FA.')
            return redirect('users:two_factor_settings')

        elif action == 'confirm_disable':
            form = TwoFactorCodeForm(request.POST)
            if form.is_valid():
                throttle_msg = throttle_two_factor_verify(request, user.pk)
                if throttle_msg:
                    messages.error(request, throttle_msg)
                else:
                    ok, error = verify_user_totp(user, form.cleaned_data['code'], purpose='disable')
                    if ok:
                        deactivate_totp(user)
                        request.session.pop(SESSION_PENDING_DISABLE, None)
                        messages.success(request, 'Two-factor authentication has been turned off.')
                        return redirect('users:two_factor_settings')
                    messages.error(request, error)
            pending_disable = True

        elif action == 'cancel':
            clear_totp_setup(request)
            request.session.pop(SESSION_PENDING_DISABLE, None)
            messages.info(request, 'Cancelled.')
            return redirect('users:two_factor_settings')

    form = TwoFactorCodeForm()
    return render(request, 'users/two_factor_settings.html', {
        'user': user,
        'form': form,
        'pending_enable': pending_enable,
        'pending_disable': pending_disable,
        'qr_data_url': qr_data_url,
        'manual_secret': manual_secret,
    })


from .user_dashboard import get_user_dashboard_context


@login_required(login_url='users:signin')
def profile_view(request):
    context = {'user': request.user}
    context.update(get_user_dashboard_context(request.user))
    return render(request, 'users/profile.html', context)


@login_required(login_url='users:signin')
def category_preferences_view(request):
    from core.category_utils import build_category_tree
    from core.models import Category
    from core.preference_services import (
        VIEWS_FOR_PARENT_PREFERENCE,
        get_explicit_preferred_category_ids,
        get_viewed_category_stats,
        infer_category_ids_from_activity,
        set_user_category_preferences,
    )
    from core.user_preference import UserCategoryPreference

    categories = Category.objects.filter(is_active=True)
    category_tree = build_category_tree(categories)
    inferred_category_ids = set(infer_category_ids_from_activity(request.user))
    viewed_preference_ids = set(
        UserCategoryPreference.objects.filter(
            user=request.user,
            source=UserCategoryPreference.Source.VIEWED,
        ).values_list('category_id', flat=True)
    )
    category_view_stats = get_viewed_category_stats(request.user)

    if request.method == 'POST':
        form = CategoryPreferencesForm(request.POST, user=request.user)
        selected_category_ids = {int(value) for value in request.POST.getlist('categories') if value.isdigit()}
        if form.is_valid():
            set_user_category_preferences(
                request.user,
                [category.pk for category in form.cleaned_data['categories']],
            )
            messages.success(request, 'Your category preferences were saved.')
            return redirect('users:category_preferences')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = CategoryPreferencesForm(user=request.user)
        selected_category_ids = set(get_explicit_preferred_category_ids(request.user))

    return render(request, 'users/category_preferences.html', {
        'form': form,
        'category_tree': category_tree,
        'inferred_category_ids': inferred_category_ids,
        'viewed_preference_ids': viewed_preference_ids,
        'category_view_stats': category_view_stats,
        'selected_category_ids': selected_category_ids,
        'views_for_preference': VIEWS_FOR_PARENT_PREFERENCE,
    })
