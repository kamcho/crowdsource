from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from users.models import User


def staff_required(view_func):
    """Allow admin and staff ops users."""

    @login_required(login_url='users:signin')
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_ops_user:
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('home:landing')
        return view_func(request, *args, **kwargs)

    return wrapper


def admin_required(view_func):
    """Allow full admins only (catalog, Django admin links, financial analytics)."""

    @login_required(login_url='users:signin')
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.role == User.Role.ADMIN:
            return view_func(request, *args, **kwargs)
        if request.user.role == User.Role.STAFF:
            messages.error(request, 'That area is restricted to admins. Use the Ops dashboard for group buys and deliveries.')
            return redirect('core:admin_dashboard')
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('home:landing')

    return wrapper
